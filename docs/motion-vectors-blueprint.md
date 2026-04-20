# Motion Vectors as an Optimization Lever — Blueprint

> **Status**: design exploration, frozen as reference. Not implemented.
> This document is the starting point for a future decision about
> whether, when, and how to add motion/change tracking to the capture
> pipeline. Not a commitment.

---

## 1. Why motion, at all?

Current stack — what already saves tokens:

- **v0.6 smart frame selection** cut cost 70-90%: dedupe, thumbs-first
  scanning, scoped watch queries.
- **v0.7 local VLM captioning** (WIP): each kept frame becomes ~20
  tokens of text instead of ~1000 tokens of image.

What remains unsolved:

- **Captions describe state, not change.** "browser showing github"
  repeated five times is useless if the relevant fact is that a
  notification appeared for 2s between frame 3 and 4.
- **Frame selection is single-signal.** The deduper ranks by mean
  pixel diff (MAD). It can't tell "uniform scroll" apart from
  "notification appeared", and they carry very different information.

Motion information addresses both gaps. Two levers:

- **Token reduction**: collapse sequences of pure translation
  (scrolling, window drag) into one compact event entry instead of
  N captioned frames.
- **Accuracy on change-detection queries**: "when did X appear?",
  "how many times did Y happen?", "what changed in the last minute?"
  become precise instead of inferred from caption soup.

### Key architectural insight

**Motion extraction does not require a local VLM.** All sources listed
below are deterministic math or metadata harvesting — zero neural
networks involved. Motion is orthogonal to the captioning track, not
dependent on it. Two independent feature lanes:

| Lane | What it adds | Depends on |
|---|---|---|
| Captioning (v0.7+) | "what's on screen" as text | torch, SmolVLM |
| Motion | "what changed between frames" | numpy (+ optional OS APIs) |

They **compose** when both exist (motion selects frames, captions
enrich them) but neither is a prerequisite for the other.

---

## 2. Sources of motion information

From cheapest to richest. Each answers a different question.

### A. Pixel-level

| Primitive | Cost | What it tells you |
|---|---|---|
| A1 Mean absolute diff (MAD) | trivial | "how much changed" — already in `ranking.compare_signatures` |
| A2 Tiled MAD (6×4 grid) | ~2ms | "where it changed" — peak tile identifies region |
| A3 Change binary mask + connected components | ~5ms | "shape of the change" — discrete rectangles |
| A4 Temporal region tracking (centroid NN across frames) | ~10ms | "what appeared/disappeared/translated" |

Dependencies: `numpy` + `Pillow` (already present). No new deps.

### B. Frequency-domain

| Primitive | Cost | What it tells you |
|---|---|---|
| B1 Phase correlation (FFT-based) | ~5ms | Exact global translation `(dx, dy)` — perfect for scrolling |
| B2 Tiled phase correlation (6×4 grid) | ~20ms | Per-region translation — distinguishes "browser scrolled, taskbar didn't" |

Dependencies: `numpy.fft` (present). No new deps.

### C. Edge-based

- **C1 Edge diff (Sobel/Canny)**: diff the edge maps rather than
  pixels. Robust against gamma/theme changes that fool raw pixel
  diff. Cheap.

### D. Feature-based (opencv)

- **D1 Shi-Tomasi corners + Lucas-Kanade sparse flow**: ~200 tracked
  points, (origin, displacement) pairs. ~10ms. Precise on feature-rich
  areas (text edges, icon corners).
- **D3 Template matching for fixed chrome**: identify title bar, tab
  strip, clock once; track their positions to detect window geometry
  changes. Domain-specific.

Dependencies: `opencv-python-headless` (already optional via `[webcam]`
extra).

### E. Semantic (heavy)

- **E1 OCR text diff**: tesseract on both frames, diff extracted
  text. Gold for coding sessions — captures exact keystroke deltas.
  Cost: 100-300ms/frame. Heavy dep.
- **E3 VLM diff captioning**: feed N-1 + N to SmolVLM, ask "what
  changed". 2x inference cost; natural-language description.

### F. OS-level — the big jump

The compositor and encoder already compute motion information. We
can harvest it rather than re-derive.

- **F1 Compositor damage regions (PipeWire, Wayland)**: Mutter already
  tracks dirty rectangles per frame (that's how it renders
  efficiently). The PipeWire stream we use for Wayland captures
  carries `SPA_META_VideoDamage` metadata per buffer — a list of
  rectangles marking "this changed".
  - Access: `gi.repository.Gst` with `appsink` + meta parsing, or
    `pipewire-python` bindings.
  - Result: authoritative change rectangles, zero pixel diff by us,
    zero false positives from gamma/theme shifts.
  - Platform: GNOME Wayland only. Fallback to A/B primitives elsewhere.
  - Effort: 3-5 days, one new dep.

