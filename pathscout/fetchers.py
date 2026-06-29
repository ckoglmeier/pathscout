from __future__ import annotations

import re
import json
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from typing import Any

from .sources import career_candidates


USER_AGENT = "PathScout role-discovery-radar/0.2"
ROLE_TITLE_TERMS = [
    "chief",
    "svp",
    "general manager",
    "gm",
    "product",
    "growth",
    "business operations",
    "strategy",
    "operations",
    "commercial",
    "partnerships",
]


@dataclass(frozen=True)
class FetchedItem:
    source_id: str
    source_name: str
    source_type: str
    company: str
    title: str
    url: str
    text: str
    evidence_type: str = "signal"


def fetch_source(source: dict[str, Any]) -> list[FetchedItem]:
    source_type = source.get("type", "")
    if source_type == "manual":
        return fetch_manual(source)
    if source_type == "watchlist":
        return fetch_watchlist(source)
    if source_type == "watchlist_careers":
        return fetch_watchlist_careers(source)
    if source_type in {"portfolio", "radar_portfolio"}:
        return fetch_portfolio(source)
    if source_type == "web_page":
        return fetch_web_page(source)
    if source_type == "rss":
        return fetch_rss(source)
    raise ValueError(f"Unsupported source type: {source_type}")


def fetch_manual(source: dict[str, Any]) -> list[FetchedItem]:
    items = []
    for item in source_setting(source, "items", []):
        items.append(
            FetchedItem(
                source_id=source["id"],
                source_name=source.get("name", source["id"]),
                source_type="manual",
                company=item.get("company", ""),
                title=item.get("title", ""),
                url=item.get("url", ""),
                text=item.get("text", ""),
                evidence_type=item.get("evidence_type", "manual"),
            )
        )
    return items


def fetch_watchlist_careers(source: dict[str, Any]) -> list[FetchedItem]:
    started_at = time.monotonic()
    max_elapsed_seconds = int(source_setting(source, "max_elapsed_seconds", 0) or 0)
    path = source_setting(source, "path", "config/watchlist.json")
    with open(path, "r", encoding="utf-8") as handle:
        watchlist = json.load(handle)
    items: list[FetchedItem] = []
    max_companies = int(source_setting(source, "max_companies", 0) or 0)
    companies = [
        company
        for company in watchlist.get("companies", [])
        if company.get("status", "watch") not in {"exclude", "archive"}
    ]
    if max_companies:
        companies = companies[:max_companies]

    for company in companies:
        if max_elapsed_seconds and time.monotonic() - started_at > max_elapsed_seconds:
            break
        urls = company.get("urls", {})
        explicit = urls.get("careers", [])
        if isinstance(explicit, str):
            explicit = [explicit]
        candidates = career_candidates(urls.get("homepage", ""), explicit, source_setting(source, "candidate_paths"))
        for url in candidates:
            try:
                body = http_get(url, timeout=int(source_setting(source, "timeout_seconds", 8)))
            except Exception:
                continue
            text = html_to_text(body)
            if not looks_like_careers_page(text):
                continue
            title = extract_title(body) or f"{company.get('name', 'Company')} careers"
            role_titles = extract_role_titles(body)
            if role_titles:
                for role_title in role_titles:
                    items.append(
                        FetchedItem(
                            source_id=source["id"],
                            source_name=source.get("name", source["id"]),
                            source_type="watchlist_careers",
                            company=company.get("name", ""),
                            title=role_title,
                            url=url,
                            text=f"{role_title}\n{text}",
                            evidence_type="job",
                        )
                    )
            else:
                items.append(
                    FetchedItem(
                        source_id=source["id"],
                        source_name=source.get("name", source["id"]),
                        source_type="watchlist_careers",
                        company=company.get("name", ""),
                        title=title,
                        url=url,
                        text=text,
                        evidence_type="job_page",
                    )
                )
            break
    return items


def fetch_portfolio(source: dict[str, Any]) -> list[FetchedItem]:
    path = source_setting(source, "path", "config/portfolio.json")
    with open(path, "r", encoding="utf-8") as handle:
        portfolio = json.load(handle)
    items = []
    for company in portfolio.get("companies", []):
        status = company.get("status", "invested")
        if status in {"exclude", "archive"}:
            continue
        text_parts = [
            "Portfolio relationship signal",
            company.get("relationship", ""),
            company.get("stage", ""),
            company.get("location", ""),
            " ".join(company.get("domains", [])),
            company.get("notes", ""),
            " ".join(company.get("signals_to_watch", [])),
        ]
        items.append(
            FetchedItem(
                source_id=source["id"],
                source_name=source.get("name", source["id"]),
                source_type=source.get("type", "portfolio"),
                company=company.get("name", ""),
                title=f"Portfolio relationship: {company.get('name', 'Unknown')}",
                url=company.get("urls", {}).get("homepage", ""),
                text=" ".join(part for part in text_parts if part),
                evidence_type=source.get("type", "portfolio"),
            )
        )
    return items


