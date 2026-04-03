# EURLex Mobile

Native SwiftUI scaffold for browsing the live EUR-Lex feed, reports, digest output, and weekly audio briefings that are already published by this repository.

## What this app reads

The app uses the public GitHub Pages payloads that `DanielTNL/EURLex` already publishes:

- `https://danieltnl.github.io/EURLex/data/posts.json`
- `https://danieltnl.github.io/EURLex/data/reports.json`
- `https://danieltnl.github.io/EURLex/data/audio.json`
- `https://danieltnl.github.io/EURLex/data/timeline-latest.json`
- `https://danieltnl.github.io/EURLex/digests/latest.json`

That keeps the iOS app aligned with the repo's existing content pipeline instead of duplicating scraper logic on-device.

## Included

- `project.yml` for XcodeGen-based project generation
- SwiftUI tab shell for `Today`, `Feed`, `Reports`, and `Audio`
- Async data client for the published JSON feeds
- Local search and lightweight source/category filtering
- In-app Safari presentation for article and report links
- Small client-side dedupe pass for repeated upstream items

## Current limitation in this workspace

This machine does not currently have the full Xcode app toolchain installed, so the scaffold could not be compiled or run here. The source tree is ready for generation once Xcode is available.

## Suggested next step once Xcode is installed

1. Generate the Xcode project from `project.yml` with XcodeGen.
2. Open the generated project in Xcode.
3. Run on an iPhone simulator and tune the visual hierarchy with real device testing.
