"""Factory that picks a recorder for the detected platform."""

from __future__ import annotations

from ..config import CaptureConfig
from ..errors import PlatformUnsupportedError
from ..platform_detect import Platform
from ..session import Session
from .base import ScreenRecorder
from .gnome_wayland import GnomeWaylandRecorder
from .mss_recorder import MssRecorder


def select_recorder(
    platform: Platform, session: Session, config: CaptureConfig
) -> ScreenRecorder:
    if platform in (Platform.X11, Platform.MACOS, Platform.WINDOWS):
        return MssRecorder(session, config)
    if platform is Platform.GNOME_WAYLAND:
        return GnomeWaylandRecorder(session, config)
    raise PlatformUnsupportedError(f"No recorder available for platform {platform}")


__all__ = ["ScreenRecorder", "select_recorder"]
