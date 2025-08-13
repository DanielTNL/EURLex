#!/usr/bin/env python3
"""
EUR-Lex Daily Digest Script
===========================

Fetches RSS/Atom feeds defined in `config.yaml`, filters entries by keywords,
optionally summarises via the OpenAI API, and sends a daily digest e-mail.

Environment variables (GitHub Actions secrets/vars recommended):
* OPENAI_API_KEY (optional): enables AI summaries.
* OPENAI_MODEL (optional): default "gpt-4o-mini".
* GMAIL_USER, GMAIL_PASS (app password) for Gmail SMTP.
* MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_FROM, MAILGUN_TO for Mailgun.
* EXTRA_FEEDS (optional): newline-separated feed URLs injected in addition to config.yaml.

Author: OpenAI Assistant (2025)
"""

import os
import sys
import yaml
import feedparser
import datetime as dt
from email.mime.text import MIMEText
import smtplib

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
        # If the SDK isn't present, we gracefully downgrade to no-AI mode.
        OPENAI_ENABLED = False
        _oa_client = None
else:
    _oa_client = None
# -----------------------------------------------------------------------------


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def keyword_match(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    for kw in keywords:
        if kw.lower() in lower:
            return True
    return False


def summarize_text(text: str, language: str, model: str = DEFAULT_MODEL, max_chars: int = 4000) -> str:
    """
    Summarize `text` into 3–5 concise bullet points in English (or `language`).
    Falls back to a truncated snippet if OpenAI is not configured.
    """
    snippet = (text or "").strip()
    if not snippet:
        return ""

    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "…"

    if not OPENAI_ENABLED or _oa_client is None:
        # Fallback: return a compact excerpt when AI is disabled
        return snippet[:500] + ("…" if len(snippet) > 500 else "")

    try:
        resp = _oa_client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=180,  # ~100–130 words
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an analyst summarizing EU legal documents for a daily email digest. "
                        "Write a concise, neutral summary. Use 3–5 bullet points. No fluff."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Summarize in {language if language else 'EN'} (<=100 words total). "
                        "Focus on: what changed, scope, obligations, dates/timelines, who is affected.\n\n"
                        f"Document text:\n{snippet}"
                    ),
                },
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print("OpenAI error:", exc)
        # Fail soft with a short excerpt
        return snippet[:500] + ("…" if len(snippet) > 500 else "")


def fetch_feed_entries(url: str) -> list[dict]:
    """Parse an RSS/Atom feed and return normalized entries."""
    parsed = feedparser.parse(url)
    entries = []
    for entry in parsed.entries:
        title = entry.get("title", "") or ""
        summary = entry.get("summary", "") or entry.get("description", "") or ""
        link = entry.get("link", "") or ""
        entries.append({"title": title, "summary": summary, "link": link})
    return entries


def compose_email(subject: str, entries: list[dict], language: str) -> str:
    """Create the e-mail body; summarise each entry if OpenAI is enabled."""
    lines: list[str] = []
    if not entries:
        lines.append("No new items matched your keywords today.")
    else:
        for ent in entries:
            title = (ent["title"] or "").strip()
            link = (ent["link"] or "").strip()
            base_text = (ent["summary"] or "").strip() or title
            summary = summarize_text(base_text, language)
            lines.append(f"- {title}\n  Link: {link}\n  Summary: {summary}\n")
    return "\n".join(lines)


def send_email_gmail(subject: str, body: str, to_addr: str) -> None:
    """Send via Gmail SMTP with app password."""
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
    """Send via Mailgun HTTP API."""
    import requests  # local import to avoid dependency if unused

    api_key = os.getenv("MAILGUN_API_KEY")
    domain = os.getenv("MAILGUN_DOMAIN")
    sender = os.getenv("MAILGUN_FROM")     # e.g., 'Digest <digest@yourdomain.com>'
    recipient = os.getenv("MAILGUN_TO")    # e.g., 'you@example.com'
    if not all([api_key, domain, sender, recipient]):
        raise RuntimeError("Mailgun credentials (MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_FROM, MAILGUN_TO) must be set")

    url = f"https://api.mailgun.net/v3/{domain}/messages"
    resp = requests.post(
        url,
        auth=("api", api_key),
        data={"from": sender, "to": [recipient], "subject": subject, "text": body},
        timeout=20,
    )
    resp.raise_for_status()


def main() -> None:
    # --- Load config ----------------------------------------------------------
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"Failed to load config: {exc}")
        sys.exit(1)

    feeds: list[str] = list(config.get("feeds", []))
    keywords: list[str] = config.get("keywords", [])
    language: str = config.get("language", "EN")
    mail_service: str = str(config.get("mail_service", "gmail")).lower()
    tz_name: str = config.get("timezone", "UTC")
    email_cfg = config.get("email") or {}
    email_to: str = email_cfg.get("to") or os.getenv("EMAIL_TO") or os.getenv("GMAIL_USER") or ""

    # Allow injecting extra feeds from a secret/variable (newline-separated)
    extra = os.getenv("EXTRA_FEEDS", "")
    if extra.strip():
        for line in extra.splitlines():
            u = line.strip()
            if u and not u.startswith("#"):
                feeds.append(u)

    if not feeds:
        print("No feeds configured; exiting.")
        sys.exit(0)

    # --- Subject with local date (Europe/Amsterdam etc.) ----------------------
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

    # --- Fetch & filter -------------------------------------------------------
    matched_entries: list[dict] = []
    for feed_url in feeds:
        try:
            entries = fetch_feed_entries(feed_url)
        except Exception as exc:
            print(f"Error fetching feed {feed_url}: {exc}")
            continue

        for ent in entries:
            text = f"{ent.get('title','')} {ent.get('summary','')}"
            if keyword_match(text, keywords):
                matched_entries.append(ent)

    # --- Compose & send -------------------------------------------------------
    body = compose_email(subject, matched_entries, language)

    if mail_service == "gmail":
        send_email_gmail(subject, body, email_to)
    elif mail_service == "mailgun":
        send_email_mailgun(subject, body)
    else:
        raise RuntimeError(f"Unsupported mail_service: {mail_service}")

    print("Digest sent successfully.")


if __name__ == "__main__":
    main()
