# claude-vision — contributor guide

A Claude Code plugin that gives Claude local vision: screen capture, webcam,
region selection, continuous-watch with live queries, and token-cost
reductions. Emits structured JSON from a CLI that a bundled subagent reads.

---

## Running tests

There is no virtualenv. Dependencies are installed by the plugin bootstrap
into `~/.local/state/claude-vision/lib/`. Tests import via PYTHONPATH:

```bash
PYTHONPATH=src:$HOME/.local/state/claude-vision/lib \
  python3 -m pytest tests/ -q
```

---

## Architecture — where things go

```
src/claude_vision/
├── cli.py                  argparse + JSON emit; one handler per subcommand
├── config.py               CaptureConfig dataclass (frozen)
├── session.py              ~/tmp session dirs, marker files
├── platform_detect.py      detect() + preflight(); X11/macOS/Win/GNOMEWayland
├── recorders/              screen capture backends (mss, gnome_wayland)
├── cameras/                webcam backends (opencv)
├── region.py               pure Region dataclass
├── region_picker.py        tkinter/pygame/gdbus GUI backends
├── image_ops.py            resize_to_width, resize_long_edge
├── dedupe.py               FrameDeduper + build_from_config factory
├── ranking.py              signature + compare_signatures (scene change)
├── capture_stats.py        typed stats (planned/kept/skipped)
├── thumbs.py               two-pass thumbnail dedupe
├── watch.py                fork-based daemon + WatchController
├── notify.py               OS desktop notifications
└── cleaner.py              session GC
```

Module boundaries that matter:

- **Recorders/cameras share nothing private.** They all reach into
  `image_ops`, `capture_stats`, `dedupe.build_from_config`. No
  `from .mss_recorder import _foo` cross-imports.
- **`region.py` has no GUI deps.** Safe to import from headless code.
  Picker backends live in `region_picker.py`.
- **`platform_detect` is called once in `cli.main()`**, not in each
  handler. Subparsers opt in via `set_defaults(requires_platform=True)`
  — screen-capturing commands need it, webcam/thumbs/clean/watch-stop
  do not (and would incorrectly fail preflight on non-GNOME Wayland).
- **Heavy/optional deps are lazy.** `mss`, `tkinter`, `pygame`, `imageio`,
  `cv2`, `jeepney` are imported inside functions so the first
  `import claude_vision.<anything>` never hard-fails on a system that
  only needs a subset.

---

## Coding principles we follow

Taken from the clean-code refactor audit — apply to new code.

**Small surfaces, explicit types.**
- Frozen dataclasses for value objects: `Region`, `CaptureStats`,
  `CaptionEntry`, `CaptureConfig`. Avoid `dict[str, int]` when a typed
  object makes the schema self-documenting.
- Factories as module-level functions next to the class
  (`build_from_config(config)` beside `FrameDeduper`), not methods.

**Single responsibility per module.**
- If a module imports `tkinter` *and* serializes data *and* exposes a
  dataclass, split it. `region.py` / `region_picker.py` is the canonical
  example.
- If three call sites share a five-line block, extract it
  (`resize_to_width`, `_add_dedupe_args`). If only two, inline it.

**Fail fast with actionable errors.**
- `PlatformUnsupportedError` tells the user *how to fix* (install the
  extra, switch sessions, pass an alternate flag).
- `CaptureError("region selection cancelled")` is explicit; no silent
  empty-region surprises downstream.
- Validation in `__post_init__` of frozen dataclasses catches bad input
  at construction, not deep in the capture loop.

**Sentinels over exceptions for "backend not available".**
- `region_picker._NOT_AVAILABLE` lets `pick_interactive()` walk backends
  linearly. An `ImportError` here would conflate "missing dep" with
  "user cancelled".

**Docstrings explain *why*, not *what*.**
- `resize_to_width` docstring explains the "never upscale" invariant
  and why `target ≤ 0` disables. It does not paraphrase the signature.
- Leave the WHAT for identifier names to carry.

**Comments only for non-obvious invariants.**
- `# GNOME 41+ locks this method down for external callers.` — yes.
- `# Iterate over frames` — no.

**No backward-compat shims in the same PR.**
- When removing a helper (e.g. `_maybe_deduper`), delete it outright
  and update every caller. Don't leave a re-export.

---

## CLI conventions

- One subcommand per action; handler is `_cmd_<name>(args) -> int`.
- Every command emits a single JSON object on stdout, parsed by the
  subagent. `_emit(payload)` is the only sink.
- Shared flag groups live in `_add_*_args(parser)` helpers —
  `_add_scale_args`, `_add_region_args`, `_add_dedupe_args`,
  `_add_webcam_args`, `_add_monitor_args`. Use them rather than
  re-declaring `--scale-width` in five places.
- Subparsers declare platform need via
  `set_defaults(handler=..., requires_platform=True)`. `main()` runs
  `detect()` + `preflight()` exactly once, stores the result on
  `args.platform`.

---

## Gotchas learned the hard way

- **pygame region picker needs a repaint delay.** `time.sleep(0.25)`
  after `pygame.quit()` so the red selection rectangle doesn't leak
  into the subsequent `mss` capture.
- **mss monitor indexing:** `sct.monitors[0]` is the *virtual* screen
  (union of all displays), `[1]` is the primary. Pygame picker uses
  `[1]` so the window maps 1:1 onto one physical display.
- **GNOME Screencast dies when the D-Bus sender vanishes.** The recorder
  holds one `jeepney` session-bus connection open across
  `Screencast` → sleep → `StopScreencast`. Don't "simplify" to one-shot
  subprocess calls.
- **GNOME 47+ denies `Screenshot` to non-sandboxed apps.** Use
  `org.freedesktop.portal.Screenshot` instead (already wired).
- **The `imageio` plugin is `FFMPEG`, not `pyav`,** for the Wayland
  webm → frames extract. `pyav` is unmaintained and breaks on newer
  wheels.
- **Tests that mock the frame deduper** must reset counters — it's
  stateful across calls.

---

## Commit style

- Imperative subject, ≤ 72 chars, no trailing period.
- Body explains the *why* and the *shape of the change*, not a file
  list (git already shows that).
- Preserve the `Co-Authored-By:` trailer for Claude-assisted commits.
- Don't amend published commits. New commit, new story.

Good examples in the log: `Extract image_ops and CaptureStats...`,
`Split region.py: pure dataclass vs GUI picker backends`.

---

## When in doubt

1. Read the immediately-adjacent module — naming and docstring style is
   established.
2. Check `agents/frame-analyst.md` for the subagent decision tree
   (e.g., when to read thumbs vs full frames).
3. Run the tests. Any new work should keep the count going up, not
   down.
