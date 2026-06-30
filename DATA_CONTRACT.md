# PathScout Data Contract

PathScout OSS stores its state locally. The durable product contract is the JSON artifact emitted by `pathscout run`, plus local user-authored context files that can be inspected, copied, or imported explicitly by the user.

## Local State

- `data/pathscout.sqlite` stores raw observations, run history, and dedupe state.
- `outputs/latest.json` is the canonical run artifact for findings and source stats.
- `outputs/latest.md` is a human renderer generated from the JSON artifact.
- `data/notes.json` stores local judgment attached to a finding or company.
- `config/background.local.json` stores private candidate context and proof points.
- `config/background.sample.json` is a tracked example only.

PathScout OSS does not provide hosted storage, sync, or background upload. Network source fetches are input collection, not remote persistence.

## Finding Object

Each finding in `outputs/latest.json` should be safe for both humans and agents to read:

```json
{
  "id": "stable-finding-id",
  "company": "Example Robotics",
  "title": "Product Lead",
  "url": "https://example.com/jobs/product-lead",
  "tier": "Act Now",
  "score": 84,
  "reasons": ["target role title signal: product lead"],
  "flags": [],
  "source_id": "watchlist_careers",
  "source_type": "watchlist_careers",
  "evidence_type": "job",
  "observed_at": "2026-06-30T12:00:00+00:00",
  "content_hash": "hash-of-observed-content",
  "suppressed": false
}
```

Required fields are `id`, `company`, `title`, `tier`, `score`, `reasons`, `flags`, `source_id`, `source_type`, `evidence_type`, `observed_at`, `content_hash`, and `suppressed`.

## Notes Object

`data/notes.json` uses schema version `1`:

```json
{
  "schema_version": 1,
  "notes": [
    {
      "id": "note-id",
      "finding_id": "optional-finding-id",
      "company": "optional company",
      "body": "Human judgment, concern, or warm-path note.",
      "created_at": "2026-06-30T12:00:00+00:00"
    }
  ]
}
```

Notes add context. They do not mutate the underlying observation or finding.

## Private Background Object

`config/background.local.json` uses schema version `1` and may include:

- `summary`
- `strengths`
- `proof_points`
- `best_environments`
- `avoid_environments`
- `constraints`
- `network_context`

This file is ignored by Git by default. Use `config/background.sample.json` as the public template.

## Compatibility

Schema versions are explicit. Consumers should reject missing or unsupported `schema_version` values instead of guessing.
