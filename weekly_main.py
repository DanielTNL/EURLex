#!/usr/bin/env python3
"""
Weekly — EU Finance & Defence
Last-7-day synthesis from config.yaml feeds/keywords.

Outputs:
  • Google Doc with headings:
      - Weekly Economic & Policy Overview (>= 1,800 words, hard minimum)
      - Weekly EU Policy Analysis (800–1200 words)
      - References (numbered list with live links)
  • Optional MP3 readout (TTS) and a 'Listen' link at the top of the Doc
  • Text mirror saved under reports/weekly/
  • Success e-mail with links

Env (provided by workflow):
  OPENAI_API_KEY
  OPENAI_WEEKLY_MODEL          # preferred model (e.g., gpt-4o-mini); falls back to OPENAI_MODEL
  OPENAI_MODEL
  OPENAI_TTS_MODEL             # e.g., gpt-4o-mini-tts or tts-1
  OPENAI_TTS_VOICE             # e.g., alloy
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_OAUTH_REFRESH_TOKEN
  GOOGLE_DOCS_FOLDER_ID        # optional
  GOOGLE_DOCS_SHARE_WITH       # optional, comma-separated emails
  GMAIL_USER, GMAIL_PASS       # optional success notice
"""

from __future__ import annotations

import os, re, smtplib, pathlib, datetime as dt
from typing import Any, Dict, List, Tuple
from email.mime.text import MIMEText

import yaml, feedparser

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# --- OpenAI SDK ---
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

# --- Audio merge (ffmpeg required; installed in workflow) ---
from pydub import AudioSegment

# --- Token counting (optional; graceful fallback) ---
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(s: str) -> int: return len(_enc.encode(s))
except Exception:
    def count_tokens(s: str) -> int: return max(1, len(s) // 4)

# Paths
ROOT = pathlib.Path(__file__).parent
REPORTS_DIR = ROOT / "reports" / "weekly"
STATE_DIR = ROOT / "state"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------ Config & window ------------------------

def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def last_7_days_utc() -> Tuple[dt.datetime, dt.datetime]:
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=7)
    return start, end

# ------------------------ Google services -----------------------

# Need full drive scope to move a Doc into a specific folder
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

def get_google_services():
    cid  = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
    csec = os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
    rtok = os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"]

    creds = Credentials(
        None,
        refresh_token=rtok,
        client_id=cid,
        client_secret=csec,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GOOGLE_SCOPES,
    )
    creds.refresh(Request())
    drive = build("drive", "v3", credentials=creds)
    docs  = build("docs",  "v1", credentials=creds)
    return drive, docs

# ------------------------ Feed ingest & scoring ------------------

def fetch_feed(url: str) -> List[Dict[str, Any]]:
    p = feedparser.parse(url)
    out: List[Dict[str, Any]] = []
    for e in p.entries:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        summary = (e.get("summary") or e.get("description") or "").strip()
        published = None
        for key in ("published_parsed", "updated_parsed"):
            t = e.get(key)
            if t:
                try:
                    published = dt.datetime(
                        t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec,
                        tzinfo=dt.timezone.utc
                    ); break
                except Exception:
                    pass
        out.append({"title": title, "link": link, "summary": summary, "published": published})
    return out

def within_week(entry: Dict[str, Any], start: dt.datetime, end: dt.datetime) -> bool:
    pub = entry.get("published")
    if pub is None: return True
    if pub.tzinfo is None: pub = pub.replace(tzinfo=dt.timezone.utc)
    return start <= pub <= end

