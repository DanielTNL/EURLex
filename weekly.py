#!/usr/bin/env python3
"""
Weekly EU Finance & Defence Report (HTML + Audio)
- 7-day window from all configured feeds (config.yaml).
- Produces a ~≥2,500-word briefing with inline [n] citations and an APA-like References list.
- Clean HTML headings (<h2>, <h3>, <p>) — no Markdown hashes in the Google Doc.
- Saves to reports/weekly/, mirrors to Google Docs, and (optionally) creates an MP3 "Listen" link.
- Uses the same Gmail + Google OAuth + OpenAI env vars as the daily job.

Env expected:
  OPENAI_API_KEY
  OPENAI_MODEL_WEEKLY (preferred) or OPENAI_MODEL (fallback)  # e.g., 'gpt-4o-mini-high'
  GMAIL_USER, GMAIL_PASS
  GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN
  GOOGLE_DOCS_FOLDER_ID (optional), GOOGLE_DOCS_SHARE_WITH (optional)
"""

import os, re, json, yaml, feedparser, datetime as dt
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse
from email.mime.text import MIMEText
import smtplib
from io import BytesIO

# Optional timezone
try:
    import pytz
except Exception:
    pytz = None

# ---------- OpenAI ----------
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

# ---------- Google (OAuth refresh token) ----------
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
    # APA-ish: Title. (YYYY-MM-DD). Site. URL
    title = item.get("title","").strip()
    date  = fmt_date(item.get("published_utc"))
    site  = domain_label(item.get("link",""))
    url   = item.get("link","").strip()
    core  = f"{title}. ({date}). {site}."
    if url: core += f" {url}"
    return core

# ---------- OpenAI helpers ----------

def model_briefing_html(key_items: List[Dict[str,Any]],
                        extra_items: List[Dict[str,Any]],
                        label_start: str, label_end: str,
                        min_words: int, model_name: str) -> str:
    """
    Ask the model for clean HTML (<h2>/<h3>/<p> only), ≥ min_words.
    If shorter, loop with a 'continue and expand' prompt until threshold or 3 attempts.
    """
    if not (OPENAI_ENABLED and _oa):
        # Fallback: simple stitched HTML
        paras = "".join(f"<p>[{it['id']}] {first_sentence(it.get('summary') or it['title'])}</p>"
                        for it in key_items)
        return f"<h2>Weekly Briefing</h2>{paras}"

    def pack_item(it: Dict[str,Any]) -> str:
        date_s = fmt_date(it.get("published_utc"))
        return f"[{it['id']}] {it['title']} ({date_s}) — {first_sentence(it.get('summary') or it['title'])} Link: {it['link']}"

    key_text = "\n".join(pack_item(it) for it in key_items)
    extra_text = "\n".join(pack_item(it) for it in extra_items) if extra_items else ""

    sysmsg = (
        "You are a senior EU policy analyst. Produce CLEAN HTML only: <h2>, <h3>, <p>, <ul>, <li>. "
        "NO markdown (#), NO code fences, NO inline CSS. Neutral, factual tone. "
        "Weave a coherent weekly narrative from the numbered items below. "
        "Insert inline citation markers like [1], [2] that match the provided items. "
        "Organize with informative subheadings (e.g., Markets, Banking, Insurance, Digital, ESG, Institutions, Defence). "
        "Minimum length hard floor: {min_words} words. If you are below the floor, expand further."
    ).format(min_words=min_words)

    usrmsg_base = (
        f"TIME WINDOW: {label_start} to {label_end}\n\n"
        f"KEY ITEMS (must ground claims; cite with [n]):\n{key_text}\n\n"
        f"OPTIONAL EXTRAS (use if helpful; cite with [n]):\n{extra_text}\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "- Return CLEAN HTML only (<h2>, <h3>, <p>, <ul>, <li>), no markdown hashes.\n"
        f"- Target length: ≥ {min_words} words (hard minimum).\n"
        "- No URLs in the body; use [n] markers only. References will be appended separately.\n"
    )

    html = ""
    attempts = 0
    while attempts < 3:
        attempts += 1
        if attempts == 1:
            messages = [
                {"role":"system","content": sysmsg},
                {"role":"user","content": usrmsg_base},
            ]
        else:
            messages = [
                {"role":"system","content": sysmsg},
                {"role":"user","content": "CONTINUE THE SAME DOCUMENT. Expand coverage and detail while keeping the same structure and style. "
                                          "Add more analysis and context across themes to exceed the minimum length."},
            ]
        try:
            r = _oa.chat.completions.create(
                model=model_name,
                temperature=0.2,
                max_tokens=8000,  # generous
                messages=messages,
            )
            add = (r.choices[0].message.content or "").strip()
            # Basic sanitization: keep only allowed tags; strip code fences/markdown remnants.
            add = re.sub(r"```.*?```", "", add, flags=re.S)
            # Count words in plain text
            plain = re.sub(r"<[^>]+>", " ", add)
            wc = len(re.findall(r"\w+", plain))
            html += add if attempts == 1 else ("<p></p>" + add)
            print(f"[weekly] model chunk {attempts}: ~{wc} words")
            if wc >= min_words:
                break
        except Exception as e:
            print("[openai] weekly chunk error:", e)
            break
    return html or "<p>(No content)</p>"

