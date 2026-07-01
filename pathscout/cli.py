from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date
from pathlib import Path

from .artifacts import build_artifact, write_json_artifact, write_markdown_artifact, write_package_from_artifact
from .config import (
    DEFAULT_BACKGROUND,
    DEFAULT_PORTFOLIO,
    DEFAULT_PROFILE,
    DEFAULT_SOURCES,
    DEFAULT_SUPPRESSIONS,
    DEFAULT_WATCHLIST,
    apply_onboarding_answers,
    build_runtime_config,
    default_background,
    ensure_default_files,
    load_background,
    load_profile,
)
from .db import connect, init_db
from .doctor import format_doctor_report, validate_setup
from .runner import run_sources
from .watchlist import load_watchlist, summarize_watchlist
from .workflow import (
    DEFAULT_NOTES,
    DEFAULT_THESES_DIR,
    add_note,
    find_finding,
    load_artifact,
    load_notes,
    related_notes,
    render_explanation,
    render_notes,
    write_thesis,
)


DEFAULT_DB = Path("data/pathscout.sqlite")
DEFAULT_JSON_OUT = Path("outputs/latest.json")
DEFAULT_MD_OUT = Path("outputs/latest.md")
DEFAULT_PACKAGE_OUT = Path("outputs/packages")
DEFAULT_BACKGROUND_SAMPLE = Path("config/background.sample.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PathScout role discovery radar.")
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Show the first-run startup checklist.")
    add_startup_paths(start_parser)

    next_parser = subparsers.add_parser("next", aliases=["/next"], help="Show the next recommended PathScout action.")
    add_startup_paths(next_parser)

    setup_parser = subparsers.add_parser("setup", help="Run the guided local setup flow.")
    add_config_paths(setup_parser)
    setup_parser.add_argument("--background", default=str(DEFAULT_BACKGROUND), help="Path to private background JSON.")

    init_parser = subparsers.add_parser("init", help="Create sample config and local folders.")
    add_config_paths(init_parser)
    init_parser.add_argument("--environment", help="Answer for: What is the right environment for you?")
    init_parser.add_argument("--role", help="Answer for: What is the right role for you?")
    init_parser.add_argument("--no-input", action="store_true", help="Create defaults without interactive onboarding prompts.")
    init_parser.add_argument("--background", default=str(DEFAULT_BACKGROUND), help="Path to private background JSON.")

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

    explain_parser = subparsers.add_parser("explain", help="Explain why a finding surfaced.")
    explain_parser.add_argument("finding_id", help="Finding ID or unique prefix.")
    explain_parser.add_argument("--json", dest="json_path", default=str(DEFAULT_JSON_OUT), help="Path to JSON artifact.")
    explain_parser.add_argument("--notes", default=str(DEFAULT_NOTES), help="Path to notes JSON.")

    notes_parser = subparsers.add_parser("notes", help="Add or list local notes for a finding or company.")
    notes_parser.add_argument("finding_id", nargs="?", help="Finding ID or unique prefix.")
    notes_parser.add_argument("--company", help="Company name for company-level notes.")
    notes_parser.add_argument("--add", help="Note body to append.")
    notes_parser.add_argument("--notes", default=str(DEFAULT_NOTES), help="Path to notes JSON.")

    thesis_parser = subparsers.add_parser("thesis", help="Generate a local role-thesis package for a finding.")
    thesis_parser.add_argument("finding_id", help="Finding ID or unique prefix.")
    thesis_parser.add_argument("--json", dest="json_path", default=str(DEFAULT_JSON_OUT), help="Path to JSON artifact.")
    thesis_parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Path to profile JSON.")
    thesis_parser.add_argument("--background", default=str(DEFAULT_BACKGROUND), help="Path to private background JSON.")
    thesis_parser.add_argument("--notes", default=str(DEFAULT_NOTES), help="Path to notes JSON.")
    thesis_parser.add_argument("--out-dir", default=str(DEFAULT_THESES_DIR), help="Directory for generated thesis files.")

    package_parser = subparsers.add_parser("package", help="Export a portable opportunity package for a finding.")
    package_parser.add_argument("finding_id", help="Finding ID or unique prefix to package.")
    package_parser.add_argument("--json", dest="json_path", default=str(DEFAULT_JSON_OUT), help="Path to JSON run artifact.")
    package_parser.add_argument("--out-dir", default=str(DEFAULT_PACKAGE_OUT), help="Directory for package exports.")

    suppress_parser = subparsers.add_parser("suppress", help="Suppress a finding by ID.")
    suppress_parser.add_argument("finding_id", help="Finding ID or content hash to suppress.")
    suppress_parser.add_argument("--reason", required=True, help="Human-readable suppression reason.")
    suppress_parser.add_argument("--expires", dest="expires_at", help="Optional expiration date in YYYY-MM-DD format.")
    suppress_parser.add_argument("--scope", default="finding", choices=["finding", "company", "source"], help="Suppression scope.")
    suppress_parser.add_argument("--suppressions", default=str(DEFAULT_SUPPRESSIONS), help="Path to suppressions JSON.")

    doctor_parser = subparsers.add_parser("doctor", help="Validate config, watchlist, and source readiness.")
    add_config_paths(doctor_parser)
    doctor_parser.add_argument("--background", default=str(DEFAULT_BACKGROUND), help="Path to private background JSON.")

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


