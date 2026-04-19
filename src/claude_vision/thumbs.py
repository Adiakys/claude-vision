"""Generate resized PNG thumbnails of a session's frames, with an optional
second-pass deduplication that keeps only "different-scene" frames.

The first-pass dedupe runs at capture time with a tight threshold (~1%) and
asks "is anything happening?". This second pass, usually at ~2%, asks "is
this frame a different scene type worth showing to the subagent?". For long
watch sessions that accumulate many visually-similar frames it collapses
clusters into a single representative each, cutting the thumbnail-scan
cost by 80%+.

An optional ``max_thumbs`` cap further restricts the output to the top-N
most significant frames (by change magnitude) so the subagent gets a
predictable budget on long watches.

The thumbnails are written alongside the full-size frames under
``<session>/thumbs/thumb_<index>.png``. The subagent reads them first,
picks the most informative ones, and only then loads the corresponding
full-size frames — two-pass selection that preserves precision while
collapsing the token budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .ranking import compare_signatures, compute_signature
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
    max_thumbs: int | None = None,
) -> list[ThumbEntry]:
    """Generate thumbnails for the frames of ``session`` that survive an
    optional second-pass dedupe and (optionally) a top-N cap.

    ``size`` is the long-edge target in pixels; aspect ratio is preserved.
    ``dedupe_threshold`` is the mean-pixel-diff cutoff (in [0, 1]) for the
    second pass; pass 0 to disable and keep every frame.
    ``max_thumbs`` caps the output: when more frames survive the dedupe
    than ``max_thumbs``, the ones with the highest diff magnitudes are
    kept and the rest discarded. Output order remains temporal.
    """
    thumb_dir = session.root / THUMB_DIR_NAME
    thumb_dir.mkdir(exist_ok=True)

    frames = session.list_frames()
    survivors = _dedupe_with_scores(frames, dedupe_threshold)
    if max_thumbs is not None and len(survivors) > max_thumbs:
        survivors = _cap_by_score(survivors, max_thumbs)

    entries: list[ThumbEntry] = []
    for source_idx, _score in survivors:
        frame_path = frames[source_idx]
        thumb_path = thumb_dir / f"thumb_{source_idx:04d}.png"
        _write_thumb(frame_path, thumb_path, size)
        entries.append(ThumbEntry(
            frame_path=frame_path, thumb_path=thumb_path, source_index=source_idx,
        ))
    return entries


def _dedupe_with_scores(
    frames: list[Path], threshold: float,
) -> list[tuple[int, float]]:
    """Walk the sequence once: return indexes of surviving frames along with
    the diff magnitude that let each one through. The first survivor carries
    a score of +inf so it's never dropped by a later top-N cap."""
    survivors: list[tuple[int, float]] = []
    reference: Image.Image | None = None
    for idx, path in enumerate(frames):
        with Image.open(path) as source:
            image = source.copy()
        signature = compute_signature(image)
        if reference is None:
            survivors.append((idx, float("inf")))
            reference = signature
            continue
        score = compare_signatures(signature, reference)
        if threshold <= 0 or score >= threshold:
            survivors.append((idx, score))
            reference = signature
    return survivors


def _cap_by_score(
    survivors: list[tuple[int, float]], limit: int,
) -> list[tuple[int, float]]:
    """Keep the ``limit`` highest-scored entries but preserve temporal order."""
    top = sorted(survivors, key=lambda pair: -pair[1])[:limit]
    return sorted(top, key=lambda pair: pair[0])


def _write_thumb(source: Path, target: Path, size: int) -> None:
    with Image.open(source) as image:
        thumb = image.copy()
    if size > 0 and max(thumb.size) > size:
        thumb.thumbnail((size, size), Image.LANCZOS)
    thumb.save(target, "PNG", optimize=True)
