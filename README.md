# EUR-Lex Daily Digest

This repository provides a minimal, **working** skeleton for automatically collecting new legal documents from EUR‑Lex (via RSS or SPARQL), optionally summarising them with the OpenAI API, and delivering a daily digest via e‑mail.  It is meant as a starting point; you can customise the feeds, keywords and delivery settings without touching the core code.

## What it does

* **Fetches updates**: The script reads a list of RSS/Atom feeds from `config.yaml` (for example the Official Journal or your own saved search).  For each feed, it checks the most recent entries and filters them by your keywords.
* **Summarises content (optional)**: If you have an `OPENAI_API_KEY` configured, the script sends the entry’s summary text to the OpenAI API and generates a concise summary in English.  Without a key, it simply includes the feed’s own description.
* **Sends a daily e‑mail**:  A GitHub Actions workflow runs the script once per day.  You can choose to send the digest via Gmail SMTP (with an app password) or via Mailgun.  All sensitive credentials live in GitHub Secrets.

## Directory structure

```
eurlex_digest/
├── .github/workflows/daily_digest.yml  # GitHub Actions workflow (schedules the job)
├── config.yaml                         # Keywords, feed URLs, optional settings
├── main.py                             # Main Python script for fetching, filtering, summarising and emailing
├── requirements.txt                    # Python dependencies
└── README.md                           # This file
```

## Quick start

1. **Fork or clone this repository**.  You can start with a public repo for free GitHub Actions minutes and later switch to private if desired.
2. **Edit `config.yaml`** to include the RSS feeds you want to monitor and the keywords that matter to you.
3. **Add your secrets** in GitHub Settings → **Secrets and variables** → **Actions**:
   * `GMAIL_USER` – your Gmail address.
   * `GMAIL_PASS` – a 16‑digit app password created via Google’s security settings.  See the [Google Help](https://support.google.com/accounts/answer/185833?hl=en) for instructions.
   * (Optional) `OPENAI_API_KEY` – your OpenAI API key if you want AI‑generated summaries.
4. *(Alternative mail service)* To send through Mailgun instead of Gmail, set `MAIL_SERVICE` to `mailgun` in `config.yaml` and add the secrets `MAILGUN_API_KEY`, `MAILGUN_DOMAIN` and `MAILGUN_FROM`/`MAILGUN_TO` as appropriate.
5. **Push to GitHub**.  The daily workflow will run automatically at the scheduled time (default 07:00 UTC).  You can also trigger it manually from the **Actions** tab.

## Adding new sources

To scrape additional websites, define them in [`sources_v2.yaml`](sources_v2.yaml). See [docs/adding_sources.md](docs/adding_sources.md) for details on the available keys such as `list_selectors`, `date_selectors`, and pagination.
