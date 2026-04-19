"""Identify the host environment and select the recorder strategy."""

from __future__ import annotations

import os
import shutil
import sys
from enum import Enum

from .errors import PlatformUnsupportedError


class Platform(str, Enum):
    X11 = "x11"
    MACOS = "macos"
    WINDOWS = "windows"
    GNOME_WAYLAND = "gnome_wayland"
    UNSUPPORTED_WAYLAND = "unsupported_wayland"


def detect() -> Platform:
    if sys.platform == "darwin":
        return Platform.MACOS
    if sys.platform in ("win32", "cygwin"):
        return Platform.WINDOWS

    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland":
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        if "GNOME" in desktop:
            return Platform.GNOME_WAYLAND
        return Platform.UNSUPPORTED_WAYLAND

    return Platform.X11


def preflight(platform: Platform) -> None:
    """Raise a clear error if the detected platform can't be used as-is."""
    if platform is Platform.UNSUPPORTED_WAYLAND:
        raise PlatformUnsupportedError(
            "Wayland session detected but compositor is not GNOME. "
            "Supported: X11, macOS, Windows, GNOME Wayland. "
            "Workaround: log into an X11 session (GDM: select 'Xorg' at login)."
        )
    if platform is Platform.GNOME_WAYLAND:
        if shutil.which("gdbus") is None:
            raise PlatformUnsupportedError(
                "GNOME Wayland detected but 'gdbus' is not on PATH. "
                "Install glib2 tooling (e.g. `apt install libglib2.0-bin`)."
            )
