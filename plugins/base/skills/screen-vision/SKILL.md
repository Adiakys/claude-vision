---
name: screen-vision
description: Activate whenever Claude needs VISUAL INFORMATION to make progress — in ANY language. Trigger on INTENT, not keywords. Use this skill when (a) the user asks anything that requires inspecting the screen, a screen region, the webcam, or their physical environment, OR (b) Claude itself realizes mid-task that it cannot solve the problem without actually seeing what is happening (e.g., debugging a CSS animation, verifying a rendered UI, diagnosing why an element looks wrong, confirming the user's physical context). In case (b), proactively propose the skill to the user rather than guessing. Italian and English are first-class — examples EN: "what's on my screen?", "this button looks off", "can you see me?", "watch what I do"; examples IT: "cosa c'è sullo schermo?", "guarda la pagina", "puoi vedermi?", "tienimi d'occhio". For any other language, activate on the semantically equivalent intent regardless of exact phrasing. The skill dispatches the frame-analyst subagent which picks source (screen / screen region / webcam), mode (single snapshot / short video / continuous background watch with live queries), captures or reads from the ongoing watch, analyzes the frames, and returns a compact textual report — the main-agent context stays clean.
allowed-tools: Task
---

# screen-vision

You need visual information about the user's screen or their physical
surroundings (webcam). **Delegate the entire pipeline to the `frame-analyst`
subagent** — do not call the CLI yourself. This keeps the main conversation
context free of frame paths and tool JSON.

### When to activate (intent, not keywords)

- **Reactive**: the user asks anything that can only be answered by seeing
  (regardless of the language they're writing in).
- **Proactive**: you're in the middle of solving a problem and realize the
  next useful step requires seeing the rendered behavior — e.g. a CSS
  animation that "doesn't start", a dialog that "looks wrong", a piece of
  UI the user is describing but that you can't verify from the code alone.
  In that case, briefly propose the capture ("per vedere come si comporta
  l'animazione apro una breve registrazione, ok?") and dispatch the
  subagent rather than guessing from code.

Italian and English intents must be recognized perfectly; for any other
language, rely on semantic equivalence.

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