- **F2 X11 XDamage**: same idea on X11 via `xcffib`. Not pursued because
  X11 is the legacy path.

- **F3 Window / focus events**: Mutter D-Bus (`org.gnome.Shell.Introspect`)
  or `xdotool getactivewindow` — "active window switched A → B at T=..."
  Semantic signal independent of pixels. Logged as separate events.

- **F4 Cursor position polling**: `xdotool getmouselocation` on X11,
  restricted on Wayland. Poll at 5-10Hz independent of frame captures.
  Free cursor trail.

- **F5 H.264 motion vectors from ffmpeg encoder**: when the Wayland
  recorder pipes through ffmpeg to webm, the encoder computes per-
  macroblock motion vectors as a compression byproduct. These vectors
  *are* the information we're trying to estimate.
  - Access: `ffmpeg -flags2 +export_mvs`, then read
    `AV_FRAME_DATA_MOTION_VECTORS` via PyAV's
    `frame.side_data[MotionVectors]`.
  - Result: per-macroblock `(dx, dy)`, ~8000 vectors per 1080p frame.
  - Cost: zero additional CPU (encoder does it anyway).
  - Caveat: vectors optimized for compression, not semantics —
    repeated-text blocks can produce spurious matches. Filter by
    spatial coherence of neighboring blocks.
  - Platform: Wayland path only (only place we go through ffmpeg).

- **F6 Kernel input events** (`/dev/input/event*`): keystroke/mouse
  ground truth. Hard privacy concern — opt-in only, disabled by
  default, documented clearly. Backlog.

### G. Hybrid / creative patterns

These are **consumption patterns** for the primitives above, not new
sources. They describe what to *do* with motion data once you have it.

- **G1 Three-tier frame classification**: `drop` / `motion_only` /
  `content_change`. Motion-only frames become event entries in a log;
  content-change frames still get captioned. **Requires a captioner**
  (v0.7+) to be fully realized.

- **G2 Motion-conditioned captioning**: feed motion hint into the
  captioner prompt: *"This image is the same scene as 3s ago but
  content scrolled up 40px. Describe what's now visible."* Requires
  captioner.

- **G3 Change-region crop + stitch**: for pixel-level queries, crop
  only the bbox of the change region rather than sending full frame
  to Claude Vision. 300×200 vs 1568×900 = 25x fewer tokens. Pure
  token win, no captioner needed.

- **G4 IPB-style keyframes + motion intermediates**: video-codec
  thinking applied to frame storage. Keyframe every N frames, motion
  deltas in between. Mainly a compression scheme; usefulness for
  subagent flow TBD.

- **G5 Event synthesis (post-processing)**: transform raw motion log
  into human-readable event strings: *"At 10:23, notification appeared
  top-right. At 10:24, it disappeared."* Pure geometric
  interpretation — no VLM. ~10 tokens per event line.

### H. Below the pixel (not recommended)

- GPU shader-based diff, `/dev/fb0` framebuffer access, eBPF on DRM/KMS
  events. All wrong-level-of-abstraction for a 0.5 fps capture loop.

---

## 3. Use cases unlocked by motion — ranked by leverage

### Tier 1 — high leverage, no captioner required

**3.1 Event log as Claude's primary input**

Transform raw motion data into pre-classified semantic events:

```json
{"t": 42.3, "event": "scroll", "vector": [0, -40], "duration_ms": 1800}
{"t": 44.7, "event": "region_appeared", "bbox": [800,50,300,100], "persistence_ms": 2400}
{"t": 47.1, "event": "region_disappeared", "bbox": [800,50,300,100]}
{"t": 50.0, "event": "scene_change", "magnitude": 0.8}
{"t": 52.2, "event": "typing", "region": [100,400,600,200], "keystroke_rate_hz": 6}
```

Claude reads this in place of (or alongside) actual frames.

- "what happened?" → narrative precise to the second
- "when did the notification appear?" → exact timestamp
- "how many scrolls?" → exact count
- "was there a context switch?" → enumerated scene_changes

**Token cost**: ~10 per event. 1h watch ≈ 300 events ≈ 3k tokens.
Compare: 500 captioned frames ≈ 10k tokens; 100 full frames ≈ 100k.

**3.2 Motion-driven smart frame selection**

The frame ranking becomes multi-signal:

```
significance_score = weighted_sum([
    motion_magnitude,           # how much moved
    new_region_score,           # something *appeared* (weight > moved)
    region_persistence,         # did it last >2s (not a flicker)
    scene_change_score,         # global context change
    region_uniqueness,          # never-seen-in-session
    cursor_vs_content_ratio,    # UI interaction vs content change
])
```

Example: over 500 kept frames in a 1h watch, maybe:

- 300 are incremental scrolls → low score
- 20 are toast appearances → high score
- 15 are window switches → very high
- 50 are cursor flickers → near-zero score
- 115 are genuine content changes → medium-high

The subagent surfaces to Claude: *"500 frames, top-30 by significance
with event description each"*. Claude picks consciously what to load.

**Expected win**: 3-5x fewer frames loaded for pixel-level queries
with no loss of accuracy.

**3.3 Event classification by motion shape (no ML)**

Geometric signatures → event tags:

| Motion pattern | Event tag |
|---|---|
| Uniform translation within a bbox | `scroll` |
| Uniform translation of entire bbox across screen | `window_drag` |
| Small pulsing region <200ms | `cursor_blink` (ignore) |
| Rectangle grows 0 → full → fades | `toast_notification` |
| Sudden full-screen change | `window_switch` / `modal` |
| Region change + keystroke-like cadence | `typing` |

~200 lines of numpy heuristics. Zero ML. Zero new deps.

### Tier 2 — medium leverage, no captioner

**3.4 Adaptive capture rate**: watch daemon adjusts fps based on motion.
High motion → boost to 2 fps; stasis → drop to 0.2 fps. Saves disk and
CPU on idle sessions, captures fast events when needed.

**3.5 Proactive triggers**: user declares *"notify me if a region
>200×100 appears top-right for >2s"*. Motion pipeline matches and wakes
Claude via desktop notification. Event-driven UX, not pull-based.

**3.6 Scene segmentation + session fingerprint**: post-process motion
log into scenes: `editor(10m), browser(5m), terminal(2m)`. Claude
reads the table of contents before drilling in. Retrospective queries
answer in 2k tokens instead of 20k.

**3.7 Motion-guided auto-crop for pixel queries**: user asks *"zoom
into the error"*. Subagent reads recent motion log, finds most recent
`region_appeared`, crops that bbox, sends just the crop to Claude
Vision. 25x fewer tokens, more precise because centered on the change.

### Tier 3 — nice-to-have, no captioner

**3.8 Attention overlay for remote vision**: when a full frame must
go to Claude Vision, render thin red boxes around detected change
regions before sending. Claude literally *sees* where to look.

**3.9 Virtual frame reconstruction**: IPB-style — send Claude a
keyframe plus motion deltas for intermediates, let a local
reconstruction step produce approximate frames that are more
compressible than raw JPEG/PNG.

### Tier 4 — requires captioner (v0.7+)

**3.10 Three-tier classification with captioning**: motion-only
frames are event log entries, content-change frames go through
SmolVLM. Full pattern from G1.

**3.11 Motion-conditioned captioning**: motion hint in the SmolVLM
prompt for better caption density.

---

## 4. Dependency separation

| Capability | Requires captioner? | Requires opencv? | Requires Wayland? |
|---|---|---|---|
| Event log (3.1) | no | no | no |
| Smart selection (3.2) | no | no | no |
| Shape classification (3.3) | no | no | no |
| Adaptive fps (3.4) | no | no | no |
| Triggers (3.5) | no | no | no |
| Scene segmentation (3.6) | no | no | no |
| Auto-crop (3.7) | no | no | no |
| Attention overlay (3.8) | no | no | no |
| Virtual reconstruction (3.9) | no | no | no |
| Three-tier with caption (3.10) | **yes** | no | no |
| Motion-conditioned caption (3.11) | **yes** | no | no |
| Sparse optical flow (D1) | no | yes | no |
| PipeWire damage (F1) | no | no | **yes (GNOME)** |
| H.264 MVs (F5) | no | no | **yes** |
| OCR diff (E1) | no | + tesseract | no |

The entire **Tier 1-3** range is v0.6-compatible.

---

## 5. Implementation phases

Phases are independent and shippable. Each is gated on whether the
prior phase's data proves useful in practice.

### Phase α — motion primitive + event log (~3-4 days)

Add a new module `claude_vision/motion.py` (or extend `ranking.py`).

