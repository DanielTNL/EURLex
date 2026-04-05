#!/usr/bin/env python3
# Process discovered URLs into normalized document.v2 records (manual-only).
# Safe to run repeatedly; appends NDJSON per ISO week under outputs/docs/.

import argparse, os, sys, json, re, hashlib
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparse

# Optional: OpenAI summarisation (falls back automatically)
USE_OPENAI = True
try:
    from openai import OpenAI
    OPENAI_CLIENT = OpenAI()
except Exception:
    USE_OPENAI = False
    OPENAI_CLIENT = None

UA = "Mozilla/5.0 (compatible; EU-Innovation-Monitor/1.0)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.8"})
TIMEOUT = 25

def iso_now():
    return datetime.now(timezone.utc).isoformat()

def safe_parse_dt(s):
    if not s:
        return None
    try:
        d = dtparse.parse(s, dayfirst=True)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None

def fetch(url):
    r = SESSION.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text, r.url

def extract_main(soup):
    root = soup.find(["main", "article"]) or soup
    ps = [p.get_text(" ", strip=True) for p in root.select("p") if p.get_text(strip=True)]
    text = "\n".join(ps)
    return text[:50000]

def extract_title(soup):
    for sel in ["h1", "meta[property='og:title']"]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(" ", strip=True) if el.name == "h1" else (el.get("content") or "").strip()
    return (soup.title.get_text(" ", strip=True) if soup.title else None)

