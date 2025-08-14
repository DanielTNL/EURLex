#!/usr/bin/env python3
"""
Weekly EU Finance & Defence Report
----------------------------------
- Aggregates the last N days (default 7) across your configured feeds (config.yaml).
- Produces one comprehensive weekly briefing (~N words) with inline [n] references.
- Saves Markdown to reports/weekly/ and mirrors to Google Docs (same folder as daily).
- Emails a short cover note with links to GitHub + Google Doc.

Env it expects (same as daily + optional weekly model):
  OPENAI_API_KEY, OPENAI_MODEL (fallback)
  OPENAI_MODEL_WEEKLY (preferred, e.g., 'gpt-4o-mini-high' or 'gpt-5' if available)
  GMAIL_USER, GMAIL_PASS
  GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN
  GOOGLE_DOCS_FOLDER_ID (optional), GOOGLE_DOCS_SHARE_WITH (optional)
"""

import os, sys, re, json, yaml, feedparser, datetime as dt
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse
from email.mime.text import MIMEText
import smtplib
from io import BytesIO

# --- Optional tz ---
try:
    import pytz
except Exception:
    pytz = None

# --- OpenAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_WEEKLY = os.getenv("OPENAI_MODEL_WEEKLY") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
OPENAI_ENABLED = bool(OPENAI_API_KEY)
if OPENAI_ENABLED:
    try:
        from openai import OpenAI
        _oa = OpenAI()
        print(f"[openai] enabled; weekly model = {MODEL_WEEKLY}")
    except Exception as _e:
        print("[openai] init error:", _e)
        _oa = None
        OPENAI_ENABLED = False
else:
    _oa = None
    print("[openai] disabled (no OPENAI_API_KEY)")

# --- Google (OAuth refresh token flow) ---
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    GOOGLE_LIBS_OK = True
except Exception as _e:
    print("[google] import error:", _e)
    Credentials = None
    build = None
    MediaIoBaseUpload = None
    GOOGLE_LIBS_OK = False

# =====================================================================

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def keyword_match_count(text: str, kws: List[str]) -> int:
    low = (text or "").lower()
    return sum(1 for kw in (kws or []) if kw.lower() in low)

def fetch_entries(url: str) -> List[Dict[str, Any]]:
    p = feedparser.parse(url)
    out = []
    for e in p.entries:
        title = e.get("title","") or ""
        summary = e.get("summary","") or e.get("description","") or ""
        link = e.get("link","") or ""
        published = None
        if getattr(e, "published_parsed", None):
            try:
                t = e.published_parsed
                published = dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
            except Exception:
                pass
        out.append({
            "title": title, "summary": summary, "link": link,
            "published_utc": published, "text": f"{title} {summary}", "source": url
        })
    return out

def score_entry(ent: Dict[str,Any], kws: List[str], recent_hours_bonus: int) -> float:
    s = float(keyword_match_count(ent["text"], kws))
    if recent_hours_bonus and ent.get("published_utc"):
        delta = dt.datetime.now(dt.timezone.utc) - ent["published_utc"]
        if delta.total_seconds() <= recent_hours_bonus*3600:
            s += 1.0
    if "uri=OJ:L" in (ent.get("source") or ""):
        s += 0.2
    return s

def first_sentence(s: str, n=200) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    m = re.search(r"(.+?[.!?])(\s|$)", s)
    return m.group(1) if m else s[:n]

def short_bullets(text: str, language: str, bullets: int, max_words: int) -> str:
    base = (text or "").strip()
    if not base:
        return ""
    if not OPENAI_ENABLED or not _oa:
        parts = re.split(r"(?<=[.!?])\s+", base)
        picks = [f"- {p.strip()}" for p in parts[:bullets] if p.strip()]
        return "\n".join(picks)[:600]
    try:
        r = _oa.chat.completions.create(
            model=MODEL_WEEKLY, temperature=0.2, max_tokens=180,
            messages=[
                {"role":"system","content":"You are a neutral EU policy analyst. Output bullets only."},
                {"role":"user","content":
                 f"Summarize in {language or 'EN'} using {bullets} concise bullets (≤{max_words} words total). "
                 "Focus on: what changed, scope, obligations, timelines, who is affected.\n\n"
                 f"TEXT:\n{base}"}
            ],
        )
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        print("[openai] short bullets error:", e)
        parts = re.split(r"(?<=[.!?])\s+", base)
        picks = [f"- {p.strip()}" for p in parts[:bullets] if p.strip()]
        return "\n".join(picks)[:600]

