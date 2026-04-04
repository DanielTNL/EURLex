#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DATA = ROOT / "docs" / "data"


def load_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Failed to parse {path}: {exc}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_collection(name: str, payload: Any, item_key: str) -> int:
    require(isinstance(payload, dict), f"{name} must be a JSON object")
    require("generated_at" in payload, f"{name} is missing generated_at")
    items = payload.get(item_key)
    require(isinstance(items, list), f"{name} must expose a list at {item_key}")
    return len(items)


def main() -> int:
    posts = load_json(DOCS_DATA / "posts.json")
    reports = load_json(DOCS_DATA / "reports.json")
    audio = load_json(DOCS_DATA / "audio.json")
    briefings = load_json(DOCS_DATA / "briefings.json")
    briefing_latest = load_json(DOCS_DATA / "briefing-latest.json")
    sunday_editions = load_json(DOCS_DATA / "sunday-editions.json")
    sunday_latest = load_json(DOCS_DATA / "sunday-edition-latest.json")
    sources = load_json(DOCS_DATA / "sources.json")
    library = load_json(DOCS_DATA / "library.json")
    status = load_json(DOCS_DATA / "backend-status.json")

    require(isinstance(posts, list), "posts.json must be a JSON array")
    require(isinstance(reports, list), "reports.json must be a JSON array")
    require(isinstance(audio, dict) and isinstance(audio.get("items"), list), "audio.json must expose items[]")

    briefing_count = validate_collection("briefings.json", briefings, "items")
    sunday_count = validate_collection("sunday-editions.json", sunday_editions, "items")
    source_count = validate_collection("sources.json", sources, "items")
    library_count = validate_collection("library.json", library, "items")

    require(isinstance(briefing_latest, dict), "briefing-latest.json must be a JSON object")
    require(isinstance(sunday_latest, dict), "sunday-edition-latest.json must be a JSON object")
    require(isinstance(status, dict), "backend-status.json must be a JSON object")

    if briefing_count:
        require(bool(briefing_latest.get("date")), "briefing-latest.json is missing date")
        require(bool(briefing_latest.get("headline")), "briefing-latest.json is missing headline")
        require(isinstance(briefing_latest.get("sections"), list), "briefing-latest.json must expose sections")
        require(isinstance(briefing_latest.get("important_documents"), list), "briefing-latest.json must expose important_documents")
    if sunday_count:
        require(bool(sunday_latest.get("week_end")), "sunday-edition-latest.json is missing week_end")
        require(bool(sunday_latest.get("headline")), "sunday-edition-latest.json is missing headline")
        require(isinstance(sunday_latest.get("sections"), list), "sunday-edition-latest.json must expose sections")

    require(status.get("briefings") == briefing_count, "backend-status.json briefing count mismatch")
    require(status.get("sunday_editions") == sunday_count, "backend-status.json sunday edition count mismatch")
    require(status.get("sources") == source_count, "backend-status.json source count mismatch")
    require(status.get("library_documents") == library_count, "backend-status.json library count mismatch")

    print(
        json.dumps(
            {
                "posts": len(posts),
                "reports": len(reports),
                "audio_items": len(audio.get("items", [])),
                "briefings": briefing_count,
                "sunday_editions": sunday_count,
                "sources": source_count,
                "library_documents": library_count,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
