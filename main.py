#!/usr/bin/env python3
"""
EUR-Lex Daily Digest — with robust Google Docs (OAuth) logging

- Fetches items from feeds in config.yaml
- Scores + summarises (OpenAI if available)
- Categorises (rules → LLM)
- Writes Markdown report to reports/YYYY-MM-DD.md
- Creates a Google Doc (owned by YOUR Gmail via OAuth) and prints the link
- Emails an executive digest + compact per-category titles + links

Env (set via GitHub Actions step):
  OPENAI_API_KEY (optional)           OPENAI_MODEL (optional; default gpt-4o-mini)
  GMAIL_USER, GMAIL_PASS (for SMTP)
  GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN
  GOOGLE_DOCS_FOLDER_ID (optional)    GOOGLE_DOCS_SHARE_WITH (optional)
"""

import os, sys, yaml, feedparser, datetime as dt
from typing import List, Dict, Any, Tuple
from email.mime.text import MIMEText
import smtplib

# ----- optional libs -----
try:
    import pytz
except Exception:
    pytz = None

# ----- OpenAI -----
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_ENABLED = bool(os.getenv("OPENAI_API_KEY"))
if OPENAI_ENABLED:
    try:
        from openai import OpenAI
        _oa = OpenAI()
    except Exception as _e:
        print("[openai] import error:", _e)
        _oa = None
        OPENAI_ENABLED = False
else:
    _oa = None

# ----- Google (OAuth) -----
from io import BytesIO
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

def summarize_text(text: str, language: str) -> str:
    base = (text or "").strip()
    if not base:
        return ""
    if not OPENAI_ENABLED or not _oa:
        return base[:500] + ("…" if len(base) > 500 else "")
    try:
        r = _oa.chat.completions.create(
            model=DEFAULT_MODEL, temperature=0.2, max_tokens=180,
            messages=[
                {"role":"system","content":"You are a neutral EU legal analyst. Be concise and precise."},
                {"role":"user","content":
                 f"Summarize in {language or 'EN'} using 3–5 bullets (<=100 words). "
                 "Focus on what changed, scope, obligations, timelines, who is affected.\n\n"
                 f"TEXT:\n{base}"}
            ],
        )
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        print("[openai] summary error:", e)
        return base[:500] + ("…" if len(base) > 500 else "")

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

def score_entry(ent: Dict[str,Any], kws: List[str], recent_hours: int) -> float:
    s = float(keyword_match_count(ent["text"], kws))
    if recent_hours and ent.get("published_utc"):
        delta = dt.datetime.now(dt.timezone.utc) - ent["published_utc"]
        if delta.total_seconds() <= recent_hours*3600:
            s += 1.0
    if "uri=OJ:L" in (ent.get("source") or ""):
        s += 0.2
    return s

def build_categories(cfg: dict) -> List[Dict[str,Any]]:
    cats = []
    for c in (cfg.get("taxonomy",{}).get("categories",[]) or []):
        cats.append({"name": str(c.get("name","Other")),
                     "include": [str(x) for x in (c.get("include",[]) or [])]})
    if not any(c["name"]=="Other" for c in cats):
        cats.append({"name":"Other","include":[]})
    return cats

def rule_category(text: str, cats: List[Dict[str,Any]]) -> str:
    low = (text or "").lower()
    for c in cats:
        if c["name"]=="Other": continue
        for pat in c["include"]:
            if pat.lower() in low:
                return c["name"]
    return ""

# ---------------- Google Docs (OAuth only) ----------------

def get_drive_service_oauth():
    """Return (drive_service, account_email) or (None, None)."""
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

