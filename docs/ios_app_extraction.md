# EURLex to iOS Extraction Notes

Generated after inspecting `DanielTNL/EURLex` on the `main` branch on 2026-04-03.

## What the repository actually contains

This repo is not only an EUR-Lex mailer. It has grown into a small content platform with these layers:

- `main.py`: daily feed collection, ranking, summarisation, Google Doc creation, and email delivery.
- `weekly_main.py`: weekly long-form analysis plus optional MP3 generation.
- `config.yaml`: monitored RSS feeds, keywords, ranking, taxonomy, timezone, and delivery settings.
- `sources_v2.yaml`: second-generation HTML source scraping definitions.
- `scripts/build_site_data.py`: publishes frontend payloads to `docs/data/`.
- `docs/`: a static GitHub Pages site and payload archive.
- `api/chat.js`: lightweight AI/Q&A endpoint over the published JSON.

## Best mobile data contract

For an iOS app, the cleanest reusable layer is the already-published GitHub Pages JSON, not the raw ingest scripts:

- `data/posts.json`: live document feed cards
- `data/reports.json`: daily and weekly report metadata
- `data/audio.json`: MP3 briefings and Drive link
- `data/timeline-latest.json`: current timeline window
- `digests/latest.json`: latest daily digest summary

These endpoints were reachable on 2026-04-03 and returned `200` responses from GitHub Pages.

## Information architecture extracted for mobile

Recommended app tabs:

- `Today`: latest digest window, report count, recent documents, timeline highlights
- `Feed`: searchable and filterable document stream from `posts.json`
- `Reports`: daily and weekly report archive with key items
- `Audio`: weekly MP3 briefings and Drive handoff

## Issues discovered during repo inspection

These are worth fixing in the pipeline, but the iOS scaffold already guards against some of them with light client-side dedupe:

- `docs/digests/2025-08-17.json` contains duplicate entries.
- `docs/digests/2025-08-17.json` also contains at least one corrupted `summary_150w` payload.
- `docs/digests/2025-12-08.json` shows a likely source-label mismatch (`source_id: investeu_news` for an Airbus URL).
- `docs/index.html` has malformed markup with duplicated body/script structure.
- Full Xcode was not installed in this workspace, so the iOS build could not be compiled here.

## Files added for the mobile app scaffold

- `iOSApp/project.yml`
- `iOSApp/EURLexMobile/...` SwiftUI source tree
- `iOSApp/README.md`

## Why this approach

Using the repo's published JSON lets the app stay thin and reliable on-device:

- no feed parsing on the phone
- no secret keys in the app
- direct reuse of the current publishing workflow
- easy future swap to a dedicated API without changing the whole UI model
