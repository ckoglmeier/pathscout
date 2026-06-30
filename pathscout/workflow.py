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
    lines = [
        f"# Role Thesis: {company}",
        "",
        f"Finding: {title}",
        f"Tier: {finding.get('tier', 'Unknown')} | Score: {finding.get('score', 0)} | Evidence strength: {finding.get('evidence_strength', 'medium')}",
    ]
    if finding.get("url"):
        lines.append(f"Source: {finding['url']}")
    if finding.get("observed_at"):
        lines.append(f"Observed: {finding['observed_at']}")
    if finding.get("content_hash"):
        lines.append(f"Content hash: {finding['content_hash']}")
    lines.extend(
        [
            "",
            "## Company Moment",
            "",
            bullets_or_placeholder(company_moment_from_finding(finding), "Add 3-5 bullets explaining why this company may be entering an interesting moment."),
            "",
            "## Why It Surfaced",
            "",
            bullets_or_placeholder(finding.get("reasons", [])[:8], "Add the concrete PathScout signals that justify more research."),
            "",
            "## Problem Map",
            "",
            bullets_or_placeholder(problem_hypotheses_from_signals(finding, profile, notes), "Add likely company problems only after reviewing evidence."),
            "",
            "## Proposed Function",
            "",
            bullets_or_placeholder(proposed_function_from_profile(profile, finding), "Add the function you believe you should own."),
            "",
            "## Fit Argument",
            "",
            bullets_or_placeholder(fit_claims_from_background(profile, background, finding), "Add private background and proof points before sharing externally."),
            "",
            "## Environment Fit",
            "",
            bullets_or_placeholder(environment_fit_from_profile(profile, background, finding), "Add environments where you have done your best work."),
            "",
            "## 90-180 Day Wedge",
            "",
            bullets_or_placeholder(wedge_questions_from_context(finding, profile, background), "Add a first-pass 90-180 day wedge after reviewing the company moment."),
            "",
            "## Evidence To Verify",
            "",
            evidence_verification_list(finding, background, notes),
            "",
            "## Notes",
            "",
            bullets_or_placeholder([note.get("body", "") for note in notes], "Add local notes, warm paths, and concerns before outreach."),
            "",
            "## Not Ready To Send Until",
            "",
            bullets_or_placeholder(not_ready_to_send_until(finding, background, notes), "Review evidence gaps before using this thesis externally."),
        ]
    )
    return "\n".join(lines) + "\n"


def company_moment_from_finding(finding: dict[str, Any]) -> list[str]:
    reasons = [str(reason) for reason in finding.get("reasons", []) if str(reason).strip()]
    items: list[str] = []
    for reason in reasons:
        lowered = reason.lower()
        if any(term in lowered for term in ["hidden-search", "watchlist", "portfolio", "domain fit", "stage", "series", "funding"]):
            items.append(f"Signal: {reason}")
    snippet = evidence_snippet(finding, width=220)
    if snippet:
        items.append(f"Observed evidence: {snippet}")
    if finding.get("evidence_strength"):
        items.append(f"Confidence starts at {finding.get('evidence_strength')} based on current source quality.")
    return dedupe_preserve_order(items)[:5]


def problem_hypotheses_from_signals(
    finding: dict[str, Any],
    profile: dict[str, Any],
    notes: list[dict[str, Any]],
) -> list[str]:
    signal_text = thesis_signal_text(finding, profile, notes)
    hypotheses: list[str] = []
    if any(term in signal_text for term in ["pilot", "deployment", "implementation", "customer rollout", "robotics", "autonomy"]):
        hypotheses.append("Turning pilots or deployments into a repeatable customer operating motion may become expensive soon.")
    if any(term in signal_text for term in ["gtm", "sales", "commercial", "revenue", "growth", "market"]):
        hypotheses.append("Moving from founder-led commercial work to a repeatable GTM system may be the next constraint.")
    if any(term in signal_text for term in ["product", "roadmap", "customer pain", "workflow", "platform"]):
        hypotheses.append("Translating customer pain into product priorities may need clearer cross-functional ownership.")
    if any(term in signal_text for term in ["community", "network", "marketplace", "liquidity", "operators"]):
        hypotheses.append("Strengthening network quality, liquidity, or community loops may be part of the role shape.")
    if any(term in signal_text for term in ["series a", "series b", "series c", "funding", "raised"]):
        hypotheses.append("A stage change may require operating cadence, hiring focus, and clearer functional ownership.")
    if not hypotheses and finding.get("tier") == "Act Now":
        hypotheses.append("The posted role should be inspected for the underlying business problem, not just the title.")
    return dedupe_preserve_order(hypotheses)[:4]


def proposed_function_from_profile(profile: dict[str, Any], finding: dict[str, Any]) -> list[str]:
    target_roles = clean_list(profile.get("role_preferences") or profile.get("target_roles", []))
    title = str(finding.get("title", "")).strip()
    items: list[str] = []
    if target_roles:
        items.append(f"Primary function thesis: {target_roles[0]}.")
    if len(target_roles) > 1:
        items.append(f"Adjacent titles to test: {', '.join(target_roles[1:4])}.")
    if title and not title.lower().endswith("careers"):
        items.append(f"Compare this against the observed signal: {title}.")
    items.append("Do not pitch this as a generic job description; keep it framed as a role thesis to validate.")
    return items


