# Fusion Model Picker (user chooses the panel + judge)

Date: 2026-07-15
Status: Approved direction (Ralph). Extends the shipped Fusion chat page
(`docs/superpowers/specs/2026-07-15-fusion-chat-page-design.md`).

## Goal

Let the user choose which models answer and which model synthesizes, instead of
only the fixed Quality/Budget presets. The user adds/removes models (a panel),
picks a judge ("Fuse with"), sends a prompt; every chosen model answers, the
judge combines them into one whole answer. Mirrors OpenRouter's Model Fusion,
constrained to the models our system actually has (OpenAI + Anthropic; no
Gemini).

## Decisions (locked with Ralph)

- **Presets + editable Custom.** Tabs: Quality | Budget | Custom. Clicking
  Quality/Budget refills the chips + judge from that preset. Editing any chip or
  the judge flips the active tab to Custom.
- **User picks the judge.** A "Fuse with" dropdown lists all registry models.
- **Server-driven HTMX picker** (consistent with the v1 page): the selection
  lives in the user's in-memory session and is edited through small HTMX
  fragments, not a client-side JS state machine. It persists across reloads and
  is the exact state the stream reads.

## Constraints

- Only the 10 registry models are selectable (the "models available to our
  system" gate): `gpt-5`, `gpt-5.5`, `o3`, `gpt-4o`, `gpt-4.1`,
  `claude-opus-4-8`, `claude-opus-4-5`, `claude-sonnet-5`, `claude-fable-5`,
  `claude-haiku-4-5-20251001`.
- Panel is **1 to 4 models** (the engine hard-caps the panel at 4). The UI
  cannot add a 5th and cannot remove the last remaining chip. All limits are
  re-validated server-side.
- Judge must be a registry model.
- No em-dashes/en-dashes anywhere; no AI attribution in commits; `.env` and
  `templates.py` untouched; reuse the existing session/auth/gateway wiring
  (no gateway or Caddy change - everything stays under `/tasks/`).

## Architecture / data flow

```
GET /tasks/fusion            -> fusion.html; a #picker div hx-get="/tasks/fusion/picker" on load
   | user clicks Quality/Budget/Custom tab, adds/removes model chips, sets judge
   v
POST /tasks/fusion/preset|panel/add|panel/remove|judge  (current_user)
   -> mutate session.panel / session.judge / session.preset_label
   -> return the re-rendered #picker fragment (hx-swap outerHTML)
   | user types a prompt, submits the composer
   v
POST /tasks/fusion/send      (current_user; message only)
   -> append user msg; return user bubble + assistant bubble wired to the stream
   v
GET /tasks/fusion/stream     (current_user, SSE)
   -> fuse(snapshot(messages), session.panel, session.judge)  [in-process]
   -> fan out to every chosen model -> judge synthesizes -> stream tokens
   v
one combined answer streams in; New chat clears the thread but KEEPS the models
```

## Components

### Engine: `mcp-servers/tasks/fusion_engine.py`
- Add a human `label` to `ModelSpec` (e.g. `gpt-5.5` -> "GPT-5.5",
  `claude-opus-4-8` -> "Claude Opus 4.8") and set it on all 10 registry
  entries.
- Add `available_models() -> list[dict]` returning
  `[{"id","label","provider"}, ...]` in a stable, human-friendly order
  (Anthropic then OpenAI, or registry order), for rendering the dropdowns.
- Change `fuse(messages, preset)` -> `fuse(messages, panel, judge, *, client=None)`
  taking an explicit panel list and judge id (the route resolves preset OR
  custom into panel+judge before calling). `resolve_preset` stays for the
  preset path. Update the three engine tests that call `fuse(msgs, "budget")`.
- Everything else (fan_out, build_judge_messages, _stream_judge, graceful
  degradation, PANEL_MAX_TOKENS) is unchanged.

### Backend: `mcp-servers/tasks/routes_fusion_page.py`
- `FusionSession` replaces `preset: str` with:
  - `panel: list[str]` (1..4 model ids)
  - `judge: str` (model id)
  - `preset_label: str` ("quality" | "budget" | "custom")
  A new session defaults to the Quality preset (panel + judge from
  `resolve_preset("quality")`, label "quality").
- Picker endpoints (all `current_user`, all return the re-rendered `#picker`
  fragment):
  - `GET  /tasks/fusion/picker` - current fragment from the session.
  - `POST /tasks/fusion/preset` (form `name`) - if `name` in `PRESETS`, set
    panel+judge from the preset and `preset_label=name`; else 400.
  - `POST /tasks/fusion/panel/add` (form `model`) - if `model` is a registry
    model, not already in panel, and `len(panel) < 4`: append; set
    `preset_label="custom"`. No-op otherwise. (400 on unknown model.)
  - `POST /tasks/fusion/panel/remove` (form `model`) - if `model` in panel and
    `len(panel) > 1`: remove; set `preset_label="custom"`. Never removes the
    last chip.
  - `POST /tasks/fusion/judge` (form `model`) - if `model` is a registry model:
    set judge; set `preset_label="custom"`. (400 on unknown model.) If the
    chosen panel+judge happens to equal a preset again, the label stays
    "custom" (simplest; no reverse-matching).
- `POST /tasks/fusion/send` drops the `preset` form field; it only takes
  `message` and uses the session's panel/judge. It 400s if `panel` is somehow
  empty (defense in depth; the picker guarantees >= 1).
- `GET /tasks/fusion/stream` calls `fuse(snapshot, s.panel, s.judge)` (the
  turn-claim, generation guard, and empty-turn snapshot filter from v1 are
  unchanged).
- `POST /tasks/fusion/new` clears messages + streaming + bumps generation but
  KEEPS panel/judge/preset_label (New chat should not reset the user's models).
- HTML-fragment builders (Python) for the picker: `_render_picker(session)`
  producing the tabs, the chips (each with a remove button unless it is the
  only chip), the "+ Add model" control (a `<select>` of registry models not
  already chosen, `hx-post` on change to `/tasks/fusion/panel/add`), and the
  "Fuse with" judge `<select>` (all registry models, `hx-post` to
  `/tasks/fusion/judge`). Every model label is HTML-escaped.

### Frontend: `mcp-servers/tasks/static/fusion.html`
- Replace the old Quality/Budget segmented toggle + hidden `preset` field with
  a `<div id="picker" hx-get="/tasks/fusion/picker" hx-trigger="load"></div>`
  above the composer. Picker mutations target `#picker` and swap `outerHTML`.
- The composer form no longer submits `preset`, only `message`.
- The existing inline JS (Bearer header via `htmx:configRequest`, Enter-to-send,
  autoscroll, Send disable/enable on stream close) is unchanged. Picker
  interactivity is pure HTMX (`hx-post` on the tabs, chip remove buttons, and
  the two `<select>`s with `hx-trigger="change"`), so no new JS state machine.

## Error handling

- Unknown model / unknown preset in any picker POST -> 400 (the UI never
  produces these; it is a guard).
- Removing the last panel chip or adding a 5th model -> the endpoint no-ops and
  returns the unchanged fragment (the buttons are also absent/disabled in the
  render, so this is belt-and-suspenders).
- Empty panel at send time -> 400 with an inline "pick at least one model" note
  (unreachable via the UI).
- Engine failures (panel-model drop, all-fail, judge-fail) degrade exactly as
  today; the stream relays whatever `fuse` yields.

## Testing (pytest, no real LLM calls)

- `available_models()` returns all 10 with labels; every registry entry has a
  non-empty label.
- `fuse` new signature: fan-out over the given panel and stream the given
  judge (monkeypatched fan_out/_stream_judge), updated from the old
  preset-based tests.
- Picker endpoints: preset refills panel+judge and sets the label; add appends
  and caps at 4 (5th is a no-op); add of a dup is a no-op; remove drops a chip
  but refuses the last one; judge sets and flips label to custom; unknown
  model/preset -> 400; each returns a fragment containing the expected chips and
  the selected judge.
- Session defaults: a fresh session starts on the Quality preset.
- `send` uses the session panel/judge and no longer requires a preset field;
  400 on empty panel. `new` keeps the model selection. `stream` calls `fuse`
  with the session panel/judge (assert via a fake fuse capturing its args).
- The v1 reconnect-safety and escaping tests stay green.

## Out of scope (future follow-ups)

- Per-model reasoning-effort / temperature controls (the OpenRouter popover).
- Saved/named fusion configurations.
- Other providers (Gemini, etc.) until they are wired into the registry.
- Reverse-matching a hand-picked selection back onto a preset label.
