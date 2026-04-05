#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import yaml
from dateutil import parser as dateparse

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / 'docs' / 'data'
DOCS_DATA.mkdir(parents=True, exist_ok=True)
DIGESTS_DIR = ROOT / 'docs' / 'digests'
STATE_DIR = ROOT / 'state'
REPO_SLUG = os.getenv('GITHUB_REPOSITORY', 'DanielTNL/EURLex')

POSTS_JSON = DOCS_DATA / 'posts.json'
REPORTS_JSON = DOCS_DATA / 'reports.json'
AUDIO_JSON = DOCS_DATA / 'audio.json'
TIMELINE_JSON = DOCS_DATA / 'timeline-latest.json'
DIGEST_LATEST_JSON = DIGESTS_DIR / 'latest.json'
SOURCES_YAML = ROOT / 'scripts' / 'sources.yaml'
SOURCES_V2_YAML = ROOT / 'sources_v2.yaml'
CUSTOM_FEEDS_JSON = STATE_DIR / 'custom_feeds.json'
LIBRARY_STATE_JSON = STATE_DIR / 'library_documents.json'

BRIEFINGS_JSON = DOCS_DATA / 'briefings.json'
BRIEFING_LATEST_JSON = DOCS_DATA / 'briefing-latest.json'
SUNDAY_EDITIONS_JSON = DOCS_DATA / 'sunday-editions.json'
SUNDAY_EDITION_LATEST_JSON = DOCS_DATA / 'sunday-edition-latest.json'
SOURCES_JSON = DOCS_DATA / 'sources.json'
LIBRARY_JSON = DOCS_DATA / 'library.json'
BACKEND_STATUS_JSON = DOCS_DATA / 'backend-status.json'

LIBRARY_DIRS = [
    ROOT / 'library',
    ROOT / 'library' / 'uploads',
    ROOT / 'knowledge',
    ROOT / 'uploads',
]
LIBRARY_EXTENSIONS = {'.pdf', '.txt', '.md', '.markdown', '.docx'}
MAX_BRIEFING_DAYS = 14
MAX_SUNDAY_EDITIONS = 8
MAX_AI_DAILY_DAYS = 7
MAX_AI_SUNDAY_EDITIONS = 4


