"""Abstract base for screen recorders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..config import CaptureConfig
from ..session import Session


class ScreenRecorder(ABC):
    """One recorder per platform strategy. Produces PNG frames on disk."""

    def __init__(self, session: Session, config: CaptureConfig):
        self.session = session
        self.config = config

    @abstractmethod
    def capture(self) -> list[Path]:
        """Record a video and return the ordered list of extracted frame paths."""

    @abstractmethod
    def screenshot(self) -> Path:
        """Grab a single frame and return its path."""
