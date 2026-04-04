#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader
from trafilatura import extract as trafilatura_extract
from trafilatura import fetch_url

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / 'state' / 'library_documents.json'

MAX_TEXT_CHARS = 20_000
SUMMARY_CHARS = 900


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {'updated_at': '', 'items': []}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {'updated_at': '', 'items': []}
    if not isinstance(payload, dict):
        return {'updated_at': '', 'items': []}
    payload.setdefault('items', [])
    payload.setdefault('updated_at', '')
    return payload


def save_state(payload: dict[str, Any]) -> None:
    payload['updated_at'] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def clean_text(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    compact = ' '.join(str(text or '').split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip(' ,;:-') + '…'


def summarize(text: str) -> str:
    return clean_text(text, SUMMARY_CHARS)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or '', 'html.parser')
    for bad in soup(['script', 'style']):
        bad.decompose()
    return clean_text(soup.get_text(' ', strip=True))


def extract_url_text(url: str) -> str:
    downloaded = fetch_url(url)
    extracted = trafilatura_extract(downloaded or '', include_comments=False, include_tables=False) if downloaded else ''
    if extracted:
        return clean_text(extracted)
    try:
        import requests

        response = requests.get(url, timeout=25, headers={'User-Agent': 'eurlex-backend/1.0'})
        response.raise_for_status()
        return html_to_text(response.text)
    except Exception:
        return ''


def extract_pdf_text(path: pathlib.Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or '')
        except Exception:
            continue
        if sum(len(part) for part in parts) >= MAX_TEXT_CHARS:
            break
    return clean_text('\n'.join(parts))


def extract_docx_text(path: pathlib.Path) -> str:
    document = Document(str(path))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    return clean_text('\n'.join(parts))


def extract_local_text(path: pathlib.Path, kind: str) -> str:
    if not path.exists():
        return ''

    lower = kind.lower()
    try:
        if lower in {'txt', 'md', 'markdown'}:
            return clean_text(path.read_text(encoding='utf-8', errors='ignore'))
        if lower == 'pdf':
            return extract_pdf_text(path)
        if lower == 'docx':
            return extract_docx_text(path)
    except Exception:
        return ''
    return ''


def process_item(item: dict[str, Any], repository: str, ref: str) -> dict[str, Any]:
    kind = str(item.get('kind') or '').lower()
    repo_path = str(item.get('repo_path') or '').strip()
    source_url = str(item.get('source_url') or '').strip()

    text = clean_text(item.get('extracted_text') or '', MAX_TEXT_CHARS)
    error = None

    if source_url:
        fetched = extract_url_text(source_url)
        if fetched:
            text = fetched
        elif not text:
            error = 'Unable to extract text from source URL.'

    if repo_path:
        local_path = ROOT / repo_path
        extracted = extract_local_text(local_path, kind or local_path.suffix.lstrip('.'))
        if extracted:
            text = extracted
        elif not text and local_path.exists():
            error = f'Unsupported or unreadable file type: {kind or local_path.suffix}'
        elif not local_path.exists():
            error = f'Missing repository file: {repo_path}'

        item['size_bytes'] = local_path.stat().st_size if local_path.exists() else int(item.get('size_bytes') or 0)
        item['raw_url'] = f'https://raw.githubusercontent.com/{repository}/{ref}/{repo_path}'

    item['status'] = 'ready' if text else 'pending_processing'
    item['summary'] = summarize(text or item.get('summary') or item.get('source_url') or '')
    item['extracted_text'] = text
    item['updated_at'] = datetime.now(timezone.utc).isoformat()
    item['error'] = error
    return item


def main() -> int:
    state = load_state()
    repository = os.getenv('GITHUB_REPOSITORY', 'DanielTNL/EURLex')
    ref = os.getenv('GITHUB_REF_NAME', 'main')

    items = [item for item in state.get('items', []) if isinstance(item, dict)]
    processed = [process_item(item, repository, ref) for item in items]
    state['items'] = processed
    save_state(state)

    ready = sum(1 for item in processed if item.get('status') == 'ready')
    print(json.dumps({'processed': len(processed), 'ready': ready}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
