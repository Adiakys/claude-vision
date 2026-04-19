"""Local machine-learning features (present only in the `claude-vision-full`
variant of the plugin).

The base `claude-vision` plugin never imports from this package — this
keeps the base install lean (no torch / transformers dependency).

Public API:
    SmolVLMCaptioner  — wrap a local SmolVLM model to caption image frames.
    CaptionEntry      — one row in the JSONL caption log.
    append_caption    — atomic append to a session's caption log.
    read_captions     — read / filter the log.
    resolve_device    — pick "cuda" | "mps" | "cpu" for the user's environment.
"""

from .captioner import (
    DEFAULT_CAPTION_MODEL,
    SUPPORTED_CAPTION_MODELS,
    SmolVLMCaptioner,
    resolve_device,
)

__all__ = [
    "SmolVLMCaptioner",
    "resolve_device",
    "DEFAULT_CAPTION_MODEL",
    "SUPPORTED_CAPTION_MODELS",
]
