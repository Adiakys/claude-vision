"""Drop near-identical frames from a multi-frame capture.

A stateful filter used inside video capture loops. The first frame is always
kept; each subsequent frame is compared to the *last kept* frame (not the
*last captured*) so that slow drifts eventually accumulate past the threshold
and get sampled. This is cheaper than saving every frame and lets the
vision subagent spend tokens only on frames that carry new information.
"""

from __future__ import annotations

from PIL import Image, ImageChops, ImageStat

# Down-sample frames to this size before diffing. 64x64 is fast and robust
# to antialiasing / sub-pixel jitter that would otherwise create false
# "changed" verdicts.
SIGNATURE_SIZE = (64, 64)

# Mean absolute per-pixel luminance difference, normalized to [0, 1].
# 1% tolerates cursor motion, text rendering jitter, and compressor noise
# while still flagging genuine content changes.
DEFAULT_THRESHOLD = 0.01


class FrameDeduper:
    """Decides whether to keep each frame of a running capture.

    Usage::

        deduper = FrameDeduper(threshold=0.01)
        for frame in frames:
            if deduper.should_keep(frame):
                save(frame)

    ``stats`` exposes running counters for the caller to emit in its output.
    """

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold
        self.kept = 0
        self.skipped = 0
        self._reference: Image.Image | None = None

    def should_keep(self, image: Image.Image) -> bool:
        signature = _signature(image)
        if self._reference is None:
            self._reference = signature
            self.kept += 1
            return True
        if _diff(signature, self._reference) >= self.threshold:
            self._reference = signature
            self.kept += 1
            return True
        self.skipped += 1
        return False


def _signature(image: Image.Image) -> Image.Image:
    return image.convert("L").resize(SIGNATURE_SIZE, Image.BILINEAR)


def _diff(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a, b)
    return ImageStat.Stat(diff).mean[0] / 255.0