def add_startup_paths(parser: argparse.ArgumentParser) -> None:
    add_config_paths(parser)
    parser.add_argument("--background", default=str(DEFAULT_BACKGROUND), help="Path to private background JSON.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to SQLite DB.")
    parser.add_argument("--json", dest="json_path", default=str(DEFAULT_JSON_OUT), help="Path to JSON artifact.")
    parser.add_argument("--notes", default=str(DEFAULT_NOTES), help="Path to notes JSON.")
    parser.add_argument("--theses-dir", default=str(DEFAULT_THESES_DIR), help="Directory for generated thesis files.")


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


def setup_command(
    profile_path: Path,
    sources_path: Path,
    watchlist_path: Path,
    suppressions_path: Path,
    background_path: Path,
) -> int:
    if not sys.stdin.isatty():
        print("Setup requires an interactive terminal. Run `pathscout setup` locally, or edit config/profile.json directly.")
        return 2
    ensure_default_files(profile_path, sources_path, watchlist_path, suppressions_path, DEFAULT_PORTFOLIO, background_path)

    print("PathScout setup")
    print("Press Enter to skip optional prompts. Answers are saved after each step.")
    print("")

    profile = read_json_or_empty(profile_path)
    background = load_setup_background(background_path)

    setup_profile(profile_path, profile)
    setup_background(background_path, background)

    print("")
    print("Setup saved.")
    print("Next: run `pathscout doctor`, then `pathscout run --dry-run --format both`.")
    return 0


def setup_profile(profile_path: Path, profile: dict[str, object]) -> None:
    environment = prompt_for_field(
        profile,
        "environment_preferences",
        "1. What is the right environment for you? ",
        list_field=True,
    )
    if environment:
        write_json_file(profile_path, profile)

    role = prompt_for_field(
        profile,
        "role_preferences",
        "2. What is the right role/function for you? ",
        list_field=True,
    )
    if role:
        target_roles = profile.setdefault("target_roles", [])
        if isinstance(target_roles, list):
            normalized_roles = {str(value).strip().lower() for value in target_roles}
            for value in clean_csv(role):
                if value.lower() not in normalized_roles:
                    target_roles.insert(0, value)
                    normalized_roles.add(value.lower())
        write_json_file(profile_path, profile)

    for field, prompt in [
        ("preferred_locations", "3. Preferred locations? "),
        ("exception_locations", "4. Exception locations you would consider? "),
        ("exclude_domains", "5. Domains to exclude? "),
    ]:
        if prompt_for_field(profile, field, prompt, list_field=True):
            write_json_file(profile_path, profile)

    scoring = profile.setdefault("scoring", {})
    if isinstance(scoring, dict):
        answer = prompt_value("6. Role terms to avoid? ", scoring.get("negative_role_terms"))
        if answer:
            scoring["negative_role_terms"] = clean_csv(answer)
            write_json_file(profile_path, profile)


