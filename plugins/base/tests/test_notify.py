"""Unit tests for the OS notification helper."""

from unittest.mock import patch

from claude_vision import notify as notify_mod
from claude_vision.notify import notify


def test_notify_is_silent_when_no_backend(monkeypatch):
    """If shutil.which returns None for every backend, notify() must not raise."""
    monkeypatch.setattr(notify_mod.shutil, "which", lambda _: None)
    notify("anything")  # must not raise


def test_notify_swallows_backend_errors(monkeypatch):
    """If the backend exists but Popen fails, notify() still must not raise."""
    monkeypatch.setattr(notify_mod.shutil, "which", lambda _: "/bin/true")

    def _boom(*args, **kwargs):
        raise OSError("subprocess exploded")

    monkeypatch.setattr(notify_mod.subprocess, "Popen", _boom)
    notify("anything")  # must not raise


def test_linux_backend_invokes_notify_send(monkeypatch):
    monkeypatch.setattr(notify_mod.sys, "platform", "linux")
    monkeypatch.setattr(notify_mod.shutil, "which",
                        lambda cmd: "/usr/bin/notify-send" if cmd == "notify-send" else None)
    called = []
    monkeypatch.setattr(notify_mod.subprocess, "Popen",
                        lambda args, **_: called.append(args))
    notify("hi")
    assert called, "expected Popen to be invoked for Linux backend"
    assert called[0][0] == "notify-send"
    assert "hi" in called[0]


def test_macos_backend_invokes_osascript(monkeypatch):
    monkeypatch.setattr(notify_mod.sys, "platform", "darwin")
    monkeypatch.setattr(notify_mod.shutil, "which",
                        lambda cmd: "/usr/bin/osascript" if cmd == "osascript" else None)
    called = []
    monkeypatch.setattr(notify_mod.subprocess, "Popen",
                        lambda args, **_: called.append(args))
    notify("hello")
    assert called
    assert called[0][0] == "osascript"
    assert any("hello" in part for part in called[0])


def test_notify_escapes_quotes_in_message(monkeypatch):
    monkeypatch.setattr(notify_mod.sys, "platform", "darwin")
    monkeypatch.setattr(notify_mod.shutil, "which", lambda cmd: "/usr/bin/osascript")
    called = []
    monkeypatch.setattr(notify_mod.subprocess, "Popen",
                        lambda args, **_: called.append(args))
    notify('message with "quotes"')
    assert called
    # Ensure no raw unescaped double-quote appears in the message portion
    script = called[0][-1]
    assert '"quotes"' not in script  # quotes must be backslash-escaped
    assert '\\"quotes\\"' in script
