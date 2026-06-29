from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import build_artifact, write_markdown_artifact


def write_digest(conn: Any, config: dict[str, Any], path: Path, window_days: int, dry_run: bool, run_result: Any) -> Path:
    artifact = build_artifact(
        conn,
        config,
        run_result,
        window_days,
        dry_run,
        {"command": "run", "digest_window_days": window_days},
    )
    return write_markdown_artifact(artifact, path)
