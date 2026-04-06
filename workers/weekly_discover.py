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
CUSTOM_FEEDS_PATH = "state/custom_feeds.json"
SOURCE_OVERRIDES_PATH = "state/source_overrides.json"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LEGACY_SOURCES_PATH = os.path.join(ROOT, "scripts", "sources.yaml")


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


def split_selector_attr(selector: str) -> Tuple[str, Optional[str]]:
    if "::attr(" in selector and selector.endswith(")"):
        head, _, tail = selector.partition("::attr(")
        return head.strip(), tail[:-1].strip()
    return selector.strip(), None


def extract_selector_value(node: Any, selectors: Iterable[str]) -> str:
    for raw in selectors:
        selector, attr = split_selector_attr(raw)
        if not selector:
            continue
        try:
            target = node.select_one(selector) if hasattr(node, "select_one") else None
        except Exception:
            target = None
        if target is None:
            continue
        if attr:
            value = (target.get(attr) or "").strip()
        else:
            value = target.get_text(" ", strip=True)
        if value:
            return value
    return ""


def matches_url_patterns(url: str, include_patterns: Iterable[str] | None, exclude_patterns: Iterable[str] | None) -> bool:
    lowered = (url or "").lower()
    if not lowered:
        return False
    if include_patterns:
        includes = [item.lower() for item in include_patterns if item]
        if includes and not any(item in lowered for item in includes):
            return False
    if exclude_patterns:
        excludes = [item.lower() for item in exclude_patterns if item]
        if any(item in lowered for item in excludes):
            return False
    return True


def stable_id(u: str) -> str:
    return hashlib.sha1(u.encode("utf-8", "ignore")).hexdigest()


def source_registry_id(source_id: str, url: str) -> str:
    return stable_id(f"{(source_id or '').strip()}|{(url or '').strip()}")


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
    source_id: str
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
    list_selectors: Optional[List[str]] = None
    date_selectors: Optional[List[str]] = None
    include_url_patterns: Optional[List[str]] = None
    exclude_url_patterns: Optional[List[str]] = None
    next_selector: Optional[str] = None
    max_pages: int = 1

    @staticmethod
    def from_any(x: Any) -> Optional["Source"]:
        if isinstance(x, str):
            name = urlparse(x).netloc or x
            return Source(source_id=name, name=name, url=x)
        if isinstance(x, dict):
            discover = x.get("discover") or {}
            parsing = x.get("parsing") or {}
            url = (x.get("url") or x.get("base_url") or "").strip()
            if not url:
                return None
            source_id = str(x.get("source_id") or x.get("id") or x.get("name") or urlparse(url).netloc or url).strip()
            name = (x.get("name") or x.get("source_id") or urlparse(url).netloc or url).strip()
            raw_type = (x.get("type") or "").strip().lower()
            mapped_type = "feed" if raw_type in {"feed", "rss", "atom"} else ("html" if raw_type else None)
            return Source(
                source_id=source_id,
                name=name,
                url=url,
                type=mapped_type,
                selector=x.get("selector") or None,
                link_attr=x.get("link_attr") or None,
                title_selector=(
                    x.get("title_selector")
                    or (parsing.get("title_selectors") or [None])[0]
                    or None
                ),
                time_selector=x.get("time_selector") or None,
                time_attr=x.get("time_attr") or None,
                time_format=x.get("time_format") or None,
                tags=x.get("tags") or None,
                enabled=bool(x.get("enabled", True)),
                base=x.get("base") or None,
                list_selectors=discover.get("list_selectors") or None,
                date_selectors=discover.get("date_selectors") or None,
                include_url_patterns=discover.get("include_url_patterns") or None,
                exclude_url_patterns=discover.get("exclude_url_patterns") or None,
                next_selector=(discover.get("pagination") or {}).get("next_selector"),
                max_pages=int((discover.get("pagination") or {}).get("max_pages") or 1),
            )
        return None


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_custom_feeds(path: str = CUSTOM_FEEDS_PATH) -> List[Source]:
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
    except Exception:
        return []

    raw = payload.get("feeds") if isinstance(payload, dict) else payload
    found: List[Source] = []

    if isinstance(raw, list):
        for item in raw:
            s = Source.from_any(item)
            if s and s.enabled:
                found.append(s)

    return found


def load_legacy_feed_sources(path: str = LEGACY_SOURCES_PATH) -> List[Source]:
    if not os.path.exists(path):
        return []

    try:
        payload = load_yaml(path)
    except Exception:
        return []

    domains = payload.get("domains", {}) if isinstance(payload, dict) else {}
    raw_feeds = payload.get("feeds", []) if isinstance(payload, dict) else []
    found: List[Source] = []

    if isinstance(raw_feeds, list):
        for item in raw_feeds:
            if isinstance(item, str):
                url = item.strip()
                if not url:
                    continue
                host = urlparse(url).netloc.lower().lstrip("www.") or url
                meta = domains.get(host, {}) if isinstance(domains, dict) else {}
                found.append(
                    Source(
                        source_id=host,
                        name=str(meta.get("source") or host).strip(),
                        url=url,
                        type="feed",
                        tags=list(meta.get("tags") or []),
                        enabled=True,
                    )
                )
            else:
                source = Source.from_any(item)
                if source and source.enabled:
                    found.append(source)

    return found


