from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists observations (
            id integer primary key autoincrement,
            source_id text not null,
            source_name text not null,
            source_type text not null,
            company text not null default '',
            title text not null default '',
            url text not null default '',
            text text not null,
            evidence_type text not null default 'signal',
            content_hash text not null unique,
            observed_at text not null,
            score integer not null,
            tier text not null,
            reasons_json text not null,
            flags_json text not null
        );

        create table if not exists runs (
            id integer primary key autoincrement,
            started_at text not null,
            finished_at text not null,
            fetched_count integer not null,
            inserted_count integer not null,
            skipped_count integer not null,
            errors_json text not null
        );

        create index if not exists idx_observations_observed_at on observations(observed_at);
        create index if not exists idx_observations_tier on observations(tier);
        create index if not exists idx_observations_company on observations(company);
        """
    )
    conn.commit()

