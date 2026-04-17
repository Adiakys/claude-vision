"""Capture configuration — a single frozen dataclass drives the whole pipeline."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import InvalidConfigError

MAX_DURATION_S = 120.0
MAX_FRAMES_CAP = 24


def _default_session_root() -> Path:
    return Path(tempfile.gettempdir()) / "claude-vision"


@dataclass(frozen=True)
class CaptureConfig:
    """Config for both video capture and single-frame screenshot modes.

    ``duration_s``/``fps``/``max_frames`` are only consulted in video mode;
    ``scale_width``/``monitor_index`` apply to both.
    """

    duration_s: float = 1.0
    fps: float = 1.0
    max_frames: int = MAX_FRAMES_CAP
    scale_width: int = 1568
    monitor_index: int = 0
    session_root: Path = field(default_factory=_default_session_root)

    def __post_init__(self) -> None:
        if self.duration_s <= 0 or self.duration_s > MAX_DURATION_S:
            raise InvalidConfigError(
                f"duration_s must be in (0, {MAX_DURATION_S}]; got {self.duration_s}"
            )
        if self.fps <= 0:
            raise InvalidConfigError(f"fps must be > 0; got {self.fps}")
        if self.max_frames <= 0 or self.max_frames > MAX_FRAMES_CAP:
            raise InvalidConfigError(
                f"max_frames must be in [1, {MAX_FRAMES_CAP}]; got {self.max_frames}"
            )
        if self.scale_width < 0:
            raise InvalidConfigError(
                f"scale_width must be >= 0 (0 = no resize); got {self.scale_width}"
            )
        if self.monitor_index < 0:
            raise InvalidConfigError(
                f"monitor_index must be >= 0; got {self.monitor_index}"
            )

    def effective_fps(self) -> float:
        """Capped fps so the total frame count never exceeds ``max_frames``."""
        return min(self.fps, self.max_frames / self.duration_s)

    def planned_frame_count(self) -> int:
        return max(1, int(round(self.effective_fps() * self.duration_s)))
