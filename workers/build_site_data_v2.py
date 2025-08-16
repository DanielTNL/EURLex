#!/usr/bin/env python3
# Minimal site payload: publish last timeline + simple aggregates to docs/data/.

import os, json, glob
from datetime import datetime

def latest(path_glob):
    files = sorted(glob.glob(path_glob), key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0] if files else None

def ensure_dirs():
    os.makedirs("docs/data", exist_ok=True)

def main():
    ensure_dirs()

    # 1) timeline
    tl_file = latest("outputs/timelines/*.json")
    if tl_file:
        with open(tl_file, "r", encoding="utf-8") as f:
            tl = json.load(f)
        with open("docs/data/timeline-latest.json", "w", encoding="utf-8") as out:
            json.dump(tl, out, ensure_ascii=False)

    # 2) aggregates over most recent ndjson
    ndjson_file = latest("outputs/docs/*.ndjson")
    agg = {"schema":"site_aggregate.v1","generated_at":datetime.utcnow().isoformat()+"Z","by_source":{}, "total":0}
    if ndjson_file:
        by_source = {}
        with open(ndjson_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    rec = json.loads(line)
                except Exception: 
                    continue
                sid = rec.get("source_id","unknown")
                by_source[sid] = by_source.get(sid, 0) + 1
                agg["total"] += 1
        agg["by_source"] = by_source

    with open("docs/data/summary-latest.json", "w", encoding="utf-8") as out:
        json.dump(agg, out, ensure_ascii=False, indent=2)

    print(json.dumps({"timeline": tl_file, "ndjson": ndjson_file}, ensure_ascii=False))

if __name__ == "__main__":
    main()
