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
