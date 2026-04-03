#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
from typing import Dict, List, Sequence, Tuple

from pydub import AudioSegment

from weekly_main import call_llm, openai_client, synthesize_tts_chunked

ROOT = pathlib.Path(__file__).parent
REPORTS_ROOT = ROOT / "reports"
MONTHLY_AUDIO_DIR = REPORTS_ROOT / "audio" / "monthly"
REQUEST_AUDIO_DIR = REPORTS_ROOT / "audio" / "requests"

MONTHLY_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
REQUEST_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SPEAKER_A = "Elena"
SPEAKER_B = "Marcus"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build audio overviews from report text.")
    sub = parser.add_subparsers(dest="mode", required=True)

    monthly = sub.add_parser("monthly", help="Create the monthly roundtable audio.")
    monthly.add_argument("--month", help="Month to cover in YYYY-MM format. Defaults to previous month.")

    weekly = sub.add_parser("weekly-request", help="Create a requested weekly audio brief.")
    weekly.add_argument("--end-date", help="End date in YYYY-MM-DD format. Defaults to today UTC.")
    weekly.add_argument("--prompt-hint", default="", help="Optional extra angle for the briefing.")

    return parser.parse_args()


def parse_day(raw: str) -> dt.date:
    return dt.date.fromisoformat(raw)


def month_window(month: str | None) -> Tuple[dt.date, dt.date]:
    if month:
        start = dt.date.fromisoformat(f"{month}-01")
    else:
        today = dt.datetime.now(dt.timezone.utc).date()
        first_of_this_month = today.replace(day=1)
        previous_month_end = first_of_this_month - dt.timedelta(days=1)
        start = previous_month_end.replace(day=1)

    if start.month == 12:
        next_month = dt.date(start.year + 1, 1, 1)
    else:
        next_month = dt.date(start.year, start.month + 1, 1)

    end = next_month - dt.timedelta(days=1)
    return start, end


def weekly_window(raw_end_date: str | None) -> Tuple[dt.date, dt.date]:
    end = parse_day(raw_end_date) if raw_end_date else dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=6)
    return start, end


def report_candidates() -> List[pathlib.Path]:
    candidates: List[pathlib.Path] = []
    for folder in [REPORTS_ROOT / "daily", REPORTS_ROOT / "weekly", REPORTS_ROOT]:
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if "reports/audio/" in path.as_posix():
                continue
            if path.suffix.lower() not in {".txt", ".md", ".markdown"}:
                continue
            candidates.append(path)
    return sorted(set(candidates))


def extract_date_from_path(path: pathlib.Path) -> dt.date | None:
    match = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})", path.as_posix())
    if not match:
        return None
    return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return "Untitled report"


def normalise_text(text: str, limit: int = 2200) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def load_reports_between(start: dt.date, end: dt.date) -> List[Dict[str, str]]:
    reports: List[Dict[str, str]] = []
    for path in report_candidates():
        report_date = extract_date_from_path(path)
        if report_date is None or not (start <= report_date <= end):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        reports.append(
            {
                "date": report_date.isoformat(),
                "title": first_nonempty_line(text),
                "body": normalise_text(text),
                "path": path.relative_to(ROOT).as_posix(),
            }
        )
    reports.sort(key=lambda item: item["date"], reverse=True)
    return reports


def build_monthly_script(reports: Sequence[Dict[str, str]], start: dt.date, end: dt.date) -> str:
    if not reports:
        raise RuntimeError("No report text was found for the requested monthly window.")

    corpus = "\n\n".join(
        f"[{idx}] {report['date']} | {report['title']}\n{report['body']}"
        for idx, report in enumerate(reports[:10], start=1)
    )

    system = (
        "You write premium podcast scripts about European policy. "
        "Write only dialogue lines for two speakers named Elena and Marcus. "
        "Each line must start with either 'Elena:' or 'Marcus:'. "
        "Make it sound like a sharp, critical monthly roundtable between two different people. "
        "Keep the tone intelligent, conversational, and analytical. Avoid stage directions."
    )
    user = (
        f"Create a monthly roundtable script covering {start.isoformat()} to {end.isoformat()}.\n"
        "Structure:\n"
        "1. A sharp opening exchange about the month's dominant theme.\n"
        "2. Discussion of the most important developments.\n"
        "3. Critical disagreement or challenge between the speakers.\n"
        "4. Closing section on what to watch next month.\n\n"
        "Use the report corpus below as the factual basis:\n"
        f"{corpus}\n\n"
        "Aim for roughly 10-12 minutes of audio."
    )
    return call_llm(system, user, max_tokens=2600)


