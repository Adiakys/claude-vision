"""Cross-platform desktop notifications for capture lifecycle events.

Used to tell the user (outside Claude Code) when a recording starts and
ends — screen/webcam captures run opaquely from the user's point of view,
and a small toast is the least-intrusive way to surface the boundaries.

Fails silently when no notification backend is available: the capture
itself must never block on the user seeing the notification.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

APP_NAME = "claude-vision"
DEFAULT_TIMEOUT_MS = 2500


def notify(message: str, *, title: str = APP_NAME) -> None:
    """Emit an OS notification. Never raises."""
    backends = {
        "linux": _notify_linux,
        "darwin": _notify_macos,
        "win32": _notify_windows,
        "cygwin": _notify_windows,
    }
    for prefix, fn in backends.items():
        if sys.platform.startswith(prefix):
            try:
                fn(title, message)
            except Exception:
                pass
            return


def _notify_linux(title: str, message: str) -> None:
    if shutil.which("notify-send") is None:
        return
    subprocess.Popen(
        [
            "notify-send",
            f"--app-name={APP_NAME}",
            f"--expire-time={DEFAULT_TIMEOUT_MS}",
            title,
            message,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _notify_macos(title: str, message: str) -> None:
    if shutil.which("osascript") is None:
        return
    # escape quotes inside the message
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')
    script = (
        f'display notification "{safe_message}" with title "{safe_title}"'
    )
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _notify_windows(title: str, message: str) -> None:
    if shutil.which("powershell") is None:
        return
    safe_title = title.replace('"', '`"')
    safe_message = message.replace('"', '`"')
    script = (
        f'New-BurntToastNotification -Text "{safe_title}", "{safe_message}"'
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
