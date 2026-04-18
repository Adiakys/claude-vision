"""Unit tests for the Session.frames_seen watermark used by watch mode."""

from pathlib import Path

import pytest

from claude_vision.config import CaptureConfig
from claude_vision.session import Session


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session.create(CaptureConfig(session_root=tmp_path))


def test_frames_seen_starts_empty(session: Session):
    assert session.frames_seen() == set()


def test_mark_frames_seen_is_additive(session: Session):
    a = session.frames_dir / "frame_001.png"
    b = session.frames_dir / "frame_002.png"
    session.mark_frames_seen([a])
    assert session.frames_seen() == {str(a)}
    session.mark_frames_seen([b])
    assert session.frames_seen() == {str(a), str(b)}


def test_mark_frames_seen_is_idempotent(session: Session):
    path = session.frames_dir / "frame_xyz.png"
    session.mark_frames_seen([path])
    session.mark_frames_seen([path])
    assert session.frames_seen() == {str(path)}


def test_mark_frames_seen_accepts_path_iterable(session: Session):
    paths = [session.frames_dir / f"frame_{i}.png" for i in range(5)]
    session.mark_frames_seen(paths)
    assert session.frames_seen() == {str(p) for p in paths}


def test_mark_frames_seen_persists_across_load(session: Session, tmp_path: Path):
    paths = [session.frames_dir / "frame_p.png"]
    session.mark_frames_seen(paths)
    reloaded = Session.load(session.root)
    assert reloaded.frames_seen() == {str(paths[0])}


def test_mark_frames_seen_survives_status_changes(session: Session):
    path = session.frames_dir / "frame_q.png"
    session.mark_frames_seen([path])
    session.mark("analyzing")
    assert session.frames_seen() == {str(path)}
    assert session.status() == "analyzing"