```python
@dataclass(frozen=True)
class MotionReport:
    tile_diffs: tuple[tuple[float, ...], ...]  # MxN grid of MAD
    global_shift: tuple[int, int]               # phase-correlated (dx,dy)
    peak_tile: tuple[int, int] | None
    peak_intensity: float
    change_regions: tuple[BBox, ...]            # connected components

def compute_motion(a: Image.Image, b: Image.Image,
                   *, grid: tuple[int, int] = (6, 4)) -> MotionReport: ...
```

Implementation sketch:
- Tiled MAD via numpy `reshape`+`mean` (A2).
- Phase correlation via `numpy.fft.fft2` + cross-spectrum peak (B1).
- Connected components via boolean mask + flood fill or `scipy.ndimage`
  (A3). Optional dep; fallback to peak-tile if scipy absent.

Integrate in the watch daemon: after `should_keep`, compute
`MotionReport`; emit to an append-only `motion.jsonl` alongside frames.

**CLI**: `watch-motion --session <id>` emits the event log as JSON.

**Tests**: synthetic frame pairs (scroll, static, notification-appear)
with expected output.

**Ship win**: zero until β consumes it, but data is live and
reviewable.

### Phase β — event classification + smart frame selection (~2-3 days)

On top of α:

- Geometric event classifier (3.3) — takes sequence of `MotionReport`
  and emits `event` lines (scroll, scene_change, region_appeared, ...).
- `ranking.rank_by_significance` extended: accept optional per-frame
  `MotionReport`, combine into multi-signal score.
- Subagent playbook update (`agents/frame-analyst.md`): read motion
  log first for "what happened" queries; select frames by score for
  pixel-level.
- `watch-query` returns frames ordered by significance, not just time.

**Ship win**: token savings on narrative queries (event log instead
of frames), 3-5x fewer frames loaded for pixel queries.

### Phase γ — OS-level upgrade (~3-5 days, platform-conditional)

Two independent upgrades, each adding a richer motion source that
supersedes the α primitives where available:

- **γ-a: PipeWire damage** (GNOME Wayland). New recorder variant
  subscribes to PipeWire directly and reads `SPA_META_VideoDamage`.
- **γ-b: H.264 motion vectors** (Wayland ffmpeg path). Enable
  `+export_mvs`, decode side_data via PyAV.

Both feed into the same `MotionReport` consumer. `MotionReport` becomes
a union of sources: Python math on platforms without γ, native
metadata on platforms with.

**Ship win**: zero CPU for motion computation on GNOME Wayland; no
false positives from theme/gamma; perfect change rectangles.

### Phase δ — captioner integration (~2-3 days, requires v0.7)

Only after v0.7 captioning ships:

- Three-tier classification (G1) applied to kept frames.
- Motion-conditioned captioning prompt (G2).
- `caption_store` schema extended with optional `motion` field.

**Ship win**: ~40% reduction in caption log tokens for scroll-heavy
sessions.

### Phase ε — semantic layer (opt-in, gradual)

- OCR diff in change regions (E1) — tesseract only on change bbox,
  not full frame.
- Window / focus event logging (F3).
- Cursor trail (F4).
- Event synthesis post-processor (G5) → human-readable narratives.

Each of these is a standalone module gated behind its own flag.

---

## 6. Risks and gotchas

1. **Multi-monitor stitching**: phase correlation lies at monitor
   boundaries when frames are virtual-screen unions. Compute per-
   monitor.
2. **DPI / fractional scaling**: pixel coordinates ambiguous. Normalize
   motion reports to logical coordinates (0..1 frame-relative).
3. **Video playback in a window**: continuous motion, phase correlation
   outputs noise. Detect "uniform-random motion pattern" → tag as
   video, don't try to collapse.
4. **Cursor blink / animated spinners**: pixel changes but nothing
   *translates*. A4 temporal tracking distinguishes flicker from
   sustained motion.
5. **Theme / gamma shifts**: MAD spikes but no real motion. Prefer
   edge-diff (C1) or normalize by global mean.
6. **Test flakiness**: CI tests must use synthetic frames (not real
   screenshots) for reproducibility. Fixture pairs with known motion.
7. **H.264 MV semantics**: encoder MVs optimize compression, not
   perception. Repeated text gives spurious matches. Filter by
   spatial coherence of neighboring blocks.
8. **PipeWire permission**: already granted for screencast via
   `xdg-desktop-portal`; no privilege escalation, but test on GNOME
   47+ where portal is stricter.
9. **Backward compatibility**: motion log must be optional —
   `motion.jsonl` absent → pipeline silently skips motion features.
10. **Subagent prompt bloat**: event log + motion schema documentation
    in `frame-analyst.md` adds tokens to every invocation. Measure.

---

## 7. Token economics (rough model)