def fit_claims_from_background(
    profile: dict[str, Any],
    background: dict[str, Any],
    finding: dict[str, Any],
) -> list[str]:
    if not background:
        return []
    items: list[str] = []
    summary = str(background.get("summary", "")).strip()
    if summary:
        items.append(f"Background summary: {summary}")
    for strength in clean_list(background.get("strengths", []))[:4]:
        items.append(f"Strength to test against this company moment: {strength}")
    for proof in clean_list(background.get("proof_points", []))[:4]:
        items.append(f"Proof point to use only if relevant: {proof}")
    role_preferences = clean_list(profile.get("role_preferences") or profile.get("target_roles", []))
    if role_preferences:
        items.append(f"Function fit starts from the user's stated role preference: {role_preferences[0]}.")
    if finding.get("evidence_strength") != "strong":
        items.append("Fit should be treated as provisional until the company need is verified.")
    return items


def environment_fit_from_profile(
    profile: dict[str, Any],
    background: dict[str, Any],
    finding: dict[str, Any],
) -> list[str]:
    items: list[str] = []
    for environment in clean_list(profile.get("environment_preferences", []))[:3]:
        items.append(f"Stated target environment: {environment}")
    for environment in clean_list(background.get("best_environments", []))[:3]:
        items.append(f"Best-work environment: {environment}")
    stages = clean_list(profile.get("stage_focus", []))
    if stages:
        items.append(f"Stage preference to compare against company evidence: {', '.join(stages[:4])}.")
    constraints = clean_list(background.get("constraints", [])) or clean_list([profile.get("travel_limit", "")])
    for constraint in constraints[:3]:
        items.append(f"Constraint to verify: {constraint}")
    if finding.get("tier") == "Hidden Search Hypothesis":
        items.append("Because this may be unposted, validate manager, ambiguity, authority, and operating pace before pitching.")
    return items


def wedge_questions_from_context(
    finding: dict[str, Any],
    profile: dict[str, Any],
    background: dict[str, Any],
) -> list[str]:
    role = first_clean(profile.get("role_preferences") or profile.get("target_roles", []), "the proposed function")
    company = finding.get("company") or "the company"
    items = [
        f"First diagnosis: what constraint is most limiting {company} right now, and does it map to {role}?",
        "First 90 days: identify one operating or product motion that could become repeatable.",
        "By 180 days: define the proof that the role is creating leverage, not just adding activity.",
    ]
    proof = first_clean(background.get("proof_points", []), "")
    if proof:
        items.append(f"Use this proof point as a comparison case only if the company problem is similar: {proof}")
    return items


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


def evidence_verification_list(finding: dict[str, Any], background: dict[str, Any], notes: list[dict[str, Any]] | None = None) -> str:
    items = []
    if finding.get("evidence_strength") == "weak":
        items.append("Verify the source signal before treating this as actionable.")
    for warning in finding.get("evidence_warnings", []):
        items.append(f"Check warning: {warning}.")
    if not background:
        items.append("Add candidate background and proof points before sharing externally.")
    if not notes:
        items.append("Add local judgment or a warm-path note before using this outside PathScout.")
    if not finding.get("url"):
        items.append("Find a source URL or relationship path that supports the thesis.")
    if not items:
        items.append("Confirm the company moment and role need with a human source before outreach.")
    return "\n".join(f"- {item}" for item in items)


def not_ready_to_send_until(
    finding: dict[str, Any],
    background: dict[str, Any],
    notes: list[dict[str, Any]],
) -> list[str]:
    items: list[str] = []
    if finding.get("evidence_strength") != "strong":
        items.append("The source signal is verified beyond the current evidence strength.")
    if not background:
        items.append("Candidate background and proof points are added in config/background.local.json.")
    if not notes:
        items.append("A human note, warm path, or concern has been captured locally.")
    if finding.get("tier") == "Hidden Search Hypothesis":
        items.append("The company need is validated with a human source or stronger public signal.")
    if not items:
        items.append("A reviewer has checked the thesis for overclaiming and missing evidence.")
    return items


def thesis_signal_text(finding: dict[str, Any], profile: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for value in [finding.get("title", ""), finding.get("tier", ""), finding.get("text", "")]:
        parts.append(str(value))
    parts.extend(str(reason) for reason in finding.get("reasons", []))
    parts.extend(str(flag) for flag in finding.get("flags", []))
    parts.extend(str(note.get("body", "")) for note in notes)
    return " ".join(parts).lower()


def evidence_snippet(finding: dict[str, Any], width: int = 220) -> str:
    text = " ".join(str(finding.get("text", "")).split())
    if not text:
        return ""
    return textwrap.shorten(text, width=width, placeholder="...")


def clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def first_clean(values: Any, fallback: str) -> str:
    cleaned = clean_list(values)
    return cleaned[0] if cleaned else fallback


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


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
