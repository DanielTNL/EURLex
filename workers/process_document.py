#!/usr/bin/env python3
import argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="queue", required=False, help="path to discovery output (JSON)")
    ap.add_argument("--config", default="config_v2.yaml")
    ap.parse_args()
    # No-op placeholder; emits nothing and exits successfully.
    return

if __name__ == "__main__":
    main()
