"""Unit tests for thumbnail generation with second-pass dedupe."""

from pathlib import Path

import pytest
from PIL import Image

from claude_vision.config import CaptureConfig
from claude_vision.session import Session
from claude_vision.thumbs import generate_thumbnails


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session.create(CaptureConfig(session_root=tmp_path))


def _write_frame(session: Session, idx: int, color) -> Path:
    path = session.frames_dir / f"frame_{idx:04d}.png"
    Image.new("RGB", (400, 300), color).save(path)
    return path


def test_generates_one_thumb_per_kept_frame(session):
    for i, c in enumerate(["red", "green", "blue"]):
        _write_frame(session, i, c)
    entries = generate_thumbnails(session, dedupe_threshold=0)
    assert len(entries) == 3
    assert all(e.thumb_path.exists() for e in entries)


def test_dedupe_collapses_identical_frames(session):
    for i in range(5):
        _write_frame(session, i, "white")
    entries = generate_thumbnails(session, dedupe_threshold=0.02)
    # All 5 frames are identical → only the first survives the second pass.
    assert len(entries) == 1


def test_dedupe_keeps_visually_distinct_frames(session):
    for i, c in enumerate(["red", "white", "red", "white", "red"]):
        _write_frame(session, i, c)
    entries = generate_thumbnails(session, dedupe_threshold=0.02)
    # Each alternating colour is clearly different from the previous kept one.
    assert len(entries) == 5


def test_threshold_zero_disables_dedupe(session):
    for i in range(4):
        _write_frame(session, i, "white")
    entries = generate_thumbnails(session, dedupe_threshold=0)
    assert len(entries) == 4


def test_thumb_size_respects_long_edge(session):
    _write_frame(session, 0, "red")
    entries = generate_thumbnails(session, size=128, dedupe_threshold=0)
    assert len(entries) == 1
    with Image.open(entries[0].thumb_path) as im:
        assert max(im.size) == 128
        # 400x300 original → aspect 4:3 → 128x96 target
        assert im.size == (128, 96)


def test_thumb_dir_is_created(session):
    _write_frame(session, 0, "red")
    assert not (session.root / "thumbs").exists()
    generate_thumbnails(session)
    assert (session.root / "thumbs").is_dir()


def test_entries_carry_source_index(session):
    for i, c in enumerate(["red", "red", "blue"]):
        _write_frame(session, i, c)
    entries = generate_thumbnails(session, dedupe_threshold=0.02)
    indexes = [e.source_index for e in entries]
    # frame 1 duplicates frame 0 and should be skipped; the original indices
    # of the kept frames (0 and 2) are reported, not a re-numbered sequence.
    assert 0 in indexes
    assert 2 in indexes
    assert 1 not in indexes


def test_no_frames_returns_empty_list(session):
    entries = generate_thumbnails(session)
    assert entries == []


def test_max_thumbs_caps_output(session):
    for i, c in enumerate(["white", "black", "red", "green", "blue"]):
        _write_frame(session, i, c)
    entries = generate_thumbnails(session, max_thumbs=2, dedupe_threshold=0)
    assert len(entries) == 2


def test_max_thumbs_preserves_temporal_order(session):
    for i, c in enumerate(["white", "red", "black", "green", "blue"]):
        _write_frame(session, i, c)
    entries = generate_thumbnails(session, max_thumbs=3, dedupe_threshold=0)
    indexes = [e.source_index for e in entries]
    assert indexes == sorted(indexes)


def test_max_thumbs_applied_after_dedup(session):
    # 4 identical, then 2 different — dedup collapses to 3 survivors,
    # a max of 2 should cap even those.
    for i in range(4):
        _write_frame(session, i, "white")
    _write_frame(session, 4, "black")
    _write_frame(session, 5, "red")
    entries = generate_thumbnails(session, max_thumbs=2, dedupe_threshold=0.02)
    assert len(entries) == 2


def test_max_thumbs_none_returns_all_dedup_survivors(session):
    for i, c in enumerate(["white", "black", "red"]):
        _write_frame(session, i, c)
    entries = generate_thumbnails(session, max_thumbs=None, dedupe_threshold=0.02)
    assert len(entries) == 3


def test_frames_scopes_to_subset(session):
    # 5 frames in session; only scope to the last 2
    colors = ["white", "black", "red", "green", "blue"]
    all_paths = [_write_frame(session, i, c) for i, c in enumerate(colors)]
    subset = all_paths[3:]   # [green, blue]
    entries = generate_thumbnails(session, frames=subset, dedupe_threshold=0)
    assert len(entries) == 2
    assert {e.frame_path for e in entries} == set(subset)


def test_frames_none_falls_back_to_whole_session(session):
    for i, c in enumerate(["red", "green", "blue"]):
        _write_frame(session, i, c)
    # frames=None → scans entire session, same as before
    entries = generate_thumbnails(session, frames=None, dedupe_threshold=0)
    assert len(entries) == 3


def test_frames_with_dedupe_collapses_only_within_subset(session):
    _write_frame(session, 0, "red")
    _write_frame(session, 1, "red")      # identical
    _write_frame(session, 2, "black")    # different
    _write_frame(session, 3, "black")    # identical to #2
    # Scope to indexes 2, 3 only — dedupe should collapse them to 1 inside that window
    subset = sorted(session.frames_dir.glob("frame_*.png"))[2:]
    entries = generate_thumbnails(session, frames=subset, dedupe_threshold=0.02)
    assert len(entries) == 1
