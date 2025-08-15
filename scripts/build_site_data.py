#!/usr/bin/env python3
"""
Builds docs/data/posts.json and docs/data/reports.json from:
 - Your RSS feeds in scripts/sources.yaml
 - Your Daily/Weekly files under reports/** (md/txt/html)

Scoring = keyword hits + recent boost.
Caps/max_age are honored.
Source labels & base tags come from `domains:` in sources.yaml.
"""

import os, re, json, hashlib, datetime as dt, pathlib, html, math
from urllib.parse import urlparse
import asyncio
import httpx, frontmatter, yaml, feedparser
from dateutil import parser as dateparse, tz
from bs4 import BeautifulSoup
from trafilatura import fetch_url, extract as trafi_extract

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
DOCS_DATA.mkdir(parents=True, exist_ok=True)
POSTS_JSON = DOCS_DATA / "posts.json"
REPORTS_JSON = DOCS_DATA / "reports.json"

CONFIG = ROOT / "scripts" / "sources.yaml"

REPORTS_DIRS = [ROOT / "reports", ROOT / "reports" / "weekly", ROOT / "reports" / "daily"]
URL_RE = re.compile(r'https?://[^\s\]\)\}\>\"\'`]+', re.IGNORECASE)

SUMMARY_CHARS = 1000
MAX_LINKS_PER_REPORT = 300  # safety

def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def load_cfg():
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg = cfg or {}
    domains = cfg.get("domains", {})
    defaults = cfg.get("defaults", {"source":"External","tags":["external"]})
    feeds = list(cfg.get("feeds", []) or [])
    keywords = [str(k).lower() for k in (cfg.get("keywords", []) or [])]
    taxonomy = cfg.get("taxonomy", {}).get("categories", [])
    caps = cfg.get("caps", {"max_total":50, "max_per_category":20, "min_per_category":5})
    ranking = cfg.get("ranking", {"max_age_days":14, "min_score":1, "prefer_recent":True})
    dedupe = cfg.get("dedupe", {"enabled":True, "path":"state/seen.json"})
    tzname = (cfg.get("timezone") or "Europe/Amsterdam")
    return domains, defaults, feeds, keywords, taxonomy, caps, ranking, dedupe, tzname

DOMAINS, DEFAULTS, FEEDS, KEYWORDS, TAXONOMY, CAPS, RANKING, DEDUPE, TZN = load_cfg()

def label_for_url(u: str):
    host = urlparse(u).netloc.lower().lstrip("www.")
    meta = DOMAINS.get(host)
    if meta:
        return meta.get("source", host), list(meta.get("tags", []))
    return DEFAULTS.get("source","External"), list(DEFAULTS.get("tags", ["external"]))

def score_text(qtokens, text):
    text = (text or "").lower()
    score = 0
    for t in qtokens:
        if re.search(rf"\b{re.escape(t)}\b", text):
            score += 1
    return score

def categories_for(text):
    text = (text or "").lower()
    cats = []
    for cat in (TAXONOMY or []):
        name = cat.get("name","Other")
        inc = [str(i).lower() for i in cat.get("include", [])]
        if any(re.search(rf"\b{re.escape(w)}\b", text) for w in inc):
            cats.append(name)
    if not cats:
        cats.append("Other")
    return cats

def clamp_posts_by_caps(items):
    buckets = {}
    for it in items:
        key = (it.get("categories") or ["Other"])[0]
        buckets.setdefault(key, []).append(it)

    for k in buckets:
        buckets[k].sort(key=lambda x: (x.get("score",0), x.get("ts",0)), reverse=True)
        buckets[k] = buckets[k][:CAPS.get("max_per_category",20)]

    min_per = CAPS.get("min_per_category", 5)
    selected = []
    for k, arr in buckets.items():
        selected.extend(arr[:min_per])

    max_total = CAPS.get("max_total", 50)
    if len(selected) < max_total:
        leftovers = []
        for k, arr in buckets.items():
            leftovers.extend(arr[min_per:])
        leftovers.sort(key=lambda x: (x.get("score",0), x.get("ts",0)), reverse=True)
        need = max_total - len(selected)
        selected.extend(leftovers[:need])

    seen = set()
    uniq = []
    for it in selected:
        if it["id"] not in seen:
            uniq.append(it)
            seen.add(it["id"])
        if len(uniq) >= max_total: break
    return uniq

def parse_date(d):
    if not d:
        return None
    try:
        return dateparse.parse(d)
    except Exception:
        return None

