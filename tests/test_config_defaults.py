from claude_vision.config import CaptureConfig


def test_config_can_be_built_without_duration_for_screenshot_mode():
    cfg = CaptureConfig()
    assert cfg.duration_s == 1.0
    assert cfg.scale_width == 1568


def test_config_screenshot_keeps_custom_scale_and_monitor():
    cfg = CaptureConfig(scale_width=800, monitor_index=1)
    assert cfg.scale_width == 800
    assert cfg.monitor_index == 1
