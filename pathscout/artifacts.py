from __future__ import annotations

import json
import re
import sqlite3
import textwrap
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import __version__


ARTIFACT_SCHEMA_VERSION = 1
PACKAGE_SCHEMA_VERSION = 1
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

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    findings = [normalize_finding(finding, config.get("suppressions", {})) for finding in raw_findings]
    return {
        "artifact_type": "run_artifact",
        "artifact_id": build_artifact_id("run", generated_at),
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "pathscout_version": __version__,
        "generated_at": generated_at,
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
    evidence_strength, evidence_warnings = classify_evidence(raw)
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
        "evidence_strength": evidence_strength,
        "evidence_warnings": evidence_warnings,
        "observed_at": raw.get("observed_at", ""),
        "content_hash": raw.get("content_hash", ""),
        "suppressed": suppression is not None,
        "suppression": suppression,
        "text": raw.get("text", ""),
    }


def classify_evidence(raw: dict[str, Any]) -> tuple[str, list[str]]:
    evidence_type = str(raw.get("evidence_type", "")).lower()
    source_type = str(raw.get("source_type", "")).lower()
    title = str(raw.get("title", "")).lower()
    text = str(raw.get("text", "")).lower()
    warnings: list[str] = []

    if evidence_type in {"job", "job_posting", "role", "recruiter", "search_firm"}:
        strength = "strong"
    elif evidence_type in {"hidden_search", "portfolio", "radar_portfolio"}:
        strength = "medium"
    else:
        strength = "weak"

    if evidence_type == "job_page" or (source_type == "watchlist_careers" and ("career" in title or "job" in title)):
        strength = "weak"
        warnings.append("page_level_fallback")
    if evidence_type in {"manual", "web_page", "rss"} or (source_type in {"web_page", "rss"} and evidence_type in {"web_page", "rss"}):
        warnings.append("generic_source_evidence")
    if evidence_type in {"job", "job_page", "job_posting", "role"} and not re.search(r"\b(20\d{2}|posted|updated|opened)\b", f"{title} {text}"):
        warnings.append("missing_posted_date")

    return strength, warnings


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


def build_artifact_id(prefix: str, generated_at: str) -> str:
    compact = generated_at.replace("+00:00", "Z")
    compact = compact.replace("-", "").replace(":", "")
    compact = compact.replace(".", "")
    return f"{prefix}_{compact}"


def write_json_artifact(artifact: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return path


def write_markdown_artifact(artifact: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(artifact), encoding="utf-8")
    return path


def write_package_from_artifact(artifact: dict[str, Any], finding_id: str, out_dir: Path) -> Path:
    finding = find_finding(artifact, finding_id)
    package = build_opportunity_package(artifact, finding)
    package_dir = out_dir / package["slug"]
    data_dir = package_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "manifest.json": package["manifest"],
        "data/opportunity.json": package["opportunity"],
        "data/evidence.json": package["evidence"],
        "data/findings.json": package["findings"],
    }
    for relative_path, data in files.items():
        target = package_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (package_dir / "package.md").write_text(render_package_markdown(package), encoding="utf-8")
    (package_dir / "agent.md").write_text(render_agent_markdown(package), encoding="utf-8")
    return package_dir


def find_finding(artifact: dict[str, Any], finding_id: str) -> dict[str, Any]:
    findings = artifact.get("findings", [])
    exact = [finding for finding in findings if finding.get("id") == finding_id or finding.get("content_hash") == finding_id]
    if exact:
        return exact[0]
    if len(finding_id) >= 8:
        prefix_matches = [finding for finding in findings if str(finding.get("id", "")).startswith(finding_id)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        if len(prefix_matches) > 1:
            raise ValueError(f"Finding ID prefix is ambiguous: {finding_id}")
    raise ValueError(f"Finding not found: {finding_id}")


def build_opportunity_package(artifact: dict[str, Any], finding: dict[str, Any]) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    finding_id = finding.get("id", "")
    company = finding.get("company") or "unknown-company"
    slug = f"{slugify(company)}-{finding_id[:12] if finding_id else 'finding'}"
    package_id = f"pkg_{finding_id[:16] if finding_id else slug}"
    source_run_id = artifact.get("artifact_id", "")
    evidence = build_evidence_document(finding, artifact, package_id, source_run_id, generated_at)
    opportunity = build_opportunity_document(finding, package_id, source_run_id, generated_at)
    findings = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": package_id,
        "source_run_artifact_id": source_run_id,
        "findings": [finding],
    }
    manifest = build_package_manifest(package_id, source_run_id, generated_at)
    return {
        "slug": slug,
        "manifest": manifest,
        "opportunity": opportunity,
        "evidence": evidence,
        "findings": findings,
    }