def build_weekly_script(reports: Sequence[Dict[str, str]], start: dt.date, end: dt.date, prompt_hint: str) -> str:
    if not reports:
        raise RuntimeError("No report text was found for the requested weekly window.")

    corpus = "\n\n".join(
        f"[{idx}] {report['date']} | {report['title']}\n{report['body']}"
        for idx, report in enumerate(reports[:8], start=1)
    )

    extra_angle = f"\nOptional angle to emphasize: {prompt_hint.strip()}\n" if prompt_hint.strip() else ""
    system = (
        "You write concise voice briefings about European policy. "
        "Write plain narration in polished paragraphs with no markdown."
    )
    user = (
        f"Create a weekly audio briefing for {start.isoformat()} to {end.isoformat()}."
        f"{extra_angle}"
        "\nOpen with the biggest theme of the week, then summarise the most important developments, "
        "and finish with what to watch next. Aim for 5-7 minutes of audio.\n\n"
        f"Use this report corpus:\n{corpus}"
    )
    return call_llm(system, user, max_tokens=1800)


def split_dialogue(script: str) -> List[Tuple[str, str]]:
    turns: List[Tuple[str, str]] = []
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line:
            speaker, content = line.split(":", 1)
            speaker = speaker.strip()
            content = content.strip()
            if speaker in {SPEAKER_A, SPEAKER_B} and content:
                turns.append((speaker, content))
                continue
        turns.append((SPEAKER_A, line))
    return turns


def synthesize_dialogue(script: str, out_mp3: pathlib.Path, model: str, voices: Dict[str, str]) -> pathlib.Path:
    client = openai_client()
    temp_dir = ROOT / "tmp_audio_dialogue"
    temp_dir.mkdir(parents=True, exist_ok=True)

    part_files: List[pathlib.Path] = []
    for index, (speaker, content) in enumerate(split_dialogue(script), start=1):
        voice = voices.get(speaker, voices[SPEAKER_A])
        part_path = temp_dir / f"dialogue_{index:03d}.mp3"
        with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=content,
        ) as response:
            response.stream_to_file(str(part_path))
        part_files.append(part_path)

    merged: AudioSegment | None = None
    pause = AudioSegment.silent(duration=220)
    for part_path in part_files:
        segment = AudioSegment.from_file(part_path, format="mp3")
        merged = segment if merged is None else (merged + pause + segment)

    if merged is None:
        raise RuntimeError("No dialogue audio segments were generated.")

    merged.export(out_mp3, format="mp3")
    return out_mp3


def write_text_mirror(path: pathlib.Path, title: str, script: str, reports: Sequence[Dict[str, str]]) -> None:
    references = "\n".join(f"- {item['date']} | {item['title']} | {item['path']}" for item in reports[:12])
    path.write_text(
        f"{title}\n\n{script.strip()}\n\nReferences\n{references}\n",
        encoding="utf-8",
    )


def monthly_title(start: dt.date) -> str:
    return f"Monthly Roundtable — EU Policy — {start.strftime('%B %Y')}"


def weekly_title(start: dt.date, end: dt.date) -> str:
    return f"Requested Weekly Voice Brief — {start.isoformat()} to {end.isoformat()}"


def main() -> int:
    args = parse_args()
    tts_model = (os.environ.get("OPENAI_TTS_MODEL") or "gpt-4o-mini-tts").strip()

    if args.mode == "monthly":
        start, end = month_window(args.month)
        reports = load_reports_between(start, end)
        title = monthly_title(start)
        script = build_monthly_script(reports, start, end)

        base_name = f"{start.strftime('%Y-%m')}-roundtable"
        txt_path = MONTHLY_AUDIO_DIR / f"{base_name}.txt"
        mp3_path = MONTHLY_AUDIO_DIR / f"{base_name}.mp3"

        voices = {
            SPEAKER_A: (os.environ.get("OPENAI_TTS_VOICE_A") or "alloy").strip(),
            SPEAKER_B: (os.environ.get("OPENAI_TTS_VOICE_B") or "verse").strip(),
        }
        synthesize_dialogue(script, mp3_path, tts_model, voices)
        write_text_mirror(txt_path, title, script, reports)
        print(f"[done] wrote {txt_path} and {mp3_path}")
        return 0

    start, end = weekly_window(args.end_date)
    reports = load_reports_between(start, end)
    title = weekly_title(start, end)
    script = build_weekly_script(reports, start, end, args.prompt_hint)

    base_name = f"{end.isoformat()}-weekly-request"
    txt_path = REQUEST_AUDIO_DIR / f"{base_name}.txt"
    mp3_path = REQUEST_AUDIO_DIR / f"{base_name}.mp3"

    write_text_mirror(txt_path, title, script, reports)
    synthesize_tts_chunked(script, mp3_path, tts_model, (os.environ.get("OPENAI_TTS_VOICE") or "alloy").strip())
    print(f"[done] wrote {txt_path} and {mp3_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
