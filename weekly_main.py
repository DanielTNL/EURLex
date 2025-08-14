#!/usr/bin/env python3
"""
Weekly EU Finance & Defence – synthesis + Google Docs + MP3 (TTS)

- Pulls the same feeds/keywords taxonomy as daily (config.yaml).
- Ranks, clusters, and selects up to ~50 key items for the week window.
- Generates a 2,500+ word Weekly Briefing + one “Weekly EU Policy Analysis” section.
- Uploads a nicely formatted Google Doc and an MP3 readout; inserts a "Listen" link at the top.
- Mirrors outputs to reports/weekly/.

Env:
  OPENAI_API_KEY
  OPENAI_MODEL               (weekly text model; defaults gpt-4o-mini)
  OPENAI_TTS_MODEL           (defaults gpt-4o-mini-tts)
  OPENAI_TTS_VOICE           (defaults alloy)
  GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REFRESH_TOKEN
  GOOGLE_DOCS_FOLDER_ID      (optional)
  GOOGLE_DOCS_SHARE_WITH     (optional, comma-separated emails)
"""

import os, sys, json, pathlib, datetime as dt
from typing import List, Dict, Any, Tuple

import pytz
import yaml
import feedparser

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from openai import OpenAI

ROOT = pathlib.Path(__file__).parent
REPORTS_DIR = ROOT / "reports" / "weekly"
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- Config / time ----------------

def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def ams_today() -> dt.date:
    tz = pytz.timezone("Europe/Amsterdam")
    return dt.datetime.now(tz=tz).date()

def last_7_days_utc() -> tuple[dt.datetime, dt.datetime]:
    # Return timezone-aware UTC datetimes
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=7)
    return start, end

# ---------------- Google auth ------------------

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

def gd_services():
    creds = google_creds()
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs  = build("docs",  "v1", credentials=creds, cache_discovery=False)
    return drive, docs

# ---------------- Feeds / scoring --------------

def fetch_feed(url: str) -> List[Dict[str, Any]]:
    p = feedparser.parse(url)
    out = []
    for e in p.entries:
        title = (e.get("title") or "").strip()
        link  = (e.get("link") or "").strip()
        summary = (e.get("summary") or e.get("description") or "").strip()
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

def within_week(entry: dict, start: dt.datetime, end: dt.datetime) -> bool:
    pub = entry.get("published")
    if pub is None:
        # Keep undated items; they’ll be de-prioritized later
        return True
    # Normalize to aware-UTC before comparing
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=dt.timezone.utc)
    return start <= pub <= end

def score_entry(entry: Dict[str,Any], keywords: List[str], recent_bonus_hours: int) -> int:
    text = (entry["title"] + " " + entry["summary"]).lower()
    s = sum(1 for kw in keywords if kw.lower() in text)
        if entry["published"]:
        now = dt.datetime.now(dt.timezone.utc)
        pub = entry["published"]
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=dt.timezone.utc)
        age_h = (now - pub).total_seconds() / 3600.0
        if age_h <= recent_bonus_hours:
            s += 1
    return s

def dedupe(entries: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
    seen, out = set(), []
    for e in entries:
        k = (e["title"].strip().lower(), e["link"].strip().lower())
        if k in seen: 
            continue
        seen.add(k); out.append(e)
    return out

# ---------------- OpenAI helpers ----------------

def openai_client() -> OpenAI:
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def call_llm(system: str, user: str, max_tokens: int = 4000, model_env: str = "OPENAI_MODEL") -> str:
    client = openai_client()
    model = os.environ.get(model_env, "gpt-4o-mini")
    r = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[{"role":"system","content":system},{"role":"user","content":user}],
        max_tokens=max_tokens
    )
    return (r.choices[0].message.content or "").strip()

def tts_mp3(text: str, out_path: pathlib.Path) -> None:
    model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.environ.get("OPENAI_TTS_VOICE", "alloy")
    client = openai_client()
    with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text
    ) as resp:
        resp.stream_to_file(str(out_path))

# -------------- Drive/Docs helpers --------------

def drive_upload_binary(drive, path: pathlib.Path, name: str, mime: str, folder_id: str|None):
    media = MediaFileUpload(str(path), mimetype=mime, resumable=False)
    body = {"name": name}
    if folder_id: body["parents"] = [folder_id]
    file = drive.files().create(body=body, media_body=media, fields="id,webViewLink,webContentLink").execute()
    return file["id"], file.get("webViewLink") or file.get("webContentLink") or ""

def doc_create(docs, title: str) -> str:
    d = docs.documents().create(body={"title": title}).execute()
    return d["documentId"]

def doc_batch_update(docs, doc_id: str, requests):
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def doc_insert_text_requests(title: str, listen_url: str|None, briefing: str, analysis: str):
    reqs = []
    cursor = 1

    def insert(text: str):
        nonlocal cursor
        reqs.append({"insertText":{"location":{"index":cursor},"text":text}})
        cursor += len(text)

    def style(start: int, end: int, named: str):
        reqs.append({"updateParagraphStyle":{
            "range":{"startIndex":start,"endIndex":end},
            "paragraphStyle":{"namedStyleType":named},
            "fields":"namedStyleType"}})

    # H1
    start = cursor; insert(title + "\n"); style(start, cursor, "HEADING_1"); insert("\n")

    # Listen link
    if listen_url:
        start = cursor; insert("▶ Listen to this briefing (MP3)\n"); style(start, cursor, "HEADING_2")
        insert(listen_url + "\n\n")

    # H2 briefing
    start = cursor; insert("Weekly Economic & Policy Overview\n"); style(start, cursor, "HEADING_2")
    insert(briefing.strip() + "\n\n")

    # H2 analysis
    start = cursor; insert("Weekly EU Policy Analysis\n"); style(start, cursor, "HEADING_2")
    insert(analysis.strip() + "\n")

    return reqs

