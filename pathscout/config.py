from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_PROFILE = Path("config/profile.json")
DEFAULT_SOURCES = Path("config/sources.json")
DEFAULT_WATCHLIST = Path("config/watchlist.json")
DEFAULT_SUPPRESSIONS = Path("config/suppressions.json")
DEFAULT_PORTFOLIO = Path("config/portfolio.json")
DEFAULT_CONFIG = DEFAULT_SOURCES


def ensure_default_files(
    profile_path: Path = DEFAULT_PROFILE,
    sources_path: Path = DEFAULT_SOURCES,
    watchlist_path: Path = DEFAULT_WATCHLIST,
    suppressions_path: Path = DEFAULT_SUPPRESSIONS,
    portfolio_path: Path = DEFAULT_PORTFOLIO,
) -> None:
    write_json_if_missing(profile_path, default_profile())
    write_json_if_missing(sources_path, default_sources(watchlist_path, portfolio_path))
    write_json_if_missing(watchlist_path, default_watchlist())
    write_json_if_missing(suppressions_path, default_suppressions())
    write_json_if_missing(portfolio_path, default_portfolio())
    Path("data").mkdir(exist_ok=True)
    Path("outputs").mkdir(exist_ok=True)


def ensure_default_config(path: Path = DEFAULT_CONFIG) -> None:
    if path == DEFAULT_CONFIG:
        ensure_default_files()
        return
    write_json_if_missing(path, default_sources(DEFAULT_WATCHLIST, DEFAULT_PORTFOLIO))


def write_json_if_missing(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    return load_json(path)


def apply_onboarding_answers(profile_path: Path, environment: str, role: str) -> None:
    profile = load_json(profile_path)
    if environment:
        profile["environment_preferences"] = [environment]
    if role:
        profile["role_preferences"] = [role]
        target_roles = profile.setdefault("target_roles", [])
        normalized_roles = {str(value).strip().lower() for value in target_roles}
        if role.strip().lower() not in normalized_roles:
            target_roles.insert(0, role)
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


def load_profile(profile_path: Path, sources_config: dict[str, Any] | None = None) -> dict[str, Any]:
    if profile_path.exists():
        profile = load_json(profile_path)
        validate_schema_version(profile, profile_path)
        return profile
    if sources_config and "profile" in sources_config:
        warnings.warn(
            "Embedding profile in sources.json is deprecated; move it to config/profile.json.",
            DeprecationWarning,
            stacklevel=2,
        )
        return sources_config["profile"]
    return {}


def load_sources(path: Path = DEFAULT_SOURCES) -> dict[str, Any]:
    sources = load_json(path)
    if sources.get("schema_version") != SCHEMA_VERSION:
        if "profile" not in sources:
            validate_schema_version(sources, path)
        warnings.warn(
            "Legacy sources.json without schema_version is deprecated; run pathscout init and migrate sources.",
            DeprecationWarning,
            stacklevel=2,
        )
    return sources


def load_suppressions(path: Path = DEFAULT_SUPPRESSIONS) -> dict[str, Any]:
    if not path.exists():
        return default_suppressions()
    suppressions = load_json(path)
    validate_schema_version(suppressions, path)
    return suppressions


def build_runtime_config(
    sources_path: Path = DEFAULT_SOURCES,
    profile_path: Path = DEFAULT_PROFILE,
    watchlist_path: Path = DEFAULT_WATCHLIST,
    suppressions_path: Path = DEFAULT_SUPPRESSIONS,
) -> dict[str, Any]:
    from .watchlist import load_watchlist

    sources_config = load_sources(sources_path)
    legacy_profile = not profile_path.exists() and "profile" in sources_config
    legacy_sources = sources_config.get("schema_version") != SCHEMA_VERSION
    profile = load_profile(profile_path, sources_config)
    suppressions = load_suppressions(suppressions_path)
    config = dict(sources_config)
    config["profile"] = profile
    config["_legacy_profile"] = legacy_profile
    config["_legacy_sources"] = legacy_sources
    config["scoring"] = profile.get("scoring", sources_config.get("scoring", {}))
    config["watchlist"] = load_watchlist(watchlist_path)
    config["suppressions"] = suppressions
    return config


def validate_schema_version(data: dict[str, Any], path: Path) -> None:
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"{path} has unsupported or missing schema_version: {version!r}")


