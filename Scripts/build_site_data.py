#!/usr/bin/env python3
import os, re, json, hashlib, datetime as dt, pathlib, html
from urllib.parse import urlparse
import httpx, frontmatter, yaml
from bs4 import BeautifulSoup
from trafilatura import fetch_url, extract as trafi_extract

# ---- CONFIG ----
REPO = os.getenv("GITHUB_REPOSITORY", "DanielTNL/EURLex")
ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORTS_DIRS = [ROOT / "reports", ROOT / "reports" / "weekly", ROOT / "reports" / "daily"]
DOCS_DATA = ROOT / "docs" / "data"
DOCS_DATA.mkdir(parents=True, exist_ok=True)
POSTS_JSON = DOCS_DATA / "posts.json"
REPORTS_JSON = DOCS_DATA / "reports.json"
SOURCES_YAML = ROOT / "scripts" / "sources.yaml"

MAX_LINKS_PER_RUN = 200   # safety cap
SUMMARY_CHARS = 1000

URL_RE = re.compile(r'https?://[^\s\]\)\}\>\"\'`]+', re.IGNORECASE)

def load_yaml(p):
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

SOURCES = load_yaml(SOURCES_YAML)
DOMAIN_MAP = SOURCES.get("domains", {})
DEFAULT_SOURCE = SOURCES.get("defaults", {"source":"External","tags":["external"]})

def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def norm_date_from_name(path: pathlib.Path) -> str:
    # Try to find YYYY-MM-DD in filename or parent
    m = re.search(r'(\d{4})[-_/](\d{2})[-_/](\d{2})', str(path))
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}"
    # fallback: file mtime (UTC)
    ts = dt.datetime.utcfromtimestamp(path.stat().st_mtime)
    return ts.strftime("%Y-%m-%d")

def guess_title_and_sections_text(text: str) -> tuple[str, str, list[str]]:
    """Return (title, abstract, key_items) best-effort from plain text/markdown."""
    lines = [l.strip() for l in text.splitlines()]
    # title = first non-empty line
    title = next((l for l in lines if l), "Untitled report")
    # abstract = first paragraph after title, up to ~300 chars
    after = "\n".join(lines[1:]).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", after) if p.strip()]
    abstract = paras[0][:300] if paras else ""
    # key items = bullets under a heading containing "key item" or lines starting with "-"
    key_items = []
    capture = False
    for l in lines:
        if re.search(r'key\s*items?|highlights', l, re.I):
            capture = True
            continue
        if capture and (l.startswith("- ") or l.startswith("* ")):
            key_items.append(l[2:].strip())
        elif capture and l and not (l.startswith("- ") or l.startswith("* ")):
            # end of bullet section
            capture = False
    # If none captured, take first 3 bullets anywhere
    if not key_items:
        for l in lines:
            if l.startswith("- ") or l.startswith("* "):
                key_items.append(l[2:].strip())
            if len(key_items) >= 3: break
    return title, abstract, key_items

