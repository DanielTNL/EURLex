#!/usr/bin/env python3
# Minimal, safe "discover" CLI for html_list sources (InvestEU first).
# Prints JSON to stdout and writes state/latest_discovery.json (aggregated).

import argparse, os, re, sys, time, json
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparse
import yaml

UA = "Mozilla/5.0 (compatible; EU-Innovation-Monitor/1.0; +https://example.local)"
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": UA,
    "Accept-Language": "en-GB,en;q=0.8"
})
TIMEOUT = 20

def iso_now():
    return datetime.now(timezone.utc).isoformat()

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def fetch(url):
    r = SESSION.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text, r.url

def absolute(base, href):
    try:
        return urljoin(base, href)
    except Exception:
        return None

def match_patterns(url, includes=None, excludes=None):
    u = url or ""
    if includes and not any(p in u for p in includes):
        return False
    if excludes and any(p in u for p in excludes):
        return False
    return True

def extract_date_from_container(container):
    # 1) <time datetime>
    t = container.select_one("time[datetime]")
    if t and t.has_attr("datetime"):
        return t["datetime"]
    # 2) meta tags in the same container (rare on list pages)
    m = container.select_one("meta[property='article:published_time']")
    if m and m.has_attr("content"):
        return m["content"]
    m2 = container.select_one("meta[name='date']")
    if m2 and m2.has_attr("content"):
        return m2["content"]
    # 3) visible text with a date-like pattern (very conservative)
    txt = container.get_text(" ", strip=True)
    m3 = re.search(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b", txt)
    return m3.group(1) if m3 else None

def parse_date_any(s):
    if not s:
        return None
    try:
        # dayfirst to be safe for EU formats; dtparse handles ISO too
        return dtparse.parse(s, dayfirst=True)
    except Exception:
        return None

def get_article_date(url):
    # Fallback: open the article and look for machine-readable dates
    try:
        html, final_url = fetch(url)
    except Exception:
        return None
    soup = BeautifulSoup(html, "lxml")
    # order of preference
    candidates = []
    for sel in [
        "meta[property='article:published_time']",
        "meta[name='date']",
        "time[datetime]"
    ]:
        el = soup.select_one(sel)
        if el:
            if el.name == "time" and el.has_attr("datetime"):
                candidates.append(el["datetime"])
            elif el.has_attr("content"):
                candidates.append(el["content"])
    # visible fallback (header area)
    if not candidates:
        header = soup.find(["header","main","article"]) or soup
        vis = extract_date_from_container(header)
        if vis:
            candidates.append(vis)
    for c in candidates:
        d = parse_date_any(c)
        if d:
            return d
    return None

def within_window(d, start, end):
    if not d:
        return False
    return (d >= start) and (d < end)

def discover_investeu(source, start_dt, end_dt):
    base_url = source["base_url"]
    includes = source.get("discover", {}).get("include_url_patterns", [])
    excludes = source.get("discover", {}).get("exclude_url_patterns", [])
    list_selectors = source.get("discover", {}).get("list_selectors", [])
    next_selector = source.get("discover", {}).get("pagination", {}).get("next_selector")
    max_pages = int(source.get("discover", {}).get("pagination", {}).get("max_pages", 1))

    found = []
    page_url = base_url
    for _ in range(max_pages):
        try:
            html, final_url = fetch(page_url)
        except Exception as e:
            break
        soup = BeautifulSoup(html, "lxml")
        # Collect anchors
        anchors = []
        if list_selectors:
            for sel in list_selectors:
                anchors.extend(soup.select(sel))
        else:
            anchors = soup.select("a[href]")
        seen_urls = set()
        for a in anchors:
            href = a.get("href")
            url = absolute(final_url, href)
            if not url or url in seen_urls:
                continue
            if not match_patterns(url, includes, excludes):
                continue
            # title hint
            title_hint = a.get_text(" ", strip=True)[:180] or None
            # local date hint near anchor
            date_hint = None
            parent = a.parent if a else None
            if parent:
                date_hint = extract_date_from_container(parent)
            # fallback: none now; we can fetch article if needed
            seen_urls.add(url)
            found.append({"url": url, "title_hint": title_hint, "published_date_hint": date_hint, "doc_type_hint": None})

        # pagination
        if not next_selector:
            break
        nxt = soup.select_one(next_selector)
        if not nxt:
            break
        href = nxt.get("href") or nxt.get("data-href")
        if not href:
            break
        page_url = absolute(final_url, href)
        if not page_url:
            break
        time.sleep(0.3)  # polite

    # refine dates: fetch article page only when needed
    results = []
    for it in found:
        d = parse_date_any(it["published_date_hint"])
        if not d:
            d = get_article_date(it["url"])
        if d and d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if within_window(d, start_dt, end_dt):
            results.append({
                "url": it["url"],
                "title_hint": it["title_hint"],
                "published_date_hint": d.isoformat() if d else None,
                "doc_type_hint": it["doc_type_hint"]
            })
    return results

def main():
    ap = argparse.ArgumentParser(description="Weekly discovery (manual-safe).")
    ap.add_argument("--window", default="7d", help="e.g., 7d")
    ap.add_argument("--sources", default="sources_v2.yaml")
    ap.add_argument("--config", default="config_v2.yaml")
    ap.add_argument("--out", default="state/latest_discovery.json")
    args = ap.parse_args()

    # compute window
    m = re.match(r"^(\d+)d$", args.window.strip())
    days = int(m.group(1)) if m else 7
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    # load sources
    src_cfg = load_yaml(args.sources)
    sources = src_cfg.get("sources", [])

    all_payloads = []
    total = 0
    for s in sources:
        if s.get("type") != "html_list":
            continue
        sid = s.get("source_id")
        items = discover_investeu(s, start_dt, end_dt)
        total += len(items)
        all_payloads.append({
            "schema": "discovery.v1",
            "source_id": sid,
            "discovered_at": iso_now(),
            "base_url": s.get("base_url"),
            "items": items
        })

    # aggregate output
    out_payload = {
        "schema": "discovery.aggregate.v1",
        "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat(), "timezone": "Europe/Amsterdam"},
        "total_items": total,
        "sources": all_payloads
    }

    # print to stdout
    try:
        import orjson as oj
        sys.stdout.write(oj.dumps(out_payload).decode("utf-8"))
    except Exception:
        sys.stdout.write(json.dumps(out_payload, ensure_ascii=False))

    # also persist to state/
    os.makedirs("state", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, ensure_ascii=False)

if __name__ == "__main__":
    main()
