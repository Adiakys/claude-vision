import pytest

from claude_vision.config import MAX_DURATION_S, MAX_FRAMES_CAP, CaptureConfig
from claude_vision.errors import InvalidConfigError


def test_defaults_are_valid():
    cfg = CaptureConfig(duration_s=5)
    assert cfg.fps == 1.0
    assert cfg.scale_width == 1024
    assert cfg.monitor_index == 0
    assert cfg.crop_center is False


def test_effective_fps_caps_to_max_frames():
    cfg = CaptureConfig(duration_s=10, fps=10, max_frames=24)
    assert cfg.effective_fps() == 2.4


def test_effective_fps_respects_user_fps_when_below_cap():
    cfg = CaptureConfig(duration_s=10, fps=1, max_frames=24)
    assert cfg.effective_fps() == 1.0


def test_planned_frame_count_never_zero():
    cfg = CaptureConfig(duration_s=0.1, fps=0.1)
    assert cfg.planned_frame_count() >= 1


def test_scale_width_zero_allowed_as_full_res_sentinel():
    cfg = CaptureConfig(duration_s=5, scale_width=0)
    assert cfg.scale_width == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"duration_s": 0},
        {"duration_s": -1},
        {"duration_s": MAX_DURATION_S + 1},
        {"duration_s": 5, "fps": 0},
        {"duration_s": 5, "fps": -1},
        {"duration_s": 5, "max_frames": 0},
        {"duration_s": 5, "max_frames": MAX_FRAMES_CAP + 1},
        {"duration_s": 5, "scale_width": -1},
        {"duration_s": 5, "monitor_index": -1},
        {"duration_s": 5, "device_index": -1},
    ],
)
def test_invalid_values_raise(kwargs):
    with pytest.raises(InvalidConfigError):
        CaptureConfig(**kwargs)


def test_frozen():
    cfg = CaptureConfig(duration_s=5)
    with pytest.raises(Exception):
        cfg.duration_s = 10  # type: ignore[misc]
