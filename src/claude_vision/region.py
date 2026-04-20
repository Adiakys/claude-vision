"""Immutable rectangle type used across capture pipelines.

Kept intentionally small: just the ``Region`` dataclass, its validation,
and the serializers downstream tools need (mss dict, Pillow bbox). The
interactive pickers that *produce* a region live in ``region_picker``
so this module stays free of GUI dependencies (tkinter, pygame, gdbus).
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidConfigError


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise InvalidConfigError(
                f"region must have positive width and height; "
                f"got {self.width}x{self.height}"
            )
        if self.left < 0 or self.top < 0:
            raise InvalidConfigError(
                f"region origin must be non-negative; "
                f"got left={self.left}, top={self.top}"
            )

    def as_mss_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }

    def as_pil_bbox(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) — the shape Pillow's Image.crop() wants."""
        return (self.left, self.top, self.left + self.width, self.top + self.height)

    @classmethod
    def parse(cls, spec: str) -> "Region":
        """Parse ``'X,Y,W,H'`` into a validated ``Region``."""
        parts = spec.split(",")
        if len(parts) != 4:
            raise InvalidConfigError(
                f"region spec must be 'X,Y,W,H'; got {spec!r}"
            )
        try:
            left, top, width, height = (int(p.strip()) for p in parts)
        except ValueError as exc:
            raise InvalidConfigError(
                f"region spec must contain integers; got {spec!r}"
            ) from exc
        return cls(left=left, top=top, width=width, height=height)
