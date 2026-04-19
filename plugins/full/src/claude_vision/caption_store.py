"""Persistent append-only log of captions produced during a watch session.

One JSONL file per session at ``<session-root>/captions.jsonl``. Each line
is an independent JSON object so the file can be read with stdlib tools
and is safe to append from a long-running daemon.

The log is the cheap text view of what the daemon saw: Claude reads it
instead of raw frames for retrospective queries, trading some fidelity
for ~50x fewer tokens on multi-minute watches.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .session import Session

CAPTIONS_FILENAME = "captions.jsonl"


@dataclass(frozen=True)
class CaptionEntry:
    """One row of the caption log."""

    timestamp_ms: int
    frame_path: str
    caption: str
    # Reserved for v0.8+ proactive triggers (CLIP match on user query).
    trigger_match: bool = False


def _captions_path(session: Session) -> Path:
    return session.root / CAPTIONS_FILENAME


def append_caption(session: Session, entry: CaptionEntry) -> None:
    """Atomic append. Safe to call from the watch daemon between frame
    captures without worrying about concurrent readers seeing a partial
    line: each call writes one complete line with a newline terminator."""
    line = json.dumps(asdict(entry), separators=(",", ":")) + "\n"
    path = _captions_path(session)
    # Append via low-level open with O_APPEND — POSIX guarantees that
    # writes < PIPE_BUF are atomic with respect to other writers, and
    # our lines are always well under that threshold (a few hundred bytes).
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def read_captions(
    session: Session,
    *,
    since_ms: int | None = None,
    only_matches: bool = False,
) -> list[CaptionEntry]:
    """Read the caption log, optionally filtered by time cutoff or only
    those rows where a proactive trigger matched (v0.8+ feature)."""
    path = _captions_path(session)
    if not path.exists():
        return []

    out: list[CaptionEntry] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Tolerate a torn last line if the daemon was killed
                # mid-write — skip silently.
                continue
            entry = CaptionEntry(
                timestamp_ms=int(data.get("timestamp_ms", 0)),
                frame_path=str(data.get("frame_path", "")),
                caption=str(data.get("caption", "")),
                trigger_match=bool(data.get("trigger_match", False)),
            )
            if since_ms is not None and entry.timestamp_ms < since_ms:
                continue
            if only_matches and not entry.trigger_match:
                continue
            out.append(entry)
    return out


def count_captions(session: Session) -> int:
    """Cheap row count without loading all entries into memory."""
    path = _captions_path(session)
    if not path.exists():
        return 0
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    return count


def truncate_captions(session: Session) -> None:
    """Reset the log (used by tests). Idempotent."""
    path = _captions_path(session)
    if path.exists():
        path.unlink()
