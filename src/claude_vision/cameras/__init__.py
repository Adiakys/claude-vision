"""Factory for webcam sources."""

from __future__ import annotations

from ..config import CaptureConfig
from ..session import Session
from .base import WebcamCamera
from .opencv_camera import OpenCvCamera


def select_camera(session: Session, config: CaptureConfig) -> WebcamCamera:
    """OpenCV handles all three OS backends internally, so no platform switching here."""
    return OpenCvCamera(session, config)


__all__ = ["WebcamCamera", "select_camera"]