def domain_label(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc.replace("www.","")
    except Exception:
        return "source"

def fmt_date(d: dt.datetime|None, tzname="Europe/Amsterdam") -> str:
    if not d: return ""
    if pytz:
        try:
            tz = pytz.timezone(tzname)
            d = d.astimezone(tz)
        except Exception:
            pass
    return d.strftime("%Y-%m-%d")

def apa_like_ref(item: Dict[str,Any]) -> str:
    # APA-achtig: Titel. (YYYY-MM-DD). Site. URL
    title = item.get("title","").strip()
    date  = fmt_date(item.get("published_utc"))
    site  = domain_label(item.get("link",""))
    url   = item.get("link","").strip()
    core  = f"{title}. ({date}). {site}."
    if url: core += f" {url}"
    return core

# ---------- Google Docs ----------
def get_drive_service_oauth():
    if not GOOGLE_LIBS_OK:
        return None, None
    cid  = os.getenv("GOOGLE_OAUTH_CLIENT_ID","").strip()
    csec = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET","").strip()
    rtok = os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN","").strip()
    if not (cid and csec and rtok):
        print("[google] OAuth vars missing; skip Google Doc.")
        return None, None
    try:
        creds = Credentials(
            None,
            refresh_token=rtok,
            client_id=cid,
            client_secret=csec,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/documents",
            ],
        )
        drv = build("drive","v3",credentials=creds, cache_discovery=False)
        about = drv.about().get(fields="user").execute()
        email = about["user"]["emailAddress"]
        print(f"[google] OAuth OK; acting as: {email}")
        return drv, email
    except Exception as e:
        print("[google] OAuth error:", e)
        return None, None

def create_google_doc_from_html(drive, html: str, title: str,
                                folder_id: str|None, share_with: str|None) -> Tuple[str,str]:
    media = MediaIoBaseUpload(BytesIO(html.encode("utf-8")), mimetype="text/html", resumable=False)
    meta = {"name": title, "mimeType": "application/vnd.google-apps.document"}
    if folder_id: meta["parents"] = [folder_id]
    f = drive.files().create(
        body=meta, media_body=media,
        fields="id,webViewLink,parents", supportsAllDrives=True
    ).execute()
    fid = f["id"]; link = f["webViewLink"]
    if share_with:
        try:
            drive.permissions().create(
                fileId=fid, fields="id", supportsAllDrives=True,
                body={"type":"user","role":"reader","emailAddress":share_with}
            ).execute()
        except Exception as e:
            print("[google] share error:", e)
    return fid, link

def html_escape(t: str) -> str:
    return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def md_to_html(title_h1: str, briefing_html: str, refs: List[str], model_name: str) -> str:
    h = []
    h.append(f"<html><head><meta charset='utf-8'><title>{html_escape(title_h1)}</title></head><body>")
    h.append(f"<h1>{html_escape(title_h1)}</h1>")
    h.append("<h2>Weekly Briefing</h2>")
    h.append(f"<div>{briefing_html}</div>")
    if refs:
        h.append("<h2>References</h2><ol>")
        for r in refs:
            h.append(f"<li>{html_escape(r)}</li>")
        h.append("</ol>")
    h.append(f"<p><em>Generated via GitHub Actions with OpenAI (model: {html_escape(model_name)}).</em></p>")
    h.append("</body></html>")
    return "".join(h)

# ---------- Email ----------
def send_email(subject: str, body: str, to_addr: str):
    user = os.getenv("GMAIL_USER"); pwd = os.getenv("GMAIL_PASS")
    if not user or not pwd: raise RuntimeError("GMAIL_USER or GMAIL_PASS not set")
    if not to_addr: to_addr = user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"]=subject; msg["From"]=user; msg["To"]=to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(user,pwd); s.sendmail(user,[to_addr], msg.as_string())

# =====================================================================