def load_json(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def load_yaml(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception:
        return {}


def write_json(path: pathlib.Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        value = dateparse.parse(raw)
    except Exception:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_day(raw: Optional[str]) -> Optional[str]:
    parsed = parse_dt(raw)
    return parsed.date().isoformat() if parsed else None


def is_live_day(day: Optional[str]) -> bool:
    if not day:
        return False
    try:
        value = date.fromisoformat(day)
    except Exception:
        return False
    return value <= datetime.now(timezone.utc).date()


def clean_text(text: str, limit: int = 400) -> str:
    compact = re.sub(r'\s+', ' ', text or '').strip()
    if len(compact) <= limit:
        return compact
    sentence_floor = max(120, int(limit * 0.6))
    for match in reversed(list(re.finditer(r'(?<=[.!?])\s+', compact[: limit + 1]))):
        cutoff = match.start()
        if cutoff >= sentence_floor:
            return compact[:cutoff].rstrip()
    cutoff = compact.rfind(' ', 0, limit - 1)
    if cutoff < max(40, int(limit * 0.45)):
        cutoff = limit - 1
    return compact[:cutoff].rstrip(' ,;:-') + '…'


def title_case_source(source_id: str) -> str:
    base = source_id.replace('_', ' ').replace('-', ' ').strip()
    return re.sub(r'\s+', ' ', base).title() or source_id


def domain_name(url: str) -> str:
    host = (urlparse(url).netloc or '').lower().lstrip('www.')
    return host or url


def openai_client() -> Optional[OpenAI]:
    if OpenAI is None:
        return None
    key = (os.getenv('OPENAI_API_KEY') or '').strip()
    if not key:
        return None
    return OpenAI(api_key=key)


def pick_model(prefer_weekly: bool = False) -> str:
    if prefer_weekly:
        return (
            os.getenv('OPENAI_WEEKLY_MODEL')
            or os.getenv('OPENAI_MODEL_WEEKLY')
            or os.getenv('OPENAI_MODEL')
            or 'gpt-5.4-nano'
        ).strip()
    return (os.getenv('OPENAI_MODEL') or 'gpt-5.4-nano').strip()


def parse_json_object(text: str) -> Optional[dict]:
    text = (text or '').strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def llm_json(system: str, user: str, prefer_weekly: bool = False) -> Optional[dict]:
    client = openai_client()
    if client is None:
        return None
    try:
        response = client.chat.completions.create(
            model=pick_model(prefer_weekly=prefer_weekly),
            temperature=0.3,
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
            max_tokens=7000,
            response_format={'type': 'json_object'},
        )
        content = response.choices[0].message.content or ''
        return parse_json_object(content)
    except Exception:
        return None


@dataclass
class CommonDocument:
    id: str
    title: str
    summary: str
    url: str
    kind: str
    source: str
    date: str
    categories: List[str]
    tags: List[str]

    def to_payload(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'summary': self.summary,
            'url': self.url,
            'kind': self.kind,
            'source': self.source,
            'date': self.date,
            'categories': self.categories,
            'tags': self.tags,
        }


def post_to_common(post: dict) -> CommonDocument:
    return CommonDocument(
        id=str(post.get('id') or post.get('url') or ''),
        title=post.get('display_title') or post.get('title') or 'Untitled',
        summary=clean_text(post.get('display_summary') or post.get('summary') or '', 340),
        url=post.get('url') or '',
        kind='post',
        source=post.get('source') or domain_name(post.get('url') or ''),
        date=iso_day(post.get('added')) or '',
        categories=list(post.get('categories') or []),
        tags=list(post.get('tags') or []),
    )


def report_to_common(report: dict) -> CommonDocument:
    return CommonDocument(
        id=str(report.get('id') or report.get('url_html') or ''),
        title=report.get('display_title') or report.get('title') or 'Untitled report',
        summary=clean_text(report.get('briefing') or report.get('abstract') or '', 860),
        url=report.get('url_html') or '',
        kind='report',
        source='EURLex reports',
        date=iso_day(report.get('date')) or '',
        categories=list(report.get('tags') or []),
        tags=list(report.get('tags') or []),
    )


def digest_to_common(item: dict) -> CommonDocument:
    categories = [x for x in (item.get('programme') or []) + (item.get('finance_instrument') or []) + (item.get('tech_area') or []) if x]
    return CommonDocument(
        id=str(item.get('url') or item.get('title') or ''),
        title=item.get('title') or 'Untitled digest item',
        summary=clean_text(item.get('summary_150w') or '', 340),
        url=item.get('url') or '',
        kind=item.get('doc_type') or 'digest',
        source=item.get('source_id') or 'Digest',
        date=iso_day(item.get('published_date')) or '',
        categories=categories[:8],
        tags=categories[:8],
    )


def timeline_to_common(item: dict) -> CommonDocument:
    categories = [x for x in (item.get('programme') or []) + (item.get('tech_area') or []) if x]
    return CommonDocument(
        id=str(item.get('id') or item.get('url') or item.get('title') or ''),
        title=item.get('title') or 'Untitled timeline event',
        summary=clean_text(item.get('summary') or item.get('summary_150w') or '', 340),
        url=item.get('url') or '',
        kind=item.get('doc_type') or item.get('stage') or 'timeline',
        source=item.get('source_id') or 'Timeline',
        date=iso_day(item.get('date')) or '',
        categories=categories[:8],
        tags=categories[:8],
    )


def unique_documents(items: Iterable[CommonDocument]) -> List[CommonDocument]:
    seen = set()
    results: List[CommonDocument] = []
    for item in items:
        key = (item.title.lower(), item.url.lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
    return results


def collect_categories(documents: Iterable[CommonDocument]) -> List[str]:
    counter: Counter[str] = Counter()
    for doc in documents:
        counter.update([c for c in doc.categories if c])
    return [name for name, _ in counter.most_common(8)]


def strip_markdown_noise(text: str, limit: int = 12000) -> str:
    cleaned = text or ''
    if not cleaned:
        return ''
    cleaned = re.sub(r'(?im)^#{1,6}\s*', '', cleaned)
    cleaned = re.sub(r'(?im)^[-*]\s+', '', cleaned)
    cleaned = re.sub(r'(?is)\bReferences\b.*$', '', cleaned)
    cleaned = cleaned.replace('_', ' ')
    cleaned = cleaned.replace('`', '')
    cleaned = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', cleaned)
    return clean_text(cleaned, limit)


def cleaned_doc_summary(doc: CommonDocument, limit: int = 520) -> str:
    base = strip_markdown_noise(doc.summary)
    lowered_base = re.sub(r'\s+', ' ', base).strip().lower()
    lowered_title = re.sub(r'\s+', ' ', doc.title).strip().lower()
    if lowered_base and lowered_title:
        if lowered_base == lowered_title:
            return ''
        if lowered_base.startswith(lowered_title) and len(lowered_base) <= len(lowered_title) + 60:
            return ''
    if lowered_base.startswith('http://') or lowered_base.startswith('https://'):
        return ''
    if base:
        return clean_text(base, limit)
    return clean_text(doc.title, min(limit, 180))


def is_synthetic_digest(doc: CommonDocument) -> bool:
    title = doc.title.lower()
    tags = [tag.lower() for tag in doc.tags]
    return (
        'daily digest' in title
        or 'sunday edition' in title
        or 'eur-lex daily digest' in title
        or (doc.kind == 'report' and doc.source.lower() == 'eurlex reports' and 'daily' in tags)
    )


def editorial_documents(documents: List[CommonDocument]) -> List[CommonDocument]:
    preferred = [doc for doc in documents if not is_synthetic_digest(doc)]
    preferred.sort(
        key=lambda doc: (
            1 if cleaned_doc_summary(doc, 220) else 0,
            len(cleaned_doc_summary(doc, 220)),
            doc.date or '',
        ),
        reverse=True,
    )
    return preferred or documents


def fallback_sections_from_documents(documents: List[CommonDocument], count: int = 3) -> List[dict]:
    sections = []
    for doc in editorial_documents(documents)[:count]:
        body = cleaned_doc_summary(doc, 820)
        if not body:
            continue
        sections.append(
            {
                'title': clean_text(doc.title, 120),
                'body': clean_text(f"{body} Source: {doc.source}, {doc.date or 'undated'}.", 980),
            }
        )
    return sections


def compact_key_points(key_points: List[str], documents: List[CommonDocument], limit: int) -> List[str]:
    cleaned = []
    for item in key_points:
        value = clean_text(strip_markdown_noise(item), 140)
        if value and value.lower() not in {'(none)', 'none'} and not value.lower().startswith(('http://', 'https://')):
            cleaned.append(value)
    preferred_cleaned = [
        item for item in cleaned
        if not any(token in item.lower() for token in ['daily digest', 'sunday edition', 'eur-lex daily digest'])
    ]
    if preferred_cleaned:
        return preferred_cleaned[:limit]
    if cleaned:
        return cleaned[:limit]
    return [clean_text(doc.title, 140) for doc in editorial_documents(documents)[:limit]]


def looks_placeholder_summary(text: str) -> bool:
    cleaned = strip_markdown_noise(text).lower()
    if not cleaned or len(cleaned) < 32:
        return True
    placeholders = [
        'items in last ',
        'executive summary',
        'no published briefing yet',
    ]
    return any(cleaned.startswith(item) for item in placeholders)


def narrative_summary_from_documents(documents: List[CommonDocument], limit: int = 1800) -> str:
    parts = []
    for doc in editorial_documents(documents)[:4]:
        summary = cleaned_doc_summary(doc, 220)
        if summary:
            parts.append(f"{doc.title}: {summary}")
    return clean_text(' '.join(parts), limit)


def build_intro(summary: str, documents: List[CommonDocument], edition_label: str) -> str:
    cleaned_summary = strip_markdown_noise(summary, limit=4000)
    if cleaned_summary and not looks_placeholder_summary(cleaned_summary):
        return clean_text(cleaned_summary, 420)
    if documents:
        lead = editorial_documents(documents)[0]
        return clean_text(
            f"{edition_label} is led by {lead.title}. {len(documents)} relevant documents are currently attached to this publication window.",
            420,
        )
    return f"{edition_label} is waiting for the next batch of published material."


def fallback_daily_payload(day_label: str, summary: str, key_points: List[str], documents: List[CommonDocument]) -> dict:
    lead_documents = editorial_documents(documents)
    headline = (lead_documents[0].title if lead_documents else '') or f'{day_label} briefing'
    fallback_summary = strip_markdown_noise(summary)
    if looks_placeholder_summary(fallback_summary):
        fallback_summary = narrative_summary_from_documents(documents, limit=2400)
    return {
        'headline': clean_text(headline, 160),
        'intro': build_intro(summary, documents, day_label),
        'summary': clean_text(fallback_summary or build_intro(summary, documents, day_label), 6200),
        'key_points': compact_key_points(key_points, documents, 4),
        'sections': fallback_sections_from_documents(documents, count=3),
    }


def maybe_ai_daily(day_label: str, summary: str, key_points: List[str], documents: List[CommonDocument]) -> dict:
    fallback = fallback_daily_payload(day_label, summary, key_points, documents)
    if not documents:
        return fallback

    prompt_documents = editorial_documents(documents)[:6]
    corpus = '\n'.join(
        f"[{index}] {doc.title} | {doc.source} | {doc.kind} | {doc.date or 'undated'} | {doc.url} | {cleaned_doc_summary(doc, 280)}"
        for index, doc in enumerate(prompt_documents, start=1)
    )
    prompt = (
        f"Create a premium daily policy briefing for {day_label}. Return JSON only with keys headline, intro, summary, key_points, sections. "
        "Use only the supplied material. Write in precise UK English with a witty, academically literate newspaper-analysis tone. "
        "Be concrete, sceptical, and explanatory. Do not invent facts, dates, figures, institutional positions, motives, or causal claims. "
        "Do not merely rewrite titles. Explain what changed, why it matters, who is affected, and how the items connect across categories. "
        "headline must be 8-18 words and should sound like a strong front-page standfirst, not a filename. "
        "intro must be one paragraph of 130-190 words with a clear thesis for the day. "
        "summary must be 8-10 compact paragraphs totalling roughly 1300-1800 words. It should read like a sharp morning newspaper article for a policy reader, with enough room to synthesize the day properly rather than merely sketching it. "
        "key_points must be an array of exactly 4 short, concrete takeaways without numbering or markdown bullets. "
        "sections must be an array of exactly 3 objects with keys title and body. Each title should usually preserve the original source-document title. "
        "Each body must be 4-6 complete sentences that summarize the document's substance, explain why it matters, and connect it to the wider day. "
        "Every field must end on a complete sentence. Do not trail off, do not end mid-word, and do not use ellipses unless the original source itself requires them. "
        "Avoid markdown headings, asterisks, raw URLs, or references to 'the supplied material', 'the corpus', or filenames.\n\n"
        f"Base summary: {fallback['summary']}\n"
        f"Known key points: {key_points[:4]}\n"
        f"Documents:\n{corpus}"
    )
    response = llm_json(
        'You write compact but substantial editorial briefings for a premium European policy app.',
        prompt,
        prefer_weekly=False,
    )
    if not response:
        return fallback
    return {
        'headline': clean_text(response.get('headline') or fallback['headline'], 160),
        'intro': clean_text(response.get('intro') or fallback['intro'], 900),
        'summary': clean_text(strip_markdown_noise(response.get('summary') or fallback['summary'], limit=16000), 9800),
        'key_points': compact_key_points(response.get('key_points') or fallback['key_points'], documents, 4),
        'sections': [
            {
                'title': clean_text(str(item.get('title') or ''), 120),
                'body': clean_text(strip_markdown_noise(str(item.get('body') or ''), limit=2600), 1500),
            }
            for item in (response.get('sections') or [])
            if isinstance(item, dict)
            and clean_text(str(item.get('title') or ''), 120)
            and clean_text(strip_markdown_noise(str(item.get('body') or ''), limit=2600), 1500)
        ][:3] or fallback['sections'],
    }


def maybe_ai_sunday(title: str, summary: str, key_points: List[str], documents: List[CommonDocument]) -> dict:
    fallback_sections = fallback_sections_from_documents(documents, count=4)
    lead_documents = editorial_documents(documents)
    cleaned_summary = strip_markdown_noise(summary)
    if looks_placeholder_summary(cleaned_summary):
        cleaned_summary = narrative_summary_from_documents(documents, limit=3600)
    fallback = {
        'headline': clean_text((lead_documents[0].title if lead_documents else title), 180),
        'intro': build_intro(summary, documents, title),
        'summary': clean_text(cleaned_summary or build_intro(summary, documents, title), 14000),
        'key_points': compact_key_points(key_points, documents, 5),
        'sections': fallback_sections,
    }
    if not documents:
        return fallback

    prompt_documents = editorial_documents(documents)[:8]
    corpus = '\n'.join(
        f"[{index}] {doc.title} | {doc.source} | {doc.kind} | {doc.date or 'undated'} | {doc.url} | {cleaned_doc_summary(doc, 320)}"
        for index, doc in enumerate(prompt_documents, start=1)
    )
    prompt = (
        f"Create a Sunday morning newspaper-style weekly edition titled '{title}'. Return JSON only with keys headline, intro, summary, key_points, sections. "
        "Use only the supplied material. Write in precise UK English with a polished, witty, critically minded weekend-newspaper tone. "
        "Do not invent facts or smooth over uncertainty. Find the red thread across the week: what kept resurfacing, what shifted, where institutions are converging, and where the pressure points remain. "
        "headline must be 8-18 words. intro must be one paragraph of 140-220 words with a strong thesis. "
        "summary must be 10-14 compact paragraphs totalling roughly 2800-4200 words. It should feel like a smart Sunday front-page analysis, not a list of items, and it should add real synthesis rather than recap alone. "
        "key_points must be an array of exactly 5 concrete takeaways without numbering or markdown bullets. "
        "sections must be an array of exactly 4 objects with keys title and body. Each title should usually preserve the original source-document title. "
        "Each body must summarize the document substance and explain why it matters in the wider weekly pattern. "
        "Every field must end on a complete sentence. Do not trail off, do not end mid-word, and do not use ellipses unless the original source itself requires them. "
        "Avoid markdown headings, bullets in prose, raw URLs, or references to filenames or the corpus. Preserve original document titles when useful so readers can look them up easily.\n\n"
        f"Base summary: {fallback['summary']}\n"
        f"Known key points: {key_points[:5]}\n"
        f"Documents:\n{corpus}"
    )
    response = llm_json(
        'You write elegant weekly front-page briefings for a premium European policy app.',
        prompt,
        prefer_weekly=True,
    )
    if not response:
        return fallback
    sections = []
    for item in response.get('sections') or []:
        if not isinstance(item, dict):
            continue
        title_text = clean_text(str(item.get('title') or ''), 140)
        body_text = clean_text(strip_markdown_noise(str(item.get('body') or ''), limit=2800), 1700)
        if title_text and body_text:
            sections.append({'title': title_text, 'body': body_text})
    return {
        'headline': clean_text(response.get('headline') or fallback['headline'], 180),
        'intro': clean_text(response.get('intro') or fallback['intro'], 1100),
        'summary': clean_text(strip_markdown_noise(response.get('summary') or fallback['summary'], limit=24000), 22000),
        'key_points': compact_key_points(response.get('key_points') or fallback['key_points'], documents, 5),
        'sections': sections[:4] or fallback['sections'],
    }


def preferred_daily_report(reports_day: List[dict]) -> dict | None:
    if not reports_day:
        return None

    def score(report: dict) -> tuple[int, int, int, int]:
        tags = report.get('tags') or []
        key_items = report.get('key_items') or []
        abstract = str(report.get('abstract') or '')
        url = str(report.get('url_html') or '')
        is_daily = 1 if 'daily' in tags else 0
        not_stub_path = 1 if '/reports/daily/' not in url else 0
        non_placeholder = 0 if looks_placeholder_summary(abstract) else 1
        richness = len(key_items) * 10 + min(len(abstract), 600)
        return (is_daily, not_stub_path, non_placeholder, richness)

    return max(reports_day, key=score)


def root_daily_report_metadata(day: str) -> dict | None:
    path = ROOT / 'reports' / f'{day}.md'
    if not path.exists():
        return None
    return {
        'id': f'root-report-{day}',
        'title': f'EUR-Lex Daily Digest — {day}',
        'url': f'https://github.com/{REPO_SLUG}/blob/main/reports/{day}.md',
    }


def daily_briefings(posts: List[dict], reports: List[dict], timeline: dict, digest: dict) -> dict:
    days = set()
    for post in posts:
        value = iso_day(post.get('added'))
        if is_live_day(value):
            days.add(value)
    for report in reports:
        value = iso_day(report.get('date'))
        if is_live_day(value):
            days.add(value)
    for event in timeline.get('events', []):
        value = iso_day(event.get('date'))
        if is_live_day(value):
            days.add(value)
    digest_day = iso_day(digest.get('generated_at'))
    if is_live_day(digest_day):
        days.add(digest_day)
    for item in digest.get('items', []):
        value = iso_day(item.get('published_date'))
        if is_live_day(value):
            days.add(value)

    ordered_days = sorted(days, reverse=True)[:MAX_BRIEFING_DAYS]
    results = []

    for index, day in enumerate(ordered_days):
        posts_day = [post_to_common(p) for p in posts if iso_day(p.get('added')) == day]
        reports_day = [r for r in reports if iso_day(r.get('date')) == day]
        timeline_day = [timeline_to_common(e) for e in timeline.get('events', []) if iso_day(e.get('date')) == day]
        digest_items = [digest_to_common(i) for i in digest.get('items', []) if iso_day(i.get('published_date')) == day]
        if not digest_items and digest_day == day:
            digest_items = [digest_to_common(i) for i in digest.get('items', [])[:4]]

        daily_report = preferred_daily_report(reports_day)
        primary_report = report_to_common(daily_report) if daily_report else None
        report_is_useful = bool(
            primary_report
            and ((daily_report or {}).get('key_items') or cleaned_doc_summary(primary_report, 260))
            and not looks_placeholder_summary((daily_report or {}).get('abstract') or '')
        )

        important_pool = unique_documents(
            ([primary_report] if (primary_report and report_is_useful) else []) + digest_items + posts_day + timeline_day
        )
        if not important_pool and primary_report:
            important_pool = [primary_report]
        important = important_pool[:5]
        related = unique_documents(posts_day + digest_items + timeline_day)[1:7]
        categories = collect_categories(important + related)

        report_key_points = list((daily_report or {}).get('key_items') or [])
        fallback_key_points = report_key_points or [doc.title for doc in important[:4]]
        summary = clean_text(
            strip_markdown_noise((daily_report or {}).get('abstract') or ' '.join(cleaned_doc_summary(doc, 240) for doc in important[:3] if doc.summary)),
            620,
        )

        dt_value = date.fromisoformat(day)
        day_label = dt_value.strftime('%A %-d %B %Y') if os.name != 'nt' else dt_value.strftime('%A %#d %B %Y')
        editorial = maybe_ai_daily(day_label, summary, fallback_key_points, important)
        if index >= MAX_AI_DAILY_DAYS:
            editorial = fallback_daily_payload(day_label, summary, fallback_key_points, important)

        report_payload = (
            {
                'id': daily_report.get('id'),
                'title': daily_report.get('display_title') or daily_report.get('title'),
                'url': daily_report.get('url_html'),
            }
            if daily_report
            else None
        )
        root_report = root_daily_report_metadata(day)
        if root_report and (report_payload is None or '/reports/daily/' in str(report_payload.get('url') or '')):
            report_payload = root_report

        results.append(
            {
                'date': day,
                'title': day_label,
                'headline': editorial['headline'],
                'intro': editorial['intro'],
                'summary': editorial['summary'],
                'key_points': editorial['key_points'],
                'sections': editorial['sections'],
                'categories': categories,
                'important_documents': [doc.to_payload() for doc in important],
                'related_documents': [doc.to_payload() for doc in related],
                'report': report_payload,
                'signal_counts': {
                    'posts': len(posts_day),
                    'reports': len(reports_day),
                    'digest_items': len(digest_items),
                    'timeline_events': len(timeline_day),
                },
            }
        )

    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'latest_date': results[0]['date'] if results else '',
        'items': results,
    }
    return payload


def sunday_editions(posts: List[dict], reports: List[dict], timeline: dict) -> dict:
    posts_by_day: defaultdict[str, List[CommonDocument]] = defaultdict(list)
    for post in posts:
        day = iso_day(post.get('added'))
        if is_live_day(day):
            posts_by_day[day].append(post_to_common(post))

    timeline_by_day: defaultdict[str, List[CommonDocument]] = defaultdict(list)
    for event in timeline.get('events', []):
        day = iso_day(event.get('date'))
        if is_live_day(day):
            timeline_by_day[day].append(timeline_to_common(event))

    reports_by_day: defaultdict[str, List[CommonDocument]] = defaultdict(list)
    for report in reports:
        day = iso_day(report.get('date'))
        if is_live_day(day):
            reports_by_day[day].append(report_to_common(report))

    available_days = sorted(set(posts_by_day) | set(timeline_by_day) | set(reports_by_day), reverse=True)
    available_sundays = sorted(
        {
            date.fromisoformat(day)
            for day in available_days
            if date.fromisoformat(day).weekday() == 6
        },
        reverse=True,
    )[:MAX_SUNDAY_EDITIONS]

    weekly_reports = [r for r in reports if 'weekly' in (r.get('tags') or []) and is_live_day(iso_day(r.get('date')))]
    weekly_reports.sort(key=lambda item: item.get('date') or '', reverse=True)
    reports_by_week_end = {
        date.fromisoformat(iso_day(report.get('date')) or report['date']): report
        for report in weekly_reports
    }

    editions = []
    for index, end_day in enumerate(available_sundays):
        report = reports_by_week_end.get(end_day)
        start_day = end_day - timedelta(days=6)
        week_days = {(start_day + timedelta(days=offset)).isoformat() for offset in range(7)}
        documents = []
        for day in sorted(week_days, reverse=True):
            documents.extend(reports_by_day.get(day, []))
            documents.extend(posts_by_day.get(day, []))
            documents.extend(timeline_by_day.get(day, []))

        anchor_documents = []
        if report:
            anchor_documents.append(report_to_common(report))

        weekly_editorial_pool = editorial_documents(documents)
        important = unique_documents(anchor_documents + weekly_editorial_pool)[:8]
        if not important:
            important = unique_documents(documents)[:8]
        related = unique_documents(weekly_editorial_pool)[1:7]
        categories = collect_categories(important + related)

        if report:
            fallback_key_points = list(report.get('key_items') or []) or [doc.title for doc in important[:5]]
            summary_seed = report.get('abstract') or ' '.join(cleaned_doc_summary(doc, 240) for doc in important[:4] if doc.summary)
        else:
            fallback_key_points = [doc.title for doc in important[:5]]
            summary_seed = ' '.join(cleaned_doc_summary(doc, 240) for doc in important[:4] if doc.summary)

        summary = clean_text(strip_markdown_noise(summary_seed), 860)
        title = f"Sunday Edition — {start_day.isoformat()} to {end_day.isoformat()}"
        editorial = maybe_ai_sunday(title, summary, fallback_key_points, important)
        if index >= MAX_AI_SUNDAY_EDITIONS:
            editorial = {
                'headline': clean_text(title, 180),
                'intro': build_intro(summary, important, title),
                'summary': strip_markdown_noise(summary),
                'key_points': compact_key_points(fallback_key_points, important, 5),
                'sections': fallback_sections_from_documents(important, count=4),
            }

        edition = {
            'edition_date': end_day.isoformat(),
            'week_start': start_day.isoformat(),
            'week_end': end_day.isoformat(),
            'title': title,
            'headline': editorial['headline'],
            'intro': editorial['intro'],
            'summary': editorial['summary'],
            'key_points': editorial['key_points'],
            'sections': editorial['sections'],
            'categories': categories,
            'important_documents': [doc.to_payload() for doc in important[:5]],
            'related_documents': [doc.to_payload() for doc in related],
            'report': (
                {
                    'id': report.get('id'),
                    'title': report.get('display_title') or report.get('title'),
                    'url': report.get('url_html'),
                }
                if report
                else None
            ),
        }
        if not any(existing['week_end'] == edition['week_end'] for existing in editions):
            editions.append(edition)

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'latest_end_date': editions[0]['week_end'] if editions else '',
        'items': editions,
    }


def load_source_catalog() -> dict:
    domain_cfg = load_yaml(SOURCES_YAML) if SOURCES_YAML.exists() else {}
    domains = domain_cfg.get('domains', {}) if isinstance(domain_cfg, dict) else {}
    feed_urls = (domain_cfg.get('feeds', []) if isinstance(domain_cfg, dict) else []) or []
    custom_payload = load_json(CUSTOM_FEEDS_JSON, {'feeds': []})
    custom_feeds = custom_payload.get('feeds', []) if isinstance(custom_payload, dict) else []
    v2_payload = load_yaml(SOURCES_V2_YAML) if SOURCES_V2_YAML.exists() else {}
    v2_sources = v2_payload.get('sources', []) if isinstance(v2_payload, dict) else []

    entries = []
    for feed in feed_urls:
        host = domain_name(feed)
        display = (domains.get(host, {}) or {}).get('source') or host
        entries.append(
            {
                'source_id': host,
                'name': display,
                'url': feed,
                'kind': 'rss',
                'origin': 'built_in',
                'enabled': True,
            }
        )

    for item in v2_sources:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get('source_id') or item.get('name') or item.get('base_url') or '').strip()
        base_url = str(item.get('base_url') or item.get('url') or '').strip()
        if not source_id or not base_url:
            continue
        entries.append(
            {
                'source_id': source_id,
                'name': title_case_source(source_id),
                'url': base_url,
                'kind': item.get('type') or 'html_list',
                'origin': 'built_in',
                'enabled': bool(item.get('enabled', True)),
            }
        )

    for item in custom_feeds:
        if isinstance(item, str):
            url = item.strip()
            name = domain_name(url)
            source_id = name
        elif isinstance(item, dict):
            url = str(item.get('url') or '').strip()
            name = str(item.get('name') or domain_name(url)).strip()
            source_id = str(item.get('source_id') or name).strip()
        else:
            continue
        if not url:
            continue
        entries.append(
            {
                'source_id': source_id,
                'name': name,
                'url': url,
                'kind': 'rss',
                'origin': 'custom',
                'enabled': True,
            }
        )

    deduped = {}
    for entry in entries:
        deduped[(entry['source_id'], entry['url'])] = entry
    final_entries = sorted(deduped.values(), key=lambda item: (item['origin'], item['name'].lower(), item['url']))

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'counts': {
            'total': len(final_entries),
            'custom': sum(1 for item in final_entries if item['origin'] == 'custom'),
            'built_in': sum(1 for item in final_entries if item['origin'] == 'built_in'),
        },
        'items': final_entries,
        'sources': final_entries,
    }


