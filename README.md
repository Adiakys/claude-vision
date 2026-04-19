# claude-vision

A Claude Code skill that lets the assistant **see** what's on your screen —
single screenshots for static questions, short videos for interactions and
animations. Cross-platform (Linux X11, macOS, Windows, GNOME Wayland) with
pip-only dependencies.

The main conversation context stays clean: the visual pipeline runs inside a
dedicated subagent and returns only a compact textual report.

## How it works

1. Skill `screen-vision` auto-activates when Claude recognizes a visual request
   ("what's on my screen?", "puoi vedermi?", "does this header look right?", …).
2. Claude dispatches the `frame-analyst` subagent with the visual question.
3. The subagent picks source and mode:
   - Source: **`screen`** (UI, pages, terminal) or **`webcam`** (face, object, room).
   - Mode: **`snapshot`** (default, one frame) or **`video`** (multiple frames when
     motion matters).
4. The subagent runs the `claude_vision` CLI, reads the frames, and produces a
   compact textual report — no image data leaks into the main-agent context.
5. A `Stop` hook garbage-collects any leftover session directories.

## Install as a Claude Code plugin

Two variants are published. Pick one.

### `claude-vision` (base) — recommended default

```
/plugin marketplace add Adiakys/claude-vision
/plugin install claude-vision@claude-vision
```

Everything shipped through v0.6 (screen + webcam capture, region picker,
smart thumbnail selection, continuous watch with live queries, token
optimizations). No ML dependencies. ~100 MB of pip dependencies.

### `claude-vision-full` — adds local captioning

```
/plugin marketplace add Adiakys/claude-vision
/plugin install claude-vision-full@claude-vision
```

Everything in base **plus** a local VLM (SmolVLM-256M) that runs during
watch mode and produces a text caption per kept frame. For retrospective
queries ("what happened in the last 10 minutes?") Claude reads the cheap
text log instead of the raw frames — ~50× fewer tokens on long sessions.

Pulls an additional ~500 MB of pip dependencies (torch CPU, transformers,
accelerate). The model itself (~250 MB) is downloaded the first time the
captioner is invoked, cached in `~/.local/state/claude-vision/models/`.

**GPU**: the bootstrap installs `torch` CPU-only. To use a CUDA GPU,
reinstall torch with CUDA support manually after the plugin bootstrap:

```bash
~/.local/state/claude-vision/bin/pip install --upgrade --force-reinstall \
    torch --index-url https://download.pytorch.org/whl/cu121
```

Then pass `--caption-device cuda` (or leave it `auto` — the captioner
detects CUDA on its own once torch supports it). Apple Silicon users
get MPS acceleration out of the box — the shipped torch CPU wheel
supports it.

### The old v0.6 single-plugin install

```
/plugin install claude-vision@claude-vision
```

still works. `claude-vision` in v0.7 is functionally v0.6 with one
additional CLI subcommand (`watch-captions`) that returns an empty list
when no captions have been written — harmless.

At the next session start, the plugin bootstraps itself: it runs
`pip install --target` to place `mss`, `Pillow`, `imageio` and
`opencv-python-headless` into `~/.local/state/claude-vision/lib/` — isolated,
no venv, no global `site-packages` pollution, no tools to install besides
`python3` (3.10+) and `pip`, both available by default on every supported OS.

It also writes a self-contained wrapper script at
`~/.local/state/claude-vision/bin/claude-vision` that the subagent invokes
directly; this path survives plugin updates and doesn't depend on any
Claude-Code-specific environment variable.

First session start takes ~10 seconds while pip downloads; subsequent
starts are instant (a hash marker skips reinstall until `pyproject.toml`
or the available system libraries change).

The interactive region picker prefers stdlib `tkinter` when present. On
distributions that strip it out (Debian/Ubuntu without `python3-tk`), the
bootstrap transparently pulls `pygame-ce` (~25 MB) as a fallback — no
manual install needed.

**Supported environments**: X11, macOS, Windows, GNOME Wayland.
Not supported: KDE/Sway/Hyprland Wayland sessions.

Check your Linux session type with `echo $XDG_SESSION_TYPE`.

## Standalone CLI (optional)

The Python package also works standalone if you want the CLI outside Claude
Code — for debugging, scripts, or CI:

```bash
git clone https://github.com/Adiakys/claude-vision
cd claude-vision
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[wayland,webcam]"
python -m claude_vision --help
```

## CLI

### Screen

