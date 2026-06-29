from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date
from pathlib import Path

from .artifacts import build_artifact, write_json_artifact, write_markdown_artifact
from .config import (
    DEFAULT_PORTFOLIO,
    DEFAULT_PROFILE,
    DEFAULT_SOURCES,
    DEFAULT_SUPPRESSIONS,
    DEFAULT_WATCHLIST,
    apply_onboarding_answers,
    build_runtime_config,
    ensure_default_files,
)
from .db import connect, init_db
from .doctor import format_doctor_report, validate_setup
from .runner import run_sources
from .watchlist import load_watchlist, summarize_watchlist


DEFAULT_DB = Path("data/pathscout.sqlite")
DEFAULT_JSON_OUT = Path("outputs/latest.json")
DEFAULT_MD_OUT = Path("outputs/latest.md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PathScout role discovery radar.")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create sample config and local folders.")
    add_config_paths(init_parser)
    init_parser.add_argument("--environment", help="Answer for: What is the right environment for you?")
    init_parser.add_argument("--role", help="Answer for: What is the right role for you?")
    init_parser.add_argument("--no-input", action="store_true", help="Create defaults without interactive onboarding prompts.")

    run_parser = subparsers.add_parser("run", help="Fetch sources, score observations, and write artifacts.")
    add_config_paths(run_parser)
    run_parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to SQLite DB.")
    run_parser.add_argument("--out", default=str(DEFAULT_MD_OUT), help="Path to Markdown output.")
    run_parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT), help="Path to JSON artifact output.")
    run_parser.add_argument("--format", choices=["markdown", "json", "both"], default="both", help="Artifact format to write.")
    run_parser.add_argument("--digest-window-days", type=int, default=7, help="Observations to include.")
    run_parser.add_argument("--dry-run", action="store_true", help="Fetch and score without writing DB rows.")

    watchlist_parser = subparsers.add_parser("watchlist", help="Summarize the current company watchlist.")
    watchlist_parser.add_argument("--watchlist", default=str(DEFAULT_WATCHLIST), help="Path to watchlist JSON.")
    watchlist_parser.add_argument("--status", help="Only print companies with this status.")

    review_parser = subparsers.add_parser("review", help="Review findings from a JSON artifact.")
    review_parser.add_argument("--json", dest="json_path", default=str(DEFAULT_JSON_OUT), help="Path to JSON artifact.")
    review_parser.add_argument("--tier", help="Only show findings in this tier.")
    review_parser.add_argument("--include-suppressed", action="store_true", help="Include suppressed findings.")
    review_parser.add_argument("--limit", type=int, default=20, help="Maximum findings to print.")

    suppress_parser = subparsers.add_parser("suppress", help="Suppress a finding by ID.")
    suppress_parser.add_argument("finding_id", help="Finding ID or content hash to suppress.")
    suppress_parser.add_argument("--reason", required=True, help="Human-readable suppression reason.")
    suppress_parser.add_argument("--expires", dest="expires_at", help="Optional expiration date in YYYY-MM-DD format.")
    suppress_parser.add_argument("--scope", default="finding", choices=["finding", "company", "source"], help="Suppression scope.")
    suppress_parser.add_argument("--suppressions", default=str(DEFAULT_SUPPRESSIONS), help="Path to suppressions JSON.")

    doctor_parser = subparsers.add_parser("doctor", help="Validate config, watchlist, and source readiness.")
    add_config_paths(doctor_parser)

    portfolio_parser = subparsers.add_parser("portfolio", help="Summarize portfolio relationship import.")
    portfolio_parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO), help="Path to portfolio JSON.")

    radar_parser = subparsers.add_parser("radar", help="Deprecated alias for portfolio.")
    radar_parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO), help="Path to portfolio JSON.")

    return parser


def add_config_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Path to profile JSON.")
    parser.add_argument("--sources", "--config", dest="sources", default=str(DEFAULT_SOURCES), help="Path to sources JSON.")
    parser.add_argument("--watchlist", default=str(DEFAULT_WATCHLIST), help="Path to watchlist JSON.")
    parser.add_argument("--suppressions", default=str(DEFAULT_SUPPRESSIONS), help="Path to suppressions JSON.")


