# Source Of Truth

PathScout OSS is local-only software. The source of truth is the user's checkout and local files, not a PathScout service.

## What Is Stored Locally

- Config lives under `config/`.
- Observations and run history live in local SQLite under `data/`.
- Canonical findings live in `outputs/latest.json`.
- Human digests and packages are renderers or exports from canonical JSON.
- Private judgment lives in `data/notes.json` and `config/background.local.json`.

## What Can Use The Network

Some source adapters fetch public pages, RSS feeds, or careers pages when the user runs PathScout. Those fetches collect evidence for the local run. They do not create hosted storage, background sync, or a remote account.

## What Is Safe To Commit

- `config/profile.json`
- `config/sources.json`
- `config/watchlist.json`
- `config/suppressions.json`
- `config/portfolio.json`
- `config/background.sample.json`
- Docs and tests

## What Should Stay Private

- `config/background.local.json`
- `data/pathscout.sqlite`
- `data/notes.json`
- `outputs/latest.json`
- `outputs/latest.md`
- `outputs/theses/`
- `outputs/packages/`

Run `pathscout doctor` to check schema versions, source IDs, suppressions, and local-only guardrails.
