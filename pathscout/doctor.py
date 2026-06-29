from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION
from .fetchers import source_setting
from .sources import career_candidates
from .watchlist import summarize_watchlist


SUPPORTED_SOURCES = {"manual", "watchlist", "watchlist_careers", "portfolio", "radar_portfolio", "web_page", "rss"}


def validate_setup(
    config: dict[str, Any],
    watchlist_path: Path,
    profile_path: Path | None = None,
    sources_path: Path | None = None,
    suppressions_path: Path | None = None,
    background_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    if not config.get("_legacy_profile"):
        validate_schema_document(config.get("profile", {}), profile_path, "profile", errors)
    if not config.get("_legacy_sources"):
        validate_schema_document(config, sources_path, "sources", errors)
    validate_schema_document(config.get("watchlist", {}), watchlist_path, "watchlist", errors)
    validate_schema_document(config.get("suppressions", {}), suppressions_path, "suppressions", errors)
    if background_path is not None:
        validate_optional_background(background_path, warnings, errors)

    if "profile" in config and sources_path and config.get("_legacy_profile"):
        warnings.append(f"{sources_path} embeds a deprecated profile; move it to config/profile.json")
    if config.get("_legacy_sources") and sources_path:
        warnings.append(f"{sources_path} uses a legacy config shape; add schema_version and move source settings under config")

    validate_profile(config.get("profile", {}), errors)
    validate_sources(config.get("sources", []), warnings, errors)
    validate_suppressions(config.get("suppressions", {}), warnings, errors)

    watchlist = config.get("watchlist", {"companies": []})
    companies = watchlist.get("companies", [])
    if not watchlist_path.exists():
        errors.append(f"missing watchlist file: {watchlist_path}")
    if not companies:
        errors.append("watchlist has no companies")

    active_companies = [
        company
        for company in companies
        if company.get("status", "watch") not in {"exclude", "archive"}
    ]
    for company in active_companies:
        urls = company.get("urls", {})
        homepage = urls.get("homepage", "")
        explicit = urls.get("careers", [])
        if isinstance(explicit, str):
            explicit = [explicit]
        if not career_candidates(homepage, explicit):
            warnings.append(f"{company.get('name', 'Unknown company')} has no homepage or careers URL")

    return warnings, errors


def validate_schema_document(data: dict[str, Any], path: Path | None, name: str, errors: list[str]) -> None:
    if path is not None and not path.exists():
        errors.append(f"missing {name} file: {path}")
        return
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        label = str(path) if path else name
        errors.append(f"{label} has unsupported or missing schema_version: {version!r}")


def validate_profile(profile: dict[str, Any], errors: list[str]) -> None:
    required = [
        "target_roles",
        "stage_focus",
        "include_domains",
        "exclude_domains",
        "preferred_locations",
        "authority_requirements",
        "scoring",
    ]
    for field in required:
        if field not in profile:
            errors.append(f"profile missing required field: {field}")


def validate_sources(sources: list[dict[str, Any]], warnings: list[str], errors: list[str]) -> None:
    if not sources:
        errors.append("no sources configured")
        return
    ids: set[str] = set()
    active_sources = []
    for source in sources:
        source_id = source.get("id")
        source_type = source.get("type")
        if not source_id:
            errors.append("source missing id")
        elif source_id in ids:
            errors.append(f"duplicate source id: {source_id}")
        else:
            ids.add(source_id)
        if source_type not in SUPPORTED_SOURCES:
            errors.append(f"unsupported source type for {source_id or 'unknown'}: {source_type}")
        if source_type == "radar_portfolio":
            warnings.append(f"{source_id} uses deprecated source type radar_portfolio; use portfolio")
        if source.get("enabled", True):
            active_sources.append(source)
        if source_type in {"watchlist", "watchlist_careers", "portfolio", "radar_portfolio"}:
            path = Path(source_setting(source, "path", ""))
            if path and not path.exists():
                warnings.append(f"{source_id} references missing source file: {path}")
    if not active_sources:
        errors.append("no enabled sources configured")


def validate_suppressions(suppressions: dict[str, Any], warnings: list[str], errors: list[str]) -> None:
    today = date.today().isoformat()
    for suppression in suppressions.get("suppressions", []):
        if not suppression.get("id"):
            errors.append("suppression missing id")
        if not suppression.get("reason"):
            warnings.append(f"suppression {suppression.get('id', 'unknown')} has no reason")
        expires_at = suppression.get("expires_at")
        if expires_at and expires_at < today:
            warnings.append(f"suppression {suppression.get('id', 'unknown')} expired on {expires_at}")


def validate_optional_background(path: Path, warnings: list[str], errors: list[str]) -> None:
    if not path.exists():
        warnings.append(f"missing optional background file: {path}")
        return
    try:
        import json

        with path.open("r", encoding="utf-8") as handle:
            background = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid background file {path}: {exc}")
        return
    version = background.get("schema_version")
    if version != SCHEMA_VERSION:
        errors.append(f"{path} has unsupported or missing schema_version: {version!r}")
    for field in ["strengths", "proof_points", "best_environments", "avoid_environments", "constraints", "network_context"]:
        if field in background and not isinstance(background[field], list):
            errors.append(f"background {field} must be a list")


def format_doctor_report(
    config: dict[str, Any],
    watchlist_path: Path,
    profile_path: Path | None = None,
    sources_path: Path | None = None,
    suppressions_path: Path | None = None,
    background_path: Path | None = None,
) -> str:
    watchlist = config.get("watchlist", {"companies": []})
    summary = summarize_watchlist(watchlist)
    warnings, errors = validate_setup(config, watchlist_path, profile_path, sources_path, suppressions_path, background_path)
    source_count = len([source for source in config.get("sources", []) if source.get("enabled", True)])
    lines = [
        "PathScout doctor",
        f"Companies: {summary['total']}",
        f"Enabled sources: {source_count}",
        f"Needs review: {summary['needs_review']}",
        f"Warnings: {len(warnings)}",
        f"Errors: {len(errors)}",
    ]
    if errors:
        lines.append("Errors:")
        lines.extend(f"  - {error}" for error in errors[:20])
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {warning}" for warning in warnings[:20])
        if len(warnings) > 20:
            lines.append(f"  ... {len(warnings) - 20} more")
    if summary["needs_review"]:
        lines.append("Review backlog:")
        lines.append(f"  - {summary['needs_review']} seed companies still need human review")
    return "\n".join(lines)
