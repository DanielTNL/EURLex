#!/usr/bin/env python3
# Create a daily digest from the last N hours of processed docs.
# Writes:
# - reports/daily/YYYY-MM-DD.md (human readable)
# - docs/digests/YYYY-MM-DD.json (API)
# - docs/digests/latest.json (pointer for website)

import os, json, glob, argparse
from datetime import datetime, timedelta, timezone
from dateutil import parser as dtparse

def load_lines(paths):
    for p in paths:
        if not os.path.exists(p): 
            continue
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue

def parse_dt(s):
    try:
        d = dtparse.parse(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None

def ensure_dirs():
    os.makedirs("reports/daily", exist_ok=True)
    os.makedirs("docs/digests", exist_ok=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()

    ensure_dirs()
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=args.hours)

    # Collect docs from all ndjson files
    ndjson_files = sorted(glob.glob("outputs/docs/*.ndjson"))
    items = []
    for rec in load_lines(ndjson_files):
        pd = parse_dt(rec.get("published_date") or rec.get("fetch_time"))
        if not pd: 
            continue
        if start <= pd <= now:
            items.append({
                "title": rec.get("title"),
                "url": rec.get("canonical_url") or rec.get("url"),
                "source_id": rec.get("source_id"),
                "published_date": pd.isoformat(),
                "doc_type": rec.get("doc_type"),
                "programme": rec.get("programme") or [],
                "finance_instrument": rec.get("finance_instrument") or [],
                "tech_area": rec.get("tech_area") or [],
                "summary_150w": rec.get("summary_150w")
            })

    # sort newest first
    items.sort(key=lambda x: x.get("published_date") or "", reverse=True)

    date_str = now.astimezone(timezone.utc).date().isoformat()
    out_json_path = f"docs/digests/{date_str}.json"
    out_json_latest = "docs/digests/latest.json"
    out_md_path = f"reports/daily/{date_str}.md"

    payload = {
        "schema": "daily_digest.v1",
        "generated_at": now.isoformat(),
        "window_hours": args.hours,
        "count": len(items),
        "items": items
    }

    # JSON outputs
    with open(out_json_path, "w", encoding="utf-8") as jf:
        json.dump(payload, jf, ensure_ascii=False, indent=2)
    with open(out_json_latest, "w", encoding="utf-8") as jf:
        json.dump(payload, jf, ensure_ascii=False)

    # Markdown (simple)
    with open(out_md_path, "w", encoding="utf-8") as mf:
        mf.write(f"# Daily Digest — {date_str}\n\n")
        mf.write(f"_Items in last {args.hours}h: {len(items)}_\n\n")
        for i, it in enumerate(items, 1):
            progs = ", ".join(it.get("programme") or [])
            inst = ", ".join(it.get("finance_instrument") or [])
            tech = ", ".join(it.get("tech_area") or [])
            mf.write(f"**{i}. {it['title']}**  \n")
            mf.write(f"Bron: `{it.get('source_id')}` · Datum: {it.get('published_date')}  \n")
            if progs: mf.write(f"Programma: {progs}  \n")
            if inst:  mf.write(f"Instrument: {inst}  \n")
            if tech:  mf.write(f"Tech: {tech}  \n")
            if it.get("summary_150w"):
                mf.write(f"{it['summary_150w']}\n")
            mf.write(f"[Link]({it['url']})\n\n")

    print(json.dumps({
        "status": "ok",
        "json": out_json_path,
        "latest": out_json_latest,
        "markdown": out_md_path,
        "count": len(items)
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
