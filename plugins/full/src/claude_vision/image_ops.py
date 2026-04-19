"""Image-processing helpers shared across recorders, cameras, and thumbs.

Kept intentionally tiny — just the two resize modes the project actually
uses. Centralizing them avoids the historical cross-module imports (e.g.,
``opencv_camera`` reaching into ``mss_recorder`` to borrow resize logic).
"""

from __future__ import annotations

from PIL import Image


def resize_to_width(image: Image.Image, target_width: int) -> Image.Image:
    """Resize by width, preserving aspect ratio, never upscale.

    Semantics match what a screen/webcam capture wants: when the native
    frame is wider than the target, downsample so the width becomes
    ``target_width``; otherwise return the original. A ``target_width``
    of ``0`` (or any non-positive value) disables resizing entirely.
    """
    if target_width <= 0 or image.width <= target_width:
        return image
    ratio = target_width / image.width
    new_size = (target_width, max(1, int(image.height * ratio)))
    return image.resize(new_size, Image.LANCZOS)


def resize_long_edge(image: Image.Image, target: int) -> Image.Image:
    """Resize so the longer edge is at most ``target``, preserving aspect.

    Used by thumbnail generation. Returns a copy so the caller can still
    reference the original untouched image if needed.
    """
    if target <= 0 or max(image.size) <= target:
        return image
    copy = image.copy()
    copy.thumbnail((target, target), Image.LANCZOS)
    return copy
