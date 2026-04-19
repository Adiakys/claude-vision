"""Drop near-identical frames from a multi-frame capture.

A stateful filter used inside video capture loops. The first frame is always
kept; each subsequent frame is compared to the *last kept* frame (not the
*last captured*) so that slow drifts eventually accumulate past the threshold
and get sampled. This is cheaper than saving every frame and lets the
vision subagent spend tokens only on frames that carry new information.
"""

from __future__ import annotations

from PIL import Image

from .ranking import compare_signatures, compute_signature

# Mean absolute per-pixel luminance difference, normalized to [0, 1].
# 1% tolerates cursor motion, text rendering jitter, and compressor noise
# while still flagging genuine content changes. Signature primitives live
# in `ranking.py` so they can be reused by the scoring API.
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
        signature = compute_signature(image)
        if self._reference is None:
            self._reference = signature
            self.kept += 1
            return True
        if compare_signatures(signature, self._reference) >= self.threshold:
            self._reference = signature
            self.kept += 1
            return True
        self.skipped += 1
        return False


def build_from_config(config) -> "FrameDeduper | None":
    """Build the deduper for a capture, or return None when dedupe is
    disabled in ``config``. Centralizing this avoids three recorder
    modules duplicating the same branch."""
    if not getattr(config, "dedupe", False):
        return None
    return FrameDeduper(threshold=config.dedupe_threshold)
