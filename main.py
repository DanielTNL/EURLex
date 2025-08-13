#!/usr/bin/env python3
"""
EUR-Lex Daily Digest – structured version
-----------------------------------------

What this script does (daily):
1) Pulls items from configured RSS feeds.
2) Scores + filters to a max of N items (configurable).
3) Summarises each item (OpenAI; fallback excerpt if no API key).
4) Categorises items (hybrid): rules first, then LLM fallback when ambiguous.
5) Builds category-level syntheses and an overall Executive Digest (with [refs]).
6) Writes a Markdown report to reports/YYYY-MM-DD.md.
7) Emails: (a) Executive Digest, plus (b) compact per-category title lists,
   and (c) a link to the full report in the repo.

Config:
- feeds (list), keywords (list), language, timezone, mail_service, email.to
- taxonomy.categories: name + include (rule keywords)
- caps: max_total, max_per_category, min_per_category
- recent_hours: recency window (e.g., 72)

Env / Secrets:
- OPENAI_API_KEY (enables AI passes)
- OPENAI_MODEL (optional; default "gpt-4o-mini")
- GMAIL_USER, GMAIL_PASS (Gmail SMTP)  OR  Mailgun secrets (if mailgun)
- (Optional) GITHUB_* envs provided by Actions used to build report link
"""

import os
import sys
import yaml
import feedparser
import datetime as dt
from email.mime.text import MIMEText
import smtplib
from typing import List, Dict, Any, Tuple

# Optional timezone support
try:
    import pytz  # type: ignore
except ImportError:
    pytz = None

# --- OpenAI (new SDK) ---------------------------------------------------------
OPENAI_ENABLED = bool(os.getenv("OPENAI_API_KEY"))
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
if OPENAI_ENABLED:
    try:
        from openai import OpenAI  # type: ignore
        _oa_client = OpenAI()
    except Exception as _e:
        OPENAI_ENABLED = False
        _oa_client = None
else:
    _oa_client = None
# -----------------------------------------------------------------------------


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def keyword_match_count(text: str, keywords: List[str]) -> int:
    lower = text.lower()
    cnt = 0
    for kw in keywords or []:
        if kw.lower() in lower:
            cnt += 1
    return cnt


def summarize_text(text: str, language: str, max_chars: int = 4000) -> str:
    """Item-level summary: 3–5 bullets, <=100 words, neutral."""
    snippet = (text or "").strip()
    if not snippet:
        return ""
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "…"

    if not OPENAI_ENABLED or _oa_client is None:
        return snippet[:500] + ("…" if len(snippet) > 500 else "")

    try:
        resp = _oa_client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=0.2,
            max_tokens=180,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an analyst summarizing EU legal documents. "
                        "Be factual, neutral, concise. Do not invent facts not present."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Summarize in {language if language else 'EN'} using 3–5 bullet points (<=100 words). "
                        "Focus on: what changed, scope, obligations, dates/timelines, who is affected.\n\n"
                        f"Document text:\n{snippet}"
                    ),
                },
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print("OpenAI summary error:", exc)
        return snippet[:500] + ("…" if len(snippet) > 500 else "")


def llm_choose_category(text: str, category_names: List[str]) -> str:
    """LLM fallback to pick the best category name; returns one of category_names or 'Other'."""
    if not OPENAI_ENABLED or _oa_client is None:
        return "Other"
    try:
        joined = ", ".join(category_names)
        resp = _oa_client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=0.0,
            max_tokens=10,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You choose the single best category label for a document, "
                        "from a fixed list. Output only the label text, nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Categories: {joined}\n\n"
                        "Pick the single best category for the following title+summary:\n"
                        f"{text}\n\n"
                        "Output exactly one category label from the list above."
                    ),
                },
            ],
        )
        label = (resp.choices[0].message.content or "").strip()
        return label if label in category_names else "Other"
    except Exception as exc:
        print("OpenAI category error:", exc)
        return "Other"


