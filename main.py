#!/usr/bin/env python3
"""
EUR-Lex Daily Digest — structured + Google Docs
-----------------------------------------------

- Fetch feeds, score & filter, summarise with OpenAI (gpt-4o-mini by default)
- Categorise with hybrid rules → LLM fallback
- Build per-category syntheses + top executive digest
- Write Markdown report to reports/YYYY-MM-DD.md
- Create a Google Doc (HTML converted via Drive API) and share it
- Email a concise digest + links to GitHub report and Google Doc

Secrets/Vars expected (GitHub Actions):
  OPENAI_API_KEY               (optional but recommended)
  OPENAI_MODEL                 (optional; defaults to gpt-4o-mini)
  GMAIL_USER, GMAIL_PASS       (for SMTP)  OR  Mailgun secrets if you use Mailgun
  GOOGLE_SERVICE_ACCOUNT_JSON  (required for Google Doc)
  GOOGLE_DOCS_FOLDER_ID        (optional; Drive folder ID)
  GOOGLE_DOCS_SHARE_WITH       (optional; email to share new doc with)

Config (config.yaml):
  feeds, keywords, language, timezone, mail_service, email.to
  caps: {max_total, max_per_category, min_per_category}
  recent_hours
  taxonomy.categories: [{name, include: [keywords]}]
"""

import os, sys, yaml, feedparser
import datetime as dt
from typing import List, Dict, Any, Tuple
from email.mime.text import MIMEText
import smtplib

try:
    import pytz  # optional
except ImportError:
    pytz = None

# ---------- OpenAI (new SDK) ----------
OPENAI_ENABLED = bool(os.getenv("OPENAI_API_KEY"))
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
if OPENAI_ENABLED:
    try:
        from openai import OpenAI  # type: ignore
        _oa_client = OpenAI()
    except Exception:
        OPENAI_ENABLED = False
        _oa_client = None
else:
    _oa_client = None

# ---------- Google (Drive API for Docs conversion) ----------
import json
from io import BytesIO
try:
    from google.oauth2 import service_account  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.http import MediaIoBaseUpload  # type: ignore
except Exception:
    service_account = None
    build = None
    MediaIoBaseUpload = None


# ------------------ Helpers ------------------

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def keyword_match_count(text: str, keywords: List[str]) -> int:
    low = text.lower()
    return sum(1 for kw in (keywords or []) if kw.lower() in low)

def summarize_text(text: str, language: str, max_chars: int = 4000) -> str:
    snippet = (text or "").strip()
    if not snippet:
        return ""
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "…"

    if not OPENAI_ENABLED or _oa_client is None:
        return snippet[:500] + ("…" if len(snippet) > 500 else "")

    try:
        resp = _oa_client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=0.2,
            max_tokens=180,
            messages=[
                {"role": "system",
                 "content": ("You are an analyst summarizing EU legal documents. "
                             "Be factual, neutral, concise. Do not invent facts.")},
                {"role": "user",
                 "content": (f"Summarize in {language if language else 'EN'} "
                             "using 3–5 bullet points (<=100 words). "
                             "Focus on: what changed, scope, obligations, dates/timelines, who is affected.\n\n"
                             f"Document text:\n{snippet}")},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print("OpenAI summary error:", exc)
        return snippet[:500] + ("…" if len(snippet) > 500 else "")

def llm_choose_category(text: str, category_names: List[str]) -> str:
    if not OPENAI_ENABLED or _oa_client is None:
        return "Other"
    try:
        joined = ", ".join(category_names)
        resp = _oa_client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=0.0,
            max_tokens=10,
            messages=[
                {"role": "system",
                 "content": "Choose a single best category from a fixed list. Output only the label."},
                {"role": "user",
                 "content": (f"Categories: {joined}\n\n"
                             f"Pick the single best category for this title+summary:\n{text}")},
            ],
        )
        label = (resp.choices[0].message.content or "").strip()
        return label if label in category_names else "Other"
    except Exception as exc:
        print("OpenAI category error:", exc)
        return "Other"

def fetch_feed_entries(url: str) -> List[Dict[str, Any]]:
    parsed = feedparser.parse(url)
    out = []
    for e in parsed.entries:
        title = e.get("title", "") or ""
        summary = e.get("summary", "") or e.get("description", "") or ""
        link = e.get("link", "") or ""
        published = None
        if getattr(e, "published_parsed", None):
            try:
                t = e.published_parsed
                published = dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
            except Exception:
                pass
        out.append({"title": title, "summary": summary, "link": link,
                    "published_utc": published, "source": url,
                    "text": f"{title} {summary}"})
    return out

