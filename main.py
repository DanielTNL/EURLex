#!/usr/bin/env python3
"""
EUR-Lex Daily Digest — ranking controls (age cutoff, min score, de-dup) + summaries + Google Doc.

New in this build:
- ranking.max_age_days: drop items older than N days
- ranking.min_score: require at least this keyword score (+ bonus) to keep
- ranking.prefer_recent: stable sort favors newer items on ties
- ranking.recent_hours_bonus: window that adds +1 score for recency
- dedupe.enabled + dedupe.path: remember seen links across days
"""

import os, sys, json, yaml, feedparser, datetime as dt, re
from typing import List, Dict, Any, Tuple
from email.mime.text import MIMEText
import smtplib
from io import BytesIO

# ---------- optional tz ----------
try:
    import pytz
except Exception:
    pytz = None

# ---------- OpenAI ----------
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_ENABLED = bool(os.getenv("OPENAI_API_KEY"))
if OPENAI_ENABLED:
    try:
        from openai import OpenAI
        _oa = OpenAI()
        print(f"[openai] enabled; model={DEFAULT_MODEL}")
    except Exception as _e:
        print("[openai] init error:", _e)
        _oa = None
        OPENAI_ENABLED = False
else:
    _oa = None
    print("[openai] disabled")

# ---------- Google (OAuth) ----------
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

def _first_sentence(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    m = re.search(r"(.+?[.!?])(\s|$)", s)
    return m.group(1) if m else s[:140]

def summarize_text(text: str, language: str) -> str:
    """Return 3–5 bullet points (text with leading '-' bullets)."""
    base = (text or "").strip()
    if not base:
        return ""
    if not OPENAI_ENABLED or not _oa:
        # simple fallback: first 4 sentences -> bullets
        sents = re.split(r"(?<=[.!?])\s+", base)
        picks = [f"- {s.strip()}" for s in sents[:4] if s.strip()]
        return "\n".join(picks)[:800]
    try:
        r = _oa.chat.completions.create(
            model=DEFAULT_MODEL, temperature=0.2, max_tokens=220,
            messages=[
                {"role":"system","content":"You are a neutral EU legal analyst. Output 3–5 concise bullets. No preface."},
                {"role":"user","content":
                 f"Summarize in {language or 'EN'} using 3–5 bullets (<=120 words total). "
                 "Focus on: what's new/changed, scope, obligations, timelines, who is affected.\n\n"
                 f"TEXT:\n{base}"}
            ],
        )
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        print("[openai] per-item summary error:", e)
        sents = re.split(r"(?<=[.!?])\s+", base)
        picks = [f"- {s.strip()}" for s in sents[:4] if s.strip()]
        return "\n".join(picks)[:800]

def llm_choose_category(text: str, labels: List[str]) -> str:
    if not OPENAI_ENABLED or not _oa:
        return "Other"
    try:
        r = _oa.chat.completions.create(
            model=DEFAULT_MODEL, temperature=0.0, max_tokens=12,
            messages=[
                {"role":"system","content":"Choose the single best label. Output only the label."},
                {"role":"user","content":f"Labels: {', '.join(labels)}\nText: {text}"},
            ],
        )
        out = (r.choices[0].message.content or "").strip()
        return out if out in labels else "Other"
    except Exception as e:
        print("[openai] category error:", e)
        return "Other"

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
            "published_utc": published, "source": url,
            "text": f"{title} {summary}"
        })
    return out

# ---------------- Ranking controls ----------------

def within_max_age(d: dt.datetime|None, max_days: int) -> bool:
    if max_days <= 0 or d is None:
        return True if d is None else True  # no cutoff if disabled or missing date
    age = (dt.datetime.now(dt.timezone.utc) - d).days
    return age <= max_days

def score_entry(ent: Dict[str,Any], kws: List[str], recent_hours_bonus: int) -> float:
    s = float(keyword_match_count(ent["text"], kws))
    if recent_hours_bonus and ent.get("published_utc"):
        delta = dt.datetime.now(dt.timezone.utc) - ent["published_utc"]
        if delta.total_seconds() <= recent_hours_bonus*3600:
            s += 1.0
    if "uri=OJ:L" in (ent.get("source") or ""):
        s += 0.2
    return s

# ---------------- De-dup store ----------------