def setup_background(background_path: Path, background: dict[str, object]) -> None:
    changed = False
    summary = prompt_for_field(
        background,
        "summary",
        "7. Short background summary? ",
        list_field=False,
    )
    changed = bool(summary) or changed

    for field, prompt in [
        ("strengths", "8. Strengths to match against opportunities? "),
        ("proof_points", "9. Proof points / wins? "),
        ("best_environments", "10. Environments where you do your best work? "),
        ("avoid_environments", "11. Environments to avoid? "),
        ("constraints", "12. Constraints PathScout should remember? "),
        ("network_context", "13. Network context / warm paths? "),
    ]:
        changed = bool(prompt_for_field(background, field, prompt, list_field=True)) or changed
        if changed:
            write_json_file(background_path, background)

    if changed:
        write_json_file(background_path, background)


def prompt_for_field(data: dict[str, object], field: str, prompt: str, list_field: bool) -> str:
    answer = prompt_value(prompt, data.get(field))
    if not answer:
        return ""
    data[field] = clean_csv(answer) if list_field else answer
    return answer


def prompt_value(prompt: str, current: object | None) -> str:
    current_text = format_current_value(current)
    suffix = f" [{current_text}]" if current_text else ""
    return input(f"{prompt}{suffix} ").strip()


def format_current_value(current: object | None) -> str:
    if isinstance(current, list):
        return ", ".join(str(item).strip() for item in current if str(item).strip())
    return str(current or "").strip()


def load_setup_background(path: Path) -> dict[str, object]:
    if path.exists():
        return read_json_or_empty(path)
    background = default_background()
    background["summary"] = ""
    for field in ["strengths", "proof_points", "best_environments", "avoid_environments", "constraints", "network_context"]:
        background[field] = []
    write_json_file(path, background)
    return background