def score_entry(entry: Dict[str, Any], keywords: List[str], recent_bonus_hours: int) -> int:
    txt = (entry["title"] + " " + entry["summary"]).lower()
    score = sum(1 for kw in keywords if kw.lower() in txt)
    pub = entry.get("published")
    if pub is None:
        score -= 1
    else:
        if pub.tzinfo is None: pub = pub.replace(tzinfo=dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        if (now - pub).total_seconds() / 3600.0 <= recent_bonus_hours:
            score += 1
    return score

def dedupe(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set(); out: List[Dict[str, Any]] = []
    for e in entries:
        k = (e["title"].strip().lower(), e["link"].strip().lower())
        if k in seen: continue
        seen.add(k); out.append(e)
    return out

# ------------------------ OpenAI helpers -------------------------

def openai_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("OpenAI package not available.")
    # Safety: some runners inject proxy envs that can trip certain SDK versions
    for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"):
        os.environ.pop(k, None)
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def pick_model() -> str:
    m = (os.environ.get("OPENAI_WEEKLY_MODEL") or os.environ.get("OPENAI_MODEL") or "").strip()
    aliases = {
        "gpt-4o-mini-high": "gpt-4o-mini",
        "o4-mini": "gpt-4o-mini",
        "o4-mini-high": "gpt-4o-mini",
    }
    return aliases.get(m, m or "gpt-4o-mini")

def call_llm(system: str, user: str, max_tokens: int, model_override: str | None = None) -> str:
    client = openai_client()
    model = model_override or pick_model()
    print(f"[llm] using model: {model}")
    r = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )
    return (r.choices[0].message.content or "").strip()

# ------------------------ Chunked TTS + merge --------------------

def strip_references_for_audio(text: str) -> str:
    t = re.sub(r"\n#+\s*References.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"\[\d+\]", "", t)
    return t

def split_into_token_chunks(text: str, max_tokens: int = 1500) -> List[str]:
    parts, buf, cur = [], [], 0
    for para in text.split("\n\n"):
        t = count_tokens(para)
        if cur + t > max_tokens and buf:
            parts.append("\n\n".join(buf).strip()); buf, cur = [para], t
        else:
            buf.append(para); cur += t
    if buf: parts.append("\n\n".join(buf).strip())
    return parts

def synthesize_tts_chunked(full_text: str, out_mp3: pathlib.Path, tts_model: str, tts_voice: str) -> pathlib.Path:
    """
    Split text to respect model input limit, synthesize each chunk via the
    streaming TTS API (no 'format' kwarg), then merge to a single MP3.
    """
    client = openai_client()
    cleaned = strip_references_for_audio(full_text)
    chunks = split_into_token_chunks(cleaned, max_tokens=1500)

    tmp_dir = ROOT / "tmp_audio"; tmp_dir.mkdir(exist_ok=True)
    part_files: List[pathlib.Path] = []

    for i, chunk in enumerate(chunks, 1):
        part_path = tmp_dir / f"part_{i:02d}.mp3"
        print(f"[audio] generating part {i}/{len(chunks)} → {part_path}")
        # Streaming API – write straight to file (no 'format' kwarg)
        with client.audio.speech.with_streaming_response.create(
            model=tts_model,
            voice=tts_voice,
            input=chunk,
        ) as resp:
            resp.stream_to_file(str(part_path))
        part_files.append(part_path)

    merged = None
    for p in part_files:
        seg = AudioSegment.from_file(p, format="mp3")
        merged = seg if merged is None else (merged + seg)
    merged.export(out_mp3, format="mp3")
    print(f"[audio] merged {len(part_files)} parts → {out_mp3}")
    return out_mp3

# ------------------------ Drive/Docs helpers --------------------

def drive_upload_binary(drive, path: pathlib.Path, name: str, mime: str, folder_id: str | None):
    body = {"name": name}
    if folder_id: body["parents"] = [folder_id]
    media = MediaFileUpload(str(path), mimetype=mime, resumable=False)
    f = drive.files().create(body=body, media_body=media, fields="id,webViewLink,webContentLink").execute()
    return f["id"], f.get("webViewLink") or f.get("webContentLink") or ""

def doc_create(docs, title: str) -> str:
    d = docs.documents().create(body={"title": title}).execute()
    return d["documentId"]

def move_doc_to_folder(drive, doc_id: str, folder_id: str):
    # Hard move: remove previous parents so it only lives in the target folder
    meta = drive.files().get(fileId=doc_id, fields="parents").execute()
    prev = ",".join(meta.get("parents", []))
    drive.files().update(
        fileId=doc_id,
        addParents=folder_id,
        removeParents=prev,
        fields="id, parents"
    ).execute()

def doc_batch_update(docs, doc_id: str, requests: List[Dict[str, Any]]):
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def _insert_chunked(reqs: List[Dict[str, Any]], cursor_ref: List[int], text: str, chunk: int = 15000):
    i = 0
    while i < len(text):
        piece = text[i:i+chunk]
        reqs.append({"insertText": {"location": {"index": cursor_ref[0]}, "text": piece}})
        cursor_ref[0] += len(piece); i += chunk

def doc_insert_text_requests(title: str, listen_url: str | None,
                             briefing: str, analysis: str,
                             references: List[str]) -> List[Dict[str, Any]]:
    reqs: List[Dict[str, Any]] = []
    cursor = [1]

    def style(start: int, end: int, named: str) -> None:
        reqs.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": named},
                "fields": "namedStyleType",
            }
        })

    # Title
    start = cursor[0]; _insert_chunked(reqs, cursor, title + "\n"); style(start, cursor[0], "HEADING_1")
    _insert_chunked(reqs, cursor, "\n")

    # Listen link (if any)
    if listen_url:
        start = cursor[0]; _insert_chunked(reqs, cursor, "Listen to this briefing (MP3)\n"); style(start, cursor[0], "HEADING_2")
        _insert_chunked(reqs, cursor, listen_url + "\n\n")

    # Briefing
    start = cursor[0]; _insert_chunked(reqs, cursor, "Weekly Economic & Policy Overview\n"); style(start, cursor[0], "HEADING_2")
    _insert_chunked(reqs, cursor, briefing.strip() + "\n\n")

    # Analysis
    start = cursor[0]; _insert_chunked(reqs, cursor, "Weekly EU Policy Analysis\n"); style(start, cursor[0], "HEADING_2")
    _insert_chunked(reqs, cursor, analysis.strip() + "\n\n")

    # References section
    if references:
        start = cursor[0]; _insert_chunked(reqs, cursor, "References\n"); style(start, cursor[0], "HEADING_2")
        refs_start = cursor[0]
        _insert_chunked(reqs, cursor, "\n".join(references) + "\n")
        refs_end = cursor[0]
        # Use a valid numbered preset; only create bullets when content exists
        reqs.append({
            "createParagraphBullets": {
                "range": {"startIndex": refs_start, "endIndex": refs_end},
                "bulletPreset": "NUMBERED_DECIMAL_ALPHA_ROMAN"
            }
        })

    return reqs

