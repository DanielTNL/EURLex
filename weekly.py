#!/usr/bin/env python3
"""
Weekly EU Finance & Defence – synthesis + Google Docs + MP3 (TTS)

- Pulls the same feeds/keywords taxonomy as daily (config.yaml).
- Ranks, clusters, and selects up to ~50 key items for the week window.
- Generates a 2,500+ word Weekly Briefing + one “Weekly EU Policy Analysis” block (no duplicates).
- Uploads a nicely formatted Google Doc and an MP3 readout; inserts a "Listen" link at the top.
- Mirrors outputs to reports/weekly/.

Env needed (already in your repo/workflow):
  OPENAI_API_KEY
  OPENAI_MODEL               (weekly text model; defaults to gpt-4o-mini)
  OPENAI_TTS_MODEL           (defaults gpt-4o-mini-tts)
  OPENAI_TTS_VOICE           (defaults alloy)
  GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REFRESH_TOKEN
  GOOGLE_DOCS_FOLDER_ID      (optional)
  GOOGLE_DOCS_SHARE_WITH     (optional, comma-separated emails)

Author: Assistant, 2025-08
"""

import os, sys, json, math, time, pathlib, datetime as dt
import pytz
import yaml
import feedparser
import requests
from typing import List, Dict, Any, Tuple

# Google APIs
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# OpenAI new SDK
from openai import OpenAI

ROOT = pathlib.Path(__file__).parent
REPORTS_DIR = ROOT / "reports" / "weekly"
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------
# Config & time window
# --------------------------

def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def ams_today() -> dt.date:
    tz = pytz.timezone("Europe/Amsterdam")
    return dt.datetime.now(tz=tz).date()

def last_7_days_utc() -> Tuple[dt.datetime, dt.datetime]:
    end = dt.datetime.utcnow()
    start = end - dt.timedelta(days=7)
    return start, end

# --------------------------
# Google auth helpers
# --------------------------

def google_creds() -> Credentials:
    cid  = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
    csec = os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
    rtok = os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"]
    return Credentials(
        None,
        refresh_token=rtok,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cid,
        client_secret=csec,
        scopes=["https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/documents"]
    )

def gd_services() -> Tuple[Any, Any]:
    creds = google_creds()
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs  = build("docs",  "v1", credentials=creds, cache_discovery=False)
    return drive, docs

# --------------------------
# Feeds → entries → scoring
# --------------------------

def fetch_feed(url: str) -> List[Dict[str, str]]:
    p = feedparser.parse(url)
    out = []
    for e in p.entries:
        title = e.get("title","").strip()
        link  = e.get("link","").strip()
        # prefer 'summary' then 'description'
        summary = (e.get("summary") or e.get("description") or "").strip()
        # parse date if present
        published = None
        for key in ("published_parsed", "updated_parsed"):
            if e.get(key):
                try:
                    published = dt.datetime(*e[key][:6], tzinfo=dt.timezone.utc)
                    break
                except Exception:
                    pass
        out.append({"title": title, "link": link, "summary": summary, "published": published})
    return out

def within_week(entry: Dict[str, Any], start: dt.datetime, end: dt.datetime) -> bool:
    if entry["published"] is None:
        # keep items with unknown date (rare) but de-prioritize later
        return True
    return start <= entry["published"] <= end

def score_entry(entry: Dict[str,Any], keywords: List[str], recent_bonus_hours: int) -> int:
    text = (entry["title"] + " " + entry["summary"]).lower()
    s = 0
    for kw in keywords:
        if kw.lower() in text:
            s += 1
    # recency bonus
    if entry["published"]:
        age_h = (dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc) - entry["published"]).total_seconds()/3600.0
        if age_h <= recent_bonus_hours:
            s += 1
    return s

def dedupe(entries: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
    seen = set()
    out = []
    for e in entries:
        k = (e["title"].strip().lower(), e["link"].strip().lower())
        if k in seen: 
            continue
        seen.add(k)
        out.append(e)
    return out

# --------------------------
# OpenAI helpers
# --------------------------

def openai_client() -> OpenAI:
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def call_llm(system: str, user: str, max_tokens: int = 3000, model_env: str = "OPENAI_MODEL") -> str:
    client = openai_client()
    model = os.environ.get(model_env, "gpt-4o-mini")
    r = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role":"system","content":system},
            {"role":"user","content":user}
        ],
        max_tokens=max_tokens
    )
    return (r.choices[0].message.content or "").strip()

def tts_mp3(text: str, out_path: pathlib.Path) -> None:
    model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.environ.get("OPENAI_TTS_VOICE", "alloy")
    client = openai_client()
    # Stream directly to file (most robust in Actions)
    with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text
    ) as resp:
        resp.stream_to_file(str(out_path))