Scenario: 1h watch session at 0.5 fps, tipical coding work.

Baseline numbers (from v0.6 behavior):
- 1800 frames captured
- ~500 kept after dedupe (~70% dropped)
- ~30 full frames loaded by subagent for a narrative query

| State | Token cost of narrative query |
|---|---|
| v0.6 today | 30 frames × 1k tok = 30k tok |
| v0.7 caption log | 500 × 20 tok = 10k tok log + 0 frames = 10k tok |
| Motion α+β event log only | 300 events × 10 tok = 3k tok |
| Motion β smart selection + v0.7 | ~8 selected frames × 1k + 10k caption = 18k tok |
| Motion δ (three-tier + captioning) | 150 caption + 300 events = 6k tok log |

The event log (3.1) is the cheapest narrative query path. The smart
selection (3.2) is the cheapest pixel-accurate query path.

Caveat: these are back-of-envelope. Real numbers depend on session
content (scroll-heavy vs stable-heavy vs animation-heavy). Measure
before committing.

---

## 8. Open questions for the next decision

1. **Do α + β ship before, after, or in parallel with v0.7?**
   They're independent. Parallel is fastest; sequential is safer.

2. **Which primitives to ship in α?** Minimum viable is tiled MAD
   (A2) + phase correlation (B1). Rich version adds connected
   components (A3) + temporal tracking (A4). The latter doubles the
   useful event types but adds engineering.

3. **scipy as dependency?** A3+A4 benefit from `scipy.ndimage`. Can
   be handrolled in numpy but less robust. Call.

4. **γ priority**: PipeWire damage (γ-a) is more elegant but GNOME-
   only. H.264 MVs (γ-b) covers Wayland broadly but has semantic
   edge cases. Do we pick one, both, neither?

5. **Trigger DSL (3.5)**: hand-crafted JSON spec or embedded Python?
   Security concern if Python — user runs arbitrary code in our
   context.

6. **Privacy posture on F6 (input events)**: off-the-table entirely,
   or backlog with opt-in flag?

7. **Storage**: motion log as separate `motion.jsonl` file, or merged
   with `captions.jsonl` (on captioning-enabled sessions) as a
   unified event stream?

8. **Where does this live in the repo if implemented?** New top-level
   module, or extend `ranking.py`? Affects import structure and test
   organization.

---

## 9. Glossary

- **MAD (mean absolute diff)**: average of |pixel_a - pixel_b| over
  a region, normalized to [0,1]. Cheap similarity measure.
- **Phase correlation**: FFT-based technique that finds the (dx, dy)
  translation best aligning two images. Robust to lighting, precise
  to the pixel.
- **Connected components**: grouping of spatially adjacent True pixels
  in a binary mask into discrete regions with bounding boxes.
- **Compositor**: the OS process that combines all application
  surfaces into the final screen image (Mutter on GNOME, KWin on KDE).
- **Damage region**: rectangle marking a changed area; fundamental
  to efficient compositor rendering. Propagated through PipeWire as
  buffer metadata.
- **Macroblock**: 16×16 pixel unit of H.264 encoding. Each carries a
  motion vector pointing into the reference frame.
- **Keyframe (I-frame)**: self-contained frame in video encoding, no
  reference to others. In our repurposed sense: a full frame + caption
  that anchors a span of motion-only deltas.
- **Three-tier**: classification of kept frames into `drop` /
  `motion_only` / `content_change`. Middle tier is the novel one.

---

## 10. Pointers into existing code to reuse

- `claude_vision/ranking.py` — `compute_signature`, `compare_signatures`,
  `rank_by_significance`. Baseline primitives for MAD-style diffs.
  Motion primitives extend this module or sit alongside it.
- `claude_vision/dedupe.py` — `FrameDeduper`, `build_from_config`.
  The keep/drop decision. Motion would refine, not replace.
- `claude_vision/thumbs.py` — second-pass ranking for thumbnails.
  Good integration point for motion-informed scoring.
- `claude_vision/watch.py` — daemon loop. The only place that sees
  every frame. Motion computation and event log appending hook here.
- `claude_vision/recorders/gnome_wayland.py` — ffmpeg pipeline and
  PipeWire consumer. The place to add `+export_mvs` (phase γ-b) and
  `SPA_META_VideoDamage` parsing (phase γ-a).
- `claude_vision/recorders/mss_recorder.py` — the mss-based path for
  X11/macOS/Windows. Falls back to α primitives (no OS-level signals).
- `plugins/base/agents/frame-analyst.md` — subagent playbook.
  New section needed: how to consume motion events and significance
  scores.
