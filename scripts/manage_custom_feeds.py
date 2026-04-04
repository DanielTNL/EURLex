#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / 'state' / 'custom_feeds.json'
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {'updated_at': '', 'feeds': []}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {'updated_at': '', 'feeds': []}
    if not isinstance(payload, dict):
        return {'updated_at': '', 'feeds': []}
    payload.setdefault('feeds', [])
    payload.setdefault('updated_at', '')
    return payload


def save_state(payload: dict) -> None:
    payload['updated_at'] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def default_name(url: str) -> str:
    host = (urlparse(url).netloc or url).lower().lstrip('www.')
    return host or url


def add_feed(payload: dict, url: str, name: str | None) -> dict:
    feeds = payload.get('feeds', [])
    if any(isinstance(item, dict) and item.get('url') == url for item in feeds):
        return {'status': 'unchanged', 'reason': 'already_present', 'url': url}
    entry = {
        'source_id': default_name(url),
        'name': (name or default_name(url)).strip(),
        'url': url,
        'type': 'feed',
        'enabled': True,
    }
    feeds.append(entry)
    payload['feeds'] = sorted(feeds, key=lambda item: (item.get('name', ''), item.get('url', '')))
    save_state(payload)
    return {'status': 'added', 'url': url, 'name': entry['name']}


def remove_feed(payload: dict, url: str) -> dict:
    before = len(payload.get('feeds', []))
    payload['feeds'] = [item for item in payload.get('feeds', []) if not (isinstance(item, dict) and item.get('url') == url)]
    if len(payload['feeds']) == before:
        return {'status': 'unchanged', 'reason': 'not_found', 'url': url}
    save_state(payload)
    return {'status': 'removed', 'url': url}


def main() -> int:
    parser = argparse.ArgumentParser(description='Manage custom RSS feeds for the GitHub pipeline.')
    parser.add_argument('action', choices=['add', 'remove', 'list'])
    parser.add_argument('--url', help='Feed URL for add/remove actions')
    parser.add_argument('--name', help='Optional display name for add action')
    args = parser.parse_args()

    payload = load_state()

    if args.action == 'list':
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not args.url:
        raise SystemExit('--url is required for add/remove actions')

    if args.action == 'add':
        result = add_feed(payload, args.url.strip(), args.name)
    else:
        result = remove_feed(payload, args.url.strip())

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
