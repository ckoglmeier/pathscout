# PathScout Artifacts

PathScout writes portable artifacts for humans and agents. JSON is canonical; Markdown is rendered from JSON.

## Run Artifacts

`outputs/latest.json` is the canonical run artifact. It answers: what did PathScout find in this run?

Required top-level fields:

- `artifact_type`: `run_artifact`.
- `artifact_id`: stable identifier for this generated run artifact.
- `schema_version`: run artifact schema version.
- `pathscout_version`: generator version.
- `generated_at`: UTC timestamp.
- `invocation`: command and path metadata.
- `summary`: fetched, inserted, skipped, errors, and dry-run status.
- `source_stats`: per-source counts and isolated errors.
- `errors`: source-level errors.
- `findings`: normalized finding objects.

Findings include stable IDs, company/title/source metadata, tier, score, reasons, flags, source URL, evidence type, evidence strength, evidence warnings, content hash, suppression state, and source text.

`outputs/latest.md` is the human-readable digest rendered from the same findings.

## Opportunity Packages

An opportunity package answers: what should a human or agent understand about this specific opportunity signal?

Create one from a run artifact:

```bash
pathscout package <finding-id>
```

Default package layout:

```text
outputs/packages/<company-slug>-<finding-prefix>/
  manifest.json
  package.md
  agent.md
  data/
    opportunity.json
    evidence.json
    findings.json
```

`manifest.json` is the package descriptor. It lists package type, schema version, generator, source run artifact, timestamps, and resources.

Its `artifact_type` is `opportunity_package`.

`package.md` is for human review. It summarizes the finding, why it surfaced, source links, warnings, and evidence gaps.

`agent.md` is for downstream agents. It explains safe-use rules and points agents to canonical JSON resources.

`data/opportunity.json` is the canonical structured opportunity object for this package.

`data/evidence.json` contains source details, reasons, flags, source stats, errors, evidence strength, and evidence gaps.

`data/findings.json` copies the selected source finding from the run artifact.

## Stable vs Flexible

Stable contract:

- Package directory layout.
- Manifest-first resource list.
- JSON canonical, Markdown derived.
- Run artifacts and opportunity packages remain separate.
- Source IDs, finding IDs, content hashes, and source URLs are preserved.

Flexible content:

- Narrative wording in Markdown.
- Evidence warning vocabulary.
- Future package types emitted by compatible generators.

OSS packages are skeletal evidence briefs. They intentionally do not include recommended roles, environment assessments, job descriptions, outreach copy, or advanced intelligence fields.
