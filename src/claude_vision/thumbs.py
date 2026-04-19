"""Generate resized PNG thumbnails of a session's frames, with an optional
second-pass deduplication that keeps only "different-scene" frames.

The first-pass dedupe runs at capture time with a tight threshold (~1%) and
asks "is anything happening?". This second pass, usually at ~2%, asks "is
this frame a different scene type worth showing to the subagent?". For long
watch sessions that accumulate many visually-similar frames it collapses
clusters into a single representative each, cutting the thumbnail-scan
cost by 80%+.

The thumbnails are written alongside the full-size frames under
``<session>/thumbs/thumb_<index>.png``. The subagent reads them first, picks
the most informative ones, and only then loads the corresponding full-size
frames — two-pass selection that preserves precision while collapsing the
token budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .dedupe import FrameDeduper
from .session import Session

THUMB_DIR_NAME = "thumbs"
DEFAULT_THUMB_SIZE = 256
DEFAULT_THUMB_DEDUPE_THRESHOLD = 0.02


@dataclass(frozen=True)
class ThumbEntry:
    """One surviving frame and its freshly-generated thumbnail."""

    frame_path: Path
    thumb_path: Path
    source_index: int


def generate_thumbnails(
    session: Session,
    *,
    size: int = DEFAULT_THUMB_SIZE,
    dedupe_threshold: float = DEFAULT_THUMB_DEDUPE_THRESHOLD,
) -> list[ThumbEntry]:
    """Generate thumbnails for the frames of ``session`` that survive an
    optional second-pass dedupe.

    ``size`` is the long-edge target in pixels; aspect ratio is preserved.
    ``dedupe_threshold`` is the mean-pixel-diff cutoff (in [0, 1]) for the
    second pass; pass 0 to disable and keep every frame.
    """
    thumb_dir = session.root / THUMB_DIR_NAME
    thumb_dir.mkdir(exist_ok=True)

    deduper = FrameDeduper(threshold=dedupe_threshold) if dedupe_threshold > 0 else None
    kept: list[ThumbEntry] = []

    for idx, frame_path in enumerate(session.list_frames()):
        with Image.open(frame_path) as source:
            image = source.copy()
        if deduper is not None and not deduper.should_keep(image):
            continue
        thumb = _resize_long_edge(image, size)
        thumb_path = thumb_dir / f"thumb_{idx:04d}.png"
        thumb.save(thumb_path, "PNG", optimize=True)
        kept.append(ThumbEntry(
            frame_path=frame_path, thumb_path=thumb_path, source_index=idx,
        ))
    return kept


def _resize_long_edge(image: Image.Image, target: int) -> Image.Image:
    """Resize preserving aspect so the longer edge equals ``target``."""
    if target <= 0 or max(image.size) <= target:
        return image
    image = image.copy()
    image.thumbnail((target, target), Image.LANCZOS)
    return image