def fetch_feed_entries(url: str) -> List[Dict[str, Any]]:
    parsed = feedparser.parse(url)
    entries = []
    for entry in parsed.entries:
        title = entry.get("title", "") or ""
        summary = entry.get("summary", "") or entry.get("description", "") or ""
        link = entry.get("link", "") or ""
        # try to parse date
        published_dt_utc = None
        if getattr(entry, "published_parsed", None):
            try:
                t = entry.published_parsed  # time.struct_time
                published_dt_utc = dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
            except Exception:
                pass
        entries.append(
            {"title": title, "summary": summary, "link": link, "published_utc": published_dt_utc, "source": url}
        )
    return entries


def score_entry(ent: Dict[str, Any], keywords: List[str], recent_hours: int) -> float:
    text = f"{ent.get('title','')} {ent.get('summary','')}"
    base = keyword_match_count(text, keywords)

    # Recency boost
    if recent_hours and ent.get("published_utc"):
        delta = dt.datetime.now(dt.timezone.utc) - ent["published_utc"]
        if delta.total_seconds() <= recent_hours * 3600:
            base += 1.0

    # Slight preference for OJ:L
    if "uri=OJ:L" in (ent.get("source") or ""):
        base += 0.2

    return float(base)


def sanitize_md(s: str) -> str:
    return (s or "").replace("\r", "")


def build_category_map(config: dict) -> List[Dict[str, Any]]:
    cats = []
    for c in (config.get("taxonomy", {}).get("categories", []) or []):
        name = str(c.get("name", "Other"))
        inc = [str(x) for x in (c.get("include", []) or [])]
        cats.append({"name": name, "include": inc})
    # Ensure "Other" exists
    if not any(c["name"] == "Other" for c in cats):
        cats.append({"name": "Other", "include": []})
    return cats


def rule_category_for(text: str, cats: List[Dict[str, Any]]) -> str:
    low = text.lower()
    for c in cats:
        if c["name"] == "Other":
            continue
        for pat in c["include"]:
            if pat.lower() in low:
                return c["name"]
    return ""  # no rule hit


def category_synthesis(category_name: str, items: List[Dict[str, Any]]) -> str:
    """2–4 bullets per category, referencing [id] tokens."""
    if not items:
        return ""
    if not OPENAI_ENABLED or _oa_client is None:
        # trivial non-AI fallback: list first 2 titles
        ids = ", ".join(f"[{it['id']}]" for it in items[:2])
        return f"- Notable items: {ids}"
    lines = []
    for it in items:
        lines.append(f"[{it['id']}] {it['title']} — {it['summary']}")
    joined = "\n".join(lines)
    try:
        resp = _oa_client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=0.2,
            max_tokens=220,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an analyst. Write a concise category brief in English. "
                        "Use 2–4 bullet points. Each bullet should cite one or more items "
                        "using their [id] tokens. Be factual and avoid repetition."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Category: {category_name}\n"
                        "Items (with [id] and summary):\n"
                        f"{joined}\n\n"
                        "Write 2–4 bullets summarizing this category; use [id] references."
                    ),
                },
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print("OpenAI category synthesis error:", exc)
        return ""


def executive_digest(all_items: List[Dict[str, Any]]) -> str:
    """5 bullets across categories, referencing [id] tokens."""
    if not all_items:
        return "No relevant developments today."

    if not OPENAI_ENABLED or _oa_client is None:
        top = ", ".join(f"[{it['id']}]" for it in all_items[:5])
        return f"- Key items: {top}"

    lines = []
    for it in all_items:
        lines.append(f"[{it['id']}] ({it['category']}) {it['title']} — {it['summary']}")
    joined = "\n".join(lines)
    try:
        resp = _oa_client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=0.2,
            max_tokens=260,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Produce an executive digest in English. Output 5 concise bullets. "
                        "Each bullet must cite one or more items using their [id] tokens. "
                        "Be factual, neutral, and avoid repetition."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Here are today’s items with [id], category, title, and summary:\n"
                        f"{joined}\n\n"
                        "Write 5 bullets with [id] references."
                    ),
                },
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print("OpenAI executive digest error:", exc)
        return ""


