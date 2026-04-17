"""Abstract base for webcam sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..config import CaptureConfig
from ..session import Session


class WebcamCamera(ABC):
    """One camera strategy per library (currently only OpenCV). Produces PNG frames on disk."""

    def __init__(self, session: Session, config: CaptureConfig):
        self.session = session
        self.config = config

    @abstractmethod
    def snapshot(self) -> Path:
        """Grab a single frame and return its path."""

    @abstractmethod
    def record(self) -> list[Path]:
        """Record a short video and return the ordered list of frame paths."""
