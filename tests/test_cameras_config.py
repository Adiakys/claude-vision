"""Config validation for webcam-relevant fields. No webcam I/O (needs hardware)."""

import pytest

from claude_vision.config import CaptureConfig
from claude_vision.errors import InvalidConfigError


def test_default_device_index_is_zero():
    cfg = CaptureConfig()
    assert cfg.device_index == 0


@pytest.mark.parametrize("idx", [0, 1, 2, 5])
def test_valid_device_indices(idx: int):
    cfg = CaptureConfig(device_index=idx)
    assert cfg.device_index == idx


def test_negative_device_index_rejected():
    with pytest.raises(InvalidConfigError):
        CaptureConfig(device_index=-1)


def test_device_and_monitor_are_independent():
    cfg = CaptureConfig(monitor_index=2, device_index=1)
    assert cfg.monitor_index == 2
    assert cfg.device_index == 1


def test_webcam_config_ignores_duration_for_snapshot_use():
    """A snapshot-style config does not need an explicit duration."""
    cfg = CaptureConfig(scale_width=800, device_index=0)
    assert cfg.scale_width == 800
    assert cfg.duration_s == 1.0  # harmless default
