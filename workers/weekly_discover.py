#!/usr/bin/env python3
import json, argparse, datetime as dt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="7d")
    ap.add_argument("--sources", default="sources_v2.yaml")
    ap.add_argument("--config", default="config_v2.yaml")
    args = ap.parse_args()

    now = dt.datetime.utcnow().isoformat() + "Z"
    payload = {
        "schema": "discovery.v1",
        "source_id": "stub",
        "discovered_at": now,
        "base_url": "",
        "items": []
    }
    print(json.dumps(payload))

if __name__ == "__main__":
    main()