def send_email_gmail(subject: str, body: str, to_addr: str) -> None:
    user = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_PASS")
    if not user or not password:
        raise RuntimeError("GMAIL_USER or GMAIL_PASS not set")
    if not to_addr:
        to_addr = user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [to_addr], msg.as_string())


def send_email_mailgun(subject: str, body: str) -> None:
    import requests
    api_key = os.getenv("MAILGUN_API_KEY")
    domain = os.getenv("MAILGUN_DOMAIN")
    sender = os.getenv("MAILGUN_FROM")
    recipient = os.getenv("MAILGUN_TO")
    if not all([api_key, domain, sender, recipient]):
        raise RuntimeError("Mailgun credentials incomplete")
    url = f"https://api.mailgun.net/v3/{domain}/messages"
    resp = requests.post(
        url,
        auth=("api", api_key),
        data={"from": sender, "to": [recipient], "subject": subject, "text": body},
        timeout=20,
    )
    resp.raise_for_status()


def build_report_markdown(date_str: str,
                          exec_digest: str,
                          categories: List[Dict[str, Any]],
                          items_by_cat: Dict[str, List[Dict[str, Any]]]) -> str:
    out = [f"# EUR-Lex Daily Digest — {date_str}", ""]
    out += ["## Executive Summary", sanitize_md(exec_digest), ""]
    out += ["## Categories", ""]
    for c in categories:
        name = c["name"]
        items = items_by_cat.get(name, [])
        if not items:
            continue
        out += [f"### {name}", ""]
        # Category synthesis
        cat_syn = category_synthesis(name, items)
        if cat_syn:
            out += [sanitize_md(cat_syn), ""]
        out += ["#### Items", ""]
        for it in items:
            out += [f"**[{it['id']}] [{sanitize_md(it['title'])}]({it['link']})**", ""]
            # item summary may already have bullets; keep as-is
            out += [sanitize_md(it["summary"]), ""]
        out.append("")
    out += ["---", "_Generated by GitHub Actions with OpenAI (model: " + DEFAULT_MODEL + ")._"]
    return "\n".join(out)