async def fetch_title_and_summary(client: httpx.AsyncClient, url: str):
    # Try trafilatura first
    try:
        downloaded = fetch_url(url)
        if downloaded:
            extracted = trafi_extract(downloaded, include_comments=False, include_links=False)
            if extracted:
                title = ""
                try:
                    r = await client.get(url, timeout=20)
                    if r.status_code == 200:
                        soup = BeautifulSoup(r.text, "html.parser")
                        if soup.title and soup.title.text.strip():
                            title = soup.title.text.strip()
                except Exception:
                    pass
                if not title:
                    first_line = extracted.strip().splitlines()[0][:140]
                    title = first_line if len(first_line) > 10 else url
                summary = re.sub(r"\s+", " ", extracted.strip())
                if len(summary) > SUMMARY_CHARS:
                    summary = summary[:SUMMARY_CHARS] + "…"
                return title, summary
    except Exception:
        pass

    # Fallback
    try:
        r = await client.get(url, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.text.strip() if soup.title else url
            text = soup.get_text(" ").strip()
            text = re.sub(r"\s+", " ", text)
            summary = (text[:SUMMARY_CHARS] + "…") if len(text) > SUMMARY_CHARS else text
            return title or url, summary
    except Exception:
        pass

    return url, ""

def norm_report_date(path: pathlib.Path):
    m = re.search(r'(\d{4})[-_/](\d{2})[-_/](\d{2})', str(path))
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}"
    ts = dt.datetime.utcfromtimestamp(path.stat().st_mtime)
    return ts.strftime("%Y-%m-%d")

def extract_urls_from_html(html_text: str):
    soup = BeautifulSoup(html_text, "html.parser")
    hrefs = []
    for a in soup.find_all("a", href=True):
        u = a["href"].strip()
        if u.startswith("http"):
            hrefs.append(u)
    return list(dict.fromkeys(hrefs))

def read_report_text_and_urls(path: pathlib.Path):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    ext = path.suffix.lower()
    if ext in (".html",".htm"):
        urls = extract_urls_from_html(raw)
        text = BeautifulSoup(raw, "html.parser").get_text("\n")
    elif ext in (".md",".markdown"):
        fm = frontmatter.loads(raw)
        text = fm.content if fm.content else raw
        urls = list(dict.fromkeys(URL_RE.findall(raw)))
    else:
        text = raw
        urls = list(dict.fromkeys(URL_RE.findall(raw)))
    return raw, text, urls

def guess_title_abstract_keyitems(text: str):
    lines = [l.strip() for l in text.splitlines()]
    title = next((l for l in lines if l), "Untitled report")
    after = "\n".join(lines[1:]).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", after) if p.strip()]
    abstract = paras[0][:300] if paras else ""
    key_items = []
    capture = False
    for l in lines:
        if re.search(r'key\s*items?|highlights', l, re.I):
            capture = True; continue
        if capture and (l.startswith("- ") or l.startswith("* ")):
            key_items.append(l[2:].strip())
        elif capture and l and not (l.startswith("- ") or l.startswith("* ")):
            break
    if not key_items:
        for l in lines:
            if l.startswith(("- ","* ")):
                key_items.append(l[2:].strip())
            if len(key_items) >= 3: break
    return title, abstract, key_items

def make_report_entry(path: pathlib.Path, title: str, abstract: str, key_items: list[str], repo: str):
    date = norm_report_date(path)
    rid = f"rep-{date}-{sha16(str(path))}"
    file_rel = path.relative_to(ROOT).as_posix()
    url_html = f"https://github.com/{repo}/blob/main/{file_rel}"
    tags = []
    lr = file_rel.lower()
    if "weekly" in lr: tags.append("weekly")
    if "daily" in lr: tags.append("daily")
    if not tags: tags.append("report")
    return {
        "id": rid,
        "date": date,
        "title": title.strip() or "Untitled",
        "url_html": url_html,
        "url_drive": "",
        "tags": tags,
        "key_items": key_items[:10],
        "abstract": abstract.strip(),
        "sections": []
    }