# ------------------------ Email notice --------------------------

def send_email_notice(subject: str, body: str) -> None:
    u = os.environ.get("GMAIL_USER"); p = os.environ.get("GMAIL_PASS")
    if not (u and p):
        print("[email] skipped (no GMAIL_USER/PASS)"); return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject; msg["From"] = u; msg["To"] = u
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(u, p); s.sendmail(u, [u], msg.as_string())
    print("[email] sent")

# ------------------------ Prompting -----------------------------

def build_prompts(selected: List[Dict[str, Any]], window: Tuple[dt.datetime, dt.datetime]):
    start, end = window
    start_iso, end_iso = start.date().isoformat(), end.date().isoformat()

    # References used both in body [n] citations and the final References list
    numbered = [f"[{i}] {e['title']} — {e['link']}" for i, e in enumerate(selected, 1)]
    # Corpus for LLM
    corpus = "\n".join(f"- {e['title']} :: {e['summary']} :: {e['link']}" for e in selected)

    system = (
        "You are a senior EU policy analyst. Write clear professional prose in plain paragraphs "
        "(no markdown symbols). Use bracketed citations [n] that correspond to a numbered list called 'References'. "
        "Use descriptive sub-headings (plain text lines) within sections; keep them concise and professional."
    )

    user_brief = (
        f"Time window: {start_iso} to {end_iso}.\n"
        f"Items (title :: snippet :: URL):\n{corpus}\n\n"
        "Produce a WEEKLY BRIEFING of at least 1,800 words (hard minimum). "
        "Open with 1–2 paragraphs stating the week's top-line narrative. Then synthesise monetary policy, "
        "financial markets, banking/insurance, digital/AI, ESG, EU institutions, and defence. "
        "Insert short sub-headings where helpful (plain text, no markdown). "
        "Weave items into the narrative with citations like [3], [7] using this numbered list:\n"
        + "\n".join(numbered)
    )

    user_analysis = (
        "Write ONE consolidated section titled 'Weekly EU Policy Analysis' (800–1200 words). "
        "Explain cross-cutting implications and forward risks for EU financial markets and defence. "
        "Use short sub-headings where helpful (plain text, no markdown). "
        "Use the same [n] references."
    )

    return (system, user_brief), (system, user_analysis), numbered

def enforce_min_words(text: str, min_words: int = 1800) -> str:
    words = len(text.split())
    if words >= min_words: return text
    extra = call_llm(
        "Extend the analysis without changing conclusions. Plain paragraphs; consistent analytical tone.",
        f"Current text has {words} words:\n\n{text}\n\n"
        f"Expand to at least {min_words} words by deepening mechanisms, EU institutional context, "
        f"policy channels, and scenarios.",
        max_tokens=3200,
    )
    return text + "\n\n" + extra

# ------------------------ Main ---------------------------------

def fmt_date(d: dt.datetime | None) -> str:
    if not d: return ""
    if d.tzinfo is None: d = d.replace(tzinfo=dt.timezone.utc)
    return d.date().isoformat()

def slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE)
    return re.sub(r"_+", "_", s).strip("_").lower()

