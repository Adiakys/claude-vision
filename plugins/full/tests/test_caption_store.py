"""Unit tests for the caption JSONL log."""

from pathlib import Path

import pytest

from claude_vision.config import CaptureConfig
from claude_vision.ml.caption_store import (
    CaptionEntry,
    append_caption,
    count_captions,
    read_captions,
    truncate_captions,
)
from claude_vision.session import Session


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session.create(CaptureConfig(session_root=tmp_path))


def _entry(t: int = 1000, caption: str = "test") -> CaptionEntry:
    return CaptionEntry(
        timestamp_ms=t,
        frame_path=f"/tmp/frame_{t}.png",
        caption=caption,
    )


def test_empty_log_reads_empty_list(session):
    assert read_captions(session) == []


def test_append_then_read_roundtrip(session):
    entry = _entry(t=1000, caption="A blue sky")
    append_caption(session, entry)
    rows = read_captions(session)
    assert len(rows) == 1
    assert rows[0] == entry


def test_multiple_appends_preserve_order(session):
    append_caption(session, _entry(t=1000, caption="first"))
    append_caption(session, _entry(t=2000, caption="second"))
    append_caption(session, _entry(t=3000, caption="third"))
    rows = read_captions(session)
    assert [r.caption for r in rows] == ["first", "second", "third"]


def test_since_ms_filters_old_entries(session):
    append_caption(session, _entry(t=1000))
    append_caption(session, _entry(t=2000))
    append_caption(session, _entry(t=3000))
    rows = read_captions(session, since_ms=2000)
    assert [r.timestamp_ms for r in rows] == [2000, 3000]


def test_only_matches_returns_trigger_rows_only(session):
    append_caption(session, _entry(t=1000))
    append_caption(session, CaptionEntry(
        timestamp_ms=2000, frame_path="/a.png",
        caption="match!", trigger_match=True,
    ))
    append_caption(session, _entry(t=3000))
    rows = read_captions(session, only_matches=True)
    assert len(rows) == 1
    assert rows[0].trigger_match is True


def test_count_captions_matches_read_length(session):
    for t in range(1000, 1500, 100):
        append_caption(session, _entry(t=t))
    assert count_captions(session) == 5
    assert count_captions(session) == len(read_captions(session))


def test_count_empty_log_is_zero(session):
    assert count_captions(session) == 0


def test_truncate_removes_log(session):
    append_caption(session, _entry())
    truncate_captions(session)
    assert read_captions(session) == []
    assert count_captions(session) == 0


def test_truncate_is_idempotent(session):
    truncate_captions(session)
    truncate_captions(session)  # must not raise


def test_torn_last_line_is_tolerated(session):
    """Daemon killed mid-write — the final line may be incomplete."""
    append_caption(session, _entry(t=1000, caption="good"))
    # Append a half-written JSON fragment manually
    log_path = session.root / "captions.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write('{"timestamp_ms": 2000, "caption": "in')
    rows = read_captions(session)
    assert len(rows) == 1
    assert rows[0].caption == "good"
