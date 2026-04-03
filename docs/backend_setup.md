# EURLex Backend Setup

This project is now set up for a **GitHub-first** backend:

- **GitHub Actions** remains the scheduled engine for discovery, summaries, reports, timeline updates, and audio generation.
- **GitHub Pages** remains the published data source for the app feed.
- A **tiny serverless runtime** is used only for the interactive features GitHub cannot host directly:
  - AI chat
  - weekly audio requests from the app
  - adding custom RSS/Atom feeds from the app

## Why GitHub cannot do this alone

GitHub is excellent for:

- scheduled automation
- repo-backed storage
- static publishing

But it does **not** provide an always-on private API runtime for a mobile app. That means the `Ask AI` tab and source-management actions still need a small deployed API layer.

This repo already includes that layer in the `api/` folder.

## Recommended deploy path

Use **Vercel**, connected to this GitHub repo.

That keeps the system GitHub-backed while making the interactive app features work.

## What is already included

- `api/chat.js`
  - grounded chat over the published EURLex corpus
  - optional live remote fetch when the app enables web mode
- `api/audio-request.js`
  - triggers the GitHub workflow that creates a requested weekly audio overview
- `api/sources.js`
  - stores custom RSS/Atom feeds in `state/custom_feeds.json`
- `api/health.js`
  - simple deployment health check
- `api/_lib/github.js`
  - GitHub API helper for repo-backed writes and workflow dispatches

## Required environment variables

Set these in your deployment platform:

- `OPENAI_API_KEY`
  - required for live AI answers
- `GITHUB_REPOSITORY`
  - example: `DanielTNL/EURLex`
- `GITHUB_BACKEND_TOKEN`
  - a fine-grained GitHub token with:
    - `Contents: Read and write`
    - `Actions: Read and write`
    - `Metadata: Read`
- `DATA_BASE`
  - set to `https://danieltnl.github.io/EURLex/data`
- `OPENAI_MODEL_CHAT`
  - optional, default is `gpt-4o-mini`

## One-time deployment steps

1. Sign in to [Vercel](https://vercel.com/) with GitHub.
2. Import the `DanielTNL/EURLex` repository.
3. Leave the project root as the repo root.
4. Add the environment variables listed above.
5. Deploy.
6. Copy the production URL, for example:
   - `https://eurlex-app-backend.vercel.app`

## App configuration

In the iOS app Info.plist:

- `EURLexPublishedDataBaseURL`
  - leave as `https://danieltnl.github.io/EURLex/`
- `EURLexBackendBaseURL`
  - set this to your deployed backend URL, for example:
    - `https://eurlex-app-backend.vercel.app/`

## GitHub token creation

Create a fine-grained token in GitHub:

1. GitHub -> Settings
2. Developer settings
3. Personal access tokens
4. Fine-grained tokens
5. Generate a new token
6. Restrict it to the `EURLex` repo
7. Grant:
   - `Contents: Read and write`
   - `Actions: Read and write`
   - `Metadata: Read`

Then paste that token into the deployment env var:

- `GITHUB_BACKEND_TOKEN`

## What works after deployment

- `Ask AI` in the app returns real answers
- `Web on` mode enriches answers with live fetches from linked sources
- asking for a weekly voice overview queues the GitHub workflow
- custom RSS/Atom feeds can be added through the backend and included by the GitHub pipeline

## What still needs a later phase

- full document uploads for PDF/DOCX storage and retrieval
- true open-web search across the broader internet
  - for that, add a dedicated search provider later such as Tavily, Exa, or SerpAPI

## Health check

After deployment, open:

- `/api/health`

It should return JSON showing whether:

- OpenAI is configured
- GitHub write access is configured
- the correct repository is targeted