def load_seen():
    try:
        p = ROOT / (DEDUPE.get("path") or "state/seen.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            return {x["id"]:x for x in json.loads(p.read_text(encoding="utf-8"))}
    except Exception:
        pass
    return {}

def save_seen(seen):
    try:
        p = ROOT / (DEDUPE.get("path") or "state/seen.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(list(seen.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

async def build():
    repo = os.getenv("GITHUB_REPOSITORY", "DanielTNL/EURLex")
    now = dt.datetime.now(tz.UTC)
    max_age_days = RANKING.get("max_age_days", 14)
    min_score = RANKING.get("min_score", 1)

    old_posts = []
    if POSTS_JSON.exists():
        try:
            old_posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
        except Exception:
            old_posts = []

    seen = load_seen()

    # 1) FEEDS
    feed_items = []
    for url in FEEDS:
        try:
            fp = feedparser.parse(url)
            for e in fp.entries:
                link = e.get("link") or e.get("id")
                if not link or not link.startswith("http"): continue
                title = e.get("title","").strip() or link
                summary = BeautifulSoup((e.get("summary") or e.get("description") or ""), "html.parser").get_text(" ").strip()
                d = None
                for key in ("published", "updated", "created"):
                    if e.get(key):
                        d = parse_date(e.get(key))
                        if d: break
                if not d and e.get("published_parsed"):
                    try:
                        d = dt.datetime(*e.published_parsed[:6], tzinfo=tz.UTC)
                    except Exception:
                        pass
                if not d:
                    d = now
                age_days = (now - (d if d.tzinfo else d.replace(tzinfo=tz.UTC))).days
                if age_days > max_age_days:
                    continue
                text_for_score = f"{title} {summary}"
                s = score_text(KEYWORDS, text_for_score)
                if s < min_score:
                    continue
                cats = categories_for(text_for_score)
                src_name, base_tags = label_for_url(link)
                pid = sha16(link)
                ts = int((d if d.tzinfo else d.replace(tzinfo=tz.UTC)).timestamp())
                feed_items.append({
                    "id": pid,
                    "source": src_name,
                    "url": link,
                    "title": title,
                    "tags": list(set(base_tags + cats)),
                    "added": now.isoformat(),
                    "summary": summary[:SUMMARY_CHARS] + ("…" if len(summary) > SUMMARY_CHARS else ""),
                    "score": s,
                    "ts": ts,
                    "categories": cats
                })
        except Exception as ex:
            print(f"[WARN] feed error {url}: {ex}")

    # 2) REPORTS + links inside them
    reports = []
    report_links = []
    for d in REPORTS_DIRS:
        if not d.exists(): continue
        for f in sorted(d.rglob("*")):
            if f.suffix.lower() not in (".md",".markdown",".txt",".html",".htm"): continue
            try:
                raw, text, urls = read_report_text_and_urls(f)
                title, abstract, key_items = guess_title_abstract_keyitems(text)
                reports.append(make_report_entry(f, title, abstract, key_items, repo))
                report_links.extend(urls[:MAX_LINKS_PER_REPORT])
            except Exception as ex:
                print(f"[WARN] report parse {f}: {ex}")

    # 3) Fetch titles/summaries for report links
    report_items = []
    async with httpx.AsyncClient(headers={"User-Agent":"eurlex-site-builder/1.0"}) as client:
        tasks = [fetch_title_and_summary(client, u) for u in report_links]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    now_iso = dt.datetime.utcnow().isoformat()+"Z"
    for u, res in zip(report_links, results):
        if isinstance(res, Exception):
            title, summary = u, ""
        else:
            title, summary = res
        src_name, base_tags = label_for_url(u)
        cats = categories_for(f"{title} {summary}")
        pid = sha16(u)
        report_items.append({
            "id": pid,
            "source": src_name,
            "url": u,
            "title": title,
            "tags": list(set(base_tags + cats)),
            "added": now_iso,
            "summary": summary,
            "score": score_text(KEYWORDS, f"{title} {summary}"),
            "ts": int(dt.datetime.now(tz.UTC).timestamp()),
            "categories": cats
        })

    # 4) Merge + rank + cap
    merged = []
    seenids = set()
    for arr in (old_posts, feed_items, report_items):
        for p in arr:
            if p["id"] in seenids: continue
            merged.append(p)
            seenids.add(p["id"])
    merged.sort(key=lambda x: (x.get("score",0), x.get("ts",0)), reverse=True)
    final_posts = clamp_posts_by_caps(merged)

    reports.sort(key=lambda r: r["date"], reverse=True)

    POSTS_JSON.write_text(json.dumps(final_posts, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORTS_JSON.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    for p in final_posts:
        seen[p["id"]] = {"id": p["id"], "url": p["url"], "ts": p.get("ts")}
    # save_seen(seen)  # optional

if __name__ == "__main__":
    asyncio.run(build())
    print("Wrote:", POSTS_JSON, REPORTS_JSON)

# add near the other paths
AUDIO_JSON = DOCS_DATA / "audio.json"

# after load_cfg():
def load_cfg():
    ...
    links = (cfg.get("links") or {})
    return domains, defaults, feeds, keywords, taxonomy, caps, ranking, dedupe, tzname, links

DOMAINS, DEFAULTS, FEEDS, KEYWORDS, TAXONOMY, CAPS, RANKING, DEDUPE, TZN, LINKS = load_cfg()

# helper
def file_raw_url(repo, relpath):
    return f"https://raw.githubusercontent.com/{repo}/main/{relpath}"

# new: scan for mp3s
def scan_audio(repo:str):
    items=[]
    for f in ROOT.rglob("*.mp3"):
        # skip venv/node_modules etc.
        if any(seg in f.parts for seg in (".git","node_modules",".venv")): continue
        rel = f.relative_to(ROOT).as_posix()
        title = f.stem.replace("_"," ").replace("-"," ").strip()
        date = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', rel)
        when = f"{date.group(1)}-{date.group(2)}-{date.group(3)}" if date else ""
        items.append({
            "title": title, "path": rel, "raw_url": file_raw_url(repo, rel), "date": when
        })
    # newest first
    items.sort(key=lambda x: x.get("date",""), reverse=True)
    payload = {"google_drive": LINKS.get("google_drive",""), "items": items[:50]}
    AUDIO_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write audio/links
    scan_audio(repo)
