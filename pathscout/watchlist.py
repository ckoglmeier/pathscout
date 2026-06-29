from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_WATCHLIST = Path("config/watchlist.json")


def load_watchlist(path: Path = DEFAULT_WATCHLIST) -> dict[str, Any]:
    if not path.exists():
        return {"companies": []}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def attach_watchlist(config: dict[str, Any], path: Path = DEFAULT_WATCHLIST) -> dict[str, Any]:
    config = dict(config)
    config["watchlist"] = load_watchlist(path)
    return config


def company_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    companies = []
    companies.extend(config.get("companies", []))
    companies.extend(config.get("watchlist", {}).get("companies", []))
    index = {}
    for company in companies:
        name = company.get("name", "")
        if name:
            index[normalize_company(name)] = company
    return index


def lookup_company(config: dict[str, Any], name: str) -> dict[str, Any] | None:
    if not name:
        return None
    return company_index(config).get(normalize_company(name))


def normalize_company(name: str) -> str:
    return " ".join(name.lower().replace(".", "").replace(",", "").split())


def summarize_watchlist(watchlist: dict[str, Any]) -> dict[str, Any]:
    companies = watchlist.get("companies", [])
    by_status: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    by_location: dict[str, int] = {}
    needs_review = 0
    for company in companies:
        status = company.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        if company.get("needs_review"):
            needs_review += 1
        for domain in company.get("domains", []):
            by_domain[domain] = by_domain.get(domain, 0) + 1
        location = company.get("location", "Unknown")
        by_location[location] = by_location.get(location, 0) + 1
    return {
        "total": len(companies),
        "needs_review": needs_review,
        "by_status": dict(sorted(by_status.items())),
        "top_domains": sorted(by_domain.items(), key=lambda item: item[1], reverse=True)[:12],
        "top_locations": sorted(by_location.items(), key=lambda item: item[1], reverse=True)[:12],
    }

