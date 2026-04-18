---
name: screen-vision
description: Use when Claude needs visual information - either from the user's SCREEN (UI debugging, verifying rendered web pages or dev servers, checking app rendering, layout issues, "what's on my screen?", "guarda la pagina", "cosa vedi sullo schermo?") OR a SPECIFIC REGION of the screen via interactive rectangle selection ("guarda il bottone login", "check the settings menu") OR from the LAPTOP WEBCAM (seeing the user, physical objects held up to the camera, the room: "puoi vedermi?", "cosa ho in mano?") OR continuously WATCH the screen in the background while the user works ("guarda cosa faccio", "tienimi d'occhio", "watch what I do") with live query support during the watch ("cosa ho appena fatto?") and an explicit summary on request ("riepilogami cosa è successo"). Dispatches the frame-analyst subagent, which picks source, region, mode (snapshot vs video vs background watch), captures or reads from the ongoing watch, analyzes, and returns a compact textual report — the main-agent context stays clean.
allowed-tools: Task
---

# screen-vision

You need visual information about the user's screen or their physical
surroundings (webcam). **Delegate the entire pipeline to the `frame-analyst`
subagent** — do not call the CLI yourself. This keeps the main conversation
context free of frame paths and tool JSON.

## Step 1 — Form the visual question

Write one concrete, answerable question. Examples:

- Screen: "Is the navbar horizontally centered on the page?"
- Screen: "How many buttons are visible in the toolbar?"
- Webcam: "What am I holding up to the camera?"
- Webcam: "Is the person smiling?"

## Step 2 — Pick source, mode, and parameter hints

First choose the **source**:

| Question is about…                                   | Source  |
|------------------------------------------------------|---------|
| Digital content: UI, pages, apps, terminal, code     | screen  |
| The user themselves, their face, an object, the room | webcam  |

Then the **region** (screen only — skip for webcam). **Strong preference
for `interactive` whenever the user is asking about a specific thing**:

| Situation                                           | Region      |
|-----------------------------------------------------|-------------|
| "Cosa c'è scritto come titolo del terminale?"       | interactive |
| "Guarda il bottone login"                           | interactive |
| "Che errore mostra questa finestra?"                | interactive |
| "Cosa dice il popup?" / "il valore di quel campo"   | interactive |
| "La tab attiva del browser"                         | interactive |
| "Cosa c'è sullo schermo?" / panoramica              | full        |
| "Descrivi tutto ciò che vedi"                       | full        |
| "Controlla tutta la pagina"                         | full        |

When in doubt between `full` and `interactive`, pick `interactive`:
full captures cost ~10× more tokens for zero added signal on focused
questions.

Finally the **mode** (prefer snapshot/single-frame whenever possible — faster
and cheaper than a video):

| Situation                                           | Mode       | Hints                 |
|-----------------------------------------------------|------------|-----------------------|
| "What's on my screen?" / static content / layout    | snapshot   | —                     |
| "How does this page look?" / dialog / error message | snapshot   | —                     |
| Small text / pixel-level inspection                 | snapshot   | `resolution: full`    |
| "Puoi vedermi?" / "Cosa ho in mano?"                | snapshot   | —                     |
| User will click or interact (screen)                | video      | `duration: 10s, fps: 2` |
| Animation, transition, loading flow                 | video      | `duration: 5-10s, fps: 3` |
| "Registra mentre saluto" / webcam motion            | video      | `duration: 3-5s, fps: 2-3` |
| Long workflow                                       | video      | `duration: 20-30s`    |

If you pick `region: interactive`, tell the user in your turn-reply that a
picker will appear and to drag a rectangle around the area of interest.

If you cannot sensibly choose duration/fps for video mode, ask the user
**one** short question.

## Step 3 — Dispatch the subagent

Call the `Task` tool with `subagent_type=frame-analyst` and a prompt of the form:

```
Visual question: <your question>

Source: screen | webcam
Mode:   snapshot | video
Region: full | interactive | X,Y,W,H        (screen only)
Hints (optional):
- duration: <seconds>       (video only)
- fps: <frames per second>  (video only)
- resolution: full | high | medium | low
- monitor: <screen index, default 0>
- device: <webcam index, default 0>
```

If you leave `Source` / `Mode` out, the subagent infers from the question and
defaults to `snapshot`.

## Step 4 — Relay the result

The subagent returns a compact text report. Summarize it for the user in 2–4
lines. Do not re-quote frame paths or JSON.

## Watch mode (continuous background vision)

When the user asks you to **watch** the screen open-endedly ("guarda cosa
faccio", "tienimi d'occhio mentre provo questa cosa", "watch me for a few
minutes"), the flow is:

1. Dispatch `frame-analyst` with `Mode: watch-start` and the usual hints
   (fps, region, scale). The subagent starts a background daemon and
   returns.
2. Acknowledge briefly: "Sto guardando. Chiedimi quello che ti serve."
3. Any visual question the user asks while the watch is running → dispatch
   `frame-analyst` normally. The subagent detects the active watch and
   reads from the live session rather than capturing fresh.
4. When the user says "basta" / "stop" / "puoi fermarti" → dispatch
   `frame-analyst` with `Mode: watch-stop`. **Do NOT automatically
   summarize.** The subagent just closes the session.
5. Only if the user then explicitly asks for a summary ("riepiloga",
   "cosa è successo in totale") → dispatch `frame-analyst` with
   `Mode: watch-summary` to produce the recap.

Default watch fps is `0.5` (one frame every 2 seconds) with dedupe on.
Adjust via hints if the user is doing something fast-paced.

## Notes

- The subagent handles capture, analysis, and cleanup on its own.
- If the subagent reports "Wayland non-GNOME" or "install extra [wayland]",
  relay the actionable hint to the user and stop.
- A forgotten watch will auto-clean itself after the next Claude turn if
  older than 2 hours (the existing `Stop` hook GC), but it's good hygiene
  to tell the user when a watch is still active.