def build_library_catalog(repo: str) -> dict:
    items_by_key: dict[str, dict] = {}
    for directory in LIBRARY_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob('*')):
            if not path.is_file() or path.suffix.lower() not in LIBRARY_EXTENSIONS:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel.endswith('.gitkeep'):
                continue
            items_by_key[rel] = {
                'id': rel,
                'title': title_case_source(path.stem),
                'path': rel,
                'kind': path.suffix.lower().lstrip('.'),
                'size_bytes': path.stat().st_size,
                'raw_url': f'https://raw.githubusercontent.com/{repo}/main/{rel}',
                'source_type': 'upload',
                'tags': [],
                'status': 'ready',
                'summary': '',
                'updated_at': '',
            }

    registry = load_json(LIBRARY_STATE_JSON, {'items': []})
    for item in registry.get('items', []) if isinstance(registry, dict) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('id') or item.get('repo_path') or item.get('source_url') or '').strip()
        if not key:
            continue
        path = str(item.get('repo_path') or '').strip()
        raw_url = str(item.get('raw_url') or item.get('source_url') or '').strip()
        items_by_key[key] = {
            'id': key,
            'title': str(item.get('title') or title_case_source(pathlib.Path(path or raw_url or key).stem)),
            'path': path or None,
            'kind': str(item.get('kind') or pathlib.Path(path).suffix.lstrip('.') or 'url'),
            'size_bytes': int(item.get('size_bytes') or 0),
            'raw_url': raw_url,
            'source_url': str(item.get('source_url') or '') or None,
            'source_type': str(item.get('source_type') or ('url' if item.get('source_url') else 'upload')),
            'tags': list(item.get('tags') or []),
            'status': str(item.get('status') or 'ready'),
            'summary': clean_text(str(item.get('summary') or ''), 800),
            'updated_at': str(item.get('updated_at') or ''),
        }

    items = sorted(items_by_key.values(), key=lambda item: ((item.get('updated_at') or ''), item.get('title') or ''), reverse=True)
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'count': len(items),
        'items': items,
        'documents': items,
    }


