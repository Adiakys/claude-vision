"""Unit tests for WatchMarker. Mocks os.kill for PID-liveness tests."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_vision import watch as watch_mod
from claude_vision.watch import MARKER_PATH, WatchMarker


@pytest.fixture(autouse=True)
def isolated_marker(tmp_path, monkeypatch):
    """Redirect the marker path into a per-test temporary directory."""
    fake = tmp_path / "active-watch.json"
    monkeypatch.setattr(watch_mod, "MARKER_PATH", fake)
    yield fake


def _write_marker(path: Path, pid: int, session_id: str = "abc123") -> None:
    path.write_text(json.dumps({
        "session_id": session_id,
        "session_path": str(path.parent / f"claude-vision-{session_id}"),
        "pid": pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "fps": 0.5,
    }))


def test_load_returns_none_when_no_marker():
    assert WatchMarker.load_active() is None


def test_load_returns_marker_when_pid_alive(isolated_marker, monkeypatch):
    _write_marker(isolated_marker, pid=os.getpid())
    monkeypatch.setattr(watch_mod, "_pid_alive", lambda _: True)
    marker = WatchMarker.load_active()
    assert marker is not None
    assert marker.pid == os.getpid()


def test_load_clears_stale_marker_when_pid_dead(isolated_marker, monkeypatch):
    _write_marker(isolated_marker, pid=999999)
    monkeypatch.setattr(watch_mod, "_pid_alive", lambda _: False)
    assert WatchMarker.load_active() is None
    assert not isolated_marker.exists()


def test_load_handles_corrupt_marker(isolated_marker):
    isolated_marker.write_text("{not valid json")
    assert WatchMarker.load_active() is None
    assert not isolated_marker.exists()


def test_load_handles_missing_fields(isolated_marker):
    isolated_marker.write_text(json.dumps({"pid": 1}))  # lacks other keys
    assert WatchMarker.load_active() is None
    assert not isolated_marker.exists()


def test_save_writes_round_trippable_marker(isolated_marker, monkeypatch):
    monkeypatch.setattr(watch_mod, "_pid_alive", lambda _: True)
    m = WatchMarker(
        session_id="xyz",
        session_path=Path("/tmp/claude-vision-xyz"),
        pid=os.getpid(),
        started_at=datetime.now(timezone.utc).isoformat(),
        fps=1.0,
    )
    m.save()
    loaded = WatchMarker.load_active()
    assert loaded is not None
    assert loaded.session_id == "xyz"
    assert loaded.pid == os.getpid()


def test_clear_removes_marker(isolated_marker):
    _write_marker(isolated_marker, pid=os.getpid())
    WatchMarker.clear()
    assert not isolated_marker.exists()


def test_clear_is_idempotent():
    WatchMarker.clear()
    WatchMarker.clear()  # must not raise


def test_pid_alive_returns_false_for_invalid_pid():
    assert watch_mod._pid_alive(0) is False
    assert watch_mod._pid_alive(-1) is False


def test_pid_alive_returns_true_for_current_process():
    assert watch_mod._pid_alive(os.getpid()) is True
