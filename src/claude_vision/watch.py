"""Continuous background screen watch with live queries.

Three collaborators, each with a single responsibility:

* :class:`WatchMarker` is a tiny JSON file at a fixed path that answers the
  question "is there a watch running right now, and if so for which
  session?". It self-heals when the daemon's PID is no longer alive.

* :func:`run_daemon` is what the forked child actually does: a simple
  fps-paced capture loop with dedupe, terminating cleanly on SIGTERM.

* :class:`WatchController` exposes the parent-side operations — start a
  new watch, stop the running one, query its status, and grab a fresh
  frame into the live session.

Frame naming in watch sessions is timestamp-based (``frame_<epoch_ms>.png``)
so that the daemon's loop and ad-hoc fresh-grab commands can write to the
same ``frames/`` directory without coordinating on an index.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import mss
from PIL import Image

from .config import CaptureConfig
from .dedupe import FrameDeduper
from .errors import CaptureError
from .notify import notify
from .recorders.mss_recorder import _maybe_resize
from .session import Session

MARKER_PATH = Path.home() / ".local" / "state" / "claude-vision" / "active-watch.json"

# Upper bound for a single watch session. Guards against forgotten watches
# accumulating frames for hours.
MAX_WATCH_DURATION_S = 60 * 60  # 1 hour


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_epoch_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Marker: single source of truth for "is a watch running?"


@dataclass
class WatchMarker:
    session_id: str
    session_path: Path
    pid: int
    started_at: str
    fps: float

    @classmethod
    def load_active(cls) -> "WatchMarker | None":
        """Return the marker if present **and** its PID is still alive.
        A stale marker (process gone) is removed as a side effect so the
        next ``watch start`` can proceed cleanly.
        """
        if not MARKER_PATH.exists():
            return None
        try:
            raw = json.loads(MARKER_PATH.read_text())
            marker = cls(
                session_id=raw["session_id"],
                session_path=Path(raw["session_path"]),
                pid=int(raw["pid"]),
                started_at=raw["started_at"],
                fps=float(raw["fps"]),
            )
        except (OSError, ValueError, KeyError):
            cls._unlink_silent()
            return None
        if not _pid_alive(marker.pid):
            cls._unlink_silent()
            return None
        return marker

    def save(self) -> None:
        MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        MARKER_PATH.write_text(
            json.dumps(
                {
                    "session_id": self.session_id,
                    "session_path": str(self.session_path),
                    "pid": self.pid,
                    "started_at": self.started_at,
                    "fps": self.fps,
                },
                indent=2,
            )
        )

    @staticmethod
    def clear() -> None:
        WatchMarker._unlink_silent()

    @staticmethod
    def _unlink_silent() -> None:
        try:
            MARKER_PATH.unlink()
        except FileNotFoundError:
            pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists but is owned by someone else; for our purposes
        # that counts as "alive" (we'd still fail to signal it, but the
        # marker isn't stale).
        return True
    return True


# ---------------------------------------------------------------------------
# Daemon: runs in the forked child


def run_daemon(session: Session, config: CaptureConfig) -> None:
    """Endless fps-paced capture loop. Exits cleanly on SIGTERM.

    Intended to be called by the forked child; the parent returns
    immediately after the fork.
    """
    stop = _SignalStop()
    interval = 1.0 / max(config.fps, 0.001)
    deduper = FrameDeduper(config.dedupe_threshold) if config.dedupe else None
    deadline = time.monotonic() + MAX_WATCH_DURATION_S

    with mss.mss() as sct:
        monitor = _resolve_monitor(sct, config)
        next_tick = time.monotonic()
        while not stop.requested and time.monotonic() < deadline:
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            try:
                image = _grab_image(sct, monitor)
            except Exception:
                # A transient screenshot error (display unplugged, etc.)
                # shouldn't kill the watch; skip the tick.
                next_tick = time.monotonic() + interval
                continue
            if deduper is None or deduper.should_keep(image):
                _save_frame(image, session, config.scale_width)
            next_tick += interval
    session.mark("done")


class _SignalStop:
    """Tiny signal handler wrapper — SIGTERM / SIGINT flip ``requested``."""

    def __init__(self) -> None:
        self.requested = False
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    def _on_signal(self, _signum, _frame) -> None:
        self.requested = True


def _resolve_monitor(sct, config: CaptureConfig) -> dict:
    if config.region is not None:
        return config.region.as_mss_dict()
    monitors = sct.monitors
    idx = config.monitor_index
    if idx == 0 or idx >= len(monitors):
        return monitors[0]
    return monitors[idx]


def _grab_image(sct, monitor: dict) -> Image.Image:
    shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.rgb)


def _save_frame(image: Image.Image, session: Session, scale_width: int) -> Path:
    image = _maybe_resize(image, scale_width)
    path = session.frames_dir / f"frame_{_now_epoch_ms()}.png"
    tmp = path.with_suffix(".png.tmp")
    image.save(tmp, "PNG", optimize=True)
    tmp.replace(path)  # atomic, so readers never see a half-written file
    return path


# ---------------------------------------------------------------------------
# Controller: parent-side operations


@dataclass
class WatchStartResult:
    marker: WatchMarker
    session: Session


class WatchController:
    @staticmethod
    def start(config: CaptureConfig) -> WatchStartResult:
        if WatchMarker.load_active() is not None:
            raise CaptureError(
                "a watch is already running; stop it first with "
                "`claude-vision watch stop`"
            )
        session = Session.create(config)
        pid = os.fork()
        if pid == 0:
            # Child: run the daemon, then terminate the process without
            # returning through the Python caller's stack.
            try:
                run_daemon(session, config)
            finally:
                os._exit(0)
        marker = WatchMarker(
            session_id=session.id,
            session_path=session.root,
            pid=pid,
            started_at=_now_iso(),
            fps=config.fps,
        )
        marker.save()
        notify(f"⏺ Watch started (fps {config.fps})")
        return WatchStartResult(marker=marker, session=session)

    @staticmethod
    def stop(timeout_s: float = 5.0) -> dict:
        marker = WatchMarker.load_active()
        if marker is None:
            raise CaptureError("no active watch to stop")
        try:
            os.kill(marker.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        _wait_for_exit(marker.pid, timeout_s)
        WatchMarker.clear()
        session = Session.load(marker.session_path)
        frames = session.list_frames()
        notify(f"⏹ Watch stopped ({len(frames)} frames)")
        return {
            "session_id": marker.session_id,
            "session_path": str(marker.session_path),
            "frames_total": len(frames),
            "started_at": marker.started_at,
        }

    @staticmethod
    def status() -> dict:
        marker = WatchMarker.load_active()
        if marker is None:
            return {"active": False}
        session = Session.load(marker.session_path)
        started = datetime.fromisoformat(marker.started_at)
        uptime_s = (datetime.now(timezone.utc) - started).total_seconds()
        return {
            "active": True,
            "session_id": marker.session_id,
            "session_path": str(marker.session_path),
            "pid": marker.pid,
            "uptime_s": round(uptime_s, 2),
            "fps": marker.fps,
            "frames_total": len(session.list_frames()),
        }

    @staticmethod
    def fresh_grab() -> Path:
        marker = WatchMarker.load_active()
        if marker is None:
            raise CaptureError("no active watch; fresh-grab requires a running watch")
        session = Session.load(marker.session_path)
        config_raw = json.loads(session.marker.read_text())["config"]
        scale_width = int(config_raw.get("scale_width", 1568))
        monitor_index = int(config_raw.get("monitor_index", 0))
        region = config_raw.get("region")
        with mss.mss() as sct:
            if region is not None:
                monitor = {k: int(v) for k, v in region.items()
                           if k in ("left", "top", "width", "height")}
            else:
                monitors = sct.monitors
                monitor = monitors[monitor_index] if monitor_index < len(monitors) else monitors[0]
            image = _grab_image(sct, monitor)
        return _save_frame(image, session, scale_width)

    @staticmethod
    def frames_since(seconds: float, only_unseen: bool) -> list[Path]:
        marker = WatchMarker.load_active()
        if marker is None:
            raise CaptureError("no active watch")
        session = Session.load(marker.session_path)
        frames = session.list_frames()
        if seconds > 0:
            cutoff_ms = _now_epoch_ms() - int(seconds * 1000)
            frames = [p for p in frames if _frame_epoch_ms(p) >= cutoff_ms]
        if only_unseen:
            seen = session.frames_seen()
            frames = [p for p in frames if str(p) not in seen]
        return frames

    @staticmethod
    def mark_seen(paths) -> None:
        marker = WatchMarker.load_active()
        if marker is None:
            raise CaptureError("no active watch")
        session = Session.load(marker.session_path)
        session.mark_frames_seen(paths)


def _wait_for_exit(pid: int, timeout_s: float) -> None:
    """Poll for the child to terminate. After ``timeout_s``, SIGKILL."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _frame_epoch_ms(path: Path) -> int:
    """Extract the epoch-millis stamp from a watch-mode frame filename.
    Falls back to the file mtime for legacy ``frame_NNNN.png`` names so
    that old sessions remain readable."""
    stem = path.stem  # "frame_1732485612345"
    suffix = stem.split("_", 1)[-1]
    if suffix.isdigit() and len(suffix) >= 10:
        return int(suffix)
    return int(path.stat().st_mtime * 1000)
