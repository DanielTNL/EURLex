#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Builds docs/data/posts.json, docs/data/reports.json and docs/data/audio.json from:
 - RSS feeds in scripts/sources.yaml
 - report files under reports/** (md/txt/html)
 - *.mp3 files anywhere in the repo (for Weekly Digest audio)

Also labels sources by domain, tags by taxonomy keywords, and ranks items.
"""

import os, re, json, hashlib, datetime as dt, pathlib, html
from urllib.parse import urlparse
import asyncio
import httpx, frontmatter, yaml, feedparser
from dateutil import parser as dateparse, tz
from bs4 import BeautifulSoup
from trafilatura import fetch_url, extract as trafi_extract

# --- Paths ---
ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"
DOCS_DATA.mkdir(parents=True, exist_ok=True)

POSTS_JSON   = DOCS_DATA / "posts.json"
REPORTS_JSON = DOCS_DATA / "reports.json"
AUDIO_JSON   = DOCS_DATA / "audio.json"
CUSTOM_FEEDS_JSON = ROOT / "state" / "custom_feeds.json"

CONFIG = ROOT / "scripts" / "sources.yaml"
if not CONFIG.exists():
    # fallback in case the folder is capitalized
    CONFIG = ROOT / "Scripts" / "sources.yaml"

REPORTS_DIRS = [ROOT / "reports"]
URL_RE = re.compile(r'https?://[^\s\]\)\}\>\"\'`]+', re.IGNORECASE)

SUMMARY_CHARS = 1000
MAX_LINKS_PER_REPORT = 80
MAX_REPORT_FILES_FOR_LINK_EXTRACTION = 20

def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def squash_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()

def collapse_repeated_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    seen = set()
    cleaned = []
    for sentence in sentences:
        candidate = sentence.strip()
        if not candidate:
            continue
        fingerprint = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        if len(fingerprint) > 24 and fingerprint in seen:
            continue
        cleaned.append(candidate)
        if len(fingerprint) > 24:
            seen.add(fingerprint)
    return " ".join(cleaned)

def trim_after_repeated_lead(text: str, min_len: int = 80) -> str:
    compact = squash_text(text)
    if len(compact) < min_len * 2:
        return compact

    for size in range(min(180, len(compact) // 2), min_len - 1, -10):
        lead = compact[:size].strip(" ,;:-")
        if len(lead) < min_len:
            continue
        second = compact.find(lead, size)
        if second > 0:
            return compact[:second].strip(" ,;:-")
    return compact

def trim_after_repeated_reference(text: str) -> str:
    compact = squash_text(text)
    match = re.match(r"^((?:Case\s+[A-Z]-\d+/\d+|P\d+_TA\(\d{4}\)\d+|CELEX:[A-Z0-9()./_-]+|OJ:[A-Z]_[A-Z0-9]+))", compact, flags=re.I)
    if not match:
        return compact
    token = match.group(1).strip()
    second = compact.find(token, len(token))
    if second > 0:
        return compact[:second].strip(" ,;:-")
    return compact

def extract_reader_reference(title: str) -> str:
    title = squash_text(title)
    patterns = [
        r"(CELEX:[A-Z0-9()./_-]+)",
        r"\b(Case\s+[A-Z]-\d+/\d+)\b",
        r"\b(CON/\d{4}/\d+)\b",
        r"\b(P\d+_TA\(\d{4}\)\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.I)
        if match:
            return match.group(1).strip()
    return ""

def derive_title_from_summary(summary: str) -> str:
    cleaned = squash_text(summary)
    if not cleaned:
        return ""
    cleaned = re.sub(r"^This document is an excerpt from the EUR-Lex website\b[:\s-]*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^Document\s+[A-Z0-9:/()._-]+\s*", "", cleaned)
    cleaned = collapse_repeated_sentences(cleaned)
    cleaned = trim_after_repeated_lead(cleaned)
    cleaned = trim_after_repeated_reference(cleaned)
    cleaned = re.split(r"\b(?:ELI:|Official Journal|Language of the case:|OJ\s+[A-Z],)\b", cleaned)[0].strip()
    if not cleaned:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", cleaned)[0].strip()
    candidate = first_sentence or cleaned
    return candidate[:220].strip(" ,;:-")

def clean_reader_title(title: str, summary: str = "") -> str:
    original = squash_text(title)
    if not original:
        return "Untitled"

    cleaned = original
    cleaned = re.sub(r"^This document is an excerpt from the EUR-Lex website\b[:\s-]*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^Document\s+[A-Z0-9:/()._-]+\s*", "", cleaned)

    celex_match = re.match(r"^(CELEX:[^:]+):\s*(.+)$", cleaned, flags=re.I)
    if celex_match:
        cleaned = celex_match.group(2).strip()

    if not cleaned or cleaned.lower().startswith("this document is an excerpt from the eur-lex website"):
        cleaned = derive_title_from_summary(summary) or original

    cleaned = cleaned.replace(".#", ": ")
    cleaned = re.sub(r"\s*#\s*", " ", cleaned)
    cleaned = re.split(r"\b(?:ELI:|Official Journal|Language of the case:)\b", cleaned)[0].strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;:-")
    return cleaned or original or "Untitled"

def clean_reader_summary(summary: str, title: str = "") -> str:
    cleaned = squash_text(summary)
    if not cleaned:
        return ""

    cleaned = re.sub(r"^This document is an excerpt from the EUR-Lex website\b[:\s-]*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^Document\s+[A-Z0-9:/()._-]+\s*", "", cleaned)
    cleaned = collapse_repeated_sentences(cleaned)
    cleaned = trim_after_repeated_lead(cleaned)
    cleaned = trim_after_repeated_reference(cleaned)
    cleaned = re.split(r"\b(?:ELI:|Official Journal|Language of the case:|OJ\s+[A-Z],)\b", cleaned)[0].strip()

    cleaned_title = clean_reader_title(title)
    if cleaned_title and cleaned.lower().startswith(cleaned_title.lower() + " "):
        cleaned = cleaned[len(cleaned_title):].strip(" .:-")

    return re.sub(r"\s+", " ", cleaned).strip()

def enrich_post_entry(item: dict) -> dict:
    enriched = dict(item)
    original_title = squash_text(enriched.get("original_title") or enriched.get("title") or "")
    raw_summary = squash_text(enriched.get("summary") or "")
    display_title = squash_text(clean_reader_title(original_title, raw_summary))
    display_summary = squash_text(clean_reader_summary(raw_summary, original_title))
    reference = squash_text(extract_reader_reference(original_title))

    enriched["title"] = original_title or enriched.get("title") or "Untitled"
    enriched["original_title"] = original_title or enriched["title"]
    enriched["summary"] = raw_summary
    enriched["display_title"] = display_title or enriched["original_title"]

    if display_summary:
        enriched["display_summary"] = display_summary
    else:
        enriched.pop("display_summary", None)

    if reference:
        enriched["reference"] = reference
    else:
        enriched.pop("reference", None)

    return enriched

# --- Config loader (fixed) ---
def load_cfg():
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg = cfg or {}

    domains  = cfg.get("domains", {}) or {}
    defaults = cfg.get("defaults", {"source":"External","tags":["external"]})
    feeds    = list(cfg.get("feeds", []) or [])
    keywords = [str(k).lower() for k in (cfg.get("keywords", []) or [])]
    taxonomy = (cfg.get("taxonomy") or {}).get("categories", []) or []
    caps     = cfg.get("caps", {"max_total":50, "max_per_category":20, "min_per_category":5})
    ranking  = cfg.get("ranking", {"max_age_days":14, "min_score":1, "prefer_recent":True})
    dedupe   = cfg.get("dedupe", {"enabled":True, "path":"state/seen.json"})
    tzname   = cfg.get("timezone") or "Europe/Amsterdam"
    links    = cfg.get("links", {}) or {}             # <--- NEW, fixed (cfg defined above)
    return domains, defaults, feeds, keywords, taxonomy, caps, ranking, dedupe, tzname, links

def load_custom_feeds():
    if not CUSTOM_FEEDS_JSON.exists():
        return []

    try:
        payload = json.loads(CUSTOM_FEEDS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []

    feeds = payload.get("feeds", []) if isinstance(payload, dict) else payload
    cleaned = []
    for item in feeds or []:
        if isinstance(item, str):
            url = item.strip()
        elif isinstance(item, dict):
            url = str(item.get("url") or "").strip()
        else:
            url = ""

        if url.startswith("http"):
            cleaned.append(url)

    return list(dict.fromkeys(cleaned))

DOMAINS, DEFAULTS, FEEDS, KEYWORDS, TAXONOMY, CAPS, RANKING, DEDUPE, TZN, LINKS = load_cfg()
FEEDS = list(dict.fromkeys(FEEDS + load_custom_feeds()))

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

    # Fallback: basic fetch + text extraction
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


def infer_report_tags(path: pathlib.Path, title: str) -> list[str]:
    lowered_path = path.as_posix().lower()
    lowered_title = squash_text(title).lower()
    tags: list[str] = []

    if "/reports/weekly/" in lowered_path or "weekly" in lowered_title or "sunday edition" in lowered_title:
        tags.append("weekly")
    if "/reports/daily/" in lowered_path or "daily digest" in lowered_title or "daily brief" in lowered_title:
        tags.append("daily")

    if not tags:
        tags.append("report")

    return tags

def make_report_entry(path: pathlib.Path, title: str, abstract: str, key_items: list[str], repo: str):
    date = norm_report_date(path)
    rid = f"rep-{date}-{sha16(str(path))}"
    file_rel = path.relative_to(ROOT).as_posix()
    url_html = f"https://github.com/{repo}/blob/main/{file_rel}"
    tags = infer_report_tags(path, title)
    display_title = re.sub(r"^#+\s*", "", squash_text(title))
    return {
        "id": rid,
        "date": date,
        "title": title.strip() or "Untitled",
        "original_title": title.strip() or "Untitled",
        "display_title": display_title or "Untitled",
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

# --- Audio / Google Drive helpers ---
def file_raw_url(repo: str, relpath: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/main/{relpath}"

def audio_metadata_for(rel: str):
    lower = rel.lower()
    if "reports/audio/monthly/" in lower:
        return {
            "kind": "monthly_roundtable",
            "series": "Monthly roundtable",
            "requested": False,
        }
    if "reports/audio/requests/" in lower:
        return {
            "kind": "requested_weekly_brief",
            "series": "Requested weekly brief",
            "requested": True,
        }
    if "reports/weekly/" in lower:
        return {
            "kind": "legacy_weekly_brief",
            "series": "Legacy weekly brief",
            "requested": False,
        }
    return {
        "kind": "audio_brief",
        "series": "Audio brief",
        "requested": False,
    }

def read_audio_summary(path: pathlib.Path) -> str:
    companion_paths = [
        path.with_suffix(".txt"),
        path.with_suffix(".md"),
    ]
    for companion in companion_paths:
        if not companion.exists():
            continue
        text = companion.read_text(encoding="utf-8", errors="ignore")
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for paragraph in paragraphs[1:] if len(paragraphs) > 1 else paragraphs:
            cleaned = re.sub(r"\s+", " ", paragraph).strip()
            if cleaned:
                return cleaned[:280] + ("…" if len(cleaned) > 280 else "")
    return ""

def scan_audio(repo: str):
    items = []
    for f in ROOT.rglob("*.mp3"):
        # skip irrelevant folders
        if any(seg in f.parts for seg in (".git","node_modules",".venv","venv","dist","build")):
            continue
        rel = f.relative_to(ROOT).as_posix()
        title = f.stem.replace("_"," ").replace("-"," ").strip()
        m = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', rel)
        when = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        meta = audio_metadata_for(rel)
        items.append({
            "title": title,
            "path": rel,
            "raw_url": file_raw_url(repo, rel),
            "date": when,
            "kind": meta["kind"],
            "series": meta["series"],
            "requested": meta["requested"],
            "summary": read_audio_summary(f),
        })
    items.sort(key=lambda x: (x.get("date",""), x.get("kind","")), reverse=True)

    monthly = [item for item in items if item.get("kind") == "monthly_roundtable"]
    requests = [item for item in items if item.get("kind") == "requested_weekly_brief"]

    payload = {
        "google_drive": LINKS.get("google_drive",""),
        "monthly": monthly[:12],
        "requests": requests[:24],
        "items": items[:50],
    }
    AUDIO_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

async def build():
    repo = os.getenv("GITHUB_REPOSITORY", "DanielTNL/EURLex")
    now = dt.datetime.now(tz.UTC)
    max_age_days = RANKING.get("max_age_days", 14)
    min_score = RANKING.get("min_score", 1)

    old_posts = []
    if POSTS_JSON.exists():
        try:
            old_posts = [enrich_post_entry(item) for item in json.loads(POSTS_JSON.read_text(encoding="utf-8"))]
        except Exception:
            old_posts = []

    # 1) FEEDS
    feed_items = []
    for url in FEEDS:
        try:
            fp = feedparser.parse(url)
            for e in fp.entries:
                link = e.get("link") or e.get("id")
                if not link or not link.startswith("http"):
                    continue
                title = e.get("title","").strip() or link
                # feedparser may leave HTML in summary; strip safely
                raw_sum = (e.get("summary") or e.get("description") or "")
                summary = BeautifulSoup(raw_sum, "html.parser").get_text(" ").strip()
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
                feed_items.append(enrich_post_entry({
                    "id": pid,
                    "source": src_name,
                    "url": link,
                    "title": title,
                    "tags": list(set(base_tags + cats)),
                    "added": d.isoformat(),
                    "summary": summary[:SUMMARY_CHARS] + ("…" if len(summary) > SUMMARY_CHARS else ""),
                    "score": s,
                    "ts": ts,
                    "categories": cats
                }))
        except Exception as ex:
            print(f"[WARN] feed error {url}: {ex}")

    # 2) REPORTS + links inside them
    reports = []
    seen_report_paths = set()
    report_links = []
    report_link_files_seen = 0
    for ddir in REPORTS_DIRS:
        if not ddir.exists(): continue
        for f in sorted(ddir.rglob("*"), reverse=True):
            if f.suffix.lower() not in (".md",".markdown",".txt",".html",".htm"): continue
            try:
                rel = f.relative_to(ROOT).as_posix()
                if rel in seen_report_paths:
                    continue
                seen_report_paths.add(rel)
                raw, text, urls = read_report_text_and_urls(f)
                title, abstract, key_items = guess_title_abstract_keyitems(text)
                reports.append(make_report_entry(f, title, abstract, key_items, repo))
                if report_link_files_seen < MAX_REPORT_FILES_FOR_LINK_EXTRACTION:
                    report_links.extend(urls[:MAX_LINKS_PER_REPORT])
                    report_link_files_seen += 1
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
        report_items.append(enrich_post_entry({
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
        }))

    # 4) Merge + rank.
    # The app feed should act like a true rolling archive, so keep the
    # deduped historical stream instead of shrinking it back to a capped slice.
    merged_by_id = {}
    for arr in (old_posts, feed_items, report_items):
        for post in arr:
            current = merged_by_id.get(post["id"])
            if current is None or post.get("ts", 0) >= current.get("ts", 0):
                merged_by_id[post["id"]] = post
    merged = list(merged_by_id.values())
    merged.sort(key=lambda x: (x.get("score",0), x.get("ts",0)), reverse=True)
    final_posts = merged

    # Sort reports newest first
    deduped_reports = {}
    for report in reports:
        deduped_reports[(report["date"], report["url_html"])] = report
    reports = sorted(deduped_reports.values(), key=lambda r: r["date"], reverse=True)

    POSTS_JSON.write_text(json.dumps(final_posts, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORTS_JSON.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5) Audio/Drive
    scan_audio(repo)

if __name__ == "__main__":
    asyncio.run(build())
    print("Wrote:", POSTS_JSON, REPORTS_JSON, AUDIO_JSON)
