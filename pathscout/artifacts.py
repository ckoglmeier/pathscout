from __future__ import annotations

import json
import sqlite3
import textwrap
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import __version__


ARTIFACT_SCHEMA_VERSION = 1
TIERS = ["Act Now", "Hidden Search Hypothesis", "Watch Signal", "Filtered"]


def build_artifact(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    run_result: Any,
    window_days: int,
    dry_run: bool,
    invocation: dict[str, Any],
) -> dict[str, Any]:
    if dry_run:
        raw_findings = run_result.dry_run_findings
    else:
        raw_findings = rows_to_raw_findings(fetch_recent_rows(conn, window_days))

    findings = [normalize_finding(finding, config.get("suppressions", {})) for finding in raw_findings]
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "pathscout_version": __version__,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "invocation": invocation,
        "summary": {
            "fetched": run_result.fetched_count,
            "inserted": run_result.inserted_count,
            "skipped": run_result.skipped_count,
            "errors": len(run_result.errors),
            "dry_run": dry_run,
        },
        "source_stats": [
            {
                "id": stat.source_id,
                "name": stat.source_name,
                "type": stat.source_type,
                "fetched": stat.fetched_count,
                "error": stat.error,
            }
            for stat in run_result.source_stats
        ],
        "errors": list(run_result.errors),
        "findings": findings,
    }


def fetch_recent_rows(conn: sqlite3.Connection, window_days: int) -> list[sqlite3.Row]:
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).replace(microsecond=0).isoformat()
    return conn.execute(
        """
        select * from observations
        where observed_at >= ?
        order by score desc, observed_at desc
        """,
        (since,),
    ).fetchall()


def rows_to_raw_findings(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    findings = []
    for row in rows:
        findings.append(
            {
                "source_id": row["source_id"],
                "source_name": row["source_name"],
                "source_type": row["source_type"],
                "company": row["company"],
                "title": row["title"],
                "url": row["url"],
                "text": row["text"],
                "evidence_type": row["evidence_type"],
                "content_hash": row["content_hash"],
                "observed_at": row["observed_at"],
                "score": row["score"],
                "tier": row["tier"],
                "reasons": json.loads(row["reasons_json"]),
                "flags": json.loads(row["flags_json"]),
            }
        )
    return findings


def normalize_finding(raw: dict[str, Any], suppressions: dict[str, Any]) -> dict[str, Any]:
    finding_id = raw["content_hash"]
    suppression = find_suppression(finding_id, suppressions)
    return {
        "id": finding_id,
        "company": raw.get("company", ""),
        "title": raw.get("title", ""),
        "url": raw.get("url", ""),
        "tier": raw.get("tier", ""),
        "score": raw.get("score", 0),
        "reasons": list(raw.get("reasons", [])),
        "flags": list(raw.get("flags", [])),
        "source_id": raw.get("source_id", ""),
        "source_name": raw.get("source_name", ""),
        "source_type": raw.get("source_type", ""),
        "evidence_type": raw.get("evidence_type", ""),
        "observed_at": raw.get("observed_at", ""),
        "content_hash": raw.get("content_hash", ""),
        "suppressed": suppression is not None,
        "suppression": suppression,
        "text": raw.get("text", ""),
    }


def find_suppression(finding_id: str, suppressions: dict[str, Any]) -> dict[str, Any] | None:
    today = date.today().isoformat()
    for suppression in suppressions.get("suppressions", []):
        if suppression.get("id") != finding_id:
            continue
        expires_at = suppression.get("expires_at")
        if expires_at and expires_at < today:
            continue
        return suppression
    return None


def write_json_artifact(artifact: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return path


def write_markdown_artifact(artifact: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(artifact), encoding="utf-8")
    return path


def render_markdown(artifact: dict[str, Any]) -> str:
    lines = [
        "# PathScout Executive Opportunity Digest",
        "",
        f"Generated: {artifact['generated_at']}",
        f"Window: last {artifact['invocation'].get('digest_window_days', 7)} day(s)",
        "",
        "## Run Summary",
        "",
        f"- Fetched: {artifact['summary']['fetched']}",
        f"- Inserted: {artifact['summary']['inserted']}",
        f"- Dedupe skipped: {artifact['summary']['skipped']}",
        f"- Errors: {artifact['summary']['errors']}",
    ]
    if artifact["summary"].get("dry_run"):
        lines.append("- Dry run: true")
    lines.extend(["", "## Source Summary", ""])
    for stat in artifact.get("source_stats", []):
        suffix = f" | error: {stat['error']}" if stat.get("error") else ""
        lines.append(f"- {stat['name']} (`{stat['type']}`): {stat['fetched']}{suffix}")
    lines.append("")

    if artifact.get("errors"):
        lines.extend(["## Source Errors", ""])
        lines.extend(f"- {error}" for error in artifact["errors"])
        lines.append("")

    findings = artifact.get("findings", [])
    for tier in TIERS:
        tier_findings = [finding for finding in findings if finding["tier"] == tier and not finding["suppressed"]]
        if tier == "Filtered" and not tier_findings:
            continue
        lines.extend([f"## {tier}", ""])
        if not tier_findings:
            lines.extend(["_No new items._", ""])
            continue
        for finding in tier_findings[:20]:
            lines.extend(format_finding(finding))
            lines.append("")

    suppressed = [finding for finding in findings if finding["suppressed"]]
    if suppressed:
        lines.extend(["## Suppressed", ""])
        for finding in suppressed[:20]:
            reason = (finding.get("suppression") or {}).get("reason", "No reason provided")
            lines.append(f"- {finding['title'] or 'Untitled signal'} - {finding['company']} ({reason})")
        lines.append("")

    return "\n".join(lines)


def format_finding(finding: dict[str, Any]) -> list[str]:
    title = finding["title"] or "Untitled signal"
    company = f" - {finding['company']}" if finding.get("company") else ""
    url = f" ([source]({finding['url']}))" if finding.get("url") else ""
    lines = [
        f"### {title}{company}{url}",
        "",
        f"Score: {finding['score']} | Source: {finding['source_name']} | Evidence: {finding['evidence_type']}",
        "",
        "Why it surfaced:",
    ]
    for reason in finding.get("reasons", [])[:6]:
        lines.append(f"- {reason}")
    if finding.get("flags"):
        lines.extend(["", "Flags:"])
        lines.extend(f"- {flag}" for flag in finding["flags"][:5])
    snippet = textwrap.shorten(" ".join(finding.get("text", "").split()), width=420, placeholder="...")
    if snippet:
        lines.extend(["", f"Evidence snippet: {snippet}"])
    return lines
