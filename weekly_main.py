#!/usr/bin/env python3
"""
Weekly — EU Finance & Defence
Last-7-day synthesis from config.yaml feeds/keywords.

Outputs:
  • Google Doc with headings:
      - Weekly Economic & Policy Overview (>= 2,500 words, hard minimum)
      - Weekly EU Policy Analysis (800–1200 words)
  • Optional MP3 readout (TTS) and a 'Listen' link at the top of the Doc
  • Text mirror saved under reports/weekly/

Env (provided by workflow):
  OPENAI_API_KEY
  OPENAI_WEEKLY_MODEL          # preferred model for this script (e.g., gpt-4o-mini)
  OPENAI_MODEL                 # fallback if weekly model missing
  OPENAI_TTS_MODEL             # e.g., gpt-4o-mini-tts or tts-1
  OPENAI_TTS_VOICE             # e.g., alloy
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_OAUTH_REFRESH_TOKEN
  GOOGLE_DOCS_FOLDER_ID        # optional
  GOOGLE_DOCS_SHARE_WITH       # optional, comma-separated emails
"""

from __future__ import annotations

import os
import re
import pathlib
import datetime as dt
from typing import Any, Dict, List, Tuple

import yaml
import feedparser

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
    # timezone-aware UTC datetimes
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=7)
    return start, end


# ------------------------ Google services -----------------------

GOOGLE_SCOPES = [
    # IMPORTANT: these must match the scopes used when the refresh token was created
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
    # Ensure access token is present/valid
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

        # feedparser exposes *_parsed time tuples (UTC by convention)
        for key in ("published_parsed", "updated_parsed"):
            t = e.get(key)
            if t:
                try:
                    published = dt.datetime(
                        t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec,
                        tzinfo=dt.timezone.utc
                    )
                    break
                except Exception:
                    pass

        out.append({"title": title, "link": link, "summary": summary, "published": published})
    return out


def within_week(entry: Dict[str, Any], start: dt.datetime, end: dt.datetime) -> bool:
    pub = entry.get("published")
    if pub is None:
        return True  # keep undated; we penalize later
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=dt.timezone.utc)
    return start <= pub <= end


def score_entry(entry: Dict[str, Any], keywords: List[str], recent_bonus_hours: int) -> int:
    txt = (entry["title"] + " " + entry["summary"]).lower()
    score = sum(1 for kw in keywords if kw.lower() in txt)

    pub = entry.get("published")
    if pub is None:
        score -= 1  # nudge down undated
    else:
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        age_h = (now - pub).total_seconds() / 3600.0
        if age_h <= recent_bonus_hours:
            score += 1

    return score