def score_entry(ent: Dict[str, Any], keywords: List[str], recent_hours: int) -> float:
    s = float(keyword_match_count(ent["text"], keywords))
    if recent_hours and ent.get("published_utc"):
        delta = dt.datetime.now(dt.timezone.utc) - ent["published_utc"]
        if delta.total_seconds() <= recent_hours * 3600:
            s += 1.0
    if "uri=OJ:L" in (ent.get("source") or ""):
        s += 0.2
    return s

def sanitize_md(s: str) -> str:
    return (s or "").replace("\r", "")

def build_category_map(cfg: dict) -> List[Dict[str, Any]]:
    cats = []
    for c in (cfg.get("taxonomy", {}).get("categories", []) or []):
        cats.append({"name": str(c.get("name", "Other")),
                     "include": [str(x) for x in (c.get("include", []) or [])]})
    if not any(c["name"] == "Other" for c in cats):
        cats.append({"name": "Other", "include": []})
    return cats

def rule_category_for(text: str, cats: List[Dict[str, Any]]) -> str:
    low = text.lower()
    for c in cats:
        if c["name"] == "Other":
            continue
        for pat in c["include"]:
            if pat.lower() in low:
                return c["name"]
    return ""

def category_synthesis(category: str, items: List[Dict[str, Any]]) -> str:
    if not items:
        return ""
    if not OPENAI_ENABLED or _oa_client is None:
        ids = ", ".join(f"[{it['id']}]" for it in items[:3])
        return f"- Notable items: {ids}"
    lines = [f"[{it['id']}] {it['title']} — {it['summary']}" for it in items]
    joined = "\n".join(lines)
    try:
        resp = _oa_client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=0.2,
            max_tokens=220,
            messages=[
                {"role": "system",
                 "content": ("Write 2–4 concise bullets for this category. "
                             "Cite items using their [id] tokens. Be factual, no repetition.")},
                {"role": "user",
                 "content": f"Category: {category}\nItems:\n{joined}"},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print("OpenAI category synthesis error:", exc)
        return ""

def executive_digest(all_items: List[Dict[str, Any]]) -> str:
    if not all_items:
        return "No relevant developments today."
    if not OPENAI_ENABLED or _oa_client is None:
        top = ", ".join(f"[{it['id']}]" for it in all_items[:5])
        return f"- Key items: {top}"
    joined = "\n".join(
        f"[{it['id']}] ({it['category']}) {it['title']} — {it['summary']}" for it in all_items
    )
    try:
        resp = _oa_client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=0.2,
            max_tokens=260,
            messages=[
                {"role": "system",
                 "content": ("Produce a 5-bullet executive digest. "
                             "Each bullet must cite one or more [id] tokens.")},
                {"role": "user",
                 "content": f"Items:\n{joined}"},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print("OpenAI executive digest error:", exc)
        return ""

# ----------- Google Drive (create Google Doc by HTML conversion) --------------

def get_drive_service():
    if service_account is None or build is None or MediaIoBaseUpload is None:
        return None
    json_str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not json_str:
        return None
    try:
        info = json.loads(json_str)
        scopes = ["https://www.googleapis.com/auth/drive"]
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        print("Google auth error:", exc)
        return None

def create_google_doc_from_html(drive, html_body: str, title: str,
                                folder_id: str | None, share_with: str | None) -> tuple[str, str]:
    media = MediaIoBaseUpload(BytesIO(html_body.encode("utf-8")),
                              mimetype="text/html", resumable=False)
    meta = {"name": title, "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        meta["parents"] = [folder_id]
    file = drive.files().create(body=meta, media_body=media,
                                fields="id,webViewLink").execute()
    file_id = file["id"]
    link = file["webViewLink"]
    if share_with:
        try:
            drive.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": "reader", "emailAddress": share_with},
                fields="id"
            ).execute()
        except Exception as exc:
            print("Share error:", exc)
    return file_id, link

def md_to_html(title_h1: str, exec_syn: str,
               categories: List[Dict[str, Any]],
               items_by_cat: Dict[str, List[Dict[str, Any]]]) -> str:
    def bullets_to_html(s: str) -> str:
        lines = [l.strip() for l in (s or "").splitlines() if l.strip()]
        # treat lines that start with '-' or '•' as bullets
        items = []
        for l in lines:
            if l.startswith("-"):
                items.append(l[1:].strip())
            elif l.startswith("•"):
                items.append(l[1:].strip())
            else:
                items.append(l)
        if not items:
            return "<p>(no items)</p>"
        return "<ul>" + "".join(f"<li>{escape_html(x)}</li>" for x in items) + "</ul>"

    def escape_html(t: str) -> str:
        return (t.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))

    html = [f"<html><head><meta charset='utf-8'><title>{escape_html(title_h1)}</title></head><body>"]
    html.append(f"<h1>{escape_html(title_h1)}</h1>")
    html.append("<h2>Executive Summary</h2>")
    html.append(bullets_to_html(exec_syn))

    html.append("<h2>Categories</h2>")
    for c in categories:
        name = c["name"]
        items = items_by_cat.get(name, [])
        if not items:
            continue
        html.append(f"<h3>{escape_html(name)}</h3>")
        # Category synthesis
        syn = category_synthesis(name, items)
        html.append(bullets_to_html(syn))
        # Items
        html.append("<ul>")
        for it in items:
            title = escape_html(it["title"])
            link = escape_html(it["link"])
            html.append(f"<li><strong>[{it['id']}]</strong> <a href='{link}'>{title}</a></li>")
        html.append("</ul>")

    html.append(f"<p><em>Generated by GitHub Actions with OpenAI (model: {escape_html(DEFAULT_MODEL)}).</em></p>")
    html.append("</body></html>")
    return "".join(html)


# ------------------ Email ------------------

def send_email_gmail(subject: str, body: str, to_addr: str) -> None:
    user = os.getenv("GMAIL_USER"); password = os.getenv("GMAIL_PASS")
    if not user or not password:
        raise RuntimeError("GMAIL_USER or GMAIL_PASS not set")
    if not to_addr:
        to_addr = user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject; msg["From"] = user; msg["To"] = to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [to_addr], msg.as_string())

