# claude-vision

A Claude Code skill that lets the assistant **see** what's on your screen —
single screenshots for static questions, short videos for interactions and
animations. Cross-platform (Linux X11, macOS, Windows, GNOME Wayland) with
pip-only dependencies.

The main conversation context stays clean: the visual pipeline runs inside a
dedicated subagent and returns only a compact textual report.

## How it works

1. Skill `screen-vision` auto-activates when Claude recognizes a visual request
   ("what's on my screen?", "does this header look right?", …).
2. Claude dispatches the `frame-analyst` subagent with the visual question.
3. The subagent picks the mode:
   - **`screenshot`** (default) — one frame, fast, cheap.
   - **`capture`** (video) — multiple frames when motion matters.
4. The subagent runs the `claude_vision` CLI, reads the frames, and produces a
   compact textual report.
5. A `Stop` hook garbage-collects any leftover session directories.

## Install

Pick the install that matches your system, then make sure Claude Code sees it.

```bash
# X11 / macOS / Windows — project venv (recommended)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# GNOME Wayland — uses org.gnome.Shell.Screencast
pip install -e ".[wayland]"
```

### Making the subagent find the package

The `frame-analyst` subagent runs `python3 -m claude_vision ...`. Two ways to
guarantee it resolves:

1. **Activate the venv before launching Claude Code** — `source .venv/bin/activate`
   and then `claude`. The subagent's `python3` will point at the venv.
2. **Or install user-local** — `pip install --user --break-system-packages -e .`
   so any `python3` finds it.

The subagent will also try `$CLAUDE_PROJECT_DIR/.venv/bin/python` first as a
fallback, so the first option works even if you launch CC without activating.

Check your Linux session type with `echo $XDG_SESSION_TYPE`.

**Supported environments**: X11, macOS, Windows, GNOME Wayland.
Not supported: KDE/Sway/Hyprland Wayland sessions.

## CLI

```bash
# Single screenshot (preferred when temporal info is not needed)
python -m claude_vision screenshot --scale-width 1568

# Video: capture 5 seconds at 1 fps, resize frames to 1568px wide
python -m claude_vision capture --duration 5 --fps 1 --scale-width 1568

# Capture at full native resolution (no resize)
python -m claude_vision capture --duration 3 --scale-width 0

# Pick a non-primary monitor
python -m claude_vision capture --duration 5 --monitor 1

# Delete a session's files
python -m claude_vision clean --session <session-id-or-path>

# Garbage-collect stale sessions
python -m claude_vision gc --ttl-hours 2
```

All commands emit JSON on stdout.

### Discovering monitor indices

```bash
python -c "import mss; print(mss.mss().monitors)"
```

## Parameters

| Option          | Default | Meaning                                             |
|-----------------|---------|-----------------------------------------------------|
| `--duration`    | —       | Seconds to capture (required for `capture`; max 120)|
| `--fps`         | 1.0     | Frames per second                                   |
| `--max-frames`  | 24      | Hard cap on emitted frames                          |
| `--scale-width` | 1568    | Target width in pixels; `0` disables resize         |
| `--monitor`     | 0       | Monitor index (0 = primary)                         |

## Layout

```
claude-vision/
├── .claude/
│   ├── skills/screen-vision/SKILL.md   # auto-dispatcher (tool Task only)
│   ├── agents/frame-analyst.md         # subagent that owns the full pipeline
│   ├── hooks/cleanup_sessions.py       # Stop hook (stdlib-only safety net)
│   └── settings.json                   # hook + permissions
├── src/claude_vision/
│   ├── config.py, session.py, errors.py
│   ├── platform_detect.py              # X11 / macOS / Windows / GNOME Wayland
│   ├── cleaner.py, cli.py, __main__.py
│   └── recorders/
│       ├── base.py                     # ABC: capture() + screenshot()
│       ├── mss_recorder.py             # mss + Pillow
│       └── gnome_wayland.py            # D-Bus Screencast + Screenshot
├── tests/                              # 30 stdlib-only tests
├── pyproject.toml
└── README.md
```

## macOS first-run note

macOS will prompt for Screen Recording permission the first time you run
`capture` or `screenshot`. Grant it to your terminal application in
*System Settings → Privacy & Security → Screen Recording*.

## License

MIT.