def clean_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def write_json_file(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        print_startup_checklist(
            Path(args.profile),
            Path(args.sources),
            Path(args.watchlist),
            Path(args.suppressions),
            Path(args.background),
            Path(args.db),
            Path(args.json_path),
            Path(args.notes),
            Path(args.theses_dir),
        )
        return 0

    if args.command in {"next", "/next"}:
        print_next_action(
            Path(args.profile),
            Path(args.sources),
            Path(args.watchlist),
            Path(args.suppressions),
            Path(args.background),
            Path(args.db),
            Path(args.json_path),
            Path(args.notes),
            Path(args.theses_dir),
        )
        return 0

    if args.command == "setup":
        return setup_command(
            Path(args.profile),
            Path(args.sources),
            Path(args.watchlist),
            Path(args.suppressions),
            Path(args.background),
        )

    if args.command == "init":
        profile_path = Path(args.profile)
        ensure_default_files(
            profile_path,
            Path(args.sources),
            Path(args.watchlist),
            Path(args.suppressions),
            DEFAULT_PORTFOLIO,
            Path(args.background),
        )
        environment, role = collect_onboarding_answers(args.environment, args.role, args.no_input)
        if environment or role:
            apply_onboarding_answers(profile_path, environment, role)
        print(f"Initialized PathScout config in {Path(args.sources).parent}")
        print("Next: run `pathscout setup` to finish guided local configuration.")
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

    if args.command == "explain":
        return explain_finding(Path(args.json_path), Path(args.notes), args.finding_id)

    if args.command == "notes":
        return notes_command(Path(args.notes), args.finding_id or "", args.company or "", args.add or "")

    if args.command == "thesis":
        return thesis_command(
            Path(args.json_path),
            Path(args.profile),
            Path(args.background),
            Path(args.notes),
            Path(args.out_dir),
            args.finding_id,
        )

    if args.command == "package":
        return package_finding(Path(args.json_path), args.finding_id, Path(args.out_dir))

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
        print(format_doctor_report(config, Path(args.watchlist), Path(args.profile), Path(args.sources), Path(args.suppressions), Path(args.background)))
        _, errors = validate_setup(config, Path(args.watchlist), Path(args.profile), Path(args.sources), Path(args.suppressions), Path(args.background))
        return 2 if errors else 0

    if args.command == "portfolio":
        return print_portfolio(Path(args.portfolio))

    if args.command == "radar":
        print("Warning: radar is deprecated; use portfolio.")
        return print_portfolio(Path(args.portfolio))

    parser.print_help()
    return 1


def print_startup_checklist(
    profile_path: Path,
    sources_path: Path,
    watchlist_path: Path,
    suppressions_path: Path,
    background_path: Path,
    db_path: Path,
    json_path: Path,
    notes_path: Path,
    theses_dir: Path,
) -> None:
    state = startup_state(
        profile_path,
        sources_path,
        watchlist_path,
        suppressions_path,
        background_path,
        db_path,
        json_path,
        notes_path,
        theses_dir,
    )
    print("PathScout startup")
    print("")
    for index, item in enumerate(state["items"], start=1):
        status = str(item["status"])
        optional = " (optional)" if item.get("optional") and not status.startswith("optional") else ""
        print(f"{index}. {item['label']}: {status}{optional}")
        detail = item.get("detail")
        if detail:
            print(f"   {detail}")
    print("")
    print(f"Next step: {state['next_step']}")
    print("")
    print("First-run sequence:")
    for command in first_run_sequence():
        print(f"  {command}")
    print("")
    print("Local-only note: PathScout OSS stores state in local files. Network source fetches collect evidence; they are not hosted storage or sync.")


def print_next_action(
    profile_path: Path,
    sources_path: Path,
    watchlist_path: Path,
    suppressions_path: Path,
    background_path: Path,
    db_path: Path,
    json_path: Path,
    notes_path: Path,
    theses_dir: Path,
) -> None:
    state = startup_state(
        profile_path,
        sources_path,
        watchlist_path,
        suppressions_path,
        background_path,
        db_path,
        json_path,
        notes_path,
        theses_dir,
    )
    item = next_startup_item(state["items"])
    print("PathScout next")
    print("")
    print(f"Step: {item['label']}")
    print(f"Status: {item['status']}")
    print(f"Action: {item['detail'] or state['next_step']}")
    print("")
    print("Run `pathscout start` for the full checklist.")


def startup_state(
    profile_path: Path,
    sources_path: Path,
    watchlist_path: Path,
    suppressions_path: Path,
    background_path: Path,
    db_path: Path,
    json_path: Path,
    notes_path: Path,
    theses_dir: Path,
) -> dict[str, object]:
    profile = read_json_or_empty(profile_path)
    watchlist = read_json_or_empty(watchlist_path)
    sources = read_json_or_empty(sources_path)
    doctor_ready = startup_setup_valid(profile_path, sources_path, watchlist_path, suppressions_path, background_path)
    items = [
        checklist_item(
            "Initialize local config",
            all(path.exists() for path in [profile_path, sources_path, watchlist_path, suppressions_path]),
            f"Run `pathscout init` to create config files." if not profile_path.exists() else "",
        ),
        checklist_item(
            "Answer environment and role",
            bool(profile.get("environment_preferences")) and bool(profile.get("role_preferences")),
            "Run `pathscout init` interactively or pass `--environment` and `--role`.",
        ),
        checklist_item(
            "Review watchlist",
            bool(watchlist.get("companies")),
            f"Edit {watchlist_path} with companies you want PathScout to monitor.",
        ),
        checklist_item(
            "Review sources",
            bool(sources.get("sources")),
            f"Edit {sources_path} to enable watchlist, careers, RSS, web page, portfolio, or manual sources.",
        ),
        checklist_item(
            "Add private background",
            background_path.exists(),
            f"Optional: copy {DEFAULT_BACKGROUND_SAMPLE} to {background_path} and add proof points.",
            optional=True,
        ),
        checklist_item(
            "Validate setup",
            doctor_ready,
            "Run `pathscout doctor` after editing config.",
        ),
        checklist_item(
            "Run first scan",
            json_path.exists() or db_path.exists(),
            "Run `pathscout run --dry-run --format both`, then `pathscout run --format both` when ready.",
        ),
        checklist_item(
            "Review findings",
            False,
            "Run `pathscout review` after a JSON artifact exists.",
            ready=json_path.exists(),
        ),
        checklist_item(
            "Explain one finding",
            False,
            "Run `pathscout explain <finding-id>` using an ID from `pathscout review`.",
            ready=json_path.exists(),
        ),
        checklist_item(
            "Add local judgment",
            notes_path.exists(),
            "Run `pathscout notes <finding-id> --add \"...\"` or `pathscout notes --company \"...\" --add \"...\"`.",
        ),
        checklist_item(
            "Draft first role thesis",
            theses_dir.exists() and any(theses_dir.glob("*.md")),
            "Run `pathscout thesis <finding-id>` after reviewing and explaining a finding.",
            ready=json_path.exists(),
        ),
    ]
    return {"items": items, "next_step": next_startup_step(items)}


def checklist_item(label: str, done: bool, detail: str, optional: bool = False, ready: bool = False) -> dict[str, object]:
    if optional and not done:
        status = "optional, not found"
    elif ready and not done:
        status = "ready"
    else:
        status = "done" if done else "needs action"
    return {"label": label, "status": status, "detail": detail if not done else "", "optional": optional, "done": done}


def next_startup_step(items: list[dict[str, object]]) -> str:
    item = next_startup_item(items)
    detail = str(item.get("detail") or "")
    return detail if detail else str(item["label"])


def next_startup_item(items: list[dict[str, object]]) -> dict[str, object]:
    for item in items:
        if item.get("optional"):
            continue
        if not item.get("done"):
            return item
    return {
        "label": "Keep reviewing opportunities",
        "status": "ready",
        "detail": "Run `pathscout review`, choose a finding, then run `pathscout thesis <finding-id>`.",
        "optional": False,
        "done": False,
    }


def first_run_sequence() -> list[str]:
    return [
        "pathscout init",
        "edit config/profile.json and config/watchlist.json",
        "optional: copy config/background.sample.json to config/background.local.json",
        "pathscout doctor",
        "pathscout run --dry-run --format both",
        "pathscout run --format both",
        "pathscout review",
        "pathscout explain <finding-id>",
        "pathscout notes <finding-id> --add \"...\"",
        "pathscout thesis <finding-id>",
    ]


def read_json_or_empty(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def startup_setup_valid(
    profile_path: Path,
    sources_path: Path,
    watchlist_path: Path,
    suppressions_path: Path,
    background_path: Path,
) -> bool:
    try:
        config = build_runtime_config(sources_path, profile_path, watchlist_path, suppressions_path)
        _, errors = validate_setup(config, watchlist_path, profile_path, sources_path, suppressions_path, background_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return not errors


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
        strength = finding.get("evidence_strength", "medium")
        url = finding.get("url") or ""
        suffix = f" | {url}" if url else ""
        print(f"{finding_id} | {tier_name} | {score} | {strength} | {company} | {title}{suffix}")
    if len(findings) > limit:
        print(f"... {len(findings) - limit} more")
    return 0


def explain_finding(artifact_path: Path, notes_path: Path, finding_id: str) -> int:
    try:
        artifact = load_artifact(artifact_path)
        finding = find_finding(artifact, finding_id)
        notes = related_notes(load_notes(notes_path), finding)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, LookupError) as exc:
        print(f"Explain error: {exc}")
        return 2
    print(render_explanation(finding, notes))
    return 0


def notes_command(notes_path: Path, finding_id: str, company: str, body: str) -> int:
    try:
        if body:
            entry = add_note(notes_path, body, finding_id=finding_id, company=company)
            target = entry.get("finding_id") or entry.get("company")
            print(f"Added note {entry['id']} for {target}")
            return 0
        if not finding_id and not company:
            print("Notes error: provide a finding ID or --company")
            return 2
        notes = related_notes(load_notes(notes_path), {"id": finding_id, "company": company}, company=company)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Notes error: {exc}")
        return 2
    print(render_notes(notes))
    return 0


def thesis_command(
    artifact_path: Path,
    profile_path: Path,
    background_path: Path,
    notes_path: Path,
    out_dir: Path,
    finding_id: str,
) -> int:
    try:
        artifact = load_artifact(artifact_path)
        finding = find_finding(artifact, finding_id)
        profile = load_profile(profile_path)
        background = load_background(background_path)
        notes = related_notes(load_notes(notes_path), finding)
        path = write_thesis(finding, profile, background, notes, out_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, LookupError, OSError) as exc:
        print(f"Thesis error: {exc}")
        return 2
    if not background:
        print(f"Warning: missing optional background file: {background_path}")
    print(f"Wrote {path}")
    return 0


def package_finding(path: Path, finding_id: str, out_dir: Path) -> int:
    if not path.exists():
        print(f"Missing JSON artifact: {path}")
        return 2
    with path.open("r", encoding="utf-8") as handle:
        artifact = json.load(handle)
    try:
        package_dir = write_package_from_artifact(artifact, finding_id, out_dir)
    except ValueError as exc:
        print(str(exc))
        return 2
    print(f"Wrote package {package_dir}")
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
