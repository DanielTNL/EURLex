#!/usr/bin/env python3
# Bridge: neem v2-uitvoer en publiceer naar paden die de site leest.
# Schrijft naar BEIDE plekken:
#  - docs/site/live.json, key-items.json, reports_timeline.json, digest_latest.json
#  - docs/live.json,    key-items.json, reports_timeline.json, digest_latest.json
# Behoudt ook docs/data/timeline-latest.json (v2).

import os, json, glob
from datetime import datetime, timedelta, timezone
from dateutil import parser as dtparse

ROOT_DIR = "docs"
SITE_DIR = "docs/site"
DATA_DIR = "docs/data"
NDJSON_GLOB = "outputs/docs/*.ndjson"
TIMELINE_GLOB = "outputs/timelines/*.json"
DAILY_LATEST = "docs/digests/latest.json"

SOURCE_LABELS = {
    "investeu_news": "InvestEU",
    "eib_press": "EIB",
    "eif_news": "EIF",
    "edf_publications": "EDF",
    "esma_publications": "ESMA",
    "investnl_news": "Invest-NL",
    "afme_news": "AFME",
    "airbus_press": "Airbus",
    "boeing_press": "Boeing",
    "helsing_news": "Helsing",
    "anduril_news": "Anduril",
    "palantir_press": "Palantir",
    "mckinsey_media": "McKinsey",
    "pwc_press": "PwC",
    "euronews_tech": "Euronews (Tech)",
    "nato_news": "NATO",
    "rand_press": "RAND",
    "bruegel_publications": "Bruegel",
}

MAJOR_PROGRAMMES = {"InvestEU","EIB","EIF","EDF","ESMA"}

def ensure_dirs():
    os.makedirs(ROOT_DIR, exist_ok=True)
    os.makedirs(SITE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

def parse_dt(s):
    if not s: return None
    try:
        d = dtparse.parse(s)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None

def load_ndjson(glob_pat):
    recs = []
    for path in sorted(glob.glob(glob_pat)):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    obj = json.loads(line)
                    if obj.get("schema") == "document.v2":
                        recs.append(obj)
                except Exception:
                    continue
    return recs

def latest_file(glob_pat):
    files = sorted(glob.glob(glob_pat), key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0] if files else None

def categorise(rec):
    progs = set(rec.get("programme") or [])
    techs = set(rec.get("tech_area") or [])
    sid = rec.get("source_id","")
    if "EDF" in progs or sid in {"helsing_news","anduril_news","boeing_press","airbus_press","nato_news"}:
        return "Defence & Security"
    if "ESMA" in progs or "afme" in sid:
        return "CMU & Financial Markets"
    if techs:
        return "AI & Digital"
    if progs & {"InvestEU","EIB","EIF"} or sid == "investnl_news":
        return "De-risking & Investment"
    return "Other"

def map_live(rec):
    title = rec.get("title") or "(untitled)"
    url = rec.get("canonical_url") or rec.get("url")
    date = rec.get("published_date") or rec.get("fetch_time")
    src_id = rec.get("source_id","unknown")
    src = SOURCE_LABELS.get(src_id, src_id)
    tags = (rec.get("tech_area") or []) + (rec.get("programme") or [])
    return {
        "title": title,
        "url": url,
        "source_id": src_id,
        "source": src,
        "date": date,
        "doc_type": rec.get("doc_type") or "News",
        "tags": tags[:12],
        "category": categorise(rec)
    }

def score_key(rec):
    score = 0
    if rec.get("monetary_values"): score += 3
    if set(rec.get("programme") or []) & MAJOR_PROGRAMMES: score += 2
    if rec.get("tech_area"): score += 1
    if (rec.get("doc_type") or "").lower() in {"guidance/notice","call_for_proposals","work_programme"}:
        score += 2
    return score

def write_json(obj, *paths):
    for p in paths:
        d = os.path.dirname(p)
        if d: os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

def main():
    ensure_dirs()
    now = datetime.now(timezone.utc)

    # Live feed: laatste 30 dagen
    records = load_ndjson(NDJSON_GLOB)
    cutoff = now - timedelta(days=30)
    recent = []
    for r in records:
        d = parse_dt(r.get("published_date") or r.get("fetch_time"))
        if d and d >= cutoff:
            recent.append(r)
    recent.sort(key=lambda r: r.get("published_date") or r.get("fetch_time") or "", reverse=True)

    live_items = [map_live(r) for r in recent[:200]]
    key_items = [map_live(r) for r in sorted(recent, key=score_key, reverse=True)[:20]]

    # Timeline
    reports_timeline = {"schema":"timeline.v1","events":[]}
    tl_file = latest_file(TIMELINE_GLOB)
    if tl_file:
        with open(tl_file, "r", encoding="utf-8") as f:
            reports_timeline = json.load(f)

    # Daily digest (laatste)
    digest_latest = None
    if os.path.exists(DAILY_LATEST):
        with open(DAILY_LATEST, "r", encoding="utf-8") as f:
            digest_latest = json.load(f)

    # Schrijf site + root
    write_json({"generated_at": now.isoformat(), "items": live_items},
               f"{SITE_DIR}/live.json", f"{ROOT_DIR}/live.json")
    write_json({"generated_at": now.isoformat(), "items": key_items},
               f"{SITE_DIR}/key-items.json", f"{ROOT_DIR}/key-items.json")
    write_json(reports_timeline,
               f"{SITE_DIR}/reports_timeline.json", f"{ROOT_DIR}/reports_timeline.json")
    if digest_latest:
        write_json(digest_latest,
                   f"{SITE_DIR}/digest_latest.json", f"{ROOT_DIR}/digest_latest.json")

    # Houd v2 payloads ook bij
    if tl_file:
        write_json(reports_timeline, f"{DATA_DIR}/timeline-latest.json")

    # Kleine index
    by_source = {}
    for r in recent:
        sid = r.get("source_id","unknown")
        by_source[sid] = by_source.get(sid, 0) + 1
    index = {
        "schema": "site_index.v1",
        "generated_at": now.isoformat(),
        "sources": by_source,
        "live_count": len(live_items),
        "key_items": len(key_items),
        "timeline_events": len(reports_timeline.get("events", []))
    }
    write_json(index, f"{SITE_DIR}/index.json", f"{ROOT_DIR}/index.json")

    print(json.dumps({"status":"ok","live":len(live_items),"key":len(key_items),
                      "timeline_events":len(reports_timeline.get("events",[]))}, ensure_ascii=False))

if __name__ == "__main__":
    main()
