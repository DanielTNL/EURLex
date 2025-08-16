#!/usr/bin/env python3
# Build a weekly timeline from document.v2 NDJSON files.
# Safe: reads outputs/docs/*.ndjson, writes outputs/timelines/YYYY-WW.json

import argparse, os, sys, json, glob, re
from datetime import datetime, timezone, timedelta

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="7d", help="Number of days, e.g. 7d")
    ap.add_argument("--config", default="config_v2.yaml")  # not used yet (kept for symmetry)
    return ap.parse_args()

def parse_iso(dtstr):
    try:
        # tolerate "Z"
        if dtstr.endswith("Z"):
            return datetime.fromisoformat(dtstr.replace("Z", "+00:00"))
        return datetime.fromisoformat(dtstr)
    except Exception:
        return None

def short_text(s, max_words=40):
    if not s:
        return ""
    words = re.split(r"\s+", s.strip())
    return " ".join(words[:max_words])

def iso_week_path(prefix="outputs/timelines"):
    now = datetime.now(timezone.utc).isocalendar()
    year, week = now[0], now[1]
    os.makedirs(prefix, exist_ok=True)
    return f"{prefix}/{year}-{week:02d}.json"

def load_ndjson(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items

def main():
    args = parse_args()
    # compute window
    m = re.match(r"^(\d+)d$", args.window.strip())
    days = int(m.group(1)) if m else 7
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    # gather documents
    docs = []
    for fp in glob.glob("outputs/docs/*.ndjson"):
        docs.extend(load_ndjson(fp))

    # filter + map to events
    events = []
    for rec in docs:
        if rec.get("schema") != "document.v2":
            continue
        d = parse_iso(rec.get("published_date") or "")
        if not d:
            continue
        if not (start_dt <= d < end_dt):
            continue

        title = rec.get("title") or "(untitled)"
        url = rec.get("canonical_url") or rec.get("url")
        doc_type = rec.get("doc_type") or "Blog/News"
        programme = rec.get("programme") or []
        tech = rec.get("tech_area") or []
        stage = rec.get("stage") or "NA"
        summary = rec.get("summary_150w") or ""
        short = short_text(summary or title, max_words=40)

        amounts = []
        for mv in (rec.get("monetary_values") or []):
            amt = mv.get("amount")
            cur = mv.get("currency")
            if isinstance(amt, (int, float)) and cur:
                amounts.append({"amount": amt, "currency": cur})

        events.append({
            "date": d.isoformat(),
            "title": title,
            "url": url,
            "doc_type": doc_type,
            "programme": programme,
            "tech_area": tech,
            "stage": stage,
            "short": short,
            "amounts": amounts
        })

    # sort newest→oldest
    events.sort(key=lambda e: e["date"], reverse=True)

    timeline = {
        "schema": "timeline.v1",
        "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat(), "timezone": "Europe/Amsterdam"},
        "events": events
    }

    out_path = iso_week_path()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "timeline_file": out_path,
        "events": len(events),
        "window_days": days
    }))

if __name__ == "__main__":
    main()
