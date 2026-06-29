from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .watchlist import lookup_company


@dataclass(frozen=True)
class ScoreResult:
    score: int
    tier: str
    reasons: list[str]
    flags: list[str]


def score_item(item: Any, config: dict[str, Any]) -> ScoreResult:
    scoring = config.get("scoring", {})
    profile = config.get("profile", {})
    title_text = normalize(getattr(item, "title", ""))
    body_text = normalize(" ".join([getattr(item, "company", ""), getattr(item, "title", ""), getattr(item, "text", "")]))
    evidence_type = normalize(getattr(item, "evidence_type", ""))

    score = 0
    reasons: list[str] = []
    flags: list[str] = []

    positive_roles = matches(title_text, scoring.get("positive_role_terms", []))
    body_positive_roles = matches(body_text, scoring.get("positive_role_terms", []))
    negative_roles = matches(title_text, scoring.get("negative_role_terms", []))
    body_negative_roles = matches(body_text, scoring.get("negative_role_terms", []))
    hidden_terms = matches(body_text, scoring.get("hidden_search_terms", []))
    authority_terms = matches(body_text, scoring.get("authority_terms", []))
    include_domains = matches(body_text, profile.get("include_domains", []))
    exclude_domains = matches(body_text, profile.get("exclude_domains", []))
    exclude_ownership = matches(body_text, profile.get("exclude_ownership", []))
    remote_terms = matches(body_text, scoring.get("remote_terms", []))
    exception_locations = matches(body_text, scoring.get("exception_location_terms", []))
    travel_risks = matches(body_text, scoring.get("travel_risk_terms", []))
    explicit_role_source = evidence_type in {"job", "job_posting", "role", "recruiter", "search_firm"}
    watchlist_company = lookup_company(config, getattr(item, "company", ""))

    if positive_roles:
        score += 38
        reasons.append("target role title signal: " + ", ".join(positive_roles[:4]))
    elif body_positive_roles and explicit_role_source:
        score += 28
        positive_roles = body_positive_roles
        reasons.append("target role signal: " + ", ".join(body_positive_roles[:4]))
    elif body_positive_roles:
        score += 6
        reasons.append("target role context: " + ", ".join(body_positive_roles[:4]))
    if "svp" in positive_roles:
        score += 6
        reasons.append("SVP title is eligible when traditionally leveled")
    if negative_roles:
        score -= 35
        flags.append("lower-priority role signal: " + ", ".join(negative_roles[:4]))
    elif body_negative_roles:
        score -= 12
        flags.append("lower-priority role context: " + ", ".join(body_negative_roles[:4]))
    if authority_terms:
        score += 24
        reasons.append("authority signal: " + ", ".join(authority_terms[:4]))
    if hidden_terms:
        score += min(24, 6 * len(hidden_terms))
        reasons.append("hidden-search company signal: " + ", ".join(hidden_terms[:5]))
    if include_domains:
        score += min(20, 5 * len(include_domains))
        reasons.append("domain fit: " + ", ".join(include_domains[:5]))
    if remote_terms:
        score += 10
        reasons.append("location fit: " + ", ".join(remote_terms[:3]))
    elif exception_locations:
        score += 5
        reasons.append("possible hybrid exception market: " + ", ".join(exception_locations[:3]))
    if "hidden_search" in evidence_type:
        score += 12
        reasons.append("source marked as hidden-search evidence")
    if "portfolio" in evidence_type:
        score += 18
        reasons.append("portfolio/company relationship signal")
    if watchlist_company:
        status = watchlist_company.get("status", "watch")
        if status == "dream":
            score += 16
            reasons.append("dream-company watchlist match")
        elif status == "strong":
            score += 12
            reasons.append("strong watchlist match")
        elif status == "watch":
            score += 6
            reasons.append("watchlist match")
        elif status in {"exclude", "archive"}:
            score -= 60
            flags.append(f"watchlist status is {status}")

    if exclude_domains:
        score -= 50
        flags.append("excluded domain: " + ", ".join(exclude_domains[:4]))
    if exclude_ownership:
        score -= 35
        flags.append("excluded ownership signal: " + ", ".join(exclude_ownership[:4]))
    if travel_risks:
        score -= 22
        flags.append("travel/location risk: " + ", ".join(travel_risks[:4]))

    has_target_role = bool(positive_roles and not negative_roles)
    has_authority = bool(authority_terms)
    has_hidden_signal = bool(hidden_terms and include_domains)
    watchlist_status = watchlist_company.get("status") if watchlist_company else ""
    priority_watchlist_match = watchlist_status in {"dream", "strong"}

    if watchlist_company and watchlist_company.get("status") in {"exclude", "archive"}:
        tier = "Filtered"
    elif exclude_domains or exclude_ownership:
        tier = "Filtered"
    elif score >= scoring.get("act_now_threshold", 78) and has_target_role and explicit_role_source:
        tier = "Act Now"
    elif score >= scoring.get("hidden_search_threshold", 64) and has_hidden_signal:
        tier = "Hidden Search Hypothesis"
    elif "portfolio" in evidence_type and score >= scoring.get("watch_threshold", 35):
        tier = "Hidden Search Hypothesis"
    elif priority_watchlist_match and score >= scoring.get("watch_threshold", 35) and has_hidden_signal:
        tier = "Hidden Search Hypothesis"
    elif score >= scoring.get("watch_threshold", 35):
        tier = "Watch Signal"
    else:
        tier = "Filtered"

    if not reasons:
        reasons.append("captured for dedupe/history, but no strong fit signal")

    return ScoreResult(score=max(0, min(100, score)), tier=tier, reasons=reasons, flags=flags)


def normalize(value: str) -> str:
    return " ".join(value.lower().replace("/", " ").replace("-", " ").split())


def matches(text: str, terms: list[str]) -> list[str]:
    found = []
    for term in terms:
        normalized = normalize(term)
        if not normalized:
            continue
        if " " not in normalized and len(normalized) <= 3:
            pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
            if re.search(pattern, text):
                found.append(term)
        elif normalized in text:
            found.append(term)
    return found