def dedupe(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for e in entries:
        k = (e["title"].strip().lower(), e["link"].strip().lower())
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out


# ------------------------ OpenAI helpers -------------------------

def openai_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("OpenAI package not available.")
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def pick_model() -> str:
    m = (os.environ.get("OPENAI_WEEKLY_MODEL") or os.environ.get("OPENAI_MODEL") or "").strip()
    # Map a couple of common aliases to safe choices
    aliases = {
        "gpt-4o-mini-high": "gpt-4o-mini",  # fallback if high-tier alias isn’t available
        "o4-mini": "gpt-4o-mini",
        "o4-mini-high": "gpt-4o-mini",
    }
    if not m:
        return "gpt-4o-mini"
    return aliases.get(m, m)

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
    """Drop long reference lists and [n] markers; TTS reads better."""
    t = re.sub(r"\n#+\s*References.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"\[\d+\]", "", t)  # remove [12] style markers
    return t

def split_into_token_chunks(text: str, max_tokens: int = 1500) -> List[str]:
    parts, buf = [], []
    cur = 0
    for para in text.split("\n\n"):
        t = count_tokens(para)
        if cur + t > max_tokens and buf:
            parts.append("\n\n".join(buf).strip())
            buf, cur = [para], t
        else:
            buf.append(para); cur += t
    if buf: parts.append("\n\n".join(buf).strip())
    return parts

def synthesize_tts_chunked(full_text: str, out_mp3: pathlib.Path, tts_model: str, tts_voice: str) -> pathlib.Path:
    """
    Split text to respect model input limit, synthesize each chunk,
    then merge to a single MP3 at out_mp3. Returns out_mp3.
    """
    client = openai_client()
    cleaned = strip_references_for_audio(full_text)
    chunks = split_into_token_chunks(cleaned, max_tokens=1500)  # safe margin < 2k limit

    tmp_dir = ROOT / "tmp_audio"
    tmp_dir.mkdir(exist_ok=True)

    part_files: List[pathlib.Path] = []

    for i, chunk in enumerate(chunks, 1):
        part_path = tmp_dir / f"part_{i:02d}.mp3"
        print(f"[audio] generating part {i}/{len(chunks)} → {part_path}")
        audio = client.audio.speech.create(
            model=tts_model,   # e.g., gpt-4o-mini-tts or tts-1
            voice=tts_voice,   # e.g., alloy
            input=chunk,
            format="mp3",
        )
        with open(part_path, "wb") as f:
            f.write(audio.read())
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
    if folder_id:
        body["parents"] = [folder_id]
    media = MediaFileUpload(str(path), mimetype=mime, resumable=False)
    f = drive.files().create(body=body, media_body=media, fields="id,webViewLink,webContentLink").execute()
    return f["id"], f.get("webViewLink") or f.get("webContentLink") or ""

def doc_create(docs, title: str) -> str:
    d = docs.documents().create(body={"title": title}).execute()
    return d["documentId"]

def doc_batch_update(docs, doc_id: str, requests: List[Dict[str, Any]]):
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def doc_insert_text_requests(title: str, listen_url: str | None, briefing: str, analysis: str) -> List[Dict[str, Any]]:
    reqs: List[Dict[str, Any]] = []
    cursor = 1

    def insert(text: str) -> None:
        nonlocal cursor
        reqs.append({"insertText": {"location": {"index": cursor}, "text": text}})
        cursor += len(text)

    def style(start: int, end: int, named: str) -> None:
        reqs.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": named},
                "fields": "namedStyleType",
            }
        })

    # Title
    start = cursor
    insert(title + "\n")
    style(start, cursor, "HEADING_1")
    insert("\n")

    # Listen link (if any)
    if listen_url:
        start = cursor
        insert("Listen to this briefing (MP3)\n")
        style(start, cursor, "HEADING_2")
        insert(listen_url + "\n\n")

    # Briefing
    start = cursor
    insert("Weekly Economic & Policy Overview\n")
    style(start, cursor, "HEADING_2")
    insert(briefing.strip() + "\n\n")

    # Analysis
    start = cursor
    insert("Weekly EU Policy Analysis\n")
    style(start, cursor, "HEADING_2")
    insert(analysis.strip() + "\n")

    return reqs


# ------------------------ Prompting -----------------------------

def build_prompts(selected: List[Dict[str, Any]], window: Tuple[dt.datetime, dt.datetime]):
    start, end = window
    start_iso, end_iso = start.date().isoformat(), end.date().isoformat()

    refs = [f"[{i}] {e['title']} — {e['link']}" for i, e in enumerate(selected, 1)]
    corpus = "\n".join(f"- {e['title']} :: {e['summary']} :: {e['link']}" for e in selected)

    system = (
        "You are a senior EU policy analyst. Write clear professional prose in plain paragraphs "
        "(no markdown symbols). Use bracketed citations [n] corresponding to a numbered list."
    )

    user_brief = (
        f"Time window: {start_iso} to {end_iso}.\n"
        f"Items (title :: snippet :: URL):\n{corpus}\n\n"
        "Produce a WEEKLY BRIEFING of at least 2,500 words (hard minimum). "
        "Open with 1–2 paragraphs stating the week's top-line narrative. Then synthesise monetary policy, "
        "financial markets, banking/insurance, digital/AI, ESG, EU institutions, and defence. "
        "Weave items into the narrative with citations like [3], [7] using this numbered list:\n"
        + "\n".join(refs)
    )

    user_analysis = (
        "Write ONE consolidated section titled 'Weekly EU Policy Analysis' (800–1200 words). "
        "Explain cross-cutting implications and forward risks for EU financial markets and defence. "
        "Use the same [n] references."
    )

    return (system, user_brief), (system, user_analysis)


