"""Recorder for GNOME Wayland.

Two distinct D-Bus surfaces are used, because GNOME 47+ locks each one
down to different callers:

- **Video** → ``org.gnome.Shell.Screencast`` (gnome-shell private).
  Still reachable for regular processes. The screencast pipeline is tied
  to the **lifetime of the D-Bus sender**: if the caller's connection
  closes, gnome-shell aborts with ``Error.RecorderError: 'Sender has
  vanished'`` and truncates the webm. We therefore hold one jeepney
  session-bus connection open across ``Screencast`` → sleep →
  ``StopScreencast`` to keep the session alive.

- **Snapshot** → ``org.freedesktop.portal.Screenshot`` (xdg-desktop-portal).
  gnome-shell's own Screenshot D-Bus returns AccessDenied for
  non-sandboxed apps on GNOME 47+. The portal is the sanctioned route.
  The portal is async: we call ``Screenshot`` to get a Request object
  path, then wait for the ``Response`` signal on it.
"""

from __future__ import annotations

import secrets
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from ..errors import CaptureError, PlatformUnsupportedError
from ..notify import notify
from .base import ScreenRecorder
from .mss_recorder import _deduper_stats, _maybe_deduper, _maybe_resize

SCREENCAST_BUS = "org.gnome.Shell.Screencast"
SCREENCAST_PATH = "/org/gnome/Shell/Screencast"
SCREENCAST_IFACE = "org.gnome.Shell.Screencast"

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"
PORTAL_REQUEST_IFACE = "org.freedesktop.portal.Request"

PORTAL_RESPONSE_TIMEOUT_S = 30.0


class GnomeWaylandRecorder(ScreenRecorder):
    def capture(self) -> list[Path]:
        imageio = _require_imageio()
        webm = self.session.root / "recording.webm"
        fps = self.config.effective_fps()

        notify(f"📷 Recording {self.config.duration_s:.0f}s of screen...")
        with _session_bus() as conn:
            self._start_screencast(conn, webm, fps)
            try:
                time.sleep(self.config.duration_s)
            finally:
                self._stop_screencast(conn)

        if not webm.exists() or webm.stat().st_size == 0:
            raise CaptureError(
                f"GNOME Shell did not produce a recording at {webm}. "
                "If this is the first run, GNOME may have shown a permission "
                "prompt — accept it and retry."
            )

        frames, stats = self._extract_frames(imageio, webm)
        webm.unlink(missing_ok=True)
        self.stats = stats
        notify(f"✓ Screen capture done ({len(frames)} frames kept)")
        return frames

    def screenshot(self) -> Path:
        output = self.session.frames_dir / "frame_0000.png"
        with _session_bus() as conn:
            _portal_screenshot(conn, output)
        if self.config.region is not None:
            # Portal has no region option: crop post-capture.
            image = Image.open(output)
            image = image.crop(self.config.region.as_pil_bbox())
            image.save(output, "PNG", optimize=True)
        if self.config.scale_width > 0:
            image = Image.open(output)
            image = _maybe_resize(image, self.config.scale_width)
            image.save(output, "PNG", optimize=True)
        return output

    def _start_screencast(self, conn, webm: Path, fps: float) -> None:
        jeepney = _require_jeepney()
        addr = jeepney.DBusAddress(
            object_path=SCREENCAST_PATH,
            bus_name=SCREENCAST_BUS,
            interface=SCREENCAST_IFACE,
        )
        options = {
            "framerate": ("u", max(1, int(round(fps)))),
            "draw-cursor": ("b", True),
        }
        msg = jeepney.new_method_call(
            addr, "Screencast", "sa{sv}", (str(webm), options)
        )
        reply = _send(conn, msg, "Screencast")
        success, filename_used = reply.body
        if not success:
            raise CaptureError(
                f"GNOME Shell refused to start Screencast "
                f"(filename={filename_used}). A permission prompt may be "
                "pending — accept it and retry."
            )

    def _stop_screencast(self, conn) -> None:
        jeepney = _require_jeepney()
        addr = jeepney.DBusAddress(
            object_path=SCREENCAST_PATH,
            bus_name=SCREENCAST_BUS,
            interface=SCREENCAST_IFACE,
        )
        msg = jeepney.new_method_call(addr, "StopScreencast", "", ())
        try:
            _send(conn, msg, "StopScreencast")
        except CaptureError:
            # Best-effort: don't let a stop failure shadow a downstream
            # decode error from an already-closed session.
            pass

    def _extract_frames(self, imageio, webm: Path) -> tuple[list[Path], dict]:
        max_frames = self.config.max_frames
        scale_width = self.config.scale_width
        region = self.config.region
        deduper = _maybe_deduper(self.config)
        frames: list[Path] = []
        decoded = 0
        for array in imageio.imiter(webm, plugin="FFMPEG"):
            if len(frames) >= max_frames:
                break
            decoded += 1
            image = Image.fromarray(array)
            # GNOME Screencast D-Bus has no region option, so we crop
            # post-decode. mss path uses native region; stays symmetric.
            if region is not None:
                image = image.crop(region.as_pil_bbox())
            if deduper is not None and not deduper.should_keep(image):
                continue
            image = _maybe_resize(image, scale_width)
            path = self.session.frames_dir / f"frame_{len(frames):04d}.png"
            image.save(path, "PNG", optimize=True)
            frames.append(path)
        if not frames:
            raise CaptureError("No frames decoded from GNOME screencast output.")
        return frames, _deduper_stats(deduper, decoded, len(frames))