def main() -> int:
    repo = os.getenv('GITHUB_REPOSITORY', 'DanielTNL/EURLex')
    posts = load_json(POSTS_JSON, [])
    reports = load_json(REPORTS_JSON, [])
    timeline = load_json(TIMELINE_JSON, {'events': []})
    digest = load_json(DIGEST_LATEST_JSON, {'items': []})

    briefing_payload = daily_briefings(posts, reports, timeline, digest)
    sunday_payload = sunday_editions(posts, reports, timeline)
    sources_payload = load_source_catalog()
    library_payload = build_library_catalog(repo)

    write_json(BRIEFINGS_JSON, briefing_payload)
    write_json(BRIEFING_LATEST_JSON, briefing_payload['items'][0] if briefing_payload['items'] else {})
    write_json(SUNDAY_EDITIONS_JSON, sunday_payload)
    write_json(SUNDAY_EDITION_LATEST_JSON, sunday_payload['items'][0] if sunday_payload['items'] else {})
    write_json(SOURCES_JSON, sources_payload)
    write_json(LIBRARY_JSON, library_payload)
    write_json(
        BACKEND_STATUS_JSON,
        {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'briefings': len(briefing_payload['items']),
            'sunday_editions': len(sunday_payload['items']),
            'sources': sources_payload['counts']['total'],
            'library_documents': library_payload['count'],
        },
    )

    print(
        json.dumps(
            {
                'briefings': str(BRIEFINGS_JSON),
                'sunday_editions': str(SUNDAY_EDITIONS_JSON),
                'sources': str(SOURCES_JSON),
                'library': str(LIBRARY_JSON),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
