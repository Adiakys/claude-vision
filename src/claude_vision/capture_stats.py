"""Typed capture-time statistics shared by recorders and cameras.

Replaces the pre-refactor ``stats: dict`` attribute on recorder/camera base
classes. Giving the contract an explicit type makes the CLI layer (which
echoes the numbers into its JSON output) self-documenting and lets
downstream callers get IDE help.

Kept deliberately narrow: the only numbers we expose are frame budget
vs frames actually kept vs frames skipped by the deduper.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dedupe import FrameDeduper


@dataclass(frozen=True)
class CaptureStats:
    """Frame-budget accounting for a video-style capture."""

    planned: int
    kept: int
    skipped: int

    @classmethod
    def from_deduper(
        cls,
        deduper: FrameDeduper | None,
        *,
        planned: int,
        kept: int,
    ) -> "CaptureStats":
        """When the deduper is present, mirror its internal counters so the
        caller sees the real kept/skipped split. When it's disabled, all
        captured frames are kept and nothing is skipped."""
        if deduper is None:
            return cls(planned=planned, kept=kept, skipped=0)
        return cls(
            planned=planned,
            kept=deduper.kept,
            skipped=deduper.skipped,
        )