def _portal_screenshot(conn, output: Path) -> None:
    jeepney = _require_jeepney()
    token = "cv" + secrets.token_hex(6)
    addr = jeepney.DBusAddress(
        object_path=PORTAL_PATH,
        bus_name=PORTAL_BUS,
        interface=PORTAL_SCREENSHOT_IFACE,
    )
    opts = {
        "handle_token": ("s", token),
        "interactive": ("b", False),
        "modal": ("b", False),
    }
    # parent_window is empty for headless requests (no X11 window id on Wayland).
    msg = jeepney.new_method_call(addr, "Screenshot", "sa{sv}", ("", opts))
    reply = _send(conn, msg, "Portal Screenshot")
    request_path = reply.body[0]

    rule = jeepney.MatchRule(
        type="signal",
        interface=PORTAL_REQUEST_IFACE,
        member="Response",
        path=request_path,
    )
    add_match = jeepney.new_method_call(
        jeepney.message_bus, "AddMatch", "s", (rule.serialise(),),
    )
    _send(conn, add_match, "AddMatch")

    try:
        deadline = time.monotonic() + PORTAL_RESPONSE_TIMEOUT_S
        while time.monotonic() < deadline:
            sig = conn.receive()
            if sig.header.message_type != jeepney.MessageType.signal:
                continue
            fields = sig.header.fields
            if fields.get(jeepney.HeaderFields.path) != request_path:
                continue
            if fields.get(jeepney.HeaderFields.member) != "Response":
                continue
            code, results = sig.body
            if code == 1:
                raise CaptureError(
                    "Portal Screenshot was cancelled by the user."
                )
            if code == 2:
                raise CaptureError("Portal Screenshot ended before producing output.")
            if code != 0:
                raise CaptureError(f"Portal Screenshot response={code}")
            uri_variant = results.get("uri")
            if uri_variant is None:
                raise CaptureError("Portal Screenshot returned no URI")
            uri = uri_variant[1]
            if not uri.startswith("file://"):
                raise CaptureError(f"Portal returned unsupported URI: {uri}")
            src = Path(uri[len("file://"):])
            # move (not copy) so we don't pollute the user's default
            # screenshots directory with a duplicate.
            try:
                shutil.move(src, output)
            except Exception:
                shutil.copyfile(src, output)
                src.unlink(missing_ok=True)
            return
        raise CaptureError(
            f"Portal Screenshot timed out after {PORTAL_RESPONSE_TIMEOUT_S:.0f}s."
        )
    finally:
        rm_match = jeepney.new_method_call(
            jeepney.message_bus, "RemoveMatch", "s", (rule.serialise(),),
        )
        try:
            _send(conn, rm_match, "RemoveMatch")
        except CaptureError:
            pass


@contextmanager
def _session_bus():
    _require_jeepney()
    from jeepney.io.blocking import open_dbus_connection

    conn = open_dbus_connection(bus="SESSION")
    try:
        yield conn
    finally:
        conn.close()


def _send(conn, msg, label: str):
    """Dispatch a D-Bus call and raise CaptureError on error reply."""
    jeepney = _require_jeepney()
    reply = conn.send_and_get_reply(msg)
    if reply.header.message_type == jeepney.MessageType.error:
        err_name = reply.header.fields.get(jeepney.HeaderFields.error_name, "")
        detail = reply.body[0] if reply.body else ""
        raise CaptureError(f"{label} failed: {err_name}: {detail}".strip(": "))
    return reply


def _require_jeepney():
    try:
        import jeepney  # noqa: F401
        return jeepney
    except ImportError as exc:
        raise PlatformUnsupportedError(
            "GNOME Wayland capture needs the [wayland] extra: "
            "install with `pip install claude-vision[wayland]`."
        ) from exc


def _require_imageio():
    try:
        import imageio.v3 as imageio
    except ImportError as exc:
        raise PlatformUnsupportedError(
            "GNOME Wayland capture needs the [wayland] extra: "
            "install with `pip install claude-vision[wayland]`."
        ) from exc
    return imageio