def build_package_manifest(package_id: str, source_run_id: str, generated_at: str) -> dict[str, Any]:
    resources = [
        {"path": "package.md", "media_type": "text/markdown", "role": "human_readable"},
        {"path": "agent.md", "media_type": "text/markdown", "role": "agent_context"},
        {"path": "data/opportunity.json", "media_type": "application/json", "role": "canonical_opportunity", "schema_version": PACKAGE_SCHEMA_VERSION},
        {"path": "data/evidence.json", "media_type": "application/json", "role": "evidence", "schema_version": PACKAGE_SCHEMA_VERSION},
        {"path": "data/findings.json", "media_type": "application/json", "role": "source_findings", "schema_version": PACKAGE_SCHEMA_VERSION},
    ]
    return {
        "artifact_type": "opportunity_package",
        "package_type": "opportunity_brief",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": package_id,
        "source_run_artifact_id": source_run_id,
        "pathscout_version": __version__,
        "generated_at": generated_at,
        "generator": "pathscout package",
        "resources": resources,
    }


def build_opportunity_document(finding: dict[str, Any], package_id: str, source_run_id: str, generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "artifact_type": "opportunity",
        "package_type": "opportunity_brief",
        "package_id": package_id,
        "source_run_artifact_id": source_run_id,
        "generated_at": generated_at,
        "status": "skeletal_oss_export",
        "finding_id": finding.get("id", ""),
        "company": finding.get("company", ""),
        "title": finding.get("title", ""),
        "url": finding.get("url", ""),
        "tier": finding.get("tier", ""),
        "score": finding.get("score", 0),
        "source": {
            "id": finding.get("source_id", ""),
            "name": finding.get("source_name", ""),
            "type": finding.get("source_type", ""),
            "evidence_type": finding.get("evidence_type", ""),
        },
        "suppressed": finding.get("suppressed", False),
        "suppression": finding.get("suppression"),
        "evidence_strength": finding.get("evidence_strength", "weak"),
        "evidence_warnings": list(finding.get("evidence_warnings", [])),
        "placeholders": [
            "company_moment",
            "problem_hypotheses",
            "fit_notes",
            "questions_to_verify",
        ],
    }


def build_evidence_document(
    finding: dict[str, Any],
    artifact: dict[str, Any],
    package_id: str,
    source_run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    gaps = list(finding.get("evidence_warnings", []))
    if not finding.get("url"):
        gaps.append("missing_source_url")
    if not finding.get("text"):
        gaps.append("missing_evidence_text")
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "artifact_type": "evidence",
        "package_id": package_id,
        "source_run_artifact_id": source_run_id,
        "generated_at": generated_at,
        "summary": {
            "evidence_strength": finding.get("evidence_strength", "weak"),
            "evidence_warnings": list(finding.get("evidence_warnings", [])),
            "evidence_gaps": gaps,
        },
        "source_stats": artifact.get("source_stats", []),
        "errors": artifact.get("errors", []),
        "sources": [
            {
                "source_id": finding.get("source_id", ""),
                "source_name": finding.get("source_name", ""),
                "source_type": finding.get("source_type", ""),
                "evidence_type": finding.get("evidence_type", ""),
                "url": finding.get("url", ""),
                "observed_at": finding.get("observed_at", ""),
                "content_hash": finding.get("content_hash", finding.get("id", "")),
            }
        ],
        "reasons": list(finding.get("reasons", [])),
        "flags": list(finding.get("flags", [])),
        "snippet": textwrap.shorten(" ".join(str(finding.get("text", "")).split()), width=600, placeholder="..."),
    }


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "opportunity"