def main() -> int:
    cfg = load_config()
    feeds: List[str] = cfg.get("feeds", [])
    keywords: List[str] = cfg.get("keywords", [])
    recent_bonus = int(cfg.get("recent_hours", 72))
    cap = int(cfg.get("caps", {}).get("max_total", 50))

    wstart, wend = last_7_days_utc()

    # Fetch and filter
    all_entries: List[Dict[str, Any]] = []
    for u in feeds:
        try:
            all_entries.extend(fetch_feed(u))
        except Exception as ex:
            print(f"[warn] feed error: {u} -> {ex}")

    week_entries = [e for e in all_entries if within_week(e, wstart, wend)]
    week_entries = dedupe(week_entries)
    for e in week_entries:
        e["_score"] = score_entry(e, keywords, recent_bonus)

    def sort_key(x: Dict[str, Any]):
        pub = x.get("published")
        if pub is None: pub = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        elif pub.tzinfo is None: pub = pub.replace(tzinfo=dt.timezone.utc)
        return (x["_score"], pub)

    week_entries.sort(key=sort_key, reverse=True)
    selected = week_entries[:cap]

    # Build prompts and generate text
    (sys_b, user_b), (sys_a, user_a), numbered_refs = build_prompts(selected, (wstart, wend))
    briefing = call_llm(sys_b, user_b, max_tokens=5000)
    briefing = enforce_min_words(briefing, 1800)
    analysis = call_llm(sys_a, user_a, max_tokens=2000)

    # Prepare title/filenames
    start_label = (wend - dt.timedelta(days=7)).date().isoformat()
    end_label = wend.date().isoformat()
    week_num = wend.isocalendar().week
    title = f"Weekly — EU Finance & Defence — {start_label} to {end_label} (W{week_num:02d})"
    base_slug = slug(f"{end_label}-weekly")

    # Optional audio (chunked)
    listen_url = None
    mp3_id = None
    mp3_path = REPORTS_DIR / f"{base_slug}.mp3"
    try:
        print("[audio] generating MP3 (chunked)…")
        tts_model = (os.environ.get("OPENAI_TTS_MODEL") or "gpt-4o-mini-tts").strip()
        tts_voice = (os.environ.get("OPENAI_TTS_VOICE") or "alloy").strip()
        tts_text = f"{title}. Weekly Economic & Policy Overview. {briefing}\n\nWeekly EU Policy Analysis. {analysis}"
        synthesize_tts_chunked(tts_text, mp3_path, tts_model, tts_voice)
    except Exception as ex:
        print(f"[audio] skipped: {ex}")
        mp3_path = None

    # Google Docs + sharing + move to folder
    drive, docs = get_google_services()
    folder_id = os.environ.get("GOOGLE_DOCS_FOLDER_ID") or None
    share_with = [s.strip() for s in (os.environ.get("GOOGLE_DOCS_SHARE_WITH") or "").split(",") if s.strip()]

    doc_id = doc_create(docs, title)
    if folder_id:
        try:
            move_doc_to_folder(drive, doc_id, folder_id)
        except Exception as ex:
            print(f"[warn] could not move doc to folder {folder_id}: {ex}")

    # Upload MP3 first (if any) so we can insert the link at top of Doc
    if mp3_path and mp3_path.exists():
        try:
            mp3_id, listen_url = drive_upload_binary(drive, mp3_path, f"{title}.mp3", "audio/mpeg", folder_id)
        except Exception as ex:
            print(f"[audio] upload failed: {ex}")
            listen_url = None

    # Build references list (live links)
    ref_lines: List[str] = []
    for i, e in enumerate(selected, 1):
        date_str = fmt_date(e.get("published"))
        suffix = f" ({date_str})" if date_str else ""
        ref_lines.append(f"{e['title']}{suffix} — {e['link']}")

    # Write Doc body (with heading styles + numbered References)
    reqs = doc_insert_text_requests(title, listen_url, briefing, analysis, ref_lines)
    doc_batch_update(docs, doc_id, reqs)

    # Share Doc/MP3 (if requested)
    if share_with:
        for addr in share_with:
            for file_id in [doc_id] + ([mp3_id] if (mp3_id and listen_url) else []):
                try:
                    drive.permissions().create(
                        fileId=file_id,
                        body={"type": "user", "role": "reader", "emailAddress": addr},
                        sendNotificationEmail=False,
                    ).execute()
                except Exception as ex:
                    print(f"[share] permission for {addr} failed on {file_id}: {ex}")

    # Local mirrors
    txt_path = REPORTS_DIR / f"{base_slug}.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        f.write(title + "\n\n")
        f.write("Weekly Economic & Policy Overview\n")
        f.write(briefing.strip() + "\n\n")
        f.write("Weekly EU Policy Analysis\n")
        f.write(analysis.strip() + "\n\n")
        f.write("References\n")
        for i, line in enumerate(ref_lines, 1):
            f.write(f"{i}. {line}\n")

    # Email success notice (if Gmail creds provided)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    body_lines = [
        f"Weekly report created:",
        f"- Doc:  {doc_url}",
        f"- MP3:  {listen_url or '(no audio)'}",
        f"- Local mirrors: {txt_path}",
    ]
    send_email_notice(subject=title, body="\n".join(body_lines))

    print(f"[done] Google Doc: {doc_url}")
    if listen_url: print(f"[done] MP3 link: {listen_url}")
    print(f"[done] Wrote mirrors in {REPORTS_DIR}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
