#!/usr/bin/env python3
import json, argparse, datetime as dt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="7d")
    ap.add_argument("--config", default="config_v2.yaml")
    args = ap.parse_args()

    now = dt.datetime.utcnow().isoformat() + "Z"
    timeline = {
        "schema": "timeline.v1",
        "window": {"start": now, "end": now, "timezone": "Europe/Amsterdam"},
        "events": []
    }
    print(json.dumps(timeline))

if __name__ == "__main__":
    main()