def load_source_overrides(path: str = SOURCE_OVERRIDES_PATH) -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
    except Exception:
        return {}

    entries = payload.get("entries") if isinstance(payload, dict) else []
    overrides: Dict[str, Dict[str, Any]] = {}
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or item.get("name") or item.get("url") or "").strip()
            url = str(item.get("url") or "").strip()
            item_id = str(item.get("id") or source_registry_id(source_id, url)).strip()
            if item_id:
                overrides[item_id] = item
    return overrides


def apply_source_overrides(found: List[Source]) -> List[Source]:
    overrides = load_source_overrides()
    if not overrides:
        return found

    adjusted: List[Source] = []
    for source in found:
        item_id = source_registry_id(source.source_id, source.url)
        override = overrides.get(item_id)
        if override and override.get("enabled") is False:
            continue
        if override:
            source = Source(
                source_id=str(override.get("source_id") or source.source_id).strip(),
                name=str(override.get("name") or source.name).strip(),
                url=str(override.get("url") or source.url).strip(),
                type=str(override.get("kind") or override.get("type") or source.type or "").strip() or source.type,
                selector=source.selector,
                link_attr=source.link_attr,
                title_selector=source.title_selector,
                time_selector=source.time_selector,
                time_attr=source.time_attr,
                time_format=source.time_format,
                tags=override.get("tags") or source.tags,
                enabled=bool(override.get("enabled", source.enabled)),
                base=source.base,
                list_selectors=source.list_selectors,
                date_selectors=source.date_selectors,
                include_url_patterns=source.include_url_patterns,
                exclude_url_patterns=source.exclude_url_patterns,
                next_selector=source.next_selector,
                max_pages=source.max_pages,
            )
        if source.enabled:
            adjusted.append(source)
    return adjusted


def pick_sources(sources_path: Optional[str], config_path: Optional[str]) -> List[Source]:
    found: List[Source] = []

    # Always include the canonical RSS/Atom registry from scripts/sources.yaml so
    # discovery stays aligned with the published source catalog surfaced in the app.
    found.extend(load_legacy_feed_sources())

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

    found.extend(load_custom_feeds())
    found = apply_source_overrides(found)

    # de-dup by stable registry identity so the app-facing source registry and the
    # discovery pipeline treat edited/overridden sources as the same entry.
    uniq: Dict[Tuple[str, str], Source] = {}
    for s in found:
        uniq[(s.source_id, s.url)] = s
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
    selectors = list(s.list_selectors or [])
    if s.selector:
        selectors.insert(0, s.selector)

    if selectors:
        selected: List[Any] = []
        for selector in selectors:
            try:
                selected.extend(soup.select(selector))
            except Exception:
                continue
        candidates = selected
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
        if not matches_url_patterns(url, s.include_url_patterns, s.exclude_url_patterns):
            continue
        title = ""
        if s.title_selector:
            tnode = node.select_one(s.title_selector) if hasattr(node, "select_one") else None
            title = (tnode.get_text(" ", strip=True) if tnode else "").strip()
        if not title:
            title = node.get_text(" ", strip=True)[:300]

        published_iso = ""
        raw_dates: List[str] = []
        if s.time_selector:
            raw_dates.append(s.time_selector)
        raw_dates.extend(s.date_selectors or [])
        if raw_dates:
            tval = extract_selector_value(node, raw_dates) or extract_selector_value(soup, raw_dates)
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
        current_url = s.url
        seen_pages = set()

        for _ in range(max(1, s.max_pages)):
            if current_url in seen_pages:
                break
            seen_pages.add(current_url)

            text, content, headers = fetch(current_url)
            ctype = headers.get("Content-Type", "")
            auto_feed = looks_like_feed(text, ctype)
            mode = (s.type or "").lower()
            is_feed = (mode == "feed") or (mode == "" and auto_feed)

            if is_feed:
                parsed = discover_from_feed_bytes(content)
                if not parsed:  # feedparser gave nothing; try tolerant XML/HTML
                    parsed = discover_from_html(text, current_url, s)
            else:
                parsed = discover_from_html(text, current_url, s)

            for it in parsed:
                it["source"] = s.name or (urlparse(s.url).netloc or s.url)
                it["source_id"] = s.source_id or s.name
                it["tags"] = list(s.tags or [])
                it["published_at"] = it.get("published_at") or ""
                if within_window(it["published_at"], cutoff_utc):
                    items.append(it)

            if is_feed or not s.next_selector:
                break

            soup = safe_soup(text, prefer_xml=False)
            next_href = extract_selector_value(soup, [s.next_selector])
            next_url = normalize_url(current_url, next_href) if next_href else ""
            if not next_url or next_url == current_url:
                break
            current_url = next_url

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