def load_seen(path: str) -> set[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_seen(path: str, items: set[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(items), f, ensure_ascii=False, indent=2)

# ---------------- Google Docs helpers ----------------

def get_drive_service_oauth():
    if not GOOGLE_LIBS_OK:
        print("[google] libs not installed; skipping Google Doc creation.")
        return None, None
    cid  = os.getenv("GOOGLE_OAUTH_CLIENT_ID","").strip()
    csec = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET","").strip()
    rtok = os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN","").strip()
    if not (cid and csec and rtok):
        print("[google] OAuth env vars missing; skipping Google Doc creation.")
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

def _bullets_to_html(s: str) -> str:
    lines = [l.strip() for l in (s or "").splitlines() if l.strip()]
    items = []
    for l in lines:
        if l.startswith("-"): items.append(l[1:].strip())
        elif l.startswith("•"): items.append(l[1:].strip())
        else: items.append(l)
    if not items: return "<p>(no items)</p>"
    return "<ul>" + "".join(f"<li>{l}</li>" for l in items) + "</ul>"

def md_to_html(title_h1: str, exec_bullets: List[str], exec_paragraph: str,
               categories: List[Dict[str,Any]],
               items_by_cat: Dict[str,List[Dict[str,Any]]]) -> str:
    esc = lambda t: (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    html = [f"<html><head><meta charset='utf-8'><title>{esc(title_h1)}</title></head><body>"]
    html.append(f"<h1>{esc(title_h1)}</h1>")
    html.append("<h2>Executive Summary</h2>")
    if exec_bullets:
        html.append("<h3>Key Items</h3><ul>")
        for b in exec_bullets:
            html.append(f"<li>{esc(b)}</li>")
        html.append("</ul>")
    if exec_paragraph:
        html.append("<h3>Briefing (~200 words)</h3>")
        html.append(f"<p>{esc(exec_paragraph)}</p>")
    html.append("<h2>Categories</h2>")
    for c in categories:
        name = c["name"]; items = items_by_cat.get(name, [])
        if not items: continue
        html.append(f"<h3>{esc(name)}</h3>")
        for it in items:
            html.append(f"<p><strong>[{it['id']}] <a href='{esc(it['link'])}'>{esc(it['title'])}</a></strong></p>")
            html.append(_bullets_to_html(it.get("summary","")))
    html.append(f"<p><em>Generated by GitHub Actions with OpenAI (model: {esc(DEFAULT_MODEL)}).</em></p>")
    html.append("</body></html>")
    return "".join(html)

def create_google_doc_from_html(drive, html: str, title: str,
                                folder_id: str|None, share_with: str|None) -> tuple[str,str]:
    media = MediaIoBaseUpload(BytesIO(html.encode("utf-8")), mimetype="text/html", resumable=False)
    meta = {"name": title, "mimeType": "application/vnd.google-apps.document"}
    if folder_id: meta["parents"] = [folder_id]
    f = drive.files().create(
        body=meta, media_body=media,
        fields="id,webViewLink,parents",
        supportsAllDrives=True
    ).execute()
    fid = f["id"]; link = f["webViewLink"]
    if share_with:
        try:
            drive.permissions().create(
                fileId=fid,
                body={"type":"user","role":"reader","emailAddress":share_with},
                fields="id",
                supportsAllDrives=True
            ).execute()
        except Exception as e:
            print("[google] share error:", e)
    return fid, link

# ---------------- Email ----------------

def send_email_gmail(subject: str, body: str, to_addr: str):
    user = os.getenv("GMAIL_USER"); pwd = os.getenv("GMAIL_PASS")
    if not user or not pwd: raise RuntimeError("GMAIL_USER or GMAIL_PASS not set")
    if not to_addr: to_addr = user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"]=subject; msg["From"]=user; msg["To"]=to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(user,pwd); s.sendmail(user,[to_addr], msg.as_string())

# =====================================================================

def main():
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    cfg = load_config(cfg_path)

    # Core config
    feeds: List[str] = list(cfg.get("feeds",[]))
    keywords: List[str] = cfg.get("keywords",[])
    language: str = cfg.get("language","EN")
    mail_service: str = str(cfg.get("mail_service","gmail")).lower()
    tz_name: str = cfg.get("timezone","Europe/Amsterdam")
    email_cfg = cfg.get("email") or {}
    email_to: str = email_cfg.get("to") or os.getenv("GMAIL_USER") or ""

    # Caps & ranking knobs
    caps = cfg.get("caps",{}) or {}
    max_total     = int(caps.get("max_total",30))
    max_per_cat   = int(caps.get("max_per_category",10))
    min_per_cat   = int(caps.get("min_per_category",1))

    rk    = cfg.get("ranking",{}) or {}
    max_age_days        = int(rk.get("max_age_days", 0))          # 0 means no cutoff
    recent_hours_bonus  = int(rk.get("recent_hours_bonus", 72))
    prefer_recent       = bool(rk.get("prefer_recent", True))
    min_score_required  = float(rk.get("min_score", 0))

    # De-dup
    dedupe_cfg = cfg.get("dedupe",{}) or {}
    dedupe_enabled = bool(dedupe_cfg.get("enabled", True))
    seen_path = os.path.join(os.path.dirname(__file__), str(dedupe_cfg.get("path","state/seen.json")))
    seen = load_seen(seen_path) if dedupe_enabled else set()

    # Taxonomy
    def build_categories(cfg: dict) -> List[Dict[str,Any]]:
        cats = []
        for c in (cfg.get("taxonomy",{}).get("categories",[]) or []):
            cats.append({"name": str(c.get("name","Other")),
                         "include": [str(x) for x in (c.get("include",[]) or [])]})
        if not any(c["name"]=="Other" for c in cats):
            cats.append({"name":"Other","include":[]})
        return cats

    cats_cfg = build_categories(cfg)
    labels = [c["name"] for c in cats_cfg]

    # Date / subject
    now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")
    if pytz:
        try:
            tz = pytz.timezone(tz_name)
            date_str = now_utc.astimezone(tz).strftime("%Y-%m-%d")
        except Exception:
            pass
    subject = f"EUR-Lex Digest — {date_str}"
    doc_title = f"EUR-Lex Daily Digest — {date_str}"

    if not feeds:
        print("[digest] No feeds configured; exiting.")
        sys.exit(0)

    # Fetch → filter by age → score
    raw_count = 0
    pool: List[Dict[str,Any]] = []
    for u in feeds:
        try:
            items = fetch_entries(u)
            raw_count += len(items)
            for e in items:
                if not within_max_age(e.get("published_utc"), max_age_days):
                    continue
                e["score"] = score_entry(e, keywords, recent_hours_bonus)
                if e["score"] < min_score_required:
                    continue
                pool.append(e)
        except Exception as ex:
            print("[fetch] error", u, ex)

    # Remove seen items (by link)
    if dedupe_enabled and seen:
        pool = [e for e in pool if e.get("link") not in seen]

    # Sort: prefer recent then score, else score then date
    def sort_key(e):
        pu = e.get("published_utc")
        pu_key = pu.timestamp() if isinstance(pu, dt.datetime) else 0.0
        if prefer_recent:
            return (0 if pu is None else -1, -pu_key, -e["score"])
        else:
            return (-e["score"], -pu_key)

    pool.sort(key=sort_key)

    # Summarize shortlisted (limit work)
    shortlist = pool[: max_total*2]
    for it in shortlist:
        base = it.get("summary") or it.get("title") or ""
        it["summary"] = summarize_text(base, language)

    # Categories
    def rule_category(text: str, cats: List[Dict[str,Any]]) -> str:
        low = (text or "").lower()
        for c in cats:
            if c["name"]=="Other": continue
            for pat in c["include"]:
                if pat.lower() in low:
                    return c["name"]
        return ""

    for it in shortlist:
        cat = rule_category(it["text"], cats_cfg) or llm_choose_category(it["text"], labels)
        it["category"] = cat if cat in labels else "Other"

    # Buckets & caps
    buckets: Dict[str,List[Dict[str,Any]]] = {c["name"]:[] for c in cats_cfg}
    for it in shortlist: buckets[it["category"]].append(it)
    for name, items in buckets.items():
        items.sort(key=sort_key)
        buckets[name] = items[:max_per_cat]

    selected: List[Dict[str,Any]] = []
    # Ensure min per category
    for c in cats_cfg:
        name = c["name"]
        if buckets[name]:
            selected.extend(buckets[name][:max(0, min_per_cat)])
    # Fill the rest by best sort order
    rest: List[Dict[str,Any]] = []
    for c in cats_cfg:
        rest.extend(buckets[c["name"]][min_per_cat:])
    rest.sort(key=sort_key)
    for it in rest:
        if len(selected) >= max_total: break
        selected.append(it)
    selected = selected[:max_total]
    for i,it in enumerate(selected,1): it["id"]=i

    # Record as seen
    if dedupe_enabled:
        for it in selected:
            if it.get("link"): seen.add(it["link"])
        save_seen(seen_path, seen)

    # Group by category
    by_cat: Dict[str,List[Dict[str,Any]]] = {c["name"]:[] for c in cats_cfg}
    for it in selected: by_cat[it["category"]].append(it)

    # Executive Summary bullets & paragraph (unchanged from your last working version)
    EXEC_TOP_N = min(5, len(selected))
    top_items = selected[:EXEC_TOP_N]
    def bullets_from_item(it):
        arr = [l.strip()[1:].strip() for l in it["summary"].splitlines() if l.strip().startswith(("-", "•"))]
        return arr[0] if arr else _first_sentence(it["summary"]) or it["title"]

    exec_bullets = [f"[{it['id']}] {bullets_from_item(it)}" for it in top_items]
    if OPENAI_ENABLED and _oa and top_items:
        try:
            items_text = "\n".join(f"[{it['id']}] {it['title']}\n{it['summary']}" for it in top_items)
            r = _oa.chat.completions.create(
                model=DEFAULT_MODEL, temperature=0.2, max_tokens=320,
                messages=[
                    {"role":"system","content":"Write ~200 words, neutral, structured, no fluff. Refer to items with [id]."},
                    {"role":"user","content": f"Synthesize the key themes and implications across these items:\n\n{items_text}"}
                ],
            )
            exec_paragraph = (r.choices[0].message.content or "").strip()
        except Exception as e:
            print("[openai] exec paragraph error:", e)
            exec_paragraph = "Key themes: " + "; ".join(bullets_from_item(it) for it in top_items)
    else:
        exec_paragraph = "Key themes: " + "; ".join(bullets_from_item(it) for it in top_items)

    # Markdown report with per-item bullets
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    md = [f"# EUR-Lex Daily Digest — {date_str}", "",
          "## Executive Summary", "",
          "### Key Items"] + ([f"- {b}" for b in exec_bullets] or ["- (none)"])
    if exec_paragraph:
        md += ["", "### Briefing (~200 words)", "", exec_paragraph, ""]
    md += ["## Categories",""]
    for c in cats_cfg:
        name = c["name"]; items = by_cat.get(name,[])
        if not items: continue
        md += [f"### {name}",""]
        for it in items:
            md += [f"**[{it['id']}] [{it['title']}]({it['link']})**","", it["summary"], ""]
    md += ["---", f"_Generated by GitHub Actions with OpenAI (model: {DEFAULT_MODEL})._"]
    md_text = "\n".join(md)
    report_path = os.path.join(reports_dir, f"{date_str}.md")
    with open(report_path,"w",encoding="utf-8") as f:
        f.write(md_text)

    # Build GitHub and Google Doc
    server = os.getenv("GITHUB_SERVER_URL","https://github.com")
    repo = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME","main")
    report_url = f"{server}/{repo}/blob/{branch}/reports/{date_str}.md" if repo else ""

    def get_drive_service_oauth_wrapper():
        return get_drive_service_oauth()

    doc_link = ""
    drv, acct = get_drive_service_oauth_wrapper()
    if drv:
        try:
            folder_id = (os.getenv("GOOGLE_DOCS_FOLDER_ID") or "").strip() or None
            share_with = (os.getenv("GOOGLE_DOCS_SHARE_WITH") or "").strip() or None
            html = md_to_html(f"EUR-Lex Daily Digest — {date_str}", exec_bullets, exec_paragraph, cats_cfg, by_cat)
            print("[google] creating doc...")
            _, doc_link = create_google_doc_from_html(drv, html, f"EUR-Lex Daily Digest — {date_str}", folder_id, share_with)
            print("[google] doc created:", doc_link)
        except Exception as e:
            print("[google] creation failed:", e)
    else:
        print("[google] skipped (no OAuth).")

    # Email body
    lines = ["Executive Summary","----------------"]
    if exec_bullets: lines += [f"- {b}" for b in exec_bullets]
    if exec_paragraph: lines += ["", exec_paragraph]
    if report_url: lines += ["", f"Full report (GitHub): {report_url}"]
    if doc_link:   lines += [f"Full report (Google Doc): {doc_link}"]
    lines += ["", "Per-category titles","-------------------"]
    for c in cats_cfg:
        name = c["name"]; items = by_cat.get(name,[])
        if not items: continue
        lines.append(f"{name}:")
        for it in items:
            lines.append(f"- {it['title']}  ({it['link']})")
        lines.append("")
    body = "\n".join(lines)

    if mail_service == "gmail":
        send_email_gmail(subject, body, email_to)
    else:
        raise RuntimeError(f"Unsupported mail_service: {mail_service}")

    print(f"[done] Pulled {raw_count} entries; kept {len(selected)} after age/score/dedupe filters.")
    print("[done] Markdown:", report_path)
    if doc_link: print("[done] Google Doc:", doc_link)

if __name__ == "__main__":
    main()