def collect_onboarding_answers(environment: str | None, role: str | None, no_input: bool) -> tuple[str, str]:
    if no_input:
        return environment or "", role or ""
    if environment is not None and role is not None:
        return environment.strip(), role.strip()
    if not sys.stdin.isatty():
        return environment or "", role or ""
    resolved_environment = environment.strip() if environment is not None else input("What is the right environment for you? ").strip()
    resolved_role = role.strip() if role is not None else input("What is the right role for you? ").strip()
    return resolved_environment, resolved_role


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        profile_path = Path(args.profile)
        ensure_default_files(
            profile_path,
            Path(args.sources),
            Path(args.watchlist),
            Path(args.suppressions),
            DEFAULT_PORTFOLIO,
        )
        environment, role = collect_onboarding_answers(args.environment, args.role, args.no_input)
        if environment or role:
            apply_onboarding_answers(profile_path, environment, role)
        print(f"Initialized PathScout config in {Path(args.sources).parent}")
        return 0

    if args.command == "run":
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", DeprecationWarning)
                config = build_runtime_config(Path(args.sources), Path(args.profile), Path(args.watchlist), Path(args.suppressions))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Setup error: {exc}")
            return 2
        for warning in caught:
            print(f"Warning: {warning.message}")
        _, setup_errors = validate_setup(config, Path(args.watchlist), Path(args.profile), Path(args.sources), Path(args.suppressions))
        if setup_errors:
            for error in setup_errors:
                print(f"Setup error: {error}")
            return 2

        db_path = Path(args.db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)

        conn = connect(db_path)
        init_db(conn)
        result = run_sources(conn, config, dry_run=args.dry_run)
        artifact = build_artifact(
            conn,
            config,
            result,
            window_days=args.digest_window_days,
            dry_run=args.dry_run,
            invocation={
                "command": "run",
                "profile": str(args.profile),
                "sources": str(args.sources),
                "watchlist": str(args.watchlist),
                "suppressions": str(args.suppressions),
                "digest_window_days": args.digest_window_days,
                "format": args.format,
            },
        )
        written = []
        if args.format in {"json", "both"}:
            written.append(write_json_artifact(artifact, Path(args.json_out)))
        if args.format in {"markdown", "both"}:
            written.append(write_markdown_artifact(artifact, Path(args.out)))
        print(f"Fetched {result.fetched_count} items; inserted {result.inserted_count}; skipped {result.skipped_count}.")
        for path in written:
            print(f"Wrote {path}")
        return 0

    if args.command == "watchlist":
        watchlist = load_watchlist(Path(args.watchlist))
        summary = summarize_watchlist(watchlist)
        print(f"Companies: {summary['total']}")
        print(f"Needs review: {summary['needs_review']}")
        print("By status:")
        for status, count in summary["by_status"].items():
            print(f"  {status}: {count}")
        print("Top domains:")
        for domain, count in summary["top_domains"]:
            print(f"  {domain}: {count}")
        if args.status:
            print(f"Companies with status={args.status}:")
            for company in watchlist.get("companies", []):
                if company.get("status") == args.status:
                    print(f"  - {company.get('name')} ({company.get('stage', 'unknown')}; {company.get('location', 'unknown')})")
        return 0

    if args.command == "review":
        return review_findings(Path(args.json_path), args.tier, args.include_suppressed, args.limit)

    if args.command == "suppress":
        return suppress_finding(Path(args.suppressions), args.finding_id, args.reason, args.expires_at, args.scope)

    if args.command == "doctor":
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", DeprecationWarning)
                config = build_runtime_config(Path(args.sources), Path(args.profile), Path(args.watchlist), Path(args.suppressions))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Setup error: {exc}")
            return 2
        for warning in caught:
            print(f"Warning: {warning.message}")
        print(format_doctor_report(config, Path(args.watchlist), Path(args.profile), Path(args.sources), Path(args.suppressions)))
        _, errors = validate_setup(config, Path(args.watchlist), Path(args.profile), Path(args.sources), Path(args.suppressions))
        return 2 if errors else 0

    if args.command == "portfolio":
        return print_portfolio(Path(args.portfolio))

    if args.command == "radar":
        print("Warning: radar is deprecated; use portfolio.")
        return print_portfolio(Path(args.portfolio))

    parser.print_help()
    return 1


def print_portfolio(path: Path) -> int:
    if not path.exists():
        print(f"Missing portfolio file: {path}")
        return 2
    with path.open("r", encoding="utf-8") as handle:
        portfolio = json.load(handle)
    companies = portfolio.get("companies", [])
    print(f"Portfolio relationship companies: {len(companies)}")
    for company in companies:
        print(f"  - {company.get('name')} ({company.get('stage', 'unknown')}; {company.get('status', 'relationship')})")
    return 0


def review_findings(path: Path, tier: str | None, include_suppressed: bool, limit: int) -> int:
    if not path.exists():
        print(f"Missing JSON artifact: {path}")
        return 2
    with path.open("r", encoding="utf-8") as handle:
        artifact = json.load(handle)
    findings = artifact.get("findings", [])
    if tier:
        findings = [finding for finding in findings if finding.get("tier") == tier]
    if not include_suppressed:
        findings = [finding for finding in findings if not finding.get("suppressed")]

    print(f"Findings: {len(findings)}")
    for finding in findings[:limit]:
        finding_id = finding.get("id", "")[:12]
        title = finding.get("title") or "Untitled signal"
        company = finding.get("company") or "Unknown company"
        tier_name = finding.get("tier") or "Unknown"
        score = finding.get("score", 0)
        url = finding.get("url") or ""
        suffix = f" | {url}" if url else ""
        print(f"{finding_id} | {tier_name} | {score} | {company} | {title}{suffix}")
    if len(findings) > limit:
        print(f"... {len(findings) - limit} more")
    return 0


def suppress_finding(path: Path, finding_id: str, reason: str, expires_at: str | None, scope: str) -> int:
    if expires_at:
        try:
            date.fromisoformat(expires_at)
        except ValueError:
            print(f"Invalid --expires date: {expires_at}. Use YYYY-MM-DD.")
            return 2

    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            suppressions = json.load(handle)
    else:
        suppressions = {"schema_version": 1, "suppressions": []}

    entries = suppressions.setdefault("suppressions", [])
    existing = next((entry for entry in entries if entry.get("id") == finding_id and entry.get("scope", "finding") == scope), None)
    entry = {
        "id": finding_id,
        "scope": scope,
        "reason": reason,
        "created_at": date.today().isoformat(),
    }
    if expires_at:
        entry["expires_at"] = expires_at
    if existing is not None:
        existing.update(entry)
        print(f"Updated suppression for {finding_id}")
    else:
        entries.append(entry)
        print(f"Added suppression for {finding_id}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(suppressions, indent=2) + "\n", encoding="utf-8")
    return 0
