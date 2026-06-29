# PathScout

PathScout is a local-first role discovery CLI for finding high-fit startup opportunities before they become obvious job posts.

It fetches broad signals, scores them against a personal fit profile, stores deduped observations in SQLite, and emits a canonical JSON artifact plus a readable Markdown digest.

## What PathScout Is

- A local CLI for monitoring companies, careers pages, RSS feeds, portfolio lists, and manual notes.
- A fit-profile engine for surfacing target roles, hidden-search hypotheses, and weaker watch signals.
- An explainable findings scanner: every surfaced item includes score, tier, reasons, flags, source metadata, and suppression state.

## What PathScout Is Not

- It is not a hosted marketplace in v0.2.
- It is not a recruiting CRM.
- It is not a general-purpose job board scraper.
- It does not send your profile, watchlist, or findings anywhere by default.

## Install

From GitHub:

```bash
pipx install git+https://github.com/ckoglmeier/pathscout.git
```

From a local checkout:

```bash
pipx install .
```

For development:

```bash
python3 -m pathscout doctor
python3 -m pathscout run --dry-run --format both
```

## Quick Start

```bash
pathscout init
pathscout doctor
pathscout run --format both
```

During `init`, PathScout asks two onboarding questions in this order:

1. What is the right environment for you?
2. What is the right role for you?

For scripted setup, pass answers directly:

```bash
pathscout init \
  --environment "Remote AI startups" \
  --role "Founding Product Lead"
```

Use `--no-input` to create default sample config without prompts.

Outputs:

- `data/pathscout.sqlite`: local state and dedupe history.
- `outputs/latest.json`: canonical machine-readable findings artifact.
- `outputs/latest.md`: human-readable digest rendered from the JSON findings.
- `config/profile.json`: personal fit profile.
- `config/sources.json`: source adapter configuration.
- `config/watchlist.json`: curated company list.
- `config/suppressions.json`: structured ignored findings.

## Configuration

PathScout uses schema-versioned JSON files.

`config/profile.json` is the personal fit model. It contains target roles, stages, domains, excluded domains, location preferences, travel constraints, authority terms, and scoring thresholds.

`config/sources.json` describes inputs. Each source uses this adapter contract:

```json
{
  "id": "watchlist_careers",
  "type": "watchlist_careers",
  "name": "Watchlist careers pages",
  "enabled": true,
  "config": {
    "path": "config/watchlist.json"
  }
}
```

`id` is stable and scriptable. `name` is display-only. `type` selects the adapter. `config` is adapter-specific.

`config/suppressions.json` stores structured ignores:

```json
{
  "schema_version": 1,
  "suppressions": [
    {
      "id": "finding-content-hash",
      "scope": "finding",
      "reason": "Not a fit",
      "expires_at": "2026-12-31",
      "created_at": "2026-06-29"
    }
  ]
}
```

Suppressions affect output visibility. They do not delete observations from SQLite.

## Source Types

The v0.2 runner supports standard-library fetches for:

- `manual`: config-entered notes for companies or opportunities you want tracked.
- `watchlist`: turns every active watchlist company into a hidden-search observation.
- `watchlist_careers`: probes active watchlist companies' careers pages for posted role evidence.
- `portfolio`: turns companies from `config/portfolio.json` into relationship-context observations.
- `web_page`: fetches a single web page.
- `rss`: fetches an RSS or Atom feed.

`radar_portfolio` remains as a deprecated alias for one release. Use `portfolio` for new config.

## Commands

```bash
pathscout init
pathscout doctor
pathscout watchlist
pathscout portfolio
pathscout review
pathscout suppress <finding-id> --reason "Not a fit"
pathscout run --format json
pathscout run --format markdown
pathscout run --format both
```

Useful paths can be overridden:

```bash
pathscout run \
  --profile config/profile.json \
  --sources config/sources.json \
  --watchlist config/watchlist.json \
  --suppressions config/suppressions.json \
  --db data/pathscout.sqlite \
  --json-out outputs/latest.json \
  --out outputs/latest.md
```

## Digest Tiers

- `Act Now`: explicit target role or recruiter-visible mandate with strong fit signals.
- `Hidden Search Hypothesis`: no role posted, but company signals suggest a likely hiring need.
- `Watch Signal`: weaker signal, lower-level posting, or incomplete evidence.
- `Filtered`: captured for history but excluded from the main digest.

## Review And Suppress

Use `review` to scan findings from the latest JSON artifact without opening the file:

```bash
pathscout review --limit 10
pathscout review --tier "Act Now"
```

Use `suppress` to hide a finding from future Markdown digests while keeping the raw observation in SQLite and the finding marked in JSON:

```bash
pathscout suppress <finding-id> --reason "Not a fit" --expires 2026-12-31
```

Careers pages are parsed into separate role findings when PathScout can identify role-title rows. If a page does not expose clear role titles, PathScout falls back to one page-level finding.

## Design Borrowed From

PathScout follows scanner-style findings: stable IDs, evidence, severity-like tiers, reasons, flags, and suppressions.

The config split borrows from dbt-style separation of personal profile from project config. Source IDs follow the pre-commit convention: stable machine IDs plus human names. Suppressions borrow from security scanners: structured ignores with reasons and optional expiration dates.

## Future Marketplace Direction

PathScout v0.2 is open-source local software. Future hosted intro workflows should be explicit opt-in only. See `docs/marketplace.md` for the product direction.
