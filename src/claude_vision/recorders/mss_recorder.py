"""Recorder for X11, macOS, and Windows: mss snapshot loop + Pillow resize."""

from __future__ import annotations

import time
from pathlib import Path

import mss
from PIL import Image

from ..errors import CaptureError
from .base import ScreenRecorder


class MssRecorder(ScreenRecorder):
    def capture(self) -> list[Path]:
        fps = self.config.effective_fps()
        interval = 1.0 / fps
        planned = self.config.planned_frame_count()
        frames: list[Path] = []

        with mss.mss() as sct:
            monitor = self._select_monitor(sct)
            start = time.monotonic()
            for idx in range(planned):
                target = start + idx * interval
                sleep_for = target - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                frames.append(self._grab_and_save(sct, monitor, idx))
        return frames

    def screenshot(self) -> Path:
        with mss.mss() as sct:
            monitor = self._select_monitor(sct)
            return self._grab_and_save(sct, monitor, 0)

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

    def _grab_and_save(self, sct, monitor: dict, idx: int) -> Path:
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
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