# -------------- Prompts / synthesis --------------

def build_prompts(selected: List[Dict[str,Any]], window: Tuple[dt.datetime, dt.datetime]):
    start, end = window
    iso_start, iso_end = start.date().isoformat(), end.date().isoformat()

    refs = [f"[{i}] {e['title']} — {e['link']}" for i, e in enumerate(selected, 1)]
    corpus = "\n".join(f"- {e['title']} :: {e['summary']} :: {e['link']}" for e in selected)

    sys = ("You are a policy analyst. Write in clear professional prose for an expert audience. "
           "No Markdown hash symbols; use plain paragraphs.")

    user_brief = (
        f"Time window: {iso_start} to {iso_end}.\n"
        f"Sources (title :: snippet :: URL):\n{corpus}\n\n"
        "Task: Produce a comprehensive weekly briefing of at least 2,500 words (hard minimum). "
        "Start with 1–2 paragraphs that state the week’s top-line narrative. Then cover monetary policy, "
        "financial markets, banking/insurance, digital/AI, ESG, EU institutions, and defence. "
        "Weave items into the narrative with bracketed citations like [3], [7] matching this list:\n"
        + "\n".join(refs)
    )

    user_analysis = (
        "Write one consolidated 'Weekly EU Policy Analysis' section (800–1200 words). "
        "Summarise cross-cutting implications for EU financial markets and defence policy. "
        "Use clear sub-paragraphs (plain text), with bracketed citations [n] where helpful matching the list above."
    )

    return (sys, user_brief), (sys, user_analysis)

def enforce_min_words(text: str, min_words: int = 2500) -> str:
    if len(text.split()) >= min_words:
        return text
    extra = call_llm(
        "You extend analysis without changing conclusions. Plain paragraphs; consistent tone.",
        f"Current text has {len(text.split())} words:\n\n{text}\n\n"
        f"Expand to at least {min_words} words by deepening mechanisms, EU context, and policy channels.",
        max_tokens=3500
    )
    return text + "\n\n" + extra

# ----------------------------- main -----------------------------

def main():
    cfg = load_config()
    feeds = cfg.get("feeds", [])
    keywords = cfg.get("keywords", [])
    recent_bonus = int(cfg.get("recent_hours", 72))
    max_total = int(cfg.get("caps", {}).get("max_total", 50))

    wstart, wend = last_7_days_utc()

    # fetch
    all_entries: List[Dict[str,Any]] = []
    for u in feeds:
        try:
            all_entries.extend(fetch_feed(u))
        except Exception as ex:
            print(f"[warn] feed error: {u} -> {ex}")

    week_entries = [e for e in all_entries if within_week(e, wstart, wend)]
    week_entries = dedupe(week_entries)

    for e in week_entries:
        e["_score"] = score_entry(e, keywords, recent_bonus)
        if e["published"] is None:
            e["_score"] -= 1

    week_entries.sort(key=lambda x: (x["_score"], x.get("published") or dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)), reverse=True)
    selected = week_entries[:max_total]

    (sys_b, user_b), (sys_a, user_a) = build_prompts(selected, (wstart, wend))
    briefing = call_llm(sys_b, user_b, max_tokens=5000)
    briefing = enforce_min_words(briefing, 2500)
    analysis = call_llm(sys_a, user_a, max_tokens=2000)

    week_label = f"{(wend - dt.timedelta(days=7)).date().isoformat()} to {wend.date().isoformat()}"
    title = f"Weekly — EU Finance & Defence — {week_label} ({wend.isocalendar().week:02d})"
    safe_date = wend.date().isoformat()

    # Audio
    mp3_path = REPORTS_DIR / f"{safe_date}-weekly.mp3"
    listen_url = None
    try:
        print("[audio] generating MP3...")
        tts_mp3(f"{title}. Weekly Economic and Policy Overview. {briefing}\n\nWeekly EU Policy Analysis. {analysis}", mp3_path)
    except Exception as ex:
        print(f"[audio] FAILED: {ex}")
        mp3_path = None

    drive, docs = gd_services()
    folder_id = os.environ.get("GOOGLE_DOCS_FOLDER_ID") or None
    share_with = [s.strip() for s in (os.environ.get("GOOGLE_DOCS_SHARE_WITH") or "").split(",") if s.strip()]

    if mp3_path and mp3_path.exists():
        mp3_name = f"{title}.mp3"
        mp3_id, listen_url = drive_upload_binary(drive, mp3_path, mp3_name, "audio/mpeg", folder_id)
        for addr in share_with:
            try:
                drive.permissions().create(fileId=mp3_id, body={"type":"user","role":"reader","emailAddress":addr}, sendNotificationEmail=False).execute()
            except Exception as ex:
                print(f"[share] mp3 perm for {addr} failed: {ex}")

    doc_id = doc_create(docs, title)
    reqs = doc_insert_text_requests(title, listen_url, briefing, analysis)
    doc_batch_update(docs, doc_id, reqs)

    if share_with:
        for addr in share_with:
            try:
                drive.permissions().create(fileId=doc_id, body={"type":"user","role":"reader","emailAddress":addr}, sendNotificationEmail=False).execute()
            except Exception as ex:
                print(f"[share] doc perm for {addr} failed: {ex}")

    print(f"[done] Google Doc ID: {doc_id}")
    if listen_url:
        print(f"[done] MP3 link: {listen_url}")

if __name__ == "__main__":
    main()
