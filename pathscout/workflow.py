from __future__ import annotations

import json
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, load_json, validate_schema_version


DEFAULT_NOTES = Path("data/notes.json")
DEFAULT_THESES_DIR = Path("outputs/theses")


def load_artifact(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON artifact: {path}")
    artifact = load_json(path)
    if artifact.get("schema_version") != 1:
        raise ValueError(f"{path} has unsupported or missing schema_version: {artifact.get('schema_version')!r}")
    return artifact


def find_finding(artifact: dict[str, Any], finding_id: str) -> dict[str, Any]:
    matches = [
        finding
        for finding in artifact.get("findings", [])
        if str(finding.get("id", "")).startswith(finding_id) or str(finding.get("content_hash", "")).startswith(finding_id)
    ]
    if not matches:
        raise LookupError(f"Finding not found: {finding_id}")
    if len(matches) > 1:
        raise LookupError(f"Finding ID is ambiguous: {finding_id}")
    return matches[0]


def default_notes() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "notes": []}


def load_notes(path: Path = DEFAULT_NOTES) -> dict[str, Any]:
    if not path.exists():
        return default_notes()
    notes = load_json(path)
    validate_schema_version(notes, path)
    return notes


def write_notes(path: Path, notes: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
    return path


def add_note(path: Path, body: str, finding_id: str = "", company: str = "") -> dict[str, Any]:
    if not finding_id and not company:
        raise ValueError("notes require a finding ID or --company")
    if not body.strip():
        raise ValueError("notes require non-empty --add text")
    notes = load_notes(path)
    entries = notes.setdefault("notes", [])
    now = now_iso()
    entry = {
        "id": note_id(now, finding_id, company, body),
        "finding_id": finding_id,
        "company": company,
        "body": body.strip(),
        "created_at": now,
    }
    entries.append(entry)
    write_notes(path, notes)
    return entry


def related_notes(notes: dict[str, Any], finding: dict[str, Any] | None = None, company: str = "") -> list[dict[str, Any]]:
    finding_id = finding.get("id", "") if finding else ""
    finding_company = finding.get("company", "") if finding else ""
    target_company = normalize_company(company or finding_company)
    related = []
    for note in notes.get("notes", []):
        note_finding = note.get("finding_id", "")
        note_company = normalize_company(note.get("company", ""))
        if finding_id and note_finding and finding_id.startswith(note_finding):
            related.append(note)
        elif finding_id and note_finding and note_finding.startswith(finding_id):
            related.append(note)
        elif target_company and note_company == target_company:
            related.append(note)
    return related


def render_notes(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "No notes found."
    lines = [f"Notes: {len(notes)}"]
    for note in notes:
        target = note.get("finding_id") or note.get("company") or "general"
        lines.append(f"- {note.get('created_at', '')} | {target}: {note.get('body', '')}")
    return "\n".join(lines)


def load_background(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    background = load_json(path)
    validate_schema_version(background, path)
    return background


def render_explanation(finding: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    lines = [
        f"# {finding.get('title') or 'Untitled signal'}",
        "",
        f"Company: {finding.get('company') or 'Unknown company'}",
        f"Tier: {finding.get('tier', 'Unknown')} | Score: {finding.get('score', 0)}",
        f"Source: {finding.get('source_name', '')} (`{finding.get('source_type', '')}`)",
        f"Evidence: {finding.get('evidence_type', '')} | Strength: {finding.get('evidence_strength', 'medium')}",
    ]
    if finding.get("url"):
        lines.append(f"URL: {finding['url']}")
    if finding.get("observed_at"):
        lines.append(f"Observed: {finding['observed_at']}")
    if finding.get("content_hash"):
        lines.append(f"Content hash: {finding['content_hash']}")
    if finding.get("suppressed"):
        suppression = finding.get("suppression") or {}
        suffix = f" until {suppression.get('expires_at')}" if suppression.get("expires_at") else ""
        lines.append(f"Suppressed: {suppression.get('reason', 'No reason provided')}{suffix}")

    lines.extend(["", "## Why It Surfaced", ""])
    reasons = finding.get("reasons", [])
    lines.extend(f"- {reason}" for reason in reasons[:8]) if reasons else lines.append("- No reasons recorded.")

    lines.extend(["", "## Fit Read", ""])
    lines.append(f"- Environment fit: {fit_summary(reasons, 'environment')}")
    lines.append(f"- Function fit: {fit_summary(reasons, 'function')}")
    lines.append(f"- Evidence gaps: {evidence_gap_summary(finding)}")

    if finding.get("flags"):
        lines.extend(["", "## Flags", ""])
        lines.extend(f"- {flag}" for flag in finding["flags"][:8])

    if finding.get("evidence_warnings"):
        lines.extend(["", "## Evidence Warnings", ""])
        lines.extend(f"- {warning}" for warning in finding["evidence_warnings"])

    snippet = textwrap.shorten(" ".join(str(finding.get("text", "")).split()), width=700, placeholder="...")
    if snippet:
        lines.extend(["", "## Evidence Snippet", "", snippet])

    lines.extend(["", "## Notes", ""])
    if notes:
        lines.extend(f"- {note.get('created_at', '')}: {note.get('body', '')}" for note in notes)
    else:
        lines.append("- No related notes yet.")
    return "\n".join(lines)


def render_thesis(
    finding: dict[str, Any],
    profile: dict[str, Any],
    background: dict[str, Any],
    notes: list[dict[str, Any]],
) -> str:
    company = finding.get("company") or "Unknown company"
    title = finding.get("title") or "Untitled signal"
    target_roles = profile.get("role_preferences") or profile.get("target_roles", [])
    strengths = background.get("strengths", [])
    proof_points = background.get("proof_points", [])
    best_environments = background.get("best_environments", [])
    lines = [
        f"# Role Thesis: {company}",
        "",
        f"Finding: {title}",
        f"Tier: {finding.get('tier', 'Unknown')} | Score: {finding.get('score', 0)} | Evidence strength: {finding.get('evidence_strength', 'medium')}",
    ]
    if finding.get("url"):
        lines.append(f"Source: {finding['url']}")
    lines.extend(
        [
            "",
            "## Company Moment",
            "",
            bullets_or_placeholder(finding.get("reasons", [])[:5], "Add 3-5 bullets explaining why this company may be entering an interesting moment."),
            "",
            "## Why It Surfaced",
            "",
            bullets_or_placeholder(finding.get("reasons", [])[:8], "Add the concrete PathScout signals that justify more research."),
            "",
            "## Problem Hypotheses",
            "",
            "- Hypothesis 1: [What problem may become expensive for this company soon?]",
            "- Hypothesis 2: [What operating gap might this company need to fill?]",
            "- Hypothesis 3: [What stage-specific constraint should be tested?]",
            "",
            "## Proposed Function",
            "",
            f"- Starting point: {', '.join(target_roles[:3]) if target_roles else '[Add the function you believe you should own.]'}",
            "- Do not turn this into a generic job description in this release.",
            "",
            "## Fit Evidence",
            "",
            f"- Background summary: {background.get('summary', '[Add a concise background summary before sharing.]')}",
            bullets_or_placeholder(strengths[:5], "Add strengths that map to this company's likely needs."),
            bullets_or_placeholder(proof_points[:5], "Add proof points before using this thesis externally."),
            "",
            "## Environment Fit",
            "",
            bullets_or_placeholder(best_environments[:5], "Add environments where you have done your best work."),
            "",
            "## 90-180 Day Questions",
            "",
            "- What would I diagnose first?",
            "- What would I try to make true by day 90?",
            "- What proof would show the role is working by day 180?",
            "",
            "## Evidence To Verify",
            "",
            evidence_verification_list(finding, background),
            "",
            "## Notes",
            "",
            bullets_or_placeholder([note.get("body", "") for note in notes], "Add local notes, warm paths, and concerns before outreach."),
            "",
            "## Outreach Draft Placeholder",
            "",
            "[Draft later only after evidence gaps are checked.]",
        ]
    )
    return "\n".join(lines) + "\n"


def write_thesis(
    finding: dict[str, Any],
    profile: dict[str, Any],
    background: dict[str, Any],
    notes: list[dict[str, Any]],
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    company_slug = slugify(finding.get("company") or "unknown-company")
    finding_prefix = str(finding.get("id", "finding"))[:12]
    path = out_dir / f"{company_slug}-{finding_prefix}.md"
    path.write_text(render_thesis(finding, profile, background, notes), encoding="utf-8")
    return path


def bullets_or_placeholder(items: list[Any], placeholder: str) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return f"- [{placeholder}]"
    return "\n".join(f"- {item}" for item in cleaned)


def evidence_verification_list(finding: dict[str, Any], background: dict[str, Any]) -> str:
    items = []
    if finding.get("evidence_strength") == "weak":
        items.append("Verify the source signal before treating this as actionable.")
    for warning in finding.get("evidence_warnings", []):
        items.append(f"Check warning: {warning}.")
    if not background:
        items.append("Add candidate background and proof points before sharing externally.")
    if not finding.get("url"):
        items.append("Find a source URL or relationship path that supports the thesis.")
    if not items:
        items.append("Confirm the company moment and role need with a human source before outreach.")
    return "\n".join(f"- {item}" for item in items)


def fit_summary(reasons: list[str], kind: str) -> str:
    joined = " | ".join(reasons).lower()
    if kind == "environment":
        terms = ["location fit", "domain fit", "watchlist", "hidden-search company signal", "portfolio"]
    else:
        terms = ["target role", "authority signal", "function"]
    matches = [reason for reason in reasons if any(term in reason.lower() for term in terms)]
    if matches:
        return "; ".join(matches[:3])
    if joined:
        return "No explicit signal; inspect the evidence before acting."
    return "No recorded fit signal."


def evidence_gap_summary(finding: dict[str, Any]) -> str:
    warnings = finding.get("evidence_warnings", [])
    if warnings:
        return ", ".join(warnings)
    if finding.get("evidence_strength") == "strong":
        return "No major evidence warnings recorded."
    return "Needs human verification before outreach."


def note_id(created_at: str, finding_id: str, company: str, body: str) -> str:
    material = "|".join([created_at, finding_id, company, body])
    value = 0
    for char in material:
        value = ((value * 33) + ord(char)) % 0xFFFFFFFF
    return f"note_{value:08x}"


def normalize_company(value: str) -> str:
    return " ".join(value.lower().split())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown-company"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
