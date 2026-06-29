from __future__ import annotations

from urllib.parse import urljoin, urlparse


DEFAULT_CAREER_PATHS = [
    "careers",
    "jobs",
]


def career_candidates(
    homepage: str,
    explicit_urls: list[str] | None = None,
    candidate_paths: list[str] | None = None,
) -> list[str]:
    urls: list[str] = []
    for url in explicit_urls or []:
        add_unique(urls, normalize_url(url))
    homepage = normalize_url(homepage)
    if not homepage:
        return urls
    for path in candidate_paths or DEFAULT_CAREER_PATHS:
        add_unique(urls, urljoin(homepage.rstrip("/") + "/", path))
    return urls


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
    return url


def add_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)