# ---------- Google ----------
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

def upload_binary(drive, data: bytes, title: str, mime: str,
                  folder_id: str|None, share_with: str|None) -> Tuple[str,str]:
    media = MediaIoBaseUpload(BytesIO(data), mimetype=mime, resumable=False)
    meta = {"name": title, "mimeType": mime}
    if folder_id: meta["parents"] = [folder_id]
    f = drive.files().create(
        body=meta, media_body=media,
        fields="id,webViewLink,webContentLink", supportsAllDrives=True
    ).execute()
    fid = f["id"]; link = f.get("webViewLink") or f.get("webContentLink")
    if share_with:
        try:
            drive.permissions().create(
                fileId=fid, fields="id", supportsAllDrives=True,
                body={"type":"user","role":"reader","emailAddress":share_with}
            ).execute()
        except Exception as e:
            print("[google] share error:", e)
    return fid, link

# ---------- Email ----------
def send_email(subject: str, body: str, to_addr: str):
    user = os.getenv("GMAIL_USER"); pwd = os.getenv("GMAIL_PASS")
    if not user or not pwd: raise RuntimeError("GMAIL_USER or GMAIL_PASS not set")
    if not to_addr: to_addr = user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"]=subject; msg["From"]=user; msg["To"]=to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(user,pwd); s.sendmail(user,[to_addr], msg.as_string())

# ---------- Utility ----------
def strip_html_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)

# =====================================================================