def md_to_html(title_h1: str, exec_syn: str,
               categories: List[Dict[str,Any]],
               items_by_cat: Dict[str,List[Dict[str,Any]]]) -> str:
    def esc(t: str) -> str:
        return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    def bullets_to_html(s: str) -> str:
        lines = [l.strip() for l in (s or "").splitlines() if l.strip()]
        items = []
        for l in lines:
            if l.startswith("-"): items.append(l[1:].strip())
            elif l.startswith("•"): items.append(l[1:].strip())
            else: items.append(l)
        if not items: return "<p>(no items)</p>"
        return "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>"

    html = [f"<html><head><meta charset='utf-8'><title>{esc(title_h1)}</title></head><body>"]
    html.append(f"<h1>{esc(title_h1)}</h1>")
    html.append("<h2>Executive Summary</h2>")
    html.append(bullets_to_html(exec_syn))
    html.append("<h2>Categories</h2>")
    for c in categories:
        name = c["name"]; items = items_by_cat.get(name, [])
        if not items: continue
        html.append(f"<h3>{esc(name)}</h3>")
        html.append("<ul>")
        for it in items:
            html.append(f"<li><strong>[{it['id']}]</strong> <a href='{esc(it['link'])}'>{esc(it['title'])}</a></li>")
        html.append("</ul>")
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

    feeds: List[str] = list(cfg.get("feeds",[]))
    keywords: List[str] = cfg.get("keywords",[])
    language: str = cfg.get("language","EN")
    mail_service: str = str(cfg.get("mail_service","gmail")).lower()
    tz_name: str = cfg.get("timezone","UTC")
    email_cfg = cfg.get("email") or {}
    email_to: str = email_cfg.get("to") or os.getenv("GMAIL_USER") or ""

    caps = cfg.get("caps",{}) or {}
    max_total     = int(caps.get("max_total",30))
    max_per_cat   = int(caps.get("max_per_category",10))
    min_per_cat   = int(caps.get("min_per_category",1))
    recent_hours  = int(cfg.get("recent_hours",72))

    cats_cfg = build_categories(cfg)
    labels = [c["name"] for c in cats_cfg]

    # Date / subject
    now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    local_dt = now_utc
    date_str = now_utc.strftime("%Y-%m-%d")
    if pytz:
        try:
            tz = pytz.timezone(tz_name)
            local_dt = now_utc.astimezone(tz)
            date_str = local_dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    subject = f"EUR-Lex Digest — {date_str}"
    doc_title = f"EUR-Lex Daily Digest — {date_str}"

    if not feeds:
        print("[digest] No feeds configured; exiting.")
        sys.exit(0)

    # Fetch + score
    pool: List[Dict[str,Any]] = []
    for u in feeds:
        try:
            for e in fetch_entries(u):
                e["score"] = score_entry(e, keywords, recent_hours)
                pool.append(e)
        except Exception as ex:
            print("[fetch] error", u, ex)
    pool.sort(key=lambda x: x["score"], reverse=True)
    shortlist = pool[: max_total*2]

    # Summaries
    for it in shortlist:
        base = it.get("summary") or it.get("title") or ""
        it["summary"] = summarize_text(base, language)

    # Categories
    for it in shortlist:
        cat = rule_category(it["text"], cats_cfg) or llm_choose_category(it["text"], labels)
        it["category"] = cat if cat in labels else "Other"

    # Bucket + caps
    buckets: Dict[str,List[Dict[str,Any]]] = {c["name"]:[] for c in cats_cfg}
    for it in shortlist: buckets[it["category"]].append(it)
    for name, items in buckets.items():
        items.sort(key=lambda x: x["score"], reverse=True)
        buckets[name] = items[:max_per_cat]

    selected: List[Dict[str,Any]] = []
    # Ensure min per category
    for c in cats_cfg:
        name = c["name"]
        if buckets[name]:
            selected.extend(buckets[name][:max(0, min_per_cat)])
    # Fill the rest best-score
    rest: List[Tuple[float,Dict[str,Any]]] = []
    for c in cats_cfg:
        for it in buckets[c["name"]][min_per_cat:]:
            rest.append((it["score"], it))
    rest.sort(key=lambda x: x[0], reverse=True)
    for _, it in rest:
        if len(selected) >= max_total: break
        selected.append(it)
    selected = selected[:max_total]
    for i,it in enumerate(selected,1): it["id"]=i

    by_cat: Dict[str,List[Dict[str,Any]]] = {c["name"]:[] for c in cats_cfg}
    for it in selected: by_cat[it["category"]].append(it)

    # Executive digest
    if selected:
        joined = "\n".join(f"[{it['id']}] ({it['category']}) {it['title']} — {it['summary']}" for it in selected)
        if OPENAI_ENABLED and _oa:
            try:
                r = _oa.chat.completions.create(
                    model=DEFAULT_MODEL, temperature=0.2, max_tokens=260,
                    messages=[
                        {"role":"system","content":"Produce 5 concise bullets citing [id] tokens."},
                        {"role":"user","content": f"Items:\n{joined}"},
                    ],
                )
                exec_syn = (r.choices[0].message.content or "").strip()
            except Exception as e:
                print("[openai] exec digest error:", e)
                exec_syn = "- Key items: " + ", ".join(f"[{it['id']}]" for it in selected[:5])
        else:
            exec_syn = "- Key items: " + ", ".join(f"[{it['id']}]" for it in selected[:5])
    else:
        exec_syn = "No relevant developments today."

    # Write Markdown (always)
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    md = [f"# EUR-Lex Daily Digest — {date_str}", "", "## Executive Summary", exec_syn, "", "## Categories",""]
    for c in cats_cfg:
        name = c["name"]; items = by_cat.get(name,[])
        if not items: continue
        md += [f"### {name}","", "#### Items",""]
        for it in items:
            md += [f"**[{it['id']}] [{it['title']}]({it['link']})**","", it["summary"], ""]
    md += ["---", f"_Generated by GitHub Actions with OpenAI (model: {DEFAULT_MODEL})._"]
    md_text = "\n".join(md)
    report_path = os.path.join(reports_dir, f"{date_str}.md")
    with open(report_path,"w",encoding="utf-8") as f:
        f.write(md_text)

    # Build GitHub link
    server = os.getenv("GITHUB_SERVER_URL","https://github.com")
    repo = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME","main")
    report_url = f"{server}/{repo}/blob/{branch}/reports/{date_str}.md" if repo else ""

    # Google Doc (OAuth only)
    doc_link = ""
    drv, acct = get_drive_service_oauth()
    if drv:
        try:
            folder_id = (os.getenv("GOOGLE_DOCS_FOLDER_ID") or "").strip() or None
            share_with = (os.getenv("GOOGLE_DOCS_SHARE_WITH") or "").strip() or None
            html = md_to_html(f"EUR-Lex Daily Digest — {date_str}", exec_syn, cats_cfg, by_cat)
            print("[google] creating doc...")
            _, doc_link = create_google_doc_from_html(drv, html, f"EUR-Lex Daily Digest — {date_str}",
                                                      folder_id, share_with)
            print("[google] doc created:", doc_link)
        except Exception as e:
            print("[google] creation failed:", e)
    else:
        print("[google] skipped (no OAuth).")

    # Email body
    lines = ["Executive Digest","----------------", exec_syn, ""]
    if report_url: lines.append(f"Full report (GitHub): {report_url}")
    if doc_link:   lines.append(f"Full report (Google Doc): {doc_link}")
    lines += ["", "Per-category titles","-------------------"]
    for c in cats_cfg:
        name = c["name"]; items = by_cat.get(name,[])
        if not items: continue
        lines.append(f"{name}:")
        for it in items:
            lines.append(f"- {it['title']}  ({it['link']})")
        lines.append("")
    body = "\n".join(lines)

    # Send email
    if mail_service == "gmail":
        send_email_gmail(subject, body, email_to)
    else:
        raise RuntimeError(f"Unsupported mail_service: {mail_service}")

    print("[done] Digest sent. Markdown:", report_path)
    if doc_link: print("[done] Google Doc:", doc_link)

if __name__ == "__main__":
    main()
