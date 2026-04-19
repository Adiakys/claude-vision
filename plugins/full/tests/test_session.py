import json
from pathlib import Path

import pytest

from claude_vision.config import CaptureConfig
from claude_vision.session import Session


@pytest.fixture
def config(tmp_path: Path) -> CaptureConfig:
    return CaptureConfig(duration_s=2, session_root=tmp_path)


def test_create_builds_directory_tree(config: CaptureConfig):
    session = Session.create(config)
    assert session.root.is_dir()
    assert session.frames_dir.is_dir()
    assert session.marker.is_file()
    assert session.root.name.startswith("claude-vision-")


def test_marker_contains_expected_fields(config: CaptureConfig):
    session = Session.create(config)
    data = json.loads(session.marker.read_text())
    assert data["id"] == session.id
    assert data["status"] == "capturing"
    assert "created_at" in data
    assert data["config"]["duration_s"] == 2


def test_mark_updates_status(config: CaptureConfig):
    session = Session.create(config)
    session.mark("analyzing")
    assert session.status() == "analyzing"
    session.mark("done")
    assert session.status() == "done"


def test_load_roundtrip(config: CaptureConfig):
    original = Session.create(config)
    loaded = Session.load(original.root)
    assert loaded.id == original.id
    assert loaded.root == original.root


def test_list_frames_is_sorted(config: CaptureConfig):
    session = Session.create(config)
    for i in [2, 0, 1]:
        (session.frames_dir / f"frame_{i:04d}.png").write_bytes(b"\x89PNG\r\n")
    frames = session.list_frames()
    assert [p.name for p in frames] == [
        "frame_0000.png",
        "frame_0001.png",
        "frame_0002.png",
    ]
