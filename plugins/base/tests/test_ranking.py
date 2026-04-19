"""Unit tests for the standalone frame-ranking primitives."""

from pathlib import Path

import pytest
from PIL import Image

from claude_vision.ranking import (
    compare_signatures,
    compute_signature,
    rank_by_significance,
)


def _write(path: Path, color) -> Path:
    Image.new("RGB", (200, 200), color).save(path)
    return path


@pytest.fixture
def frames(tmp_path: Path) -> list[Path]:
    return [
        _write(tmp_path / "f0.png", "white"),
        _write(tmp_path / "f1.png", "white"),   # identical
        _write(tmp_path / "f2.png", "black"),   # big change
        _write(tmp_path / "f3.png", "black"),   # identical
        _write(tmp_path / "f4.png", "red"),     # moderate change
    ]


def test_signature_returns_64x64_grayscale():
    image = Image.new("RGB", (1920, 1080), "red")
    sig = compute_signature(image)
    assert sig.size == (64, 64)
    assert sig.mode == "L"


def test_compare_identical_signatures_is_zero():
    image = Image.new("RGB", (100, 100), "white")
    sig = compute_signature(image)
    assert compare_signatures(sig, sig) == 0.0


def test_compare_max_contrast_is_near_one():
    white = compute_signature(Image.new("RGB", (100, 100), "white"))
    black = compute_signature(Image.new("RGB", (100, 100), "black"))
    assert compare_signatures(white, black) > 0.95


def test_rank_all_without_cap(frames):
    ranked = rank_by_significance(frames)
    assert len(ranked) == len(frames)
    # Temporal order preserved by default
    assert [r.index for r in ranked] == [0, 1, 2, 3, 4]


def test_rank_first_frame_score_is_inf(frames):
    ranked = rank_by_significance(frames)
    assert ranked[0].score == float("inf")


def test_rank_max_caps_output(frames):
    ranked = rank_by_significance(frames, max_frames=3)
    assert len(ranked) == 3


def test_rank_max_keeps_highest_scored(frames):
    # Scores: [inf, 0, high(white->black), 0, moderate(black->red)]
    # Top 3 should be: frame 0 (inf), frame 2 (huge diff), frame 4 (moderate)
    ranked = rank_by_significance(frames, max_frames=3)
    kept = {r.index for r in ranked}
    assert 0 in kept   # +inf always qualifies
    assert 2 in kept   # black-after-white is the biggest "real" change
    assert 4 in kept   # red-after-black is next


def test_rank_max_preserves_temporal_order_by_default(frames):
    ranked = rank_by_significance(frames, max_frames=3)
    indexes = [r.index for r in ranked]
    assert indexes == sorted(indexes)


def test_rank_without_temporal_order_sorts_by_score_desc(frames):
    ranked = rank_by_significance(
        frames, max_frames=3, preserve_temporal_order=False,
    )
    scores = [r.score for r in ranked]
    assert scores == sorted(scores, reverse=True)


def test_empty_input_returns_empty_list():
    assert rank_by_significance([]) == []


def test_single_frame_gets_infinite_score(tmp_path: Path):
    path = _write(tmp_path / "only.png", "blue")
    ranked = rank_by_significance([path])
    assert len(ranked) == 1
    assert ranked[0].score == float("inf")