def main():
    base = os.path.dirname(__file__)
    cfg = load_config(os.path.join(base, "config.yaml"))

    # Weekly knobs
    wk = cfg.get("weekly", {}) or {}
    window_days     = int(wk.get("window_days", 7))
    exec_top_n      = int(wk.get("exec_top_n", 50))
    exec_max_words  = int(wk.get("exec_max_words", 2500))
    summ = cfg.get("summary", {}) or {}
    per_item_bullets    = int(summ.get("per_item_bullets", 3))
    per_item_max_words  = int(summ.get("per_item_max_words", 80))

    # Ranking
    ranking = cfg.get("ranking", {}) or {}
    prefer_recent      = bool(ranking.get("prefer_recent", True))
    recent_hours_bonus = int(ranking.get("recent_hours_bonus", 72))
    min_score_required = float(ranking.get("min_score", 1))

    # Feeds & keywords
    feeds = list(cfg.get("feeds", []))
    keywords = cfg.get("keywords", [])
    language = cfg.get("language","EN")
    tz_name  = cfg.get("timezone","Europe/Amsterdam")
    email_to = (cfg.get("email") or {}).get("to") or os.getenv("GMAIL_USER") or ""

    # Time window
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    start = now - dt.timedelta(days=window_days)
    if pytz:
        try:
            tz = pytz.timezone(tz_name)
            label_end = now.astimezone(tz).strftime("%Y-%m-%d")
            label_start = start.astimezone(tz).strftime("%Y-%m-%d")
        except Exception:
            label_end = now.strftime("%Y-%m-%d"); label_start = start.strftime("%Y-%m-%d")
    else:
        label_end = now.strftime("%Y-%m-%d"); label_start = start.strftime("%Y-%m-%d")

    # Title paths
    iso = now.isocalendar()
    week_no = iso[1]
    title = f"Weekly — EU Finance & Defence — {label_start} to {label_end} (W{week_no})"
    subject = f"Weekly Digest — {label_start} → {label_end}"

    # Fetch & filter
    raw = []
    for u in feeds:
        try:
            raw.extend(fetch_entries(u))
        except Exception as e:
            print("[fetch] error", u, e)

    pool = []
    uniq = set()
    for e in raw:
        pu = e.get("published_utc")
        if pu is None or not (start <= pu <= now):
            continue
        if e.get("link") in uniq:  # de-dup this week
            continue
        uniq.add(e.get("link"))
        e["score"] = score_entry(e, keywords, recent_hours_bonus)
        if e["score"] < min_score_required:
            continue
        pool.append(e)

    # Sort: prefer newest then score (or opposite)
    def sort_key(ent):
        ts = ent["published_utc"].timestamp() if ent.get("published_utc") else 0.0
        return (-ts, -ent["score"]) if prefer_recent else (-ent["score"], -ts)
    pool.sort(key=sort_key)

    # Build shortlist: exec_top_n forms the “key items” ceiling; we can still include more in refs
    shortlist = pool[: max(exec_top_n, 60)]  # allow ~60 refs if available
    # Pre-compute terse bullets for model context (cheap and capped)
    for it in shortlist:
        base = it.get("summary") or it.get("title") or ""
        it["short"] = short_bullets(base, language, per_item_bullets, per_item_max_words)
    # Assign numeric ids for references
    for i, it in enumerate(shortlist, 1):
        it["id"] = i

    # Compose model context: only the first exec_top_n are “key”, remainder “also noted”
    key_items = shortlist[:exec_top_n]
    extra_items = shortlist[exec_top_n:exec_top_n+10]  # a few extras if model wants to mention
    # References (APA-like)
    refs = [apa_like_ref(it) for it in shortlist]

    # Build structured prompt
    def pack_item(it: Dict[str,Any]) -> str:
        date_s = fmt_date(it.get("published_utc"), tz_name)
        return f"[{it['id']}] {it['title']} ({date_s})\n{it['short']}\nLink: {it['link']}\n"

    key_text = "\n".join(pack_item(it) for it in key_items)
    extra_text = "\n".join(pack_item(it) for it in extra_items) if extra_items else ""

    # Ask model for ~2500-word synthesis with [id] citations
    briefing = ""
    if OPENAI_ENABLED and _oa:
        try:
            sysmsg = (
                "You are a senior EU policy analyst. Write a comprehensive weekly briefing "
                "in clear professional English. Use factual, neutral tone; no hype. "
                "Weave in up to the 50 key items and optionally a few extra items. "
                "Insert inline citation markers like [1], [2] referring to the numbered items provided. "
                "Do not fabricate sources. Structure with informative subheadings."
            )
            usrmsg = (
                f"TIME WINDOW: {label_start} to {label_end}\n\n"
                f"KEY ITEMS (use these; cite with [n]):\n{key_text}\n"
            )
            if extra_text:
                usrmsg += f"\nOPTIONAL EXTRAS (cite with [n] if you use them):\n{extra_text}\n"
            usrmsg += (
                f"\nOUTPUT REQUIREMENTS:\n"
                f"- Length target: ~{exec_max_words} words.\n"
                f"- Use subheadings that group themes (e.g., Markets, Banking, Insurance, Digital/Crypto, ESG, Institutions, Defence).\n"
                f"- Refer to items only with [n] markers; do not include raw URLs in the body.\n"
                f"- No bullet lists except sparingly; prefer narrative.\n"
            )
            r = _oa.chat.completions.create(
                model=MODEL_WEEKLY,
                temperature=0.2,
                max_tokens=5000,  # generous for ~2500 words; API may cap lower
                messages=[
                    {"role":"system","content": sysmsg},
                    {"role":"user","content": usrmsg},
                ],
            )
            briefing = (r.choices[0].message.content or "").strip()
        except Exception as e:
            print("[openai] weekly briefing error:", e)
            # Fallback: stitch concise lines
            parts = [f"[{it['id']}] {first_sentence(it.get('summary') or it['title'])}" for it in key_items]
            briefing = "Weekly highlights:\n" + "\n".join(parts)
    else:
        parts = [f"[{it['id']}] {first_sentence(it.get('summary') or it['title'])}" for it in key_items]
        briefing = "Weekly highlights:\n" + "\n".join(parts)

    # --- Write Markdown ---
    weekly_dir = os.path.join(base, "reports", "weekly")
    os.makedirs(weekly_dir, exist_ok=True)
    md_lines = [f"# {title}", "", "## Weekly Briefing", "", briefing, "", "## References", ""]
    for i, ref in enumerate(refs, 1):
        md_lines.append(f"{i}. {ref}")
    md_text = "\n".join(md_lines)
    md_name = f"{label_start}_to_{label_end}_W{week_no}.md"
    md_path = os.path.join(weekly_dir, md_name)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    # GitHub link (if available in Actions)
    server = os.getenv("GITHUB_SERVER_URL","https://github.com")
    repo   = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME","main")
    report_url = f"{server}/{repo}/blob/{branch}/reports/weekly/{md_name}" if repo else ""

    # --- Google Doc ---
    doc_link = ""
    drv, acct = get_drive_service_oauth()
    if drv:
        try:
            # Convert briefing with [n] markers and then append ordered references
            # Use simple HTML; Google will convert to Doc.
            # Convert line breaks to <p> blocks for the body.
            briefing_html = "".join(f"<p>{line}</p>" for line in briefing.splitlines() if line.strip())
            html = md_to_html(title, briefing_html, refs, MODEL_WEEKLY)
            folder_id = (os.getenv("GOOGLE_DOCS_FOLDER_ID") or "").strip() or None
            share_with = (os.getenv("GOOGLE_DOCS_SHARE_WITH") or "").strip() or None
            print("[google] creating weekly doc...")
            _, doc_link = create_google_doc_from_html(drv, html, title, folder_id, share_with)
            print("[google] doc created:", doc_link)
        except Exception as e:
            print("[google] doc error:", e)

    # --- Email (short cover note) ---
    body = [
        f"Weekly window: {label_start} → {label_end}",
        "",
        "Links:",
        f"- GitHub: {report_url}" if report_url else "- GitHub: (n/a)",
        f"- Google Doc: {doc_link}" if doc_link else "- Google Doc: (n/a)",
        "",
        "This is an automated weekly briefing compiled from EUR-Lex and EU institutional feeds.",
    ]
    send_email(subject, "\n".join(body), email_to)

    print("[weekly] Done.")
    print("Saved:", md_path)
    if report_url: print("GitHub:", report_url)
    if doc_link:   print("Google Doc:", doc_link)

if __name__ == "__main__":
    main()
