#!/usr/bin/env python3
# Bridge: neem v2-uitvoer (document.v2 NDJSON + timeline.v1) en publiceer
# naar paden die je front-end kan lezen.
# Schrijft:
# - docs/site/live.json               (laatste 50 items)
# - docs/site/reports_timeline.json   (rolling timeline 7d/30d)
# - docs/site/digest_latest.json      (kopie van docs/digests/latest.json)
# - docs/data/timeline-latest.json    (blijft bestaan voor v2)
# - docs/site/index.json              (kleine index/statistiek)

import os, json, glob, re
from datetime import datetime, timedelta, timezone
from dateutil import parser as dtparse

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

def load_ndjson(paths_glob):
    records = []
    for path in sorted(glob.glob(paths_glob)):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    rec = json.loads(line)
                    if rec.get("schema") == "document.v2":
                        records.append(rec)
                except Exception:
                    continue
    return records

def latest_file(glob_pat):
    files = sorted(glob.glob(glob_pat), key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0] if files else None

def categorise(rec):
    # Basic, but useful for filters in je UI
    progs = set(rec.get("programme") or [])
    techs = set(rec.get("tech_area") or [])
    sid = rec.get("source_id","")

    if "EDF" in progs or sid in {"helsing_news","anduril_news","boeing_press","airbus_press","nato_news"}:
        return "Defence & Security"
    if "ESMA" in progs or any(k in sid for k in ["afme"]):
        return "CMU & Financial Markets"
    if techs:
        return "AI & Digital"
    if progs & {"InvestEU","EIB","EIF"} or sid in {"investnl_news"}:
        return "De-risking & Investment"
    return "Other"

def map_live_item(rec):
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

def score_key_item(rec):
    score = 0
    if rec.get("monetary_values"): score += 3
    if set(rec.get("programme") or []) & MAJOR_PROGRAMMES: score += 2
    if rec.get("tech_area"): score += 1
    if (rec.get("doc_type") or "").lower() in {"guidance/notice","call_for_proposals","work_programme"}:
        score += 2
    return score

def main():
    ensure_dirs()
    now = datetime.now(timezone.utc)

    # 1) live feed uit laatste 30 dagen
    records = load_ndjson(NDJSON_GLOB)
    cutoff = now - timedelta(days=30)
    filtered = []
    for r in records:
        d = parse_dt(r.get("published_date") or r.get("fetch_time"))
        if not d: continue
        if d >= cutoff:
            filtered.append(r)

    # sort nieuw → oud
    filtered.sort(key=lambda r: r.get("published_date") or r.get("fetch_time") or "", reverse=True)

    live_items = [map_live_item(r) for r in filtered[:200]]  # hou compact voor frontend
    key_items = sorted(filtered, key=score_key_item, reverse=True)[:20]
    key_items = [map_live_item(r) for r in key_items]

    # 2) timeline: pak laatste timeline-bestand (v2) en dupliceer als site-payload
    tl_file = latest_file(TIMELINE_GLOB)
    reports_timeline = {"schema":"timeline.v1","events":[]}
    if tl_file:
        with open(tl_file, "r", encoding="utf-8") as f:
            reports_timeline = json.load(f)

    # 3) daily digest (laatste)
    digest_latest = None
    if os.path.exists(DAILY_LATEST):
        with open(DAILY_LATEST, "r", encoding="utf-8") as f:
            digest_latest = json.load(f)

    # Schrijf site-bestanden
    with open(f"{SITE_DIR}/live.json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": now.isoformat(), "items": live_items}, f, ensure_ascii=False)
    with open(f"{SITE_DIR}/key-items.json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": now.isoformat(), "items": key_items}, f, ensure_ascii=False)
    with open(f"{SITE_DIR}/reports_timeline.json", "w", encoding="utf-8") as f:
        json.dump(reports_timeline, f, ensure_ascii=False)
    if digest_latest:
        with open(f"{SITE_DIR}/digest_latest.json", "w", encoding="utf-8") as f:
            json.dump(digest_latest, f, ensure_ascii=False)

    # Houd ook de v2 data aan voor andere consumers
    if tl_file:
        with open("docs/data/timeline-latest.json", "w", encoding="utf-8") as f:
            json.dump(reports_timeline, f, ensure_ascii=False)

    # kleine index/telemetrie
    by_source = {}
    for r in filtered:
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
    with open(f"{SITE_DIR}/index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(json.dumps({"status":"ok","live":len(live_items),"key":len(key_items),
                      "timeline_events":len(reports_timeline.get("events",[]))}, ensure_ascii=False))

if __name__ == "__main__":
    main()
