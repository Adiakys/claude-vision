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

```
/plugin marketplace add Adiakys/claude-vision
/plugin install claude-vision@claude-vision
```

At the next session start, the plugin bootstraps itself: it runs
`pip install --target` to place `mss`, `Pillow`, `imageio` and `opencv-python-headless`
into `${CLAUDE_PLUGIN_DATA}/lib` — isolated, no venv, no global `site-packages`
pollution, no tools to install besides `python3` (3.10+) and `pip`, both
available by default on every supported OS.

First session start takes ~20–30 seconds while pip downloads; subsequent
starts are instant (a hash marker skips reinstall until `pyproject.toml`
changes).

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

| Option          | Default | Meaning                                             |
|-----------------|---------|-----------------------------------------------------|
| `--duration`    | —       | Seconds to capture (required for video; max 120)    |
| `--fps`         | 1.0     | Frames per second                                   |
| `--max-frames`  | 24      | Hard cap on emitted frames                          |
| `--scale-width` | 1568    | Target width in pixels; `0` disables resize         |
| `--monitor`     | 0       | Monitor index for screen commands (0 = primary)     |
| `--device`      | 0       | Webcam device index for webcam commands             |

## Layout

```
claude-vision/
├── .claude-plugin/
│   ├── plugin.json                     # plugin manifest
│   └── marketplace.json                # single-plugin marketplace manifest
├── skills/screen-vision/SKILL.md       # auto-dispatcher (tool Task only)
├── agents/frame-analyst.md             # subagent that owns the full pipeline
├── hooks/
│   ├── hooks.json                      # SessionStart + Stop hook registration
│   ├── bootstrap.sh                    # pip install --target into plugin data dir
│   └── cleanup_sessions.py             # Stop hook (stdlib-only)
├── bin/claude-vision                   # shell wrapper: sets PYTHONPATH and runs python3 -m claude_vision
├── src/claude_vision/
│   ├── config.py, session.py, errors.py
│   ├── platform_detect.py              # X11 / macOS / Windows / GNOME Wayland
│   ├── cleaner.py, cli.py, __main__.py
│   ├── recorders/
│   │   ├── base.py                     # ABC: capture() + screenshot()
│   │   ├── mss_recorder.py             # mss + Pillow (screen)
│   │   └── gnome_wayland.py            # D-Bus Screencast + Screenshot
│   └── cameras/
│       ├── base.py                     # ABC: snapshot() + record()
│       └── opencv_camera.py            # OpenCV (webcam, cross-platform)
├── tests/                              # 39 stdlib-only tests
├── pyproject.toml
└── README.md
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
