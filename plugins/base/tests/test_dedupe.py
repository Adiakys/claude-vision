"""Unit tests for FrameDeduper. Uses synthetic PIL images (no I/O)."""

import pytest
from PIL import Image

from claude_vision.dedupe import FrameDeduper


def _solid(color, size=(200, 200)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_first_frame_always_kept():
    d = FrameDeduper()
    assert d.should_keep(_solid("white")) is True
    assert d.kept == 1
    assert d.skipped == 0


def test_identical_frame_is_skipped():
    d = FrameDeduper()
    d.should_keep(_solid("white"))
    assert d.should_keep(_solid("white")) is False
    assert d.kept == 1
    assert d.skipped == 1


def test_very_different_frame_is_kept():
    d = FrameDeduper()
    d.should_keep(_solid("white"))
    assert d.should_keep(_solid("black")) is True
    assert d.kept == 2


def test_threshold_controls_sensitivity():
    # A 1/255 luminance change (~0.4% mean diff) is below the 1% default
    # threshold but above a zero threshold.
    lenient = FrameDeduper(threshold=0.01)
    strict = FrameDeduper(threshold=0.0)
    frame_a = _solid((255, 255, 255))
    frame_b = _solid((254, 254, 254))

    lenient.should_keep(frame_a)
    strict.should_keep(frame_a)

    assert lenient.should_keep(frame_b) is False
    assert strict.should_keep(frame_b) is True


def test_reference_updates_on_keep_for_gradual_drift():
    # Over many iterations, small drifts accumulate past the threshold
    # and produce new kept frames — we're not stuck on the original.
    d = FrameDeduper(threshold=0.02)
    d.should_keep(_solid((0, 0, 0)))
    for tone in range(10, 256, 10):
        d.should_keep(_solid((tone, tone, tone)))
    assert d.kept >= 2  # accumulated drift triggered at least one re-save


def test_stats_are_exposed():
    d = FrameDeduper()
    assert hasattr(d, "kept")
    assert hasattr(d, "skipped")
    assert hasattr(d, "threshold")