# --------------------------
# Google Drive/Docs helpers
# --------------------------

def drive_upload_binary(drive, path: pathlib.Path, name: str, mime: str, folder_id: str|None) -> Tuple[str,str]:
    media = MediaFileUpload(str(path), mimetype=mime, resumable=False)
    body = {"name": name}
    if folder_id:
        body["parents"] = [folder_id]
    file = drive.files().create(body=body, media_body=media, fields="id,webViewLink,webContentLink").execute()
    return file["id"], file.get("webViewLink") or file.get("webContentLink") or ""

def doc_create(docs, title: str) -> str:
    d = docs.documents().create(body={"title": title}).execute()
    return d["documentId"]

def doc_batch_update(docs, doc_id: str, requests: List[Dict[str,Any]]) -> None:
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def doc_insert_text_requests(title: str, listen_url: str|None, briefing: str, analysis: str) -> List[Dict[str,Any]]:
    """
    Build Google Docs requests with proper headings.
    """
    reqs: List[Dict[str,Any]] = []
    cursor = 1  # always insert at start

    def insert(text: str):
        nonlocal cursor
        reqs.append({"insertText":{"location":{"index":cursor},"text":text}})
        cursor += len(text)

    def style_block(start: int, end: int, heading: str):
        reqs.append({
            "updateParagraphStyle":{
                "range":{"startIndex":start,"endIndex":end},
                "paragraphStyle":{"namedStyleType": heading},
                "fields":"namedStyleType"
            }
        })

    # H1: title
    start = cursor
    insert(title + "\n")
    style_block(start, cursor, "HEADING_1")
    insert("\n")

    # Listen link (if any)
    if listen_url:
        start = cursor
        insert("▶ Listen to this briefing (MP3)\n")
        style_block(start, cursor, "HEADING_2")
        # add link right below as a normal paragraph
        insert(listen_url + "\n\n")

    # H2: Weekly Economic & Policy Overview
    start = cursor
    insert("Weekly Economic & Policy Overview\n")
    style_block(start, cursor, "HEADING_2")
    insert(briefing.strip() + "\n\n")

    # H2: Weekly EU Policy Analysis
    start = cursor
    insert("Weekly EU Policy Analysis\n")
    style_block(start, cursor, "HEADING_2")
    insert(analysis.strip() + "\n")

    return reqs

# --------------------------
# Weekly synthesis
# --------------------------

def build_prompts(selected: List[Dict[str,Any]], week_range: Tuple[dt.datetime, dt.datetime]) -> Tuple[str,str]:
    """Create prompts for the 2500+ word briefing and the single analysis block (no markdown #)."""
    start, end = week_range
    iso_start = start.date().isoformat()
    iso_end   = end.date().isoformat()

    refs = []
    for i, e in enumerate(selected, 1):
        refs.append(f"[{i}] {e['title']} — {e['link']}")

    corpus = "\n".join(f"- {e['title']} :: {e['summary']} :: {e['link']}" for e in selected)

    sys = (
        "You are a policy analyst. Write in clear, professional prose for an expert audience. "
        "No Markdown hash headings. Use normal paragraphs and explicit section headings when asked."
    )

    user_briefing = (
        f"Time window: {iso_start} to {iso_end}.\n"
        f"Sources (titles, snippet, URL):\n{corpus}\n\n"
        "Task: Produce a comprehensive weekly briefing of at least 2,500 words (hard minimum). "
        "Structure: Start with 1–2 paragraphs of the week's top line narrative, then discuss the "
        "most material developments across monetary policy, markets, banking, insurance, digital/AI, "
        "ESG, institutions, and defence. Weave the most relevant items into the narrative in-text "
        "using bracketed reference numbers like [3], [7] aligned to the reference list. "
        "Avoid Markdown symbols; write clean paragraphs only."
        "\n\nReferences:\n" + "\n".join(refs)
    )

    user_analysis = (
        f"Using the same sources, write one consolidated 'Weekly EU Policy Analysis' section (800–1200 words). "
        "Summarise cross-cutting implications for EU financial markets and defence policy. "
        "Use clear sub-paragraphs; no Markdown symbols. Use bracketed citations [n] where helpful "
        "matching the reference list above."
    )

    return (sys + "\n", user_briefing), (sys + "\n", user_analysis)

def enforce_min_words(text: str, min_words: int = 2500) -> str:
    words = text.split()
    if len(words) >= min_words:
        return text
    # Ask model to expand with more detail, consistent tone.
    add = call_llm(
        "You are extending the same analysis without changing conclusions. No Markdown; keep same tone.",
        f"Current text (~{len(words)} words):\n\n{text}\n\n"
        f"Please expand to at least {min_words} words by elaborating on mechanisms, channels, "
        "comparative context within the EU, and potential policy paths.",
        max_tokens=3000,
        model_env="OPENAI_MODEL"
    )
    return text + "\n\n" + add

