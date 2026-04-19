"""Rank a sequence of frames by change magnitude.

Two responsibilities:

* **Signature primitives** (:func:`compute_signature`, :func:`compare_signatures`)
  — shared with ``dedupe.py``; a frame's signature is a 64×64 grayscale
  downsample, cheap to produce and robust to compression/aliasing noise.
* **Ranking API** (:class:`RankedFrame`, :func:`rank_by_significance`) —
  score every frame by the diff of its signature against the previous
  frame's, optionally cap the output at the top-N by score while keeping
  the temporal order in the final list.

Used by :mod:`claude_vision.thumbs` to cap thumbnail output at a
user-supplied maximum, and available to the subagent for any similar
"which of these frames carry the most new information?" decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops, ImageStat

SIGNATURE_SIZE = (64, 64)


@dataclass(frozen=True)
class RankedFrame:
    path: Path
    index: int        # position in the source sequence (0-based)
    score: float      # diff vs previous frame's signature; first frame = +inf


def compute_signature(image: Image.Image) -> Image.Image:
    """Downsample to 64×64 grayscale — cheap and robust to AA jitter."""
    return image.convert("L").resize(SIGNATURE_SIZE, Image.BILINEAR)


def compare_signatures(a: Image.Image, b: Image.Image) -> float:
    """Mean absolute per-pixel difference, normalized to ``[0, 1]``."""
    diff = ImageChops.difference(a, b)
    return ImageStat.Stat(diff).mean[0] / 255.0


def rank_by_significance(
    paths: Sequence[Path],
    *,
    max_frames: int | None = None,
    preserve_temporal_order: bool = True,
) -> list[RankedFrame]:
    """Score every frame, optionally keep only the top-N by score.

    The first frame's score is ``+inf`` so it always qualifies when a
    cap is applied. When ``preserve_temporal_order`` is true (default)
    the final list is sorted by source index; otherwise by score
    descending.
    """
    scored = _score_sequence(paths)
    if max_frames is not None and len(scored) > max_frames:
        scored = sorted(scored, key=lambda f: -f.score)[:max_frames]
    if preserve_temporal_order:
        scored.sort(key=lambda f: f.index)
    else:
        scored.sort(key=lambda f: -f.score)
    return scored


def _score_sequence(paths: Sequence[Path]) -> list[RankedFrame]:
    ranked: list[RankedFrame] = []
    previous_signature: Image.Image | None = None
    for idx, path in enumerate(paths):
        with Image.open(path) as source:
            image = source.copy()
        signature = compute_signature(image)
        if previous_signature is None:
            score = float("inf")
        else:
            score = compare_signatures(signature, previous_signature)
        ranked.append(RankedFrame(path=path, index=idx, score=score))
        previous_signature = signature
    return ranked
