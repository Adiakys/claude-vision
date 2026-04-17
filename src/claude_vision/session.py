"""Per-capture filesystem state: session dir, frames dir, marker file."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .config import CaptureConfig

Status = Literal["capturing", "analyzing", "done"]
MARKER_NAME = "session.json"
FRAMES_DIR_NAME = "frames"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Session:
    """Owns the filesystem layout for one capture and its status marker."""

    def __init__(self, root: Path, session_id: str):
        self.root = root
        self.id = session_id

    @property
    def frames_dir(self) -> Path:
        return self.root / FRAMES_DIR_NAME

    @property
    def marker(self) -> Path:
        return self.root / MARKER_NAME

    @classmethod
    def create(cls, config: CaptureConfig) -> "Session":
        session_id = uuid.uuid4().hex[:8]
        root = config.session_root / f"claude-vision-{session_id}"
        root.mkdir(parents=True, exist_ok=False)
        (root / FRAMES_DIR_NAME).mkdir()
        session = cls(root=root, session_id=session_id)
        session._write_marker(
            status="capturing",
            created_at=_now_iso(),
            config=_serialize_config(config),
        )
        return session

    @classmethod
    def load(cls, path: Path) -> "Session":
        marker = path / MARKER_NAME
        data = json.loads(marker.read_text())
        return cls(root=path, session_id=data["id"])

    def mark(self, status: Status) -> None:
        data = json.loads(self.marker.read_text())
        data["status"] = status
        data["updated_at"] = _now_iso()
        self.marker.write_text(json.dumps(data, indent=2))

    def status(self) -> Status:
        return json.loads(self.marker.read_text())["status"]

    def created_at(self) -> datetime:
        raw = json.loads(self.marker.read_text())["created_at"]
        return datetime.fromisoformat(raw)

    def list_frames(self) -> list[Path]:
        return sorted(self.frames_dir.glob("frame_*.png"))

    def _write_marker(self, **payload: object) -> None:
        payload["id"] = self.id
        self.marker.write_text(json.dumps(payload, indent=2, default=str))


def _serialize_config(config: CaptureConfig) -> dict:
    data = asdict(config)
    data["session_root"] = str(config.session_root)
    return data