def main():
    cfg = load_config()
    feeds = cfg.get("feeds", [])
    keywords = cfg.get("keywords", [])
    recent_bonus = int(cfg.get("recent_hours", 72))
    max_total = int(cfg.get("caps", {}).get("max_total", 50))  # weekly cap (we keep 50)
    # week window
    wstart, wend = last_7_days_utc()

    # 1) Fetch & filter
    all_entries: List[Dict[str,Any]] = []
    for u in feeds:
        try:
            all_entries.extend(fetch_feed(u))
        except Exception as ex:
            print(f"[warn] feed error: {u} -> {ex}")

    # within last 7 days (keep unknown dates too)
    week_entries = [e for e in all_entries if within_week(e, wstart, wend)]
    week_entries = dedupe(week_entries)

    # score + sort
    for e in week_entries:
        e["_score"] = score_entry(e, keywords, recent_bonus)
        # de-prioritise very old/undated
        if e["published"] is None:
            e["_score"] -= 1

    week_entries.sort(key=lambda x: (x["_score"], x.get("published") or dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)), reverse=True)

    selected = week_entries[:max_total]

    # 2) Build prompts & call LLM
    (sys_b, user_b), (sys_a, user_a) = build_prompts(selected, (wstart, wend))
    briefing = call_llm(sys_b, user_b, max_tokens=5000, model_env="OPENAI_MODEL")
    briefing = enforce_min_words(briefing, min_words=2500)

    analysis = call_llm(sys_a, user_a, max_tokens=2000, model_env="OPENAI_MODEL")

    # 3) Prepare outputs
    today = ams_today()
    week_label = f"{(wend - dt.timedelta(days=7)).date().isoformat()} to {wend.date().isoformat()}"
    title = f"Weekly — EU Finance & Defence — {week_label} ({wend.isocalendar().week:02d})"

    # Audio text = title + brief + short bridge + analysis (single block)
    audio_text = f"{title}. Weekly Economic and Policy Overview. {briefing}\n\nWeekly EU Policy Analysis. {analysis}"

    # local paths
    safe_date = wend.date().isoformat()
    doc_md_path = REPORTS_DIR / f"{safe_date}-weekly.md"     # optional mirror (not used by doc)
    mp3_path    = REPORTS_DIR / f"{safe_date}-weekly.mp3"

    # 4) Generate TTS MP3
    try:
        print("[audio] generating MP3...")
        tts_mp3(audio_text, mp3_path)
    except Exception as ex:
        print(f"[audio] FAILED, continuing without audio: {ex}")
        mp3_path = None

    # 5) Upload to Drive (+ share if requested)
    drive, docs = gd_services()
    folder_id = os.environ.get("GOOGLE_DOCS_FOLDER_ID") or None
    share_with = [e.strip() for e in (os.environ.get("GOOGLE_DOCS_SHARE_WITH") or "").split(",") if e.strip()]

    listen_url = None
    if mp3_path and mp3_path.exists():
        mp3_name = f"{title}.mp3"
        mp3_id, listen_url = drive_upload_binary(drive, mp3_path, mp3_name, "audio/mpeg", folder_id)
        # share (viewer)
        for addr in share_with:
            try:
                drive.permissions().create(fileId=mp3_id, body={"type":"user","role":"reader","emailAddress":addr}, sendNotificationEmail=False).execute()
            except Exception as ex:
                print(f"[share] mp3 perm for {addr} failed: {ex}")

    # 6) Create Google Doc with proper headings (and optional Listen link)
    doc_id = doc_create(docs, title)
    reqs = doc_insert_text_requests(title, listen_url, briefing, analysis)
    doc_batch_update(docs, doc_id, reqs)

    # share doc
    if share_with:
        for addr in share_with:
            try:
                drive.permissions().create(fileId=doc_id, body={"type":"user","role":"reader","emailAddress":addr}, sendNotificationEmail=False).execute()
            except Exception as ex:
                print(f"[share] doc perm for {addr} failed: {ex}")

    # 7) Optional local mirror for reference
    try:
        with open(doc_md_path, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n")
            if listen_url:
                f.write(f"[Listen (MP3)]({listen_url})\n\n")
            f.write("## Weekly Economic & Policy Overview\n\n")
            f.write(briefing + "\n\n")
            f.write("## Weekly EU Policy Analysis\n\n")
            f.write(analysis + "\n")
    except Exception as ex:
        print(f"[mirror] write failed: {ex}")

    print(f"[done] Google Doc ID: {doc_id}")
    if listen_url:
        print(f"[done] MP3 link: {listen_url}")

if __name__ == "__main__":
    main()