def render_package_markdown(package: dict[str, Any]) -> str:
    opportunity = package["opportunity"]
    evidence = package["evidence"]
    title = opportunity.get("title") or "Untitled signal"
    company = opportunity.get("company") or "Unknown company"
    lines = [
        f"# {company}: Opportunity Brief",
        "",
        "This is a skeletal PathScout OSS package generated from local findings. It is evidence context, not career advice.",
        "",
        "## Finding",
        "",
        f"- Title: {title}",
        f"- Company: {company}",
        f"- Tier: {opportunity.get('tier', '')}",
        f"- Score: {opportunity.get('score', 0)}",
        f"- Evidence strength: {opportunity.get('evidence_strength', 'weak')}",
    ]
    if opportunity.get("url"):
        lines.append(f"- Source: {opportunity['url']}")
    if opportunity.get("suppressed"):
        reason = (opportunity.get("suppression") or {}).get("reason", "No reason provided")
        lines.append(f"- Suppressed: true ({reason})")
    warnings = opportunity.get("evidence_warnings", [])
    if warnings:
        lines.extend(["", "## Evidence Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(["", "## Why It Surfaced", ""])
    reasons = evidence.get("reasons", [])
    lines.extend(f"- {reason}" for reason in reasons) if reasons else lines.append("- No scoring reasons were captured.")
    flags = evidence.get("flags", [])
    if flags:
        lines.extend(["", "## Flags", ""])
        lines.extend(f"- {flag}" for flag in flags)
    gaps = evidence.get("summary", {}).get("evidence_gaps", [])
    lines.extend(["", "## Evidence To Verify", ""])
    lines.extend(f"- {gap}" for gap in gaps) if gaps else lines.append("- No evidence gaps were detected by the OSS exporter.")
    if evidence.get("snippet"):
        lines.extend(["", "## Evidence Snippet", "", evidence["snippet"]])
    lines.extend(
        [
            "",
            "## Package Status",
            "",
            "This package intentionally stays at the evidence-brief layer and does not include advanced intelligence or outreach copy.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_agent_markdown(package: dict[str, Any]) -> str:
    opportunity = package["opportunity"]
    evidence = package["evidence"]
    lines = [
        "# Agent Context",
        "",
        "Use this package as structured evidence from PathScout. Do not treat it as a final career recommendation.",
        "",
        "## Safe Use Rules",
        "",
        "- Preserve source URLs, finding IDs, and evidence gaps when producing downstream work.",
        "- Distinguish observed evidence from inference.",
        "- Do not invent a recommended role, job description, compensation, or outreach unless the user explicitly asks for that work.",
        "- If evidence is weak or incomplete, say so plainly.",
        "",
        "## Canonical Data",
        "",
        "- Read `data/opportunity.json` for the canonical opportunity object.",
        "- Read `data/evidence.json` for source details, reasons, flags, and evidence gaps.",
        "- Read `data/findings.json` for copied source findings from the run artifact.",
        "",
        "## Opportunity Snapshot",
        "",
        f"- Finding ID: {opportunity.get('finding_id', '')}",
        f"- Company: {opportunity.get('company', '')}",
        f"- Title: {opportunity.get('title', '')}",
        f"- Tier: {opportunity.get('tier', '')}",
        f"- Score: {opportunity.get('score', 0)}",
        f"- Evidence strength: {opportunity.get('evidence_strength', 'weak')}",
    ]
    gaps = evidence.get("summary", {}).get("evidence_gaps", [])
    if gaps:
        lines.extend(["", "## Evidence Gaps", ""])
        lines.extend(f"- {gap}" for gap in gaps)
    return "\n".join(lines) + "\n"


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
        f"Score: {finding['score']} | Source: {finding['source_name']} | Evidence: {finding['evidence_type']} | Strength: {finding.get('evidence_strength', 'medium')}",
        "",
        "Why it surfaced:",
    ]
    for reason in finding.get("reasons", [])[:6]:
        lines.append(f"- {reason}")
    if finding.get("flags"):
        lines.extend(["", "Flags:"])
        lines.extend(f"- {flag}" for flag in finding["flags"][:5])
    if finding.get("evidence_warnings"):
        lines.extend(["", "Evidence warnings:"])
        lines.extend(f"- {warning}" for warning in finding["evidence_warnings"][:5])
    snippet = textwrap.shorten(" ".join(finding.get("text", "").split()), width=420, placeholder="...")
    if snippet:
        lines.extend(["", f"Evidence snippet: {snippet}"])
    return lines