def extract_urls_from_html(html_text: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    hrefs = []
    for a in soup.find_all("a", href=True):
        u = a["href"].strip()
        if u.startswith("http"):
            hrefs.append(u)
    return list(dict.fromkeys(hrefs))  # unique order

def read_text_from_file(path: pathlib.Path) -> tuple[str, list[str]]:
    ext = path.suffix.lower()
    raw = path.read_text(encoding="utf-8", errors="ignore")
    urls = []
    if ext in (".html", ".htm"):
        urls = extract_urls_from_html(raw)
        # crude text from HTML
        soup = BeautifulSoup(raw, "html.parser")
        text = soup.get_text("\n")
    elif ext in (".md", ".markdown"):
        text = frontmatter.loads(raw).content if raw.lstrip().startswith(("---", "+++")) else raw
        urls = list(dict.fromkeys(URL_RE.findall(raw)))
    else:
        # .txt or other: treat as plain text
        text = raw
        urls = list(dict.fromkeys(URL_RE.findall(raw)))
    return text, urls

async def fetch_title_and_summary(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    # First try Trafilatura (better text); then fallback to <title>
    try:
        downloaded = fetch_url(url)
        if downloaded:
            extracted = trafi_extract(downloaded, include_comments=False, include_links=False)
            if extracted:
                # Try to get a title separately with a light fetch
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
                    # Use the first line of extracted text as title-ish
                    first_line = extracted.strip().splitlines()[0][:140]
                    title = first_line if len(first_line) > 10 else url
                summary = extracted.strip().replace("\n", " ")
                if len(summary) > SUMMARY_CHARS:
                    summary = summary[:SUMMARY_CHARS] + "…"
                return title, summary
    except Exception:
        pass

    # Fallback simple GET for <title>
    try:
        r = await client.get(url, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.text.strip() if soup.title else url
            # Simple summary: first 300 chars of visible text
            text = soup.get_text(" ").strip()
            text = re.sub(r"\s+", " ", text)
            summary = (text[:SUMMARY_CHARS] + "…") if len(text) > SUMMARY_CHARS else text
            return title or url, summary
    except Exception:
        pass
    return url, ""  # ultimate fallback

def label_for_url(u: str) -> tuple[str, list[str]]:
    try:
        host = urlparse(u).netloc.lower()
        # normalise common www.
        host = host[4:] if host.startswith("www.") else host
        meta = DOMAIN_MAP.get(host)
        if meta:
            return meta.get("source", host), list(meta.get("tags", []))
        return DEFAULT_SOURCE.get("source", host), list(DEFAULT_SOURCE.get("tags", []))
    except Exception:
        return DEFAULT_SOURCE.get("source", "External"), list(DEFAULT_SOURCE.get("tags", ["external"]))

def make_report_entry(path: pathlib.Path, title: str, abstract: str, key_items: list[str]) -> dict:
    date = norm_date_from_name(path)
    rid = f"rep-{date}-{sha16(str(path))}"
    # Link to the file in GitHub UI
    file_rel = path.relative_to(ROOT).as_posix()
    url_html = f"https://github.com/{REPO}/blob/main/{file_rel}"
    tags = []
    if "weekly" in file_rel.lower(): tags.append("weekly")
    if "daily" in file_rel.lower(): tags.append("daily")
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

async def build():
    # Load previous outputs to preserve and dedupe
    old_posts = []
    if POSTS_JSON.exists():
        try:
            old_posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
        except Exception:
            old_posts = []
    seen_ids = {p.get("id") for p in old_posts}

    reports = []
    new_posts = old_posts[:]  # start from previous and append new
    collected_links = []

    # Gather report files
    report_files = []
    for d in REPORTS_DIRS:
        if d.exists():
            for ext in (".md", ".markdown", ".txt", ".html", ".htm"):
                report_files += list(d.rglob(f"*{ext}"))
    report_files = sorted(report_files)

    # Parse reports, extract links
    for f in report_files:
        try:
            raw = f.read_text(encoding="utf-8", errors="ignore")
            if f.suffix.lower() in (".md", ".markdown"):
                fm = frontmatter.loads(raw)
                content = fm.content
                title = fm.get("title")
                date = fm.get("date")
                abstract = fm.get("abstract", "")
                key_items = fm.get("key_items", [])
                body_for_urls = raw
                if not title or not abstract or not key_items:
                    # fall back to heuristic on content
                    t2, a2, k2 = guess_title_and_sections_text(content or raw)
                    title = title or t2
                    abstract = abstract or a2
                    key_items = key_items or k2
            else:
                content = raw
                title, abstract, key_items = guess_title_and_sections_text(content)

            # Make report entry
            r_entry = make_report_entry(f, title, abstract, key_items)
            reports.append(r_entry)

            # Extract URLs (from full raw so links in frontmatter/body are caught)
            urls = []
            if f.suffix.lower() in (".html", ".htm"):
                urls = extract_urls_from_html(raw)
            else:
                urls = list(dict.fromkeys(URL_RE.findall(raw)))
            # cap total across all reports
            for u in urls:
                if len(collected_links) >= MAX_LINKS_PER_RUN:
                    break
                collected_links.append((u, r_entry["date"]))
        except Exception as e:
            print(f"[WARN] Could not parse report {f}: {e}")

    # Create/append posts for each URL
    async with httpx.AsyncClient(headers={"User-Agent":"eurlex-site-builder/1.0"}) as client:
        for url, date in collected_links:
            pid = sha16(url)
            if pid in seen_ids:
                continue
            source_name, tags = label_for_url(url)
            title, summary = await fetch_title_and_summary(client, url)
            item = {
                "id": pid,
                "source": source_name,
                "url": url,
                "title": title,
                "tags": tags,
                "added": dt.datetime.utcnow().isoformat() + "Z",
                "summary": summary or ""
            }
            new_posts.insert(0, item)
            seen_ids.add(pid)

    # De-dupe posts by id, keep newest first, cap length
    uniq = {}
    for p in new_posts:
        if p["id"] not in uniq:
            uniq[p["id"]] = p
    new_posts = list(uniq.values())[:1000]

    # Sort reports newest first
    reports.sort(key=lambda r: r["date"], reverse=True)

    # Write outputs
    POSTS_JSON.write_text(json.dumps(new_posts, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORTS_JSON.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    import asyncio
    asyncio.run(build())
    print("Wrote:", POSTS_JSON, REPORTS_JSON)
