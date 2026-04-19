import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_vision.cleaner import clean, purge_stale


def _make_session(root: Path, name: str, *, status: str, age: timedelta) -> Path:
    session = root / name
    session.mkdir(parents=True)
    created = (datetime.now(timezone.utc) - age).isoformat()
    (session / "session.json").write_text(
        json.dumps({"id": name.split("-")[-1], "status": status, "created_at": created})
    )
    return session


def test_clean_removes_directory(tmp_path: Path):
    session = tmp_path / "claude-vision-abc"
    session.mkdir()
    (session / "file").write_text("x")
    assert clean(session) is True
    assert not session.exists()


def test_clean_is_idempotent(tmp_path: Path):
    session = tmp_path / "claude-vision-missing"
    assert clean(session) is False


def test_purge_removes_done_sessions(tmp_path: Path):
    done = _make_session(tmp_path, "claude-vision-done", status="done", age=timedelta(minutes=1))
    active = _make_session(tmp_path, "claude-vision-live", status="capturing", age=timedelta(minutes=1))

    removed = purge_stale(tmp_path, ttl=timedelta(hours=2))
    assert done in removed
    assert active not in removed
    assert not done.exists()
    assert active.exists()


def test_purge_respects_active_sessions_under_ttl(tmp_path: Path):
    young = _make_session(tmp_path, "claude-vision-young", status="analyzing", age=timedelta(minutes=1))
    removed = purge_stale(tmp_path, ttl=timedelta(hours=2))
    assert young not in removed
    assert young.exists()


def test_purge_removes_old_active_sessions_past_ttl(tmp_path: Path):
    ancient = _make_session(tmp_path, "claude-vision-ancient", status="analyzing", age=timedelta(hours=3))
    removed = purge_stale(tmp_path, ttl=timedelta(hours=2))
    assert ancient in removed
    assert not ancient.exists()


def test_purge_removes_sessions_without_marker(tmp_path: Path):
    corrupt = tmp_path / "claude-vision-broken"
    corrupt.mkdir()
    removed = purge_stale(tmp_path, ttl=timedelta(hours=2))
    assert corrupt in removed


def test_purge_ignores_unrelated_directories(tmp_path: Path):
    unrelated = tmp_path / "some-other-dir"
    unrelated.mkdir()
    (unrelated / "file").write_text("x")
    removed = purge_stale(tmp_path, ttl=timedelta(hours=2))
    assert unrelated not in removed
    assert unrelated.exists()


def test_purge_on_missing_root_is_noop(tmp_path: Path):
    removed = purge_stale(tmp_path / "does-not-exist")
    assert removed == []
