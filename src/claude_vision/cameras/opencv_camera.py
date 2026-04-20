"""Cross-platform webcam source backed by OpenCV.

OpenCV handles the platform-specific backends (V4L2 on Linux, AVFoundation on
macOS, MediaFoundation / DirectShow on Windows), so one implementation suffices.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from ..capture_stats import CaptureStats
from ..dedupe import build_from_config as build_deduper
from ..errors import CaptureError, PlatformUnsupportedError, WebcamPermissionError
from ..image_ops import resize_to_width
from ..notify import notify
from .base import WebcamCamera

# Logitech C920-class webcams need ~5 frames for auto-exposure to settle.
# Shorter and the first saved frame can be black or under-exposed.
WARMUP_FRAMES = 5

# Force a predictable capture resolution regardless of driver default (often 640x480).
# scale_width (via Pillow) then downsamples to the Claude-vision sweet spot.
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720

# macOS over SSH cannot trigger the TCC permission prompt; first read() will hang.
DARWIN_READ_TIMEOUT_S = 2.0

# Mean pixel value below this threshold is treated as "all black" —
# shutter closed, privacy mode on, or driver producing placeholder frames.
BLACK_FRAME_THRESHOLD = 2.0


def _crop_center(image: Image.Image, area_fraction: float = 1 / 3) -> Image.Image:
    """Crop to the central region whose area is ``area_fraction`` of the total,
    preserving aspect ratio. Default 1/3 keeps the subject (face / held object)
    and drops background noise — typical for webcam captures."""
    side_fraction = area_fraction ** 0.5
    w, h = image.size
    new_w = max(1, int(w * side_fraction))
    new_h = max(1, int(h * side_fraction))
    left = (w - new_w) // 2
    top = (h - new_h) // 2
    return image.crop((left, top, left + new_w, top + new_h))


def _require_cv2():
    try:
        import cv2  # noqa: F401
    except ImportError as exc:
        raise PlatformUnsupportedError(
            "Webcam support requires the [webcam] extra: "
            "install with `pip install claude-vision[webcam]`."
        ) from exc
    return cv2


def _backend_for_platform(cv2) -> int:
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    if sys.platform.startswith("win"):
        return cv2.CAP_MSMF
    return cv2.CAP_V4L2


class OpenCvCamera(WebcamCamera):
    def snapshot(self) -> Path:
        with self._managed_capture() as cap:
            frame = self._read_after_warmup(cap)
            return self._save_frame(frame, 0)

    def record(self) -> list[Path]:
        target_count = self.config.planned_frame_count()
        deduper = build_deduper(self.config)
        frames: list[Path] = []
        captured = 0
        notify(f"📷 Recording {self.config.duration_s:.0f}s from webcam...")
        with self._managed_capture() as cap:
            self._warmup(cap)
            for _ in range(target_count):
                bgr = self._read_next(cap)
                if bgr is None:
                    continue
                captured += 1
                image = self._bgr_to_pil(bgr)
                if deduper is not None and not deduper.should_keep(image):
                    continue
                frames.append(self._save_image(image, len(frames)))
        if not frames:
            raise CaptureError("Webcam produced no frames during recording.")
        self.stats = CaptureStats.from_deduper(
            deduper, planned=captured, kept=len(frames),
        )
        notify(f"✓ Webcam capture done ({len(frames)} frames kept)")
        return frames

    @contextmanager
    def _managed_capture(self):
        cv2 = _require_cv2()
        cap = self._open(cv2)
        try:
            yield cap
        finally:
            cap.release()

    def _open(self, cv2):
        device = self.config.device_index
        primary = _backend_for_platform(cv2)
        cap = cv2.VideoCapture(device, primary)

        # Windows: MediaFoundation has a known cold-start flakiness on some drivers.
        # Fall back to DirectShow once, transparently.
        if not cap.isOpened() and sys.platform.startswith("win"):
            cap.release()
            cap = cv2.VideoCapture(device, cv2.CAP_DSHOW)

        if not cap.isOpened():
            cap.release()
            raise CaptureError(f"webcam device {device} not available")

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_HEIGHT)
        return cap

    def _read_after_warmup(self, cap):
        self._warmup(cap)
        frame = self._read_next(cap)
        if frame is None:
            raise WebcamPermissionError(
                "Webcam opened but no frame received. Likely causes: another app "
                "is using the camera; macOS Camera permission not granted "
                "(System Settings > Privacy & Security > Camera); "
                "or running over SSH where the TCC prompt cannot appear."
            )
        self._guard_black_frame(frame)
        return frame

    def _guard_black_frame(self, bgr_frame) -> None:
        import numpy as np
        if float(np.mean(bgr_frame)) < BLACK_FRAME_THRESHOLD:
            raise WebcamPermissionError(
                "Webcam returned an all-black frame. Likely causes: the physical "
                "privacy cover is closed, the laptop's webcam privacy switch is "
                "enabled, or the camera is in a power-saving state. "
                "Open the shutter / disable privacy mode and retry."
            )

    def _warmup(self, cap) -> None:
        for _ in range(WARMUP_FRAMES):
            cap.read()

    def _read_next(self, cap):
        deadline = time.monotonic() + DARWIN_READ_TIMEOUT_S if sys.platform == "darwin" else None
        while True:
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame
            if deadline is not None and time.monotonic() >= deadline:
                return None
            if deadline is None:
                return None

    def _save_frame(self, bgr_frame, idx: int) -> Path:
        # Kept for snapshot(); record() goes via _bgr_to_pil + _save_image
        # so the deduper can run between the two steps.
        return self._save_image(self._bgr_to_pil(bgr_frame), idx)

    def _bgr_to_pil(self, bgr_frame) -> Image.Image:
        cv2 = _require_cv2()
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        if self.config.crop_center:
            image = _crop_center(image)
        return image

    def _save_image(self, image: Image.Image, idx: int) -> Path:
        image = resize_to_width(image, self.config.scale_width)
        path = self.session.frames_dir / f"frame_{idx:04d}.png"
        image.save(path, "PNG", optimize=True)
        return path