def default_profile() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "target_name": "Startup role seeker",
        "target_roles": [
            "product manager",
            "product lead",
            "founding product manager",
            "founding operator",
            "business operations",
            "strategy and operations",
            "growth lead",
            "chief of staff",
            "chief product officer",
            "general manager",
            "founder in residence",
            "entrepreneur in residence",
        ],
        "stage_focus": ["Series A", "Series B", "Series C"],
        "include_domains": [
            "ai",
            "robotics",
            "autonomy",
            "dual-use",
            "industrial automation",
            "marketplace",
            "logistics",
        ],
        "exclude_domains": ["dev tools", "developer tools", "healthcare", "biotech", "pharma"],
        "exclude_ownership": ["private equity", "PE-backed", "rollup"],
        "preferred_locations": ["Remote", "Denver", "Boulder"],
        "exception_locations": ["Bay Area", "Los Angeles", "San Diego", "Boston", "New York"],
        "travel_limit": "Up to one week per month",
        "authority_requirements": [
            "reports to CEO",
            "reports to founder",
            "leadership team",
            "P&L",
            "business line ownership",
        ],
        "scoring": default_scoring(),
    }


def default_scoring() -> dict[str, Any]:
    return {
        "act_now_threshold": 78,
        "hidden_search_threshold": 64,
        "watch_threshold": 35,
        "positive_role_terms": [
            "chief product officer",
            "cpo",
            "product manager",
            "product lead",
            "founding product manager",
            "founding operator",
            "business operations",
            "strategy and operations",
            "growth lead",
            "chief of staff",
            "general manager",
            "gm",
            "founder in residence",
            "entrepreneur in residence",
            "eir",
        ],
        "negative_role_terms": [
            "special projects",
            "director",
            "senior director",
            "product operations",
            "product ops",
            "principal product manager",
            "group product manager",
        ],
        "hidden_search_terms": [
            "series a",
            "series b",
            "series c",
            "raised",
            "funding",
            "commercialization",
            "go-to-market",
            "gtm",
            "scale",
            "category",
            "platform",
            "enterprise adoption",
            "customer deployment",
            "pilot",
            "manufacturing",
            "field operations",
            "deployment",
            "strategic partnerships",
        ],
        "authority_terms": [
            "reports to ceo",
            "reports to founder",
            "founder-facing",
            "leadership team",
            "p&l",
            "profit and loss",
            "business line",
            "board-facing",
            "own the business",
            "general manager",
        ],
        "remote_terms": ["remote", "denver", "boulder", "colorado"],
        "exception_location_terms": ["bay area", "san francisco", "los angeles", "san diego", "boston", "new york", "nyc"],
        "travel_risk_terms": ["relocation required", "onsite", "5 days", "extensive travel", "75% travel", "50% travel"],
    }


def default_sources(watchlist_path: Path, portfolio_path: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sources": [
            {
                "id": "company_watchlist",
                "type": "watchlist",
                "name": "Company watchlist",
                "enabled": True,
                "config": {"path": str(watchlist_path)},
            },
            {
                "id": "watchlist_careers",
                "type": "watchlist_careers",
                "name": "Watchlist careers pages",
                "enabled": True,
                "config": {
                    "path": str(watchlist_path),
                    "timeout_seconds": 3,
                    "candidate_paths": ["careers", "jobs"],
                    "max_elapsed_seconds": 300,
                },
            },
            {
                "id": "portfolio",
                "type": "portfolio",
                "name": "Portfolio relationship signals",
                "enabled": True,
                "config": {"path": str(portfolio_path)},
            },
            {
                "id": "manual_seed_notes",
                "type": "manual",
                "name": "Manual seed notes",
                "enabled": True,
                "config": {"items": []},
            },
        ],
    }


def default_watchlist() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "methodology": "Fictional sample watchlist for fit-based startup role discovery.",
        "companies": [
            {
                "name": "Northstar Robotics",
                "status": "strong",
                "stage": "Series B",
                "domains": ["robotics", "logistics"],
                "location": "Remote",
                "watch_reason": "Scaling field deployments and likely to need business-line leadership.",
                "signals_to_watch": ["new GM role", "customer deployment expansion"],
                "urls": {"homepage": "https://example.com/northstar"},
            },
            {
                "name": "Atlas Foundry",
                "status": "watch",
                "stage": "Series A",
                "domains": ["industrial automation", "manufacturing"],
                "location": "Denver",
                "watch_reason": "Early commercialization signal in a complex physical-world market.",
                "signals_to_watch": ["commercial leadership hire", "factory launch"],
                "urls": {"homepage": "https://example.com/atlas"},
            },
            {
                "name": "Vector Market",
                "status": "watch",
                "stage": "Series C",
                "domains": ["ai", "marketplace"],
                "location": "Remote",
                "watch_reason": "Marketplace with possible hiring need as enterprise adoption grows.",
                "signals_to_watch": ["new vertical", "P&L owner"],
                "urls": {"homepage": "https://example.com/vector"},
            },
        ],
    }


def default_suppressions() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "suppressions": []}


def default_portfolio() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "notes": "Companies where you have a relationship or investment context.",
        "companies": [],
    }