def enforce_min_words(text: str, min_words: int = 2500) -> str:
    words = len(text.split())
    if words >= min_words:
        return text
    extra = call_llm(
        "Extend the analysis without changing conclusions. Plain paragraphs; consistent analytical tone.",
        f"Current text has {words} words:\n\n{text}\n\n"
        f"Expand to at least {min_words} words by deepening mechanisms, EU institutional context, "
        f"policy channels, and scenarios.",
        max_tokens=3500,
    )
    return text + "\n\n" + extra


# ------------------------ Main ---------------------------------

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

    # Sort by score then recency
    def sort_key(x: Dict[str, Any]):
        pub = x.get("published")
        if pub is None:
            pub = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        elif pub.tzinfo is None:
            pub = pub.replace(tzinfo=dt.timezone.utc)
        return (x["_score"], pub)

    week_entries.sort(key=sort_key, reverse=True)
    selected = week_entries[:cap]

    # Build prompts and generate text
    (sys_b, user_b), (sys_a, user_a) = build_prompts(selected, (wstart, wend))
    briefing = call_llm(sys_b, user_b, max_tokens=5000)
    briefing = enforce_min_words(briefing, 2500)
    analysis = call_llm(sys_a, user_a, max_tokens=2000)

    start_label = (wend - dt.timedelta(days=7)).date().isoformat()
    end_label = wend.date().isoformat()
    week_num = wend.isocalendar().week
    title = f"Weekly — EU Finance & Defence — {start_label} to {end_label} (W{week_num:02d})"
    base = f"{end_label}-weekly"
    base_slug = slug(base)

    # Optional audio (chunked)
    listen_url = None
    mp3_path = REPORTS_DIR / f"{base_slug}.mp3"
    try:
        print("[audio] generating MP3 (chunked)…")
        tts_model = (os.environ.get("OPENAI_TTS_MODEL") or "gpt-4o-mini-tts").strip()
        tts_voice = (os.environ.get("OPENAI_TTS_VOICE") or "alloy").strip()
        tts_text = (
            f"{title}. Weekly Economic & Policy Overview. {briefing}\n\n"
            f"Weekly EU Policy Analysis. {analysis}"
        )
        synthesize_tts_chunked(tts_text, mp3_path, tts_model, tts_voice)
    except Exception as ex:
        print(f"[audio] skipped: {ex}")
        mp3_path = None

    # Google Docs + sharing
    drive, docs = get_google_services()
    folder_id = os.environ.get("GOOGLE_DOCS_FOLDER_ID") or None
    share_with = [
        s.strip() for s in (os.environ.get("GOOGLE_DOCS_SHARE_WITH") or "").split(",") if s.strip()
    ]

    if mp3_path and mp3_path.exists():
        mp3_id, listen_url = drive_upload_binary(
            drive, mp3_path, f"{title}.mp3", "audio/mpeg", folder_id
        )
        for addr in share_with:
            try:
                drive.permissions().create(
                    fileId=mp3_id,
                    body={"type": "user", "role": "reader", "emailAddress": addr},
                    sendNotificationEmail=False,
                ).execute()
            except Exception as ex:
                print(f"[share] mp3 perm for {addr} failed: {ex}")

    doc_id = doc_create(docs, title)
    reqs = doc_insert_text_requests(title, listen_url, briefing, analysis)
    doc_batch_update(docs, doc_id, reqs)

    if share_with:
        for addr in share_with:
            try:
                drive.permissions().create(
                    fileId=doc_id,
                    body={"type": "user", "role": "reader", "emailAddress": addr},
                    sendNotificationEmail=False,
                ).execute()
            except Exception as ex:
                print(f"[share] doc perm for {addr} failed: {ex}")

    # Local mirror
    txt_path = REPORTS_DIR / f"{base_slug}.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        f.write(title + "\n\n")
        f.write("Weekly Economic & Policy Overview\n")
        f.write(briefing.strip() + "\n\n")
        f.write("Weekly EU Policy Analysis\n")
        f.write(analysis.strip() + "\n")

    print(f"[done] Google Doc ID: {doc_id}")
    if listen_url:
        print(f"[done] MP3 link: {listen_url}")
    print(f"[done] Wrote mirrors in {REPORTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
