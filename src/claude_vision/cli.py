"""Command-line interface — emits structured JSON so Claude can parse it."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from .cameras import select_camera
from .cleaner import SESSION_PREFIX, clean, purge_stale
from .config import CaptureConfig
from .errors import ClaudeVisionError
from .platform_detect import detect, preflight
from .recorders import select_recorder
from .session import Session


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ClaudeVisionError as exc:
        _emit({"error": type(exc).__name__, "message": str(exc)})
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-vision")
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="Record screen and emit frame paths")
    capture.add_argument("--duration", type=float, required=True)
    capture.add_argument("--fps", type=float, default=1.0)
    capture.add_argument("--max-frames", type=int, default=24)
    capture.add_argument(
        "--scale-width", type=int, default=1568,
        help="Target width in pixels; 0 disables resize",
    )
    capture.add_argument("--monitor", type=int, default=0)
    capture.set_defaults(handler=_cmd_capture)

    shot = sub.add_parser("screenshot", help="Grab a single frame")
    shot.add_argument(
        "--scale-width", type=int, default=1568,
        help="Target width in pixels; 0 disables resize",
    )
    shot.add_argument("--monitor", type=int, default=0)
    shot.set_defaults(handler=_cmd_screenshot)

    wshot = sub.add_parser("webcam-snapshot", help="Grab a single frame from the webcam")
    wshot.add_argument(
        "--scale-width", type=int, default=1568,
        help="Target width in pixels; 0 disables resize",
    )
    wshot.add_argument("--device", type=int, default=0, help="Webcam device index")
    wshot.set_defaults(handler=_cmd_webcam_snapshot)

    wcap = sub.add_parser("webcam-capture", help="Record a short video from the webcam")
    wcap.add_argument("--duration", type=float, required=True)
    wcap.add_argument("--fps", type=float, default=1.0)
    wcap.add_argument("--max-frames", type=int, default=24)
    wcap.add_argument(
        "--scale-width", type=int, default=1568,
        help="Target width in pixels; 0 disables resize",
    )
    wcap.add_argument("--device", type=int, default=0, help="Webcam device index")
    wcap.set_defaults(handler=_cmd_webcam_capture)

    clean_cmd = sub.add_parser("clean", help="Delete a single session")
    clean_cmd.add_argument("--session", required=True)
    clean_cmd.set_defaults(handler=_cmd_clean)

    gc = sub.add_parser("gc", help="Remove stale sessions older than TTL")
    gc.add_argument("--ttl-hours", type=float, default=2.0)
    gc.set_defaults(handler=_cmd_gc)

    return parser


def _cmd_capture(args: argparse.Namespace) -> int:
    platform = detect()
    preflight(platform)

    config = CaptureConfig(
        duration_s=args.duration,
        fps=args.fps,
        max_frames=args.max_frames,
        scale_width=args.scale_width,
        monitor_index=args.monitor,
    )

    session = Session.create(config)
    recorder = select_recorder(platform, session, config)
    try:
        frames = recorder.capture()
        session.mark("analyzing")
    except Exception:
        session.mark("done")
        raise

    _emit({
        "session_id": session.id,
        "session_path": str(session.root),
        "frames": [str(p) for p in frames],
        "count": len(frames),
        "duration_s": config.duration_s,
        "fps": config.effective_fps(),
        "scale_width": config.scale_width,
        "platform": platform.value,
        "source": "screen",
    })
    return 0


def _cmd_screenshot(args: argparse.Namespace) -> int:
    platform = detect()
    preflight(platform)

    config = CaptureConfig(
        scale_width=args.scale_width,
        monitor_index=args.monitor,
    )

    session = Session.create(config)
    recorder = select_recorder(platform, session, config)
    try:
        frame = recorder.screenshot()
        session.mark("analyzing")
    except Exception:
        session.mark("done")
        raise

    _emit({
        "session_id": session.id,
        "session_path": str(session.root),
        "frame": str(frame),
        "scale_width": config.scale_width,
        "platform": platform.value,
        "source": "screen",
    })
    return 0


def _cmd_webcam_snapshot(args: argparse.Namespace) -> int:
    config = CaptureConfig(
        scale_width=args.scale_width,
        device_index=args.device,
    )
    session = Session.create(config)
    camera = select_camera(session, config)
    try:
        frame = camera.snapshot()
        session.mark("analyzing")
    except Exception:
        session.mark("done")
        raise

    _emit({
        "session_id": session.id,
        "session_path": str(session.root),
        "frame": str(frame),
        "scale_width": config.scale_width,
        "device_index": config.device_index,
        "source": "webcam",
    })
    return 0


def _cmd_webcam_capture(args: argparse.Namespace) -> int:
    config = CaptureConfig(
        duration_s=args.duration,
        fps=args.fps,
        max_frames=args.max_frames,
        scale_width=args.scale_width,
        device_index=args.device,
    )
    session = Session.create(config)
    camera = select_camera(session, config)
    try:
        frames = camera.record()
        session.mark("analyzing")
    except Exception:
        session.mark("done")
        raise

    _emit({
        "session_id": session.id,
        "session_path": str(session.root),
        "frames": [str(p) for p in frames],
        "count": len(frames),
        "duration_s": config.duration_s,
        "fps": config.effective_fps(),
        "scale_width": config.scale_width,
        "device_index": config.device_index,
        "source": "webcam",
    })
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    path = _resolve_session(args.session)
    removed = clean(path)
    _emit({"cleaned": removed, "path": str(path)})
    return 0


def _cmd_gc(args: argparse.Namespace) -> int:
    root = Path(tempfile.gettempdir()) / "claude-vision"
    removed = purge_stale(root, ttl=timedelta(hours=args.ttl_hours))
    _emit({"removed": [str(p) for p in removed]})
    return 0


def _resolve_session(identifier: str) -> Path:
    """Accept either a full path or a bare session id."""
    as_path = Path(identifier)
    if as_path.is_absolute() or as_path.exists():
        return as_path
    root = Path(tempfile.gettempdir()) / "claude-vision"
    return root / f"{SESSION_PREFIX}{identifier}"


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
