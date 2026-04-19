#!/usr/bin/env python3
"""Stop-hook: garbage-collect stale claude-vision session directories.

Stdlib-only so it works with any python3 regardless of whether the
claude_vision package is installed in the interpreter that runs it.

Silent on success. Never blocks the agent.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(tempfile.gettempdir()) / "claude-vision"
SESSION_PREFIX = "claude-vision-"
TTL = timedelta(hours=2)
ACTIVE_STATUSES = {"capturing", "analyzing"}


def main() -> int:
    if not ROOT.exists():
        return 0
    now = datetime.now(timezone.utc)
    for entry in ROOT.iterdir():
        if not entry.is_dir() or not entry.name.startswith(SESSION_PREFIX):
            continue
        if _is_safe_to_delete(entry, now):
            shutil.rmtree(entry, ignore_errors=True)
    return 0


def _is_safe_to_delete(entry: Path, now: datetime) -> bool:
    marker = entry / "session.json"
    if not marker.exists():
        return True
    try:
        data = json.loads(marker.read_text())
    except (OSError, json.JSONDecodeError):
        return True

    if data.get("status") == "done":
        return True
    created_raw = data.get("created_at")
    if created_raw:
        try:
            if now - datetime.fromisoformat(created_raw) > TTL:
                return True
        except ValueError:
            return True
    return data.get("status") not in ACTIVE_STATUSES


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
