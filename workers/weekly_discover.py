#!/usr/bin/env python3
"""
weekly_discover.py
------------------
Discover new documents/items from configured sources over a recent time window
and write a single aggregated state file:

  state/latest_discovery.json

The output structure is intentionally simple and stable:
{
  "generated_at": "<ISO8601 UTC>",
  "window": "1d",
  "cutoff_utc": "<ISO8601 UTC>",
  "items": [
    {
      "id": "<stable hash of url>",
      "source": "<source name or host>",
      "title": "<title>",
      "url": "<absolute url>",
      "published_at": "<ISO8601 | '' if unknown>",
      "summary": "<optional short text>",
      "tags": []
    },
    ...
  ],
  "documents": [],   # kept for downstream compatibility
  "sources": [ ... ] # list of source names processed
}

USAGE (as in your workflow):
  python workers/weekly_discover.py --window 1d --sources sources_v2.yaml --config config_v2.yaml

Notes:
- Uses `feedparser` first for feeds (robust), and falls back to tolerant BeautifulSoup.
- Never lets a single broken source crash the run; errors are logged and the loop continues.
- If everything fails, it still writes a valid (empty) state file so the pipeline continues.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import feedparser  # tolerant feed parser
from bs4 import BeautifulSoup  # tolerant HTML/XML via helper below
from dateutil import parser as dateparse
import yaml

USER_AGENT = "Mozilla/5.0 (compatible; PipelineV2/1.0; +https://example.com)"
REQ_TIMEOUT = 20
MAX_HTML_LINKS = 200  # soft cap per page


# -------------------------- helpers: parsing & robustness --------------------------

def safe_soup(markup: str, prefer_xml: bool = False) -> BeautifulSoup:
    """
    Try multiple parsers so bad XML/feeds don't crash the run.
    """
    parsers_xml_first = ["lxml-xml", "xml", "lxml", "html5lib", "html.parser"]
    parsers_html_first = ["lxml", "html5lib", "html.parser", "lxml-xml", "xml"]
    chain = parsers_xml_first if prefer_xml else parsers_html_first
    last_err: Optional[Exception] = None
    for p in chain:
        try:
            return BeautifulSoup(markup, p)
        except Exception as e:
            last_err = e
            print(f"[discover] parser={p} failed: {e}", file=sys.stderr)
    print(f"[discover] falling back to html.parser due to: {last_err}", file=sys.stderr)
    return BeautifulSoup(markup, "html.parser")


def looks_like_feed(text: str, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if "xml" in ct or "rss" in ct or "atom" in ct:
        return True
    head = text.lstrip()[:300].lower()
    return ("<rss" in head) or ("<feed" in head and "xmlns" in head)


def is_abs_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return bool(p.scheme and p.netloc)
    except Exception:
        return False


def normalize_url(base: str, href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    try:
        absu = href if is_abs_url(href) else urljoin(base, href)
        p = urlparse(absu)
        # Strip fragments and redundant parts
        p = p._replace(fragment="")
        return urlunparse(p)
    except Exception:
        return href


def stable_id(u: str) -> str:
    return hashlib.sha1(u.encode("utf-8", "ignore")).hexdigest()


def parse_date_to_iso(s: str) -> str:
    if not s:
        return ""
    try:
        dt = dateparse.parse(s)
        if not dt:
            return ""
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


def within_window(iso_str: str, cutoff_utc: datetime) -> bool:
    if not iso_str:
        return True  # keep items with unknown date; downstream can decide
    try:
        dt = dateparse.parse(iso_str)
        if not dt:
            return True
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc) >= cutoff_utc
    except Exception:
        return True


# -------------------------------- config & sources --------------------------------

@dataclass
class Source:
    name: str
    url: str
    type: Optional[str] = None  # "feed" | "html" | None=auto
    selector: Optional[str] = None  # CSS selector for links/items (HTML)
    link_attr: Optional[str] = None  # e.g. "href"
    title_selector: Optional[str] = None
    time_selector: Optional[str] = None
    time_attr: Optional[str] = None
    time_format: Optional[str] = None  # strptime format if needed
    tags: Optional[List[str]] = None
    enabled: bool = True
    base: Optional[str] = None  # override base for relative URLs

    @staticmethod
    def from_any(x: Any) -> Optional["Source"]:
        if isinstance(x, str):
            return Source(name=urlparse(x).netloc or x, url=x)
        if isinstance(x, dict):
            url = (x.get("url") or "").strip()
            if not url:
                return None
            name = (x.get("name") or urlparse(url).netloc or url).strip()
            return Source(
                name=name,
                url=url,
                type=(x.get("type") or None),
                selector=x.get("selector") or None,
                link_attr=x.get("link_attr") or None,
                title_selector=x.get("title_selector") or None,
                time_selector=x.get("time_selector") or None,
                time_attr=x.get("time_attr") or None,
                time_format=x.get("time_format") or None,
                tags=x.get("tags") or None,
                enabled=bool(x.get("enabled", True)),
                base=x.get("base") or None,
            )
        return None


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def pick_sources(sources_path: Optional[str], config_path: Optional[str]) -> List[Source]:
    found: List[Source] = []

    if sources_path and os.path.exists(sources_path):
        y = load_yaml(sources_path)
        raw = y.get("sources", y)  # either {"sources":[...]} or a plain list
        if isinstance(raw, list):
            for x in raw:
                s = Source.from_any(x)
                if s and s.enabled:
                    found.append(s)

    if config_path and os.path.exists(config_path):
        y = load_yaml(config_path)
        # allow both "sources" or "feeds" in config
        raw = y.get("sources") or y.get("feeds") or []
        if isinstance(raw, list):
            for x in raw:
                s = Source.from_any(x)
                if s and s.enabled:
                    found.append(s)

    # de-dup by (name,url)
    uniq: Dict[Tuple[str, str], Source] = {}
    for s in found:
        uniq[(s.name, s.url)] = s
    return list(uniq.values())


# ---------------------------------- discovery core ---------------------------------

def fetch(url: str) -> Tuple[str, bytes, Dict[str, str]]:
    r = requests.get(url, timeout=REQ_TIMEOUT, headers={"User-Agent": USER_AGENT})
    return r.text, r.content, {k: v for k, v in r.headers.items()}


def discover_from_feed_bytes(content: bytes) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    d = feedparser.parse(content)
    # d.bozo indicates parse trouble but entries may still be usable
    for e in d.entries or []:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or e.get("id") or "").strip()
        published = (
            e.get("published")
            or e.get("updated")
            or e.get("created")
            or ""
        )
        if not link:
            continue
        out.append({
            "title": title,
            "url": link,
            "published_at": parse_date_to_iso(published),
            "summary": (e.get("summary") or e.get("description") or "").strip(),
        })
    return out


def discover_from_html(text: str, base_url: str, s: Source) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    soup = safe_soup(text, prefer_xml=False)

    # Use custom selector if provided
    candidates: Iterable[Any]
    if s.selector:
        candidates = soup.select(s.selector)
    else:
        # try common article patterns first, then all links
        candidates = soup.select("article a[href], .article a[href], a[href]")

    count = 0
    for node in candidates:
        if count >= MAX_HTML_LINKS:
            break
        href = node.get(s.link_attr or "href")
        if not href:
            continue
        url = normalize_url(s.base or base_url, href)
        if not url:
            continue
        title = ""
        if s.title_selector:
            tnode = node.select_one(s.title_selector) if hasattr(node, "select_one") else None
            title = (tnode.get_text(" ", strip=True) if tnode else "").strip()
        if not title:
            title = node.get_text(" ", strip=True)[:300]

        published_iso = ""
        if s.time_selector:
            tnode = soup.select_one(s.time_selector)
            if tnode is not None:
                tval = tnode.get(s.time_attr or "datetime") or tnode.get_text(" ", strip=True)
                if tval:
                    if s.time_format:
                        try:
                            dt = datetime.strptime(tval, s.time_format).replace(tzinfo=timezone.utc)
                            published_iso = dt.isoformat()
                        except Exception:
                            published_iso = parse_date_to_iso(tval)
                    else:
                        published_iso = parse_date_to_iso(tval)

        out.append({
            "title": title,
            "url": url,
            "published_at": published_iso,
            "summary": "",
        })
        count += 1

    return out


def process_source(s: Source, cutoff_utc: datetime) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        text, content, headers = fetch(s.url)
        ctype = headers.get("Content-Type", "")
        auto_feed = looks_like_feed(text, ctype)
        mode = (s.type or "").lower()
        is_feed = (mode == "feed") or (mode == "" and auto_feed)

        if is_feed:
            parsed = discover_from_feed_bytes(content)
            if not parsed:  # feedparser gave nothing; try tolerant XML/HTML
                parsed = discover_from_html(text, s.url, s)  # will handle xml-as-html too
        else:
            parsed = discover_from_html(text, s.url, s)

        # augment with source name and filter by window
        for it in parsed:
            it["source"] = s.name or (urlparse(s.url).netloc or s.url)
            it["tags"] = list(s.tags or [])
            it["published_at"] = it.get("published_at") or ""
            if within_window(it["published_at"], cutoff_utc):
                items.append(it)

    except Exception as e:
        print(f"[discover] skipping '{s.name}' ({s.url}): {e}", file=sys.stderr)

    return items


# -------------------------------------- main ---------------------------------------

def parse_window(win: str) -> timedelta:
    """
    Accepts forms like: 6h, 12h, 1d, 3d, 2w.
    Default: 1d
    """
    if not win:
        return timedelta(days=1)
    m = re.match(r"^\s*(\d+)\s*([hdw])\s*$", win, re.IGNORECASE)
    if not m:
        return timedelta(days=1)
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "h":
        return timedelta(hours=n)
    if unit == "d":
        return timedelta(days=n)
    if unit == "w":
        return timedelta(weeks=n)
    return timedelta(days=1)


def dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    out: List[Dict[str, Any]] = []
    for it in items:
        url = it.get("url") or ""
        if not url:
            continue
        key = normalize_url("", url)
        if key in seen:
            continue
        it["url"] = key
        it["id"] = stable_id(key)
        out.append(it)
        seen[key] = it
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Discover new items for the last window and write state/latest_discovery.json")
    ap.add_argument("--window", default="1d", help="Time window: e.g. 12h, 1d, 3d, 2w (default: 1d)")
    ap.add_argument("--sources", default=None, help="Path to sources YAML (e.g., sources_v2.yaml)")
    ap.add_argument("--config", default=None, help="Path to config YAML (e.g., config_v2.yaml)")
    args = ap.parse_args()

    window_td = parse_window(args.window)
    now = datetime.now(timezone.utc)
    cutoff = now - window_td

    sources = pick_sources(args.sources, args.config)
    if not sources:
        print("[discover] no sources found; writing empty state", file=sys.stderr)

    all_items: List[Dict[str, Any]] = []
    source_names: List[str] = []

    for s in sources:
        if not s.enabled:
            continue
        source_names.append(s.name)
        items = process_source(s, cutoff)
        all_items.extend(items)
        print(f"[discover] {s.name}: +{len(items)} items", file=sys.stderr)

        # be nice to servers
        time.sleep(0.2)

    all_items = dedupe_items(all_items)

    payload: Dict[str, Any] = {
        "generated_at": now.isoformat(),
        "window": args.window,
        "cutoff_utc": cutoff.isoformat(),
        "items": all_items,
        "documents": [],   # kept for downstream compatibility
        "sources": source_names,
    }

    os.makedirs("state", exist_ok=True)
    out_path = os.path.join("state", "latest_discovery.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    print(f"[discover] wrote {out_path} with {len(all_items)} item(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
