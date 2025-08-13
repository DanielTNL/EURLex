#!/usr/bin/env python3
"""
EUR‑Lex Daily Digest Script
===========================

This script fetches RSS/Atom feeds defined in `config.yaml`, filters
entries based on a list of keywords, optionally summarises the
content via the OpenAI API, and sends a digest e‑mail to you.

The behaviour is driven by environment variables and the YAML
configuration file:

* `OPENAI_API_KEY` (optional): API key for OpenAI.  If set,
  the script will generate concise summaries of each entry.  If not
  set, it will include the feed’s own description.
* `GMAIL_USER` and `GMAIL_PASS`: your Gmail address and a 16‑digit
  app password created in your Google account security settings.  Used
  when `mail_service` in the config is set to `gmail`.
* `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_FROM`, `MAILGUN_TO`
  (optional): required if you choose `mailgun` as the mail service.

This script is designed to run on GitHub Actions, but it can also be
executed locally for testing.  When run locally, ensure that the
environment variables are set in your shell or via a `.env` file.

Author: OpenAI Assistant (2025)
"""

import os
import sys
import yaml
import feedparser
import datetime as dt
from email.mime.text import MIMEText
import smtplib
import re

# Optional imports for AI summarisation and timezone handling
try:
    import openai  # type: ignore
except ImportError:
    openai = None  # Fallback if openai library is not installed

try:
    import pytz  # type: ignore
except ImportError:
    pytz = None  # Timezone support is optional


def load_config(path: str) -> dict:
    """Load YAML configuration from the given path."""
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def keyword_match(text: str, keywords: list[str]) -> bool:
    """Return True if any keyword appears in the text (case‑insensitive)."""
    lower = text.lower()
    for kw in keywords:
        if kw.lower() in lower:
            return True
    return False


def summarise_text(text: str, language: str) -> str:
    """Use OpenAI to summarise the provided text.

    Returns the summary or a fallback message on error.
    """
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key or openai is None:
        # Fallback: return truncated original text
        return text.strip()[:500] + ('...' if len(text) > 500 else '')
    try:
        openai.api_key = api_key
        # Compose a prompt instructing the assistant to provide a short summary
        prompt = (
            f"Summarise the following document in a few sentences in {language}:\n"\
            f"\n{text}\n"
        )
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarises legal documents."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        return f"(AI summary unavailable: {exc})"


def fetch_feed_entries(url: str) -> list[dict]:
    """Parse the RSS/Atom feed and return a list of entries."""
    parsed = feedparser.parse(url)
    entries = []
    for entry in parsed.entries:
        # Normalise fields to ensure presence
        title = entry.get('title', '')
        summary = entry.get('summary', '') or entry.get('description', '')
        link = entry.get('link', '')
        entries.append({'title': title, 'summary': summary, 'link': link})
    return entries


def compose_email(subject: str, entries: list[dict], language: str) -> str:
    """Create the e‑mail body with summaries for each entry."""
    lines: list[str] = []
    if not entries:
        lines.append("No new items matched your keywords today.")
    else:
        for ent in entries:
            title = ent['title'].strip()
            link = ent['link'].strip()
            summary_text = ent['summary'].strip()
            # Summarise using OpenAI if configured
            summary = summarise_text(summary_text, language)
            lines.append(f"- {title}\n  Link: {link}\n  Summary: {summary}\n")
    return "\n".join(lines)


def send_email_gmail(subject: str, body: str) -> None:
    """Send the email via Gmail SMTP."""
    user = os.getenv('GMAIL_USER')
    password = os.getenv('GMAIL_PASS')
    if not user or not password:
        raise RuntimeError('GMAIL_USER or GMAIL_PASS not set')
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = user
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [user], msg.as_string())


def send_email_mailgun(subject: str, body: str) -> None:
    """Send the email via Mailgun HTTP API."""
    import requests  # Imported here to avoid dependency if not used
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN')
    sender = os.getenv('MAILGUN_FROM')  # e.g. 'Digest <digest@yourdomain.com>'
    recipient = os.getenv('MAILGUN_TO')  # e.g. 'you@example.com'
    if not all([api_key, domain, sender, recipient]):
        raise RuntimeError('Mailgun credentials (MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_FROM, MAILGUN_TO) must be set')
    url = f"https://api.mailgun.net/v3/{domain}/messages"
    response = requests.post(
        url,
        auth=("api", api_key),
        data={
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "text": body,
        },
    )
    response.raise_for_status()


def main() -> None:
    # Load configuration
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"Failed to load config: {exc}")
        sys.exit(1)

    feeds: list[str] = config.get('feeds', [])
    keywords: list[str] = config.get('keywords', [])
    language: str = config.get('language', 'EN')
    mail_service: str = config.get('mail_service', 'gmail').lower()
    tz_name: str = config.get('timezone', 'UTC')

    # Determine current date for subject line
    now = dt.datetime.utcnow()
    date_str = now.strftime('%Y-%m-%d')
    if pytz is not None:
        try:
            tz = pytz.timezone(tz_name)
            local_dt = now.replace(tzinfo=dt.timezone.utc).astimezone(tz)
            date_str = local_dt.strftime('%Y-%m-%d')
        except Exception:
            pass

    subject = f"EUR‑Lex Digest – {date_str}"

    matched_entries: list[dict] = []
    for feed_url in feeds:
        try:
            entries = fetch_feed_entries(feed_url)
        except Exception as exc:
            print(f"Error fetching feed {feed_url}: {exc}")
            continue
        for ent in entries:
            text = ent['title'] + ' ' + ent['summary']
            if keyword_match(text, keywords):
                matched_entries.append(ent)

    body = compose_email(subject, matched_entries, language)

    # Dispatch email
    if mail_service == 'gmail':
        send_email_gmail(subject, body)
    elif mail_service == 'mailgun':
        send_email_mailgun(subject, body)
    else:
        raise RuntimeError(f"Unsupported mail_service: {mail_service}")

    print("Digest sent successfully.")


if __name__ == '__main__':
    main()