---
name: screen-vision
description: Use when Claude needs to visually see the user's screen - debugging UI bugs, verifying rendered web pages or dev servers, checking what an app looks like, diagnosing visual layout issues, confirming a screenshot matches expectations, inspecting a running application, or any task where "look at my screen", "see what I see", "check how this renders", "what does it look like now", "guarda lo schermo", "cosa vedi" is implied. Dispatches the frame-analyst subagent, which captures the screen, analyzes the frames, and returns a compact textual report — the main-agent context stays clean.
allowed-tools: Task
---

# screen-vision

You need to look at the user's screen. **Delegate the entire visual pipeline to
the `frame-analyst` subagent** — do not call the CLI yourself. This keeps the
main conversation context free of frame paths and tool JSON.

## Step 1 — Form the visual question

Write one concrete, answerable question. Examples:

- "Is the navbar horizontally centered on the page?"
- "How many buttons are visible in the toolbar, and are any disabled?"
- "Does the modal overlay cover the full viewport?"

## Step 2 — Pick the mode and parameter hints

**Prefer `screenshot` over `video` whenever possible.** A single frame is
faster, cheaper, and just as informative for static questions.

| Situation                                           | Mode       | Hints                 |
|-----------------------------------------------------|------------|-----------------------|
| "What's on my screen?" / static content / layout    | screenshot | —                     |
| "How does this page look?" / dialog / error message | screenshot | —                     |
| Small text / pixel-level inspection                 | screenshot | `resolution: full`    |
| User will click or interact                         | video      | `duration: 10s, fps: 2` |
| Animation, transition, loading flow                 | video      | `duration: 5-10s, fps: 3` |
| Long workflow                                       | video      | `duration: 20-30s`    |

If you cannot sensibly choose duration/fps for video mode, ask the user
**one** short question.

## Step 3 — Dispatch the subagent

Call the `Task` tool with `subagent_type=frame-analyst` and a prompt of the form:

```
Visual question: <your question>

Mode: screenshot | video
Hints (optional):
- duration: <seconds>       (video only)
- fps: <frames per second>  (video only)
- resolution: full | high | medium | low
- monitor: <index if not the primary>
```

If you leave `Mode` out the subagent will default to `screenshot` unless the
question clearly requires temporal information.

## Step 4 — Relay the result

The subagent returns a compact text report. Summarize it for the user in 2–4
lines. Do not re-quote frame paths or JSON.

## Notes

- The subagent handles capture, analysis, and cleanup on its own.
- If the subagent reports "Wayland non-GNOME" or "install extra [wayland]",
  relay the actionable hint to the user and stop.
