"""Unit tests for the captioner module. Mocks torch + transformers so we
don't need the real models on CI or during iteration."""

from unittest.mock import MagicMock

import pytest
from PIL import Image

from claude_vision.errors import PlatformUnsupportedError
from claude_vision.ml import captioner as captioner_mod
from claude_vision.ml.captioner import (
    DEFAULT_CAPTION_MODEL,
    SUPPORTED_CAPTION_MODELS,
    SmolVLMCaptioner,
    resolve_device,
)


# ----- resolve_device --------------------------------------------------


def _stub_torch(cuda_available: bool = False, mps_available: bool = False):
    torch = MagicMock()
    torch.cuda.is_available.return_value = cuda_available
    torch.backends.mps.is_available.return_value = mps_available
    return torch


def test_resolve_auto_prefers_cuda_over_mps_over_cpu():
    assert resolve_device("auto", torch=_stub_torch(cuda_available=True)) == "cuda"
    assert resolve_device("auto", torch=_stub_torch(mps_available=True)) == "mps"
    assert resolve_device("auto", torch=_stub_torch()) == "cpu"


def test_resolve_cuda_requires_availability():
    assert resolve_device("cuda", torch=_stub_torch(cuda_available=True)) == "cuda"
    with pytest.raises(PlatformUnsupportedError, match="CUDA"):
        resolve_device("cuda", torch=_stub_torch())


def test_resolve_mps_requires_availability():
    assert resolve_device("mps", torch=_stub_torch(mps_available=True)) == "mps"
    with pytest.raises(PlatformUnsupportedError, match="MPS"):
        resolve_device("mps", torch=_stub_torch())


def test_resolve_cpu_always_works():
    assert resolve_device("cpu", torch=_stub_torch()) == "cpu"


def test_resolve_rejects_invalid_device():
    with pytest.raises(PlatformUnsupportedError):
        resolve_device("tpu", torch=_stub_torch())


# ----- constructor validation -----------------------------------------


def test_constructor_rejects_unsupported_model(monkeypatch):
    monkeypatch.setattr(captioner_mod, "_load_torch", _stub_torch)
    monkeypatch.setattr(captioner_mod, "_load_transformers", MagicMock)
    with pytest.raises(PlatformUnsupportedError, match="not supported"):
        SmolVLMCaptioner(model_id="microsoft/Florence-2-base")


def test_constructor_rejects_invalid_device(monkeypatch):
    monkeypatch.setattr(captioner_mod, "_load_torch", _stub_torch)
    monkeypatch.setattr(captioner_mod, "_load_transformers", MagicMock)
    with pytest.raises(PlatformUnsupportedError, match="device"):
        SmolVLMCaptioner(device="tpu")


def test_constructor_bubbles_up_missing_torch(monkeypatch):
    def raise_torch():
        raise PlatformUnsupportedError("torch missing")
    monkeypatch.setattr(captioner_mod, "_load_torch", raise_torch)
    with pytest.raises(PlatformUnsupportedError, match="torch missing"):
        SmolVLMCaptioner()


def test_default_model_is_in_supported_set():
    assert DEFAULT_CAPTION_MODEL in SUPPORTED_CAPTION_MODELS


# ----- caption() with full mocks --------------------------------------


class _FakeProcessor:
    """Just enough of the HF processor surface to drive the captioner."""

    def __init__(self, echo: str):
        self._echo = echo

    def apply_chat_template(self, messages, add_generation_prompt=True):
        # Return a template that echoes the user prompt; the captioner
        # strips it from the decoded output.
        text = messages[0]["content"][-1]["text"]
        return f"<system>\n<user>{text}</user>\n<assistant>"

    def __call__(self, *, text, images, return_tensors):
        batch = MagicMock()
        batch.to.return_value = batch
        return batch

    def batch_decode(self, outputs, skip_special_tokens=True):
        return [self._echo]


def _build_captioner_with_echo(monkeypatch, echo: str):
    torch_stub = _stub_torch()
    torch_stub.no_grad.return_value.__enter__ = lambda self: None
    torch_stub.no_grad.return_value.__exit__ = lambda self, *a: None
    torch_stub.float32 = "float32"

    fake_transformers = MagicMock()
    fake_transformers.AutoProcessor.from_pretrained.return_value = _FakeProcessor(echo)
    fake_model = MagicMock()
    fake_model.to.return_value = fake_model
    fake_model.eval.return_value = fake_model
    fake_model.generate.return_value = ["<tokens>"]
    fake_transformers.AutoModelForVision2Seq.from_pretrained.return_value = fake_model

    monkeypatch.setattr(captioner_mod, "_load_torch", lambda: torch_stub)
    monkeypatch.setattr(captioner_mod, "_load_transformers", lambda: fake_transformers)
    return SmolVLMCaptioner(), fake_model


def test_caption_strips_echoed_prompt(monkeypatch):
    prompt_echo = "Describe this image in one sentence. A red square on a white canvas."
    captioner, _ = _build_captioner_with_echo(monkeypatch, prompt_echo)
    image = Image.new("RGB", (64, 64), "red")
    result = captioner.caption(image)
    assert result == "A red square on a white canvas."


def test_caption_handles_assistant_marker(monkeypatch):
    captioner, _ = _build_captioner_with_echo(
        monkeypatch, "system stuff... Assistant: A terminal with text."
    )
    result = captioner.caption(Image.new("RGB", (10, 10)))
    assert result == "A terminal with text."


def test_caption_detailed_uses_different_prompt(monkeypatch):
    captioner, model = _build_captioner_with_echo(monkeypatch, "ignore")
    captioner.caption(Image.new("RGB", (10, 10)), detailed=True)
    kwargs = model.generate.call_args.kwargs
    # detailed mode requests a larger token budget
    assert kwargs["max_new_tokens"] > 100


def test_caption_default_uses_short_budget(monkeypatch):
    captioner, model = _build_captioner_with_echo(monkeypatch, "ignore")
    captioner.caption(Image.new("RGB", (10, 10)))
    kwargs = model.generate.call_args.kwargs
    assert kwargs["max_new_tokens"] <= 80
