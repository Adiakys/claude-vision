"""Interactive region pickers — three backends tried in order.

Given the user's drag on screen, produce a ``Region`` for the capture
pipeline. Each backend is a ``() -> Region | _NotAvailable`` callable;
``pick_interactive()`` walks them and returns the first real result.

Preference order:

1. **tkinter** — stdlib overlay. Ships with Python on macOS, Windows,
   Fedora, Arch; Debian/Ubuntu split it out as ``python3-tk``.
2. **pygame** — pip dependency pulled by the bootstrap when tkinter is
   missing. Heavier (~25 MB) but works on the same screen model.
3. **GNOME Shell** via ``gdbus`` — legacy path that only works on
   GNOME < 41; modern Shell returns ``AccessDenied`` and we move on.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time

from .errors import CaptureError
from .region import Region

# Sentinel returned by a backend when it cannot run in this environment.
_NOT_AVAILABLE = object()


def pick_interactive() -> Region:
    """Ask the user to drag a rectangle; return the selected ``Region``.

    Raises ``CaptureError`` if no backend succeeds, the user cancels, or
    the resulting selection is empty.
    """
    for backend in _PICKER_BACKENDS:
        result = backend()
        if result is _NOT_AVAILABLE:
            continue
        return result
    raise CaptureError(
        "No interactive region picker is available on this system.\n"
        "  - Reinstall the plugin so the bootstrap pulls `pygame-ce`\n"
        "  - Or install tkinter: Debian/Ubuntu `apt install python3-tk`\n"
        "  - Or pass --region X,Y,W,H with explicit coordinates"
    )


# ---------------------------------------------------------------------------
# Backend 1: GNOME Shell built-in SelectArea (legacy, < GNOME 41)


def _pick_gnome_shell():
    """GNOME Shell's built-in interactive selector via D-Bus.

    Works only on legacy GNOME (< 41). GNOME 41+ locked ``SelectArea`` to
    trusted callers; the call returns ``AccessDenied`` and we fall through.
    """
    if not shutil.which("gdbus"):
        return _NOT_AVAILABLE

    result = subprocess.run(
        ["gdbus", "call", "--session",
         "--dest", "org.gnome.Shell.Screenshot",
         "--object-path", "/org/gnome/Shell/Screenshot",
         "--method", "org.gnome.Shell.Screenshot.SelectArea"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").lower()
        # GNOME 41+ locks this method down for external callers.
        if "accessdenied" in stderr or "not allowed" in stderr:
            return _NOT_AVAILABLE
        # Method doesn't exist (non-GNOME or stripped shell).
        if "unknown method" in stderr or "no such interface" in stderr:
            return _NOT_AVAILABLE
        # Any other non-zero exit: treat as user cancellation.
        raise CaptureError("region selection cancelled")

    numbers = re.findall(r"-?\d+", result.stdout)
    if len(numbers) < 4:
        raise CaptureError(
            f"GNOME SelectArea returned unexpected output: {result.stdout!r}"
        )
    x, y, w, h = (int(n) for n in numbers[:4])
    if w <= 0 or h <= 0:
        raise CaptureError("region selection cancelled")
    return Region(left=x, top=y, width=w, height=h)


# ---------------------------------------------------------------------------
# Backend 2: tkinter fullscreen overlay (stdlib on most platforms)


def _pick_tkinter():
    """Fullscreen semi-transparent tkinter overlay as a cross-platform fallback."""
    try:
        import tkinter as tk
    except ImportError:
        return _NOT_AVAILABLE

    selection = _RegionSelection()
    root = tk.Tk()
    try:
        _configure_tk_overlay(root)
        canvas = tk.Canvas(root, cursor="crosshair", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        _bind_tk_events(root, canvas, selection)
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass

    if selection.cancelled or selection.region is None:
        raise CaptureError("region selection cancelled")
    return selection.region


class _RegionSelection:
    """Mutable container for picker state — used to pass the result out of tk."""

    def __init__(self) -> None:
        self.region: Region | None = None
        self.cancelled: bool = False
        self.start_x: int | None = None
        self.start_y: int | None = None


def _configure_tk_overlay(root) -> None:
    root.attributes("-fullscreen", True)
    root.attributes("-alpha", 0.3)
    root.attributes("-topmost", True)
    root.configure(background="black")
    root.title("claude-vision region picker — drag a rectangle, Esc to cancel")


def _bind_tk_events(root, canvas, selection: _RegionSelection) -> None:
    def on_press(event):
        selection.start_x = event.x_root
        selection.start_y = event.y_root
        canvas.delete("selection")

    def on_drag(event):
        if selection.start_x is None or selection.start_y is None:
            return
        canvas.delete("selection")
        canvas.create_rectangle(
            selection.start_x, selection.start_y, event.x_root, event.y_root,
            outline="red", width=2, tags="selection",
        )

    def on_release(event):
        if selection.start_x is None or selection.start_y is None:
            root.quit()
            return
        x1, x2 = sorted((selection.start_x, event.x_root))
        y1, y2 = sorted((selection.start_y, event.y_root))
        width, height = x2 - x1, y2 - y1
        if width > 0 and height > 0:
            selection.region = Region(left=x1, top=y1, width=width, height=height)
        root.quit()

    def on_cancel(_event=None):
        selection.cancelled = True
        root.quit()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_cancel)


# ---------------------------------------------------------------------------
# Backend 3: pygame-based picker (pip dependency, pulled when tkinter is absent)


def _pick_pygame():
    """pygame-based fullscreen picker — pulled by the bootstrap on systems
    without tkinter. Shows a frozen screenshot of the desktop, dimmed, with
    a live cut-out over the current selection for clear feedback.
    """
    try:
        import pygame
    except ImportError:
        return _NOT_AVAILABLE
    import mss as _mss

    # Snapshot the primary monitor; mss.monitors[0] is the virtual screen
    # (useful for multi-monitor), [1] is the primary. Prefer primary so the
    # pygame window maps 1:1 onto one physical display.
    with _mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)

    try:
        region = _run_pygame_picker(pygame, shot, monitor)
    finally:
        pygame.display.quit()
        pygame.quit()
    # Give the compositor a beat to repaint the desktop before the caller
    # grabs it with mss — otherwise our red selection rectangle can leak
    # into the subsequent capture.
    time.sleep(0.25)
    return region


def _run_pygame_picker(pygame, shot, monitor) -> Region:
    origin_x, origin_y = monitor["left"], monitor["top"]
    width, height = shot.size

    pygame.init()
    pygame.display.set_caption(
        "claude-vision — drag to select a region, Esc to cancel"
    )
    screen = pygame.display.set_mode((width, height), pygame.FULLSCREEN)
    background = pygame.image.frombuffer(shot.rgb, shot.size, "RGB")
    dim = pygame.Surface((width, height))
    dim.set_alpha(80)
    dim.fill((0, 0, 0))

    start = None
    end = None
    clock = pygame.time.Clock()

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise CaptureError("region selection cancelled")
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                raise CaptureError("region selection cancelled")
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                start = event.pos
                end = event.pos
            elif event.type == pygame.MOUSEMOTION and start is not None:
                end = event.pos
            elif (
                event.type == pygame.MOUSEBUTTONUP
                and event.button == 1
                and start is not None
            ):
                x1, x2 = sorted((start[0], event.pos[0]))
                y1, y2 = sorted((start[1], event.pos[1]))
                w, h = x2 - x1, y2 - y1
                if w <= 0 or h <= 0:
                    raise CaptureError("region selection cancelled")
                return Region(
                    left=x1 + origin_x, top=y1 + origin_y, width=w, height=h,
                )

        screen.blit(background, (0, 0))
        screen.blit(dim, (0, 0))
        if start is not None and end is not None:
            x1, x2 = sorted((start[0], end[0]))
            y1, y2 = sorted((start[1], end[1]))
            w, h = x2 - x1, y2 - y1
            if w > 0 and h > 0:
                # Undim the selection area for clear feedback
                screen.blit(background, (x1, y1), (x1, y1, w, h))
                pygame.draw.rect(screen, (255, 40, 40), (x1, y1, w, h), 2)
        pygame.display.flip()
        clock.tick(60)


# Ordered by preference: stdlib tkinter first (no extra weight when present),
# then pygame (pulled by the bootstrap only when tkinter is absent),
# then legacy GNOME SelectArea as a last-resort fallback.
_PICKER_BACKENDS = [_pick_tkinter, _pick_pygame, _pick_gnome_shell]
