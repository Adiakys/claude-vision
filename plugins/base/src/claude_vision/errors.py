"""Typed exceptions raised by the package."""


class ClaudeVisionError(Exception):
    """Base class for all package errors."""


class InvalidConfigError(ClaudeVisionError):
    """A CaptureConfig field has an out-of-range or inconsistent value."""


class PlatformUnsupportedError(ClaudeVisionError):
    """The current platform cannot be used for capture."""


class CaptureError(ClaudeVisionError):
    """A runtime failure occurred during the capture pipeline."""


class WebcamPermissionError(CaptureError):
    """Webcam access denied by OS (macOS TCC) or device busy (held by another app)."""