```bash
# Single screenshot (preferred when temporal info is not needed)
python -m claude_vision screenshot --scale-width 1568

# Video: 5 seconds at 1 fps, frames resized to 1568px wide
python -m claude_vision capture --duration 5 --fps 1 --scale-width 1568

# Full native resolution (no resize)
python -m claude_vision capture --duration 3 --scale-width 0

# Non-primary monitor
python -m claude_vision capture --duration 5 --monitor 1

# Capture only a region: interactive picker (drag a rectangle)
python -m claude_vision screenshot --region interactive

# Capture only a region: explicit pixel coords (X,Y,W,H)
python -m claude_vision capture --duration 3 --region 100,200,800,600

# Keep every frame even if nothing moves (default drops near-duplicates)
python -m claude_vision capture --duration 5 --fps 2 --no-dedupe
```

### Webcam

```bash
# Single webcam photo (preferred for static questions)
python -m claude_vision webcam-snapshot --scale-width 1568

# Short webcam video (3s at 2fps)
python -m claude_vision webcam-capture --duration 3 --fps 2 --scale-width 1568

# Non-default webcam (e.g., external USB at index 1)
python -m claude_vision webcam-snapshot --device 1
```

### Local captioning (full variant only)

```bash
# Start a watch with per-frame SmolVLM captioning on auto-detected device
python -m claude_vision watch-start --fps 0.5 --captions

# Higher-quality variant (2x bigger / slower)
python -m claude_vision watch-start --fps 0.5 --captions \
    --caption-model "HuggingFaceTB/SmolVLM-500M-Instruct"

# Force CPU even if a GPU is available (saves battery on laptops)
python -m claude_vision watch-start --fps 0.5 --captions --caption-device cpu

# Read the caption log (defaults to the active watch's session)
python -m claude_vision watch-captions

# Explicit session + time window
python -m claude_vision watch-captions --session <id> --since-seconds 60
```

The caption log is a plain JSONL file at `<session>/captions.jsonl` — it
works even after the watch has stopped and can be queried any time until
the session is garbage-collected.

### Continuous watch (background vision with live queries)

```bash
# Start an open-ended background watch (fps 0.5 = one frame every 2 sec)
python -m claude_vision watch-start --fps 0.5

# Check it's running
python -m claude_vision watch-status

# Mid-watch: get the last 5s of frames + one fresh frame right now
python -m claude_vision watch-query

# Mid-watch: widen the window to the last minute, exclude frames you've
# already looked at
python -m claude_vision watch-query --since-seconds 60 --only-unseen

# Tell the watch "I've analyzed these frames — don't return them again"
python -m claude_vision watch-mark-seen /tmp/.../frame_XXX.png

# Stop the watch (does NOT produce a summary)
python -m claude_vision watch-stop
```

In the Claude Code skill, the subagent handles all of this automatically:
`"guarda cosa faccio"` starts a watch, subsequent questions are answered
from the live session, `"basta"` stops it, and `"riepilogami"` triggers
the summary.

### Thumbnail pre-scan (token-saving)

For multi-frame captures the subagent can generate 256px thumbnails with a
second-pass dedupe and pick only the most informative ones to load at full
resolution:

```bash
# Generate thumbnails for an existing session
python -m claude_vision thumbs --session <session-id-or-path>

# Aggressive collapse (fewer thumbs, larger clusters)
python -m claude_vision thumbs --session <id> --dedupe-threshold 0.05

# Disable second-pass dedupe (one thumb per frame)
python -m claude_vision thumbs --session <id> --dedupe-threshold 0

# Cap the output at the top-N most significant thumbs (by change magnitude,
# temporal order preserved)
python -m claude_vision thumbs --session <id> --max 10
```

The subagent invokes this automatically when a capture returns more than
~4 frames, cutting typical token usage by ~70-90% without losing precision.

### Housekeeping

```bash
# Delete a session's files
python -m claude_vision clean --session <session-id-or-path>

# Garbage-collect stale sessions
python -m claude_vision gc --ttl-hours 2
```

All commands emit JSON on stdout.

### Discovering monitor / device indices

```bash
# Screen monitors
python -c "import mss; print(mss.mss().monitors)"

# Webcam devices (first 5 indices)
python -c "import cv2; [print(i, cv2.VideoCapture(i).isOpened()) for i in range(5)]"
```

## Parameters

| Option                | Default | Meaning                                             |
|-----------------------|---------|-----------------------------------------------------|
| `--duration`          | —       | Seconds to capture (required for video; max 120)    |
| `--fps`               | 1.0     | Frames per second                                   |
| `--max-frames`        | 24      | Hard cap on emitted frames                          |
| `--scale-width`       | 1024    | Target width in pixels; `0` disables resize         |
| `--monitor`           | 0       | Monitor index for screen commands (0 = primary)     |
| `--device`            | 0       | Webcam device index for webcam commands             |
| `--region`            | (full)  | `interactive` or `X,Y,W,H`; screen commands only    |
| `--no-crop`           | (on)    | Webcam only: disable the default center-crop (~1/3 area) |
| `--no-dedupe`         | off     | Keep every frame (video commands); default drops near-identical frames |
| `--dedupe-threshold`  | 0.01    | Mean pixel diff in [0,1] to count as "changed"      |
| `--captions`          | off     | Full variant only: caption each kept frame with SmolVLM |
| `--caption-model`     | SmolVLM-256M-Instruct | Full variant only: any model in the SmolVLM family |
| `--caption-device`    | auto    | Full variant only: `auto` \| `cpu` \| `cuda` \| `mps`   |