def fetch_radar_portfolio(source: dict[str, Any]) -> list[FetchedItem]:
    return fetch_portfolio(source)


def fetch_watchlist(source: dict[str, Any]) -> list[FetchedItem]:
    path = source_setting(source, "path", "config/watchlist.json")
    with open(path, "r", encoding="utf-8") as handle:
        watchlist = json.load(handle)
    items = []
    for company in watchlist.get("companies", []):
        status = company.get("status", "watch")
        if status in {"exclude", "archive"}:
            continue
        text_parts = [
            company.get("watch_reason", ""),
            company.get("notes", ""),
            " ".join(company.get("domains", [])),
            company.get("stage", ""),
            company.get("location", ""),
            " ".join(company.get("investors", [])),
            " ".join(company.get("signals_to_watch", [])),
        ]
        items.append(
            FetchedItem(
                source_id=source["id"],
                source_name=source.get("name", source["id"]),
                source_type="watchlist",
                company=company.get("name", ""),
                title=f"{status.title()} watchlist company",
                url=company.get("urls", {}).get("homepage", ""),
                text=" ".join(part for part in text_parts if part),
                evidence_type="hidden_search",
            )
        )
    return items


def fetch_web_page(source: dict[str, Any]) -> list[FetchedItem]:
    url = source_setting(source, "url")
    body = http_get(url)
    title = extract_title(body) or source.get("name", url)
    text = html_to_text(body)
    return [
        FetchedItem(
            source_id=source["id"],
            source_name=source.get("name", source["id"]),
            source_type="web_page",
            company=source_setting(source, "company", ""),
            title=title,
            url=url,
            text=text,
            evidence_type=source_setting(source, "evidence_type", "web_page"),
        )
    ]


def fetch_rss(source: dict[str, Any]) -> list[FetchedItem]:
    body = http_get(source_setting(source, "url"))
    root = ET.fromstring(body)
    items: list[FetchedItem] = []
    for node in root.findall(".//item") + root.findall("{http://www.w3.org/2005/Atom}entry"):
        title = find_text(node, ["title", "{http://www.w3.org/2005/Atom}title"])
        link = find_text(node, ["link"])
        atom_link = node.find("{http://www.w3.org/2005/Atom}link")
        if not link and atom_link is not None:
            link = atom_link.attrib.get("href", "")
        summary = find_text(
            node,
            [
                "description",
                "summary",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content",
            ],
        )
        items.append(
            FetchedItem(
                source_id=source["id"],
                source_name=source.get("name", source["id"]),
                source_type="rss",
                company=source_setting(source, "company", ""),
                title=html_to_text(title),
                url=link,
                text=html_to_text(f"{title}\n{summary}"),
                evidence_type=source_setting(source, "evidence_type", "rss"),
            )
        )
    return items


def source_setting(source: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in source:
        return source[key]
    return source.get("config", {}).get(key, default)


def http_get(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc


def extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return " ".join(html_to_text(match.group(1)).split())


def html_to_text(value: str) -> str:
    no_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    no_tags = re.sub(r"<[^>]+>", " ", no_scripts)
    return " ".join(unescape(no_tags).split())


def html_to_lines(value: str) -> list[str]:
    no_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    with_breaks = re.sub(r"</(a|li|h[1-6]|div|p|span|button)>", "\n", no_scripts, flags=re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", with_breaks)
    lines = []
    for line in unescape(no_tags).splitlines():
        normalized = " ".join(line.split())
        if normalized:
            lines.append(normalized)
    return lines


def extract_role_titles(html: str) -> list[str]:
    titles: list[str] = []
    for line in html_to_lines(html):
        candidate = clean_role_title(line)
        if candidate and candidate not in titles:
            titles.append(candidate)
    return titles[:50]


def clean_role_title(line: str) -> str:
    value = line.strip(" -|*")
    if not 4 <= len(value) <= 90:
        return ""
    normalized = value.lower()
    reject_terms = [
        "careers",
        "open roles",
        "open positions",
        "apply now",
        "benefits",
        "privacy",
        "cookie",
        "terms",
        "don't see",
        "talent network",
    ]
    if any(term in normalized for term in reject_terms):
        return ""
    if not any(term in normalized for term in ROLE_TITLE_TERMS):
        return ""
    if normalized.count(" ") > 10:
        return ""
    return value


def find_text(node: ET.Element, names: list[str]) -> str:
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text
    return ""


def looks_like_careers_page(text: str) -> bool:
    normalized = text.lower()
    career_terms = ["careers", "jobs", "open roles", "open positions", "join us", "openings"]
    return any(term in normalized for term in career_terms) and any(term in normalized for term in ROLE_TITLE_TERMS)