def main():
    base = os.path.dirname(__file__)
    cfg = load_config(os.path.join(base, "config.yaml"))

    # Weekly knobs
    wk = cfg.get("weekly", {}) or {}
    window_days     = int(wk.get("window_days", 7))
    exec_top_n      = int(wk.get("exec_top_n", 50))
    exec_max_words  = int(wk.get("exec_max_words", 2500))

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
        if e.get("link") in uniq:  # de-dup
            continue
        uniq.add(e.get("link"))
        e["score"] = score_entry(e, keywords, recent_hours_bonus)
        if e["score"] < min_score_required:
            continue
        pool.append(e)

    # Sort newest first then score (or reverse if you prefer)
    def sort_key(ent):
        ts = ent["published_utc"].timestamp() if ent.get("published_utc") else 0.0
        return (-ts, -ent["score"]) if prefer_recent else (-ent["score"], -ts)
    pool.sort(key=sort_key)

    # Shortlist to drive citations (allow some extras beyond 50)
    shortlist = pool[: max(exec_top_n, 60)]
    for i, it in enumerate(shortlist, 1):
        it["id"] = i

    key_items   = shortlist[:exec_top_n]
    extra_items = shortlist[exec_top_n:exec_top_n+10]  # optional extras

    # Build the briefing (pure HTML, ≥ 2,500 words)
    briefing_html = model_briefing_html(
        key_items, extra_items, label_start, label_end, exec_max_words, MODEL_WEEKLY
    )

    # References
    refs = [apa_like_ref(it) for it in shortlist]

    # Persist to Markdown (for GitHub view)
    weekly_dir = os.path.join(base, "reports", "weekly")
    os.makedirs(weekly_dir, exist_ok=True)
    md_name = f"{label_start}_to_{label_end}_W{week_no}.md"
    md_path = os.path.join(weekly_dir, md_name)
    # Convert HTML to a simple Markdown-ish file for repo record (keep headings but drop tags crudely)
    md_body = re.sub(r"</h2>", "\n\n", re.sub(r"<h2>", "## ", briefing_html))
    md_body = re.sub(r"</h3>", "\n\n", re.sub(r"<h3>", "### ", md_body))
    md_body = re.sub(r"<li>\s*", "- ", md_body)
    md_body = re.sub(r"</li>", "\n", md_body)
    md_body = re.sub(r"<[^>]+>", "", md_body)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{md_body}\n\n## References\n")
        for i, ref in enumerate(refs, 1):
            f.write(f"{i}. {ref}\n")

    # Build GitHub blob URL if on Actions
    server = os.getenv("GITHUB_SERVER_URL","https://github.com")
    repo   = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME","main")
    report_url = f"{server}/{repo}/blob/{branch}/reports/weekly/{md_name}" if repo else ""

    # Optional: Text-to-Speech (MP3) -----------------------------------
    # Uses OpenAI TTS (e.g., 'gpt-4o-mini-tts' / 'tts-1'); see official docs:
    # https://platform.openai.com/docs/guides/text-to-speech  and  https://platform.openai.com/docs/api-reference/audio
    audio_link = ""
    if OPENAI_ENABLED and _oa:
        try:
            # Prefer TTS model name from var; else a sensible default
            TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
            TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")
            print(f"[tts] generating audio via {TTS_MODEL} / voice={TTS_VOICE}")
            plain_text = re.sub(r"\s+", " ", strip_html_tags(briefing_html)).strip()
            # Stream MP3 bytes
            with _oa.audio.speech.with_streaming_response.create(
                model=TTS_MODEL,
                voice=TTS_VOICE,
                input=plain_text
            ) as resp:
                mp3_bytes = resp.read()  # stream to bytes in memory
            # Upload to Drive
            drv, _ = get_drive_service_oauth()
            if drv:
                folder_id = (os.getenv("GOOGLE_DOCS_FOLDER_ID") or "").strip() or None
                share_with = (os.getenv("GOOGLE_DOCS_SHARE_WITH") or "").strip() or None
                title_mp3 = f"{title} — Audio.mp3"
                _, audio_link = upload_binary(drv, mp3_bytes, title_mp3, "audio/mpeg",
                                              folder_id, share_with)
                print("[tts] uploaded:", audio_link)
        except Exception as e:
            print("[tts] error:", e, "— skipping audio")

    # Google Doc (HTML import for nice headings) -----------------------
    doc_link = ""
    drv, _acct = get_drive_service_oauth()
    if drv:
        try:
            folder_id = (os.getenv("GOOGLE_DOCS_FOLDER_ID") or "").strip() or None
            share_with = (os.getenv("GOOGLE_DOCS_SHARE_WITH") or "").strip() or None
            # Build final HTML (add "Listen" link if present)
            def esc(t:str)->str: return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            h = []
            h.append(f"<html><head><meta charset='utf-8'><title>{esc(title)}</title></head><body>")
            h.append(f"<h1>{esc(title)}</h1>")
            if audio_link:
                h.append(f"<p><strong>Listen:</strong> <a href='{esc(audio_link)}'>Audio version (MP3)</a></p>")
            h.append(briefing_html)  # already clean HTML
            h.append("<h2>References</h2><ol>")
            for r in refs: h.append(f"<li>{esc(r)}</li>")
            h.append("</ol>")
            h.append(f"<p><em>Generated via GitHub Actions with OpenAI (model: {esc(MODEL_WEEKLY)}).</em></p>")
            h.append("</body></html>")
            full_html = "".join(h)

            print("[google] creating weekly doc...")
            _, doc_link = create_google_doc_from_html(drv, full_html, title, folder_id, share_with)
            print("[google] doc created:", doc_link)
        except Exception as e:
            print("[google] doc error:", e)

    # Email cover note --------------------------------------------------
    body = [
        f"Weekly window: {label_start} → {label_end}",
        "",
        "Links:",
        f"- GitHub: {report_url}" if report_url else "- GitHub: (n/a)",
        f"- Google Doc: {doc_link}" if doc_link else "- Google Doc: (n/a)",
    ]
    if audio_link:
        body.append(f"- Audio (MP3): {audio_link}")
    body.append("")
    body.append("This is an automated weekly briefing compiled from EUR-Lex and EU institutional feeds.")
    send_email(subject, "\n".join(body), email_to)

    print("[weekly] Done.")
    print("Saved:", md_path)
    if report_url: print("GitHub:", report_url)
    if doc_link:   print("Google Doc:", doc_link)
    if audio_link: print("Audio:", audio_link)

if __name__ == "__main__":
    main()