## Repository layout

Two installable plugins live side-by-side in `plugins/`. The base plugin
is the source of truth; `scripts/sync.sh` regenerates the full plugin
from it, layering a small set of full-only files on top (the `ml`
module, the ml-extended pyproject, the full bootstrap, and the full
version of the subagent playbook).

```
claude-vision/
├── .claude-plugin/
│   └── marketplace.json                # lists both plugin variants
├── plugins/
│   ├── base/                            # claude-vision — self-contained v0.6++
│   │   ├── .claude-plugin/plugin.json
│   │   ├── skills/screen-vision/SKILL.md
│   │   ├── agents/frame-analyst.md      # baseline playbook (no captioning)
│   │   ├── hooks/
│   │   │   ├── hooks.json
│   │   │   ├── bootstrap.sh             # pip extras: wayland,webcam,picker
│   │   │   └── cleanup_sessions.py
│   │   ├── bin/claude-vision
│   │   ├── src/claude_vision/           # full Python package
│   │   └── pyproject.toml
│   └── full/                            # claude-vision-full = base + ml/
│       ├── .claude-plugin/plugin.json  # different name
│       ├── skills/screen-vision/SKILL.md        # sync'd from base
│       ├── agents/frame-analyst.md     # extended playbook (captioning)
│       ├── hooks/bootstrap.sh           # pip extras: +ml
│       ├── src/claude_vision/
│       │   └── ml/                      # full-only: SmolVLMCaptioner etc.
│       └── pyproject.toml                # adds [ml] optional-dependency
├── scripts/sync.sh                      # regenerates full/ from base/
└── README.md
```

Inside each plugin the Python package layout is the usual one:

```
plugins/base/src/claude_vision/
├── config.py, session.py, errors.py
├── platform_detect.py              # X11 / macOS / Windows / GNOME Wayland
├── region.py                       # Region + tkinter / pygame / GNOME pickers
├── dedupe.py                       # drop near-identical frames during video capture
├── ranking.py                      # signature primitives + rank-by-significance
├── thumbs.py                       # token-saving second-pass dedupe + 256px thumbnails
├── watch.py                        # background daemon + live query controller
├── caption_store.py                # JSONL append/read for the caption log
├── notify.py                       # OS toast notifications on capture start/end
├── cleaner.py, cli.py, __main__.py
├── recorders/
│   ├── base.py                     # ABC: capture() + screenshot()
│   ├── mss_recorder.py             # mss + Pillow (screen)
│   └── gnome_wayland.py            # D-Bus Screencast + Screenshot / ScreenshotArea
└── cameras/
    ├── base.py                     # ABC: snapshot() + record()
    └── opencv_camera.py            # OpenCV (webcam, cross-platform)
```

`plugins/full/src/claude_vision/` is identical except for an additional
`ml/` subpackage:

```
plugins/full/src/claude_vision/ml/
├── __init__.py
└── captioner.py                    # SmolVLMCaptioner + resolve_device
```

## Dev workflow

Always edit `plugins/base/`. When you need full-only changes, edit those
files directly under `plugins/full/` (they're listed in `scripts/sync.sh`
as `FULL_ONLY`). After any change, run:

```bash
./scripts/sync.sh            # regenerate plugins/full/ from base
./scripts/sync.sh --verify   # check they're in sync (safe for CI)
```

Tests run separately against each plugin:

```bash
PYTHONPATH=plugins/base/src pytest plugins/base/tests
PYTHONPATH=plugins/full/src pytest plugins/full/tests
```

## macOS first-run note

macOS will prompt for Screen Recording permission the first time you run
`capture` or `screenshot`, and for Camera permission the first time you run
`webcam-snapshot` or `webcam-capture`. Grant both to your terminal application
in *System Settings → Privacy & Security*.

The TCC permission prompt requires a graphical session. If you run Claude
Code over SSH, webcam calls will hang on the first read; run CC locally
instead.

## Webcam troubleshooting

| Symptom                                              | Fix                                                                 |
|------------------------------------------------------|---------------------------------------------------------------------|
| `PlatformUnsupportedError: install [webcam]`         | `pip install -e ".[webcam]"`                                        |
| `CaptureError: webcam device N not available`        | Wrong index — enumerate devices as shown above                      |
| `WebcamPermissionError: webcam busy or permission…`  | Close browsers / Zoom / OBS / other camera apps, or grant Camera permission |
| Very dark first frames                               | Raise room lighting; the tool already discards 5 warmup frames      |

## License

MIT.
