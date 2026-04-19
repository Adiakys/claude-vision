"""Recorder for X11, macOS, and Windows: mss snapshot loop + Pillow resize."""

from __future__ import annotations

import time
from pathlib import Path

import mss
from PIL import Image

from ..dedupe import FrameDeduper
from ..errors import CaptureError
from ..notify import notify
from .base import ScreenRecorder


class MssRecorder(ScreenRecorder):
    def capture(self) -> list[Path]:
        fps = self.config.effective_fps()
        interval = 1.0 / fps
        planned = self.config.planned_frame_count()
        deduper = _maybe_deduper(self.config)
        frames: list[Path] = []

        notify(f"📷 Recording {self.config.duration_s:.0f}s of screen...")
        with mss.mss() as sct:
            monitor = self._select_monitor(sct)
            start = time.monotonic()
            for idx in range(planned):
                target = start + idx * interval
                sleep_for = target - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                image = self._grab_image(sct, monitor)
                if deduper is not None and not deduper.should_keep(image):
                    continue
                frames.append(self._save_image(image, len(frames)))
        self.stats = _deduper_stats(deduper, planned, len(frames))
        notify(f"✓ Screen capture done ({len(frames)} frames kept)")
        return frames

    def screenshot(self) -> Path:
        with mss.mss() as sct:
            monitor = self._select_monitor(sct)
            image = self._grab_image(sct, monitor)
            return self._save_image(image, 0)

    def _select_monitor(self, sct: "mss.base.MSSBase") -> dict:
        if self.config.region is not None:
            return self.config.region.as_mss_dict()
        monitors = sct.monitors
        index = self.config.monitor_index
        if index == 0:
            return monitors[0]
        if index >= len(monitors):
            raise CaptureError(
                f"monitor_index {index} out of range; "
                f"available: 0..{len(monitors) - 1}"
            )
        return monitors[index]

    def _grab_image(self, sct, monitor: dict) -> Image.Image:
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def _save_image(self, image: Image.Image, idx: int) -> Path:
        image = _maybe_resize(image, self.config.scale_width)
        path = self.session.frames_dir / f"frame_{idx:04d}.png"
        image.save(path, "PNG", optimize=True)
        return path


def _maybe_resize(image: Image.Image, target_width: int) -> Image.Image:
    if target_width <= 0 or image.width <= target_width:
        return image
    ratio = target_width / image.width
    new_size = (target_width, max(1, int(image.height * ratio)))
    return image.resize(new_size, Image.LANCZOS)


def _maybe_deduper(config) -> FrameDeduper | None:
    if not config.dedupe:
        return None
    return FrameDeduper(threshold=config.dedupe_threshold)


def _deduper_stats(deduper: FrameDeduper | None, planned: int, kept: int) -> dict:
    if deduper is None:
        return {"kept": kept, "skipped": 0, "planned": planned}
    return {"kept": deduper.kept, "skipped": deduper.skipped, "planned": planned}