def extract_date(soup, hint=None):
    for sel in ["meta[property='article:published_time']", "time[datetime]", "meta[name='date']"]:
        el = soup.select_one(sel)
        if el:
            val = el.get("content") or el.get("datetime")
            d = safe_parse_dt(val)
            if d:
                return d
    if hint:
        d = safe_parse_dt(hint)
        if d:
            return d
    header = soup.find(["header", "main", "article"]) or soup
    txt = header.get_text(" ", strip=True)
    m = re.search(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b", txt)
    if m:
        d = safe_parse_dt(m.group(1))
        if d:
            return d
    return datetime.now(timezone.utc)

def detect_doc_type(text):
    t = text.lower()
    if "press release" in t or "press" in t[:200]:
        return "Press_Release"
    if "call for proposals" in t:
        return "Call_for_Proposals"
    if "award" in t and "grant" in t:
        return "Award/Grant"
    if "guidance" in t or "guidelines" in t:
        return "Guidance/Notice"
    if "report" in t:
        return "Report"
    return "Blog/News"

def detect_programme(text, base_domain):
    labs = set()
    t = text.lower()
    if "investeu" in t or "invest eu" in t or "investeu" in base_domain:
        labs.add("InvestEU")
    if "european defence fund" in t or "edf" in t:
        labs.add("EDF")
    if "european investment bank" in t or "eib" in t:
        labs.add("EIB")
    if "european investment fund" in t or "eif" in t:
        labs.add("EIF")
    if "asap" in t and "support act" in t.lower():
        labs.add("ASAP")
    return sorted(labs) or ["Other/NA"]

def detect_instrument(text):
    t = text.lower()
    labs = []
    if re.search(r"\bgrant(s)?\b", t):
        labs.append("Grant")
    if re.search(r"\bguarantee(s)?|guarantee facility\b", t):
        labs.append("Guarantee")
    if re.search(r"\bequity\b|\bventure\b|\bfund of funds\b", t):
        labs.append("Equity/Venture")
    if re.search(r"\bloan(s)?\b|\bframework loan\b", t):
        labs.append("Loan")
    if re.search(r"\bprocurement\b|\btender\b", t):
        labs.append("Procurement")
    if re.search(r"\blisting\b|\bipo\b", t):
        labs.append("Listing/Market")
    return labs or (["Procurement"] if "tender" in t else [])

TECH_MAP = {
    "AI/Autonomy": r"\bAI\b|\bartificial intelligence\b|\bautonom(y|ous)\b|\bC4ISR\b|\bcommand\b",
    "Advanced_Semiconductors": r"\bsemiconductor|chip|node\b|\bphotonic\b",
    "Quantum": r"\bquantum\b",
    "Biotech": r"\bbiotech|bio(tech|technology)\b",
    "Space/EO": r"\bsatellite|earth observation|EO\b|\bGNSS\b",
    "Cybersecurity": r"\bcyber|SOC|threat intel|zero trust\b",
    "Advanced_Computing/HPC": r"\bHPC|supercomput(ing|er)\b",
    "Robotics/Drones": r"\bdrone|UAV|UAS|robotics|swarm\b",
    "Advanced_Materials": r"\bcomposite|graphene|advanced materials\b",
    "Energy_Tech": r"\bbattery|hydrogen|fusion|energy storage\b",
    "Communications/5G+/SatCom": r"\b5G|6G|satcom|optical comm\b",
    "Positioning/Navigation/Timing": r"\bPNT|navigation|GNSS\b"
}

def detect_tech(text):
    t = text.lower()
    labels = []
    for k, rx in TECH_MAP.items():
        if re.search(rx, t, flags=re.IGNORECASE):
            labels.append(k)
    return labels

def extract_amounts(text):
    amounts = []
    for m in re.finditer(r"(€|\bEUR\b)\s*([\d\.,\s]+)\s*(billion|bn|million|mn|m)?", text, flags=re.IGNORECASE):
        raw = m.group(2).replace(" ", "")
        unit = (m.group(3) or "").lower()
        try:
            val = float(raw.replace(".", "").replace(",", "."))
        except Exception:
            continue
        if unit in ("billion", "bn"):
            val *= 1_000_000_000
        elif unit in ("million", "mn", "m"):
            val *= 1_000_000
        amounts.append({"amount": val, "currency": "EUR", "label": "stated_value"})
    return amounts[:5]

# === UPDATED: produce ~500-word newsletter-style intro with a References block ===
def summarise_150w(title, text, url=None, pub_dt=None):
    body = text[:6000]
    # Format a friendly date for references if available
    date_str = None
    if isinstance(pub_dt, datetime):
        try:
            date_str = pub_dt.strftime("%d %b %Y")
        except Exception:
            date_str = None

    if USE_OPENAI and OPENAI_CLIENT:
        prompt = (
            "Write a ~800-word newsletter-style summary for policy/finance readers tracking EU innovation, "
            "defence and capital markets. Be fun but informative, crisp and precise (UK English). Connect the dots "
            "without hype. Include:\n"
            "1) What happened and why it matters.\n"
            "2) Programme/instrument links (e.g., EDF, EDIP, InvestEU, EIB/EIF, SAFE, CMU) only if present in the text—do not invent.\n"
            "3) Any € amounts, timelines, eligibility/financing changes.\n"
            "4) Implications for startups/SMEs, primes, and regulators.\n"
            "5) One or two short, smart ‘so what’ insights.\n\n"
            "After the summary, add a 'References' block with 2–5 bullet points citing ONLY the source(s) in the provided text. "
            "Use this format per bullet: • <Site or Title> — <date if available> — <URL>. If you don't know the date, omit it. "
            "Do not fabricate sources or facts."
        )
        content = (
            f"TITLE: {title or '(untitled)'}\n"
            f"SOURCE_URL: {url or 'N/A'}\n"
            f"SOURCE_DATE: {date_str or 'N/A'}\n"
            f"ARTICLE_TEXT:\n{body}"
        )
        try:
            resp = OPENAI_CLIENT.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-5.4-nano"),
                messages=[
                    {"role": "system", "content": "You are a precise newsletter writer for EU policy and finance audiences."},
                    {"role": "user", "content": prompt + "\n\n" + content}
                ],
                temperature=0.3,
                max_completion_tokens=1100
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            pass

    # Fallback (no OpenAI): take the first ~500 words and append a simple reference
    sentences = re.split(r"(?<=[\.\?\!])\s+", text)
    # collect sentences until roughly 500 words
    acc = []
    wc = 0
    for s in sentences:
        words = s.split()
        if not words:
            continue
        if wc + len(words) > 520:
            break
        acc.append(s)
        wc += len(words)
    summary = " ".join(acc).strip()
    if not summary:
        summary = (text[:3800] + "…") if len(text) > 3800 else text

    ref_date = f" — {date_str}" if date_str else ""
    src = url or ""
    refs = "\n\nReferences\n• Source" + (ref_date if ref_date else "") + (f" — {src}" if src else "")
    return summary + refs

def week_path():
    now = datetime.now(timezone.utc).isocalendar()
    year, week = now[0], now[1]
    os.makedirs("outputs/docs", exist_ok=True)
    return f"outputs/docs/{year}-{week:02d}.ndjson"

def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="queue", required=False, default="state/latest_discovery.json",
                    help="path to discovery aggregate json")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--config", default="config_v2.yaml")  # accept & ignore to match workflow
    args = ap.parse_args()

    if not os.path.exists(args.queue):
        print(json.dumps({"processed": 0, "reason": "no discovery file"}))
        return

    with open(args.queue, "r", encoding="utf-8") as f:
        agg = json.load(f)

    items = []
    if isinstance(agg.get("items"), list):
        items.extend([it for it in agg.get("items", []) if isinstance(it, dict)])
    else:
        for src in agg.get("sources", []):
            if not isinstance(src, dict):
                continue
            for it in src.get("items", []):
                if isinstance(it, dict):
                    items.append(it)
    items = items[: args.limit]

    out_file = week_path()
    processed = 0
    written_urls = []

    for it in items:
        url = it.get("url")
        title_hint = it.get("title") or it.get("title_hint")
        published_hint = it.get("published_at") or it.get("published_date_hint")
        source_id = it.get("source_id") or "external_source"
        source_name = it.get("source") or source_id
        try:
            html, final_url = fetch(url)
            soup = BeautifulSoup(html, "lxml")
            title = extract_title(soup) or title_hint or "(untitled)"
            text = extract_main(soup)
            pub_dt = extract_date(soup, hint=published_hint)
            doc_type = detect_doc_type(text)
            programme = detect_programme(text, base_domain=final_url)
            instrument = detect_instrument(text)
            tech = detect_tech(text)
            amounts = extract_amounts(soup.get_text(" ", strip=True))
            # === UPDATED CALL: pass URL + date so the summary can cite them ===
            summary = summarise_150w(title, text, url=(final_url or url), pub_dt=pub_dt)
            dedupe = sha256((final_url or url) + title + (pub_dt.isoformat() if pub_dt else ""))

            rec = {
                "schema": "document.v2",
                "source_id": source_id,
                "source_name": source_name,
                "url": final_url or url,
                "canonical_url": final_url or url,
                "fetch_time": iso_now(),
                "language": "en",
                "title": title,
                "published_date": pub_dt.isoformat() if pub_dt else iso_now(),
                "updated_date": None,
                "doc_type": doc_type,
                "programme": programme,
                "finance_instrument": instrument,
                "stage": None,
                "actors": [],
                "tech_area": tech,
                "monetary_values": amounts,
                # Field name left unchanged for backwards compatibility
                "summary_150w": summary,
                "key_points": [],
                "implications": {
                    "innovation_direction": [],
                    "capital_structure": [],
                    "regulatory_change": []
                },
                "links": {"pdf": [], "dataset": [], "related": []},
                "celex_id": None,
                "call_id": None,
                "award_id": None,
                "tags": [],
                "dedupe_signature": dedupe,
                "embeddings": None,
                "extraction_notes": None
            }

            with open(out_file, "a", encoding="utf-8") as wf:
                wf.write(json.dumps(rec, ensure_ascii=False) + "\n")

            processed += 1
            written_urls.append(final_url or url)

        except Exception:
            continue

    print(json.dumps({"processed": processed, "ndjson": out_file, "urls": written_urls}, ensure_ascii=False))

if __name__ == "__main__":
    main()
