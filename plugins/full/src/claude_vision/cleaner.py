"""Deterministic cleanup of session directories."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

SESSION_PREFIX = "claude-vision-"
ACTIVE_STATUSES = {"capturing", "analyzing"}


def clean(session_root: Path) -> bool:
    """Remove a single session directory. Idempotent. Returns True if removed."""
    if not session_root.exists():
        return False
    shutil.rmtree(session_root)
    return True


def purge_stale(root: Path, ttl: timedelta = timedelta(hours=2)) -> list[Path]:
    """
    Remove session dirs that are safe to delete. A session is safe to delete if:
      - its status is 'done', OR
      - it has no marker (corrupt / abandoned), OR
      - its created_at is older than ttl (regardless of status).

    Never removes 'capturing' or 'analyzing' sessions younger than ttl.
    """
    if not root.exists():
        return []

    removed: list[Path] = []
    now = datetime.now(timezone.utc)

    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith(SESSION_PREFIX):
            continue
        if _is_safe_to_delete(entry, now, ttl):
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry)
    return removed


def _is_safe_to_delete(entry: Path, now: datetime, ttl: timedelta) -> bool:
    marker = entry / "session.json"
    if not marker.exists():
        return True
    try:
        data = json.loads(marker.read_text())
    except (OSError, json.JSONDecodeError):
        return True

    status = data.get("status")
    created_raw = data.get("created_at")

    if status == "done":
        return True
    if created_raw:
        try:
            created_at = datetime.fromisoformat(created_raw)
            if now - created_at > ttl:
                return True
        except ValueError:
            return True
    return status not in ACTIVE_STATUSES
