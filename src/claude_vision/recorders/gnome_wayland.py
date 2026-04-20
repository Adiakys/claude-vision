"""Recorder for GNOME Wayland via org.gnome.Shell.Screencast over D-Bus."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PIL import Image

from ..dedupe import FrameDeduper
from ..errors import CaptureError, PlatformUnsupportedError
from .base import ScreenRecorder
from .mss_recorder import _deduper_stats, _maybe_deduper, _maybe_resize

DBUS_DEST = "org.gnome.Shell.Screencast"
DBUS_PATH = "/org/gnome/Shell/Screencast"
START_METHOD = "org.gnome.Shell.Screencast.Screencast"
STOP_METHOD = "org.gnome.Shell.Screencast.StopScreencast"

SHOT_DEST = "org.gnome.Shell.Screenshot"
SHOT_PATH = "/org/gnome/Shell/Screenshot"
SHOT_METHOD = "org.gnome.Shell.Screenshot.Screenshot"
SHOT_AREA_METHOD = "org.gnome.Shell.Screenshot.ScreenshotArea"


class GnomeWaylandRecorder(ScreenRecorder):
    def capture(self) -> list[Path]:
        imageio = _require_imageio()
        webm = self.session.root / "recording.webm"
        fps = self.config.effective_fps()

        self._start_screencast(webm, fps)
        try:
            time.sleep(self.config.duration_s)
        finally:
            self._stop_screencast()

        if not webm.exists() or webm.stat().st_size == 0:
            raise CaptureError(
                f"GNOME Shell did not produce a recording at {webm}. "
                "If this is the first run, GNOME may have shown a permission "
                "prompt — accept it and retry."
            )

        frames, stats = self._extract_frames(imageio, webm)
        webm.unlink(missing_ok=True)
        self.stats = stats
        return frames

    def screenshot(self) -> Path:
        output = self.session.frames_dir / "frame_0000.png"
        self._gdbus_screenshot(output)
        if self.config.scale_width > 0:
            image = Image.open(output)
            image = _maybe_resize(image, self.config.scale_width)
            image.save(output, "PNG", optimize=True)
        return output

    def _gdbus_screenshot(self, output: Path) -> None:
        """Dispatch to ScreenshotArea when a region is configured, else Screenshot."""
        region = self.config.region
        if region is None:
            cmd = [
                "gdbus", "call", "--session",
                "--dest", SHOT_DEST,
                "--object-path", SHOT_PATH,
                "--method", SHOT_METHOD,
                "true", "false", str(output),
            ]
        else:
            # ScreenshotArea(x, y, width, height, flash, filename)
            cmd = [
                "gdbus", "call", "--session",
                "--dest", SHOT_DEST,
                "--object-path", SHOT_PATH,
                "--method", SHOT_AREA_METHOD,
                str(region.left), str(region.top),
                str(region.width), str(region.height),
                "false", str(output),
            ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not output.exists():
            raise CaptureError(
                f"GNOME Screenshot failed: {result.stderr.strip() or 'no output file'}"
            )

    def _start_screencast(self, webm: Path, fps: float) -> None:
        options = (
            f"{{'framerate': <uint32 {max(1, int(round(fps)))}>, "
            "'draw-cursor': <true>}"
        )
        self._gdbus(START_METHOD, str(webm), options)

    def _stop_screencast(self) -> None:
        try:
            self._gdbus(STOP_METHOD)
        except CaptureError:
            pass

    def _gdbus(self, method: str, *args: str) -> str:
        cmd = [
            "gdbus", "call", "--session",
            "--dest", DBUS_DEST,
            "--object-path", DBUS_PATH,
            "--method", method,
            *args,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise CaptureError(
                f"gdbus call failed ({method}): {result.stderr.strip()}"
            )
        return result.stdout

    def _extract_frames(self, imageio, webm: Path) -> tuple[list[Path], dict]:
        max_frames = self.config.max_frames
        scale_width = self.config.scale_width
        region = self.config.region
        deduper = _maybe_deduper(self.config)
        frames: list[Path] = []
        decoded = 0
        for array in imageio.imiter(webm, plugin="FFMPEG"):
            if len(frames) >= max_frames:
                break
            decoded += 1
            image = Image.fromarray(array)
            # GNOME Screencast D-Bus has no region option, so we crop
            # post-decode. mss path uses native region; stays symmetric.
            if region is not None:
                image = image.crop(region.as_pil_bbox())
            if deduper is not None and not deduper.should_keep(image):
                continue
            image = _maybe_resize(image, scale_width)
            path = self.session.frames_dir / f"frame_{len(frames):04d}.png"
            image.save(path, "PNG", optimize=True)
            frames.append(path)
        if not frames:
            raise CaptureError("No frames decoded from GNOME screencast output.")
        return frames, _deduper_stats(deduper, decoded, len(frames))


def _require_imageio():
    try:
        import imageio.v3 as imageio
    except ImportError as exc:
        raise PlatformUnsupportedError(
            "GNOME Wayland capture needs the [wayland] extra: "
            "install with `pip install claude-vision[wayland]`."
        ) from exc
    return imageio
