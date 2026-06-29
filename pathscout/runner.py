from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .fetchers import FetchedItem, fetch_source
from .scoring import score_item


@dataclass(frozen=True)
class SourceStat:
    source_id: str
    source_name: str
    source_type: str
    fetched_count: int
    error: str = ""


@dataclass(frozen=True)
class RunResult:
    fetched_count: int
    inserted_count: int
    skipped_count: int
    errors: list[str]
    source_stats: list[SourceStat]
    dry_run_findings: list[dict[str, Any]]


def run_sources(conn: sqlite3.Connection, config: dict[str, Any], dry_run: bool = False) -> RunResult:
    started_at = now_iso()
    fetched_count = 0
    inserted_count = 0
    skipped_count = 0
    errors: list[str] = []
    source_stats: list[SourceStat] = []
    dry_run_findings: list[dict[str, Any]] = []

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        try:
            items = fetch_source(source)
        except Exception as exc:  # The run should survive a single bad source.
            error = f"{source.get('id', 'unknown')}: {exc}"
            errors.append(error)
            source_stats.append(
                SourceStat(
                    source_id=source.get("id", "unknown"),
                    source_name=source.get("name", source.get("id", "unknown")),
                    source_type=source.get("type", "unknown"),
                    fetched_count=0,
                    error=str(exc),
                )
            )
            continue

        fetched_count += len(items)
        source_stats.append(
            SourceStat(
                source_id=source.get("id", "unknown"),
                source_name=source.get("name", source.get("id", "unknown")),
                source_type=source.get("type", "unknown"),
                fetched_count=len(items),
            )
        )
        for item in items:
            result = score_item(item, config)
            content_hash = hash_item(item)
            observed_at = now_iso()
            if dry_run:
                inserted_count += 1
                dry_run_findings.append(
                    {
                        "source_id": item.source_id,
                        "source_name": item.source_name,
                        "source_type": item.source_type,
                        "company": item.company,
                        "title": item.title,
                        "url": item.url,
                        "text": item.text,
                        "evidence_type": item.evidence_type,
                        "content_hash": content_hash,
                        "observed_at": observed_at,
                        "score": result.score,
                        "tier": result.tier,
                        "reasons": result.reasons,
                        "flags": result.flags,
                    }
                )
                continue
            try:
                conn.execute(
                    """
                    insert into observations (
                        source_id, source_name, source_type, company, title, url, text,
                        evidence_type, content_hash, observed_at, score, tier, reasons_json, flags_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.source_id,
                        item.source_name,
                        item.source_type,
                        item.company,
                        item.title,
                        item.url,
                        item.text,
                        item.evidence_type,
                        content_hash,
                        observed_at,
                        result.score,
                        result.tier,
                        json.dumps(result.reasons),
                        json.dumps(result.flags),
                    ),
                )
                inserted_count += 1
            except sqlite3.IntegrityError:
                skipped_count += 1

    finished_at = now_iso()
    if not dry_run:
        conn.execute(
            """
            insert into runs (started_at, finished_at, fetched_count, inserted_count, skipped_count, errors_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (started_at, finished_at, fetched_count, inserted_count, skipped_count, json.dumps(errors)),
        )
        conn.commit()

    return RunResult(
        fetched_count=fetched_count,
        inserted_count=inserted_count,
        skipped_count=skipped_count,
        errors=errors,
        source_stats=source_stats,
        dry_run_findings=dry_run_findings,
    )


def hash_item(item: FetchedItem) -> str:
    material = "\n".join([item.source_id, item.company, item.title, item.url, item.text])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
