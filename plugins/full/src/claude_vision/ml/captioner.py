"""Local image captioning via SmolVLM, used during continuous watch sessions.

SmolVLM-256M-Instruct is the default model: ~250 MB, ~100ms per frame on a
modern CPU, ~20–40ms on GPU/MPS. Quality is sufficient for narrative
captions ("a browser showing a GitHub page", "a terminal with a compile
error") — enough for Claude to answer "what happened during the watch?"
from the text log instead of reading raw frames.

The 500M variant is also accepted out of the box for users who want more
detail at the cost of ~2x the latency. Other models (Florence-2, MoonDream,
BLIP-2) are slated for v0.8+ as separate backend classes.

``torch`` and ``transformers`` are imported lazily: the very first import
of this module must not fail on systems where the `ml` extra isn't
installed (the importer gets a clear ``PlatformUnsupportedError`` when it
actually tries to construct the captioner).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

from ..errors import PlatformUnsupportedError

log = logging.getLogger(__name__)

DEFAULT_CAPTION_MODEL = "HuggingFaceTB/SmolVLM-256M-Instruct"
SUPPORTED_CAPTION_MODELS = frozenset({
    "HuggingFaceTB/SmolVLM-256M-Instruct",
    "HuggingFaceTB/SmolVLM-500M-Instruct",
})

_DEFAULT_PROMPT = "Describe this image in one sentence."
_DETAILED_PROMPT = (
    "Describe this image in two to three sentences, mentioning the "
    "visible application or webpage, what content is on screen, and any "
    "notable UI state."
)

_MAX_NEW_TOKENS_DEFAULT = 60
_MAX_NEW_TOKENS_DETAILED = 160

# Valid values for the --caption-device flag.
VALID_DEVICES = {"auto", "cpu", "cuda", "mps"}


class SmolVLMCaptioner:
    """SmolVLM-family image captioner.

    Loaded once on construction, kept in memory for the caller's lifetime.
    Thread-unsafe — intended to live inside the watch daemon's single loop.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_CAPTION_MODEL,
        device: str = "auto",
        cache_dir: Path | str | None = None,
    ) -> None:
        if model_id not in SUPPORTED_CAPTION_MODELS:
            raise PlatformUnsupportedError(
                f"model {model_id!r} is not supported in v0.7. "
                f"Supported: {sorted(SUPPORTED_CAPTION_MODELS)}. "
                "Other backends (Florence, MoonDream) are on the v0.8+ roadmap."
            )
        if device not in VALID_DEVICES:
            raise PlatformUnsupportedError(
                f"device {device!r} must be one of {sorted(VALID_DEVICES)}"
            )

        torch = _load_torch()
        transformers = _load_transformers()

        self.model_id = model_id
        self.device = resolve_device(device, torch=torch)
        self._cache_dir = str(cache_dir) if cache_dir is not None else None

        log.info("loading %s on %s (cache=%s)",
                 model_id, self.device, self._cache_dir or "<default>")

        self._processor = transformers.AutoProcessor.from_pretrained(
            model_id, cache_dir=self._cache_dir,
        )
        model = transformers.AutoModelForVision2Seq.from_pretrained(
            model_id,
            cache_dir=self._cache_dir,
            torch_dtype=torch.float32,
        )
        self._model = model.to(self.device).eval()
        self._torch = torch

    def caption(self, image: Image.Image, *, detailed: bool = False) -> str:
        """Produce a short text description of ``image``.

        With ``detailed=True`` the description is 2–3 sentences instead of 1.
        """
        prompt = _DETAILED_PROMPT if detailed else _DEFAULT_PROMPT
        max_new = _MAX_NEW_TOKENS_DETAILED if detailed else _MAX_NEW_TOKENS_DEFAULT

        messages = [{
            "role": "user",
            "content": [{"type": "image"}, {"type": "text", "text": prompt}],
        }]
        chat = self._processor.apply_chat_template(
            messages, add_generation_prompt=True,
        )
        inputs = self._processor(
            text=chat, images=[image], return_tensors="pt",
        ).to(self.device)

        with self._torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new,
                do_sample=False,
            )

        text = self._processor.batch_decode(
            output_ids, skip_special_tokens=True,
        )[0]
        return _strip_chat_prompt(text, prompt)


def resolve_device(requested: str, *, torch: Any | None = None) -> str:
    """Map ``auto|cuda|mps|cpu`` to the concrete device string to pass
    to ``model.to()``. Explicit requests that aren't available raise
    ``PlatformUnsupportedError`` with a clear hint.
    """
    if requested not in VALID_DEVICES:
        raise PlatformUnsupportedError(
            f"device {requested!r} must be one of {sorted(VALID_DEVICES)}"
        )
    if torch is None:
        torch = _load_torch()

    cuda_ok = torch.cuda.is_available()
    mps_ok = _mps_available(torch)

    if requested == "cuda":
        if not cuda_ok:
            raise PlatformUnsupportedError(
                "CUDA requested but torch.cuda.is_available() is False. "
                "Install torch with CUDA support (see docs) or pass "
                "--caption-device cpu."
            )
        return "cuda"
    if requested == "mps":
        if not mps_ok:
            raise PlatformUnsupportedError(
                "MPS requested but not available on this system. "
                "MPS needs macOS ≥ 12.3 on Apple Silicon with torch ≥ 2.1."
            )
        return "mps"
    if requested == "cpu":
        return "cpu"

    # requested == "auto"
    if cuda_ok:
        return "cuda"
    if mps_ok:
        return "mps"
    return "cpu"


def _mps_available(torch: Any) -> bool:
    backends = getattr(torch, "backends", None)
    if backends is None:
        return False
    mps = getattr(backends, "mps", None)
    if mps is None:
        return False
    return bool(mps.is_available())


def _load_torch():
    try:
        import torch  # noqa: F401
    except ImportError as exc:
        raise PlatformUnsupportedError(
            "local captioning requires the `claude-vision-full` variant "
            "(torch is not installed). Install with the full plugin."
        ) from exc
    return torch


def _load_transformers():
    try:
        import transformers  # noqa: F401
    except ImportError as exc:
        raise PlatformUnsupportedError(
            "local captioning requires the `claude-vision-full` variant "
            "(transformers is not installed). Install with the full plugin."
        ) from exc
    return transformers


def _strip_chat_prompt(full_text: str, user_prompt: str) -> str:
    """The decoded output often echoes the user's prompt before the
    assistant's reply. Strip it so the caller gets just the caption.
    """
    # Heuristic: find the last occurrence of the prompt text and return
    # whatever follows (after whitespace). Falls back to the whole text
    # if the prompt isn't echoed verbatim.
    idx = full_text.rfind(user_prompt)
    if idx >= 0:
        tail = full_text[idx + len(user_prompt):]
        return tail.strip()
    # Some chat templates emit an "Assistant:" marker instead.
    for marker in ("Assistant:", "assistant:"):
        if marker in full_text:
            return full_text.split(marker, 1)[-1].strip()
    return full_text.strip()