def main() -> None:
    # --- Load config ----------------------------------------------------------
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"Failed to load config: {exc}")
        sys.exit(1)

    feeds: List[str] = list(config.get("feeds", []))
    keywords: List[str] = config.get("keywords", [])
    language: str = config.get("language", "EN")
    mail_service: str = str(config.get("mail_service", "gmail")).lower()
    tz_name: str = config.get("timezone", "UTC")
    email_cfg = config.get("email") or {}
    email_to: str = email_cfg.get("to") or os.getenv("EMAIL_TO") or os.getenv("GMAIL_USER") or ""

    caps = config.get("caps", {}) or {}
    max_total = int(caps.get("max_total", 30))
    max_per_cat = int(caps.get("max_per_category", 10))
    min_per_cat = int(caps.get("min_per_category", 1))

    recent_hours = int(config.get("recent_hours", 72))

    categories_cfg = build_category_map(config)
    category_names = [c["name"] for c in categories_cfg]

    if not feeds:
        print("No feeds configured; exiting.")
        sys.exit(0)

    # --- Subject / date in local tz ------------------------------------------
    now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")
    if pytz is not None:
        try:
            tz = pytz.timezone(tz_name)
            local_dt = now_utc.astimezone(tz)
            date_str = local_dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    subject = f"EUR-Lex Digest – {date_str}"

    # --- Fetch & preliminary scoring -----------------------------------------
    pool: List[Dict[str, Any]] = []
    for feed_url in feeds:
        try:
            entries = fetch_feed_entries(feed_url)
        except Exception as exc:
            print(f"Error fetching feed {feed_url}: {exc}")
            continue
        for ent in entries:
            text = f"{ent.get('title','')} {ent.get('summary','')}"
            s = score_entry(ent, keywords, recent_hours)
            pool.append({**ent, "score": s, "text": text})

    # Sort by score desc, keep a working shortlist to control token/cost
    pool.sort(key=lambda x: x["score"], reverse=True)
    shortlist = pool[: max_total * 2]  # pre-cap before category distribution

    # --- Item-level summaries (on shortlist) ---------------------------------
    for it in shortlist:
        base_text = (it.get("summary") or it.get("title") or "")
        it["summary"] = summarize_text(base_text, language)

    # --- Categorise (rules → LLM fallback) -----------------------------------
    for it in shortlist:
        text = it["text"]
        # rule pass
        cat = rule_category_for(text, categories_cfg)
        if not cat:
            # fallback to LLM
            cat = llm_choose_category(text, category_names)
        it["category"] = cat if cat in category_names else "Other"

    # --- Per-category selection caps -----------------------------------------
    # Prepare buckets in the order of categories_cfg
    cat_buckets: Dict[str, List[Dict[str, Any]]] = {c["name"]: [] for c in categories_cfg}
    for it in shortlist:
        cat_buckets[it["category"]].append(it)

    # Within each category, keep top by score
    for name, items in cat_buckets.items():
        items.sort(key=lambda x: x["score"], reverse=True)
        cat_buckets[name] = items[:max_per_cat]

    # Enforce overall cap while keeping at least min_per_cat where possible
    # Flatten (respect category order), then truncate
    flattened: List[Dict[str, Any]] = []
    # First, ensure min_per_cat if available
    for c in categories_cfg:
        name = c["name"]
        if cat_buckets[name]:
            flattened.extend(cat_buckets[name][:min( len(cat_buckets[name]), max(min_per_cat, 0) )])
    # Then add the rest by score
    remainder: List[Tuple[float, Dict[str, Any]]] = []
    for c in categories_cfg:
        name = c["name"]
        items = cat_buckets[name][min_per_cat:]
        for it in items:
            remainder.append((it["score"], it))
    remainder.sort(key=lambda x: x[0], reverse=True)
    for _, it in remainder:
        if len(flattened) >= max_total:
            break
        flattened.append(it)

    # Reassign ids 1..N for referencing
    selected = flattened[:max_total]
    for i, it in enumerate(selected, start=1):
        it["id"] = i

    # Rebuild per-category dict for report
    selected_by_cat: Dict[str, List[Dict[str, Any]]] = {c["name"]: [] for c in categories_cfg}
    for it in selected:
        selected_by_cat[it["category"]].append(it)

    # --- Category syntheses & Executive Digest -------------------------------
    exec_syn = executive_digest(selected)

    # --- Markdown report ------------------------------------------------------
    md = build_report_markdown(date_str, exec_syn, categories_cfg, selected_by_cat)
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"{date_str}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)

    # Build a link to the report on GitHub
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repo = os.getenv("GITHUB_REPOSITORY")  # e.g., owner/repo
    branch = os.getenv("GITHUB_REF_NAME", "main")
    report_url = ""
    if repo:
        report_url = f"{server}/{repo}/blob/{branch}/reports/{date_str}.md"

    # --- Email body (Exec Digest + compact per-category titles with links) ---
    lines: List[str] = []
    lines.append("Executive Digest")
    lines.append("----------------")
    lines.append(exec_syn if exec_syn else "No relevant developments today.")
    lines.append("")
    if report_url:
        lines.append(f"Full report: {report_url}")
        lines.append("")

    lines.append("Per-category titles")
    lines.append("-------------------")
    for c in categories_cfg:
        name = c["name"]
        items = selected_by_cat.get(name, [])
        if not items:
            continue
        lines.append(f"{name}:")
        for it in items:
            lines.append(f"- {it['title']}  ({it['link']})")
        lines.append("")

    body = "\n".join(lines)

    # --- Send email -----------------------------------------------------------
    if mail_service == "gmail":
        send_email_gmail(subject, body, email_to)
    elif mail_service == "mailgun":
        send_email_mailgun(subject, body)
    else:
        raise RuntimeError(f"Unsupported mail_service: {mail_service}")

    print(f"Digest sent. Report saved at {report_path}")
    # Note: the workflow step will commit & push the report.
    # (We keep git operations in the workflow for clearer audit.)
    

if __name__ == "__main__":
    main()