def send_email_mailgun(subject: str, body: str) -> None:
    import requests
    api_key = os.getenv("MAILGUN_API_KEY"); domain = os.getenv("MAILGUN_DOMAIN")
    sender = os.getenv("MAILGUN_FROM"); recipient = os.getenv("MAILGUN_TO")
    if not all([api_key, domain, sender, recipient]):
        raise RuntimeError("Mailgun credentials incomplete")
    url = f"https://api.mailgun.net/v3/{domain}/messages"
    resp = requests.post(url, auth=("api", api_key),
                         data={"from": sender, "to": [recipient], "subject": subject, "text": body},
                         timeout=20)
    resp.raise_for_status()


# ------------------ Main ------------------

def main() -> None:
    # Load config
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    try:
        cfg = load_config(cfg_path)
    except Exception as exc:
        print(f"Failed to load config: {exc}"); sys.exit(1)

    feeds: List[str] = list(cfg.get("feeds", []))
    keywords: List[str] = cfg.get("keywords", [])
    language: str = cfg.get("language", "EN")
    mail_service: str = str(cfg.get("mail_service", "gmail")).lower()
    tz_name: str = cfg.get("timezone", "UTC")
    email_cfg = cfg.get("email") or {}
    email_to: str = email_cfg.get("to") or os.getenv("EMAIL_TO") or os.getenv("GMAIL_USER") or ""

    caps = cfg.get("caps", {}) or {}
    max_total = int(caps.get("max_total", 30))
    max_per_cat = int(caps.get("max_per_category", 10))
    min_per_cat = int(caps.get("min_per_category", 1))
    recent_hours = int(cfg.get("recent_hours", 72))

    cats_cfg = build_category_map(cfg)
    cat_names = [c["name"] for c in cats_cfg]

    if not feeds:
        print("No feeds configured; exiting."); sys.exit(0)

    # Subject date (local)
    now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")
    local_dt = now_utc
    if pytz is not None:
        try:
            tz = pytz.timezone(tz_name)
            local_dt = now_utc.astimezone(tz)
            date_str = local_dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    subject = f"EUR-Lex Digest — {date_str}"
    doc_title = f"EUR-Lex Daily Digest — {date_str}"

    # Fetch + score
    pool: List[Dict[str, Any]] = []
    for url in feeds:
        try:
            for ent in fetch_feed_entries(url):
                ent["score"] = score_entry(ent, keywords, recent_hours)
                pool.append(ent)
        except Exception as exc:
            print(f"Error fetching {url}: {exc}")

    pool.sort(key=lambda x: x["score"], reverse=True)
    shortlist = pool[: max_total * 2]

    # Item summaries
    for it in shortlist:
        base = it.get("summary") or it.get("title") or ""
        it["summary"] = summarize_text(base, language)

    # Categorise
    for it in shortlist:
        cat = rule_category_for(it["text"], cats_cfg) or llm_choose_category(it["text"], cat_names)
        it["category"] = cat if cat in cat_names else "Other"

    # Per-category buckets + caps
    buckets: Dict[str, List[Dict[str, Any]]] = {c["name"]: [] for c in cats_cfg}
    for it in shortlist:
        buckets[it["category"]].append(it)
    for name, items in buckets.items():
        items.sort(key=lambda x: x["score"], reverse=True)
        buckets[name] = items[:max_per_cat]

    # Ensure min_per_cat, then overall cap
    selected: List[Dict[str, Any]] = []
    for c in cats_cfg:
        name = c["name"]
        if buckets[name]:
            selected.extend(buckets[name][:min(len(buckets[name]), max(min_per_cat, 0))])
    remainder: List[Tuple[float, Dict[str, Any]]] = []
    for c in cats_cfg:
        name = c["name"]
        for it in buckets[name][min_per_cat:]:
            remainder.append((it["score"], it))
    remainder.sort(key=lambda x: x[0], reverse=True)
    for _, it in remainder:
        if len(selected) >= max_total:
            break
        selected.append(it)

    # Assign ids for references and rebuild per-category
    selected = selected[:max_total]
    for i, it in enumerate(selected, 1):
        it["id"] = i
    by_cat: Dict[str, List[Dict[str, Any]]] = {c["name"]: [] for c in cats_cfg}
    for it in selected:
        by_cat[it["category"]].append(it)

    # Syntheses
    exec_syn = executive_digest(selected)

    # Markdown report on disk
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    md_lines = [f"# EUR-Lex Daily Digest — {date_str}", "",
                "## Executive Summary", exec_syn, "",
                "## Categories", ""]
    for c in cats_cfg:
        name = c["name"]; items = by_cat.get(name, [])
        if not items: continue
        md_lines += [f"### {name}", ""]
        md_lines += [category_synthesis(name, items), ""]
        md_lines += ["#### Items", ""]
        for it in items:
            md_lines += [f"**[{it['id']}] [{it['title']}]({it['link']})**", "", it["summary"], ""]
    md_lines += ["---", f"_Generated by GitHub Actions with OpenAI (model: {DEFAULT_MODEL})._"]
    md = "\n".join(md_lines)
    report_path = os.path.join(reports_dir, f"{date_str}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)

    # GitHub link for the Markdown report
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repo = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME", "main")
    report_url = f"{server}/{repo}/blob/{branch}/eurlex_digest/reports/{date_str}.md" if repo else ""

    # Google Doc (via Drive HTML conversion)
    doc_link = ""
    drive = get_drive_service()
    if drive:
        try:
            folder_id = os.getenv("GOOGLE_DOCS_FOLDER_ID", "").strip() or None
            share_with = os.getenv("GOOGLE_DOCS_SHARE_WITH", "").strip() or None
            html = md_to_html(doc_title, exec_syn, cats_cfg, by_cat)
            _, doc_link = create_google_doc_from_html(drive, html, doc_title, folder_id, share_with)
            print("Google Doc created:", doc_link)
        except Exception as exc:
            print("Google Doc creation failed:", exc)
    else:
        print("Google Drive service not available (check GOOGLE_SERVICE_ACCOUNT_JSON).")

    # Email body (plain text)
    lines = []
    lines.append("Executive Digest")
    lines.append("----------------")
    lines.append(exec_syn if exec_syn else "No relevant developments today.")
    lines.append("")
    if report_url:
        lines.append(f"Full report (GitHub): {report_url}")
    if doc_link:
        lines.append(f"Full report (Google Doc): {doc_link}")
    lines.append("")
    lines.append("Per-category titles")
    lines.append("-------------------")
    for c in cats_cfg:
        name = c["name"]; items = by_cat.get(name, [])
        if not items: continue
        lines.append(f"{name}:")
        for it in items:
            lines.append(f"- {it['title']}  ({it['link']})")
        lines.append("")
    body = "\n".join(lines)

    # Send email
    if mail_service == "gmail":
        send_email_gmail(subject, body, email_to)
    elif mail_service == "mailgun":
        send_email_mailgun(subject, body)
    else:
        raise RuntimeError(f"Unsupported mail_service: {mail_service}")

    print("Digest sent. Markdown:", report_path)
    if doc_link:
        print("Google Doc:", doc_link)


if __name__ == "__main__":
    main()
