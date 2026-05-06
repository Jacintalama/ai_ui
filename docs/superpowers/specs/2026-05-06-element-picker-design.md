# Element Picker — Design Spec

**Date:** 2026-05-06
**Status:** Draft for review
**Owner:** alamajacintg04@gmail.com
**Scope:** v1, chat mode only

## Problem

Users describing UI changes in chat have to type out which element they're talking about ("the second card under the Skills heading"). This is slow, error-prone, and hard to do well — the operator's stated pain in the meeting was: *"When you interact with the website project—like inspecting the page—and then paste/share it in the chat. It's a bit hard to explain."*

This spec adds a "Select" mode to the preview pane: click an element in the preview iframe and it becomes a chip in the chat input, scoping the next AI prompt to that element.

## Goals (v1)

- Click an element in the preview iframe → it becomes a chip in the chat input.
- The next chat send carries the chip as scoping context (selector + outerHTML + key computed styles).
- Works for the same-origin live preview today; the architecture extends cleanly to cross-origin published URLs later.
- Three primary use cases supported by the same payload: restyle ("make this blue"), rewrite ("change this headline"), explain ("why is this overlapping?").

## Non-goals (v1)

- Build-mode integration (chip in build prompt) — deferred. Payload shape is generic and reusable.
- Multi-element selection — single-slot chip only.
- Direct property editors (color picker, padding sliders) — chat-only flow for v1.
- Pick-from-layers UI panel — replaced by a single Alt-hover affordance for v1.
- Cross-origin published-URL inspection — out of scope; postMessage protocol does not change when we add it.
- Screenshot crops in the payload — token-heavy; outerHTML + computed styles cover the use cases.
- Persistence across sessions — chip lives in memory only.

## Architecture

Three actors. One new message channel.

```
┌────────────────────────────┐         ┌────────────────────────────┐
│  Parent UI (preview.html)  │         │  Server (FastAPI tasks)    │
│                            │  HTTP   │                            │
│  • "Select" toggle button  │ ◄──────►│  • GET /tasks/preview-app/ │
│  • Renders selection chip  │         │      <slug>/index.html     │
│  • Owns chat input         │         │      injects picker.js     │
│  • Sends /chat w/selection │         │      when ?picker=1        │
└──────────────┬─────────────┘         │  • POST /chat              │
               │                       │      accepts new           │
               │  postMessage          │      `selection` field     │
               ▼                       └────────────▲───────────────┘
┌────────────────────────────┐                      │
│  Preview iframe            │                      │
│  /tasks/preview-app/<slug>/│ ─────────────────────┘
│   ?picker=1                │   HTTP (initial load)
│                            │
│  • picker.js (server-      │
│    injected)               │
│  • Hover overlay           │
│  • Click → posts payload   │
│    to parent               │
└────────────────────────────┘
```

**Mental model:** parent owns chat UI and the network; iframe owns DOM observation; server's only new responsibility is splicing one `<script>` tag into served HTML when `?picker=1` is present. Picker is **stateless and ephemeral** — only runs when the user toggles picker mode on; one message per click; deactivates itself on selection.

## Components

### 1. Picker script (iframe-side)

**File:** `mcp-servers/tasks/static/picker.js`
**Size budget:** ~150 lines + inlined `@medv/finder` (~1.5KB minified).
**State:** `inert` (default) → `listening` → `inert`. Set by parent via postMessage.

**Lifecycle messages**

| Direction | Message | When |
|---|---|---|
| iframe → parent | `{type: "io.picker.ready"}` | Once on script load |
| parent → iframe | `{type: "io.picker.activate"}` | User toggles Select on |
| parent → iframe | `{type: "io.picker.deactivate"}` | User toggles Select off / ESC / tab switch |
| iframe → parent | `{type: "io.picker.selected", ...payload}` | User clicks an element |
| iframe → parent | `{type: "io.picker.cancelled"}` | ESC during picking |

**Listening-mode behavior**

- Adds `<div id="__io_picker_overlay">` to `<body>`. CSS: `position: fixed; pointer-events: none; outline: 2px solid #4f8df0; border-radius: 4px; z-index: 2147483647;`. The `pointer-events: none` is non-negotiable — without it the overlay eats every event.
- Adds `<div id="__io_picker_label">` in the same z-index space — small floating tag showing the selector that *would* be picked.
- Sets `body { cursor: crosshair !important }` while active.
- On `mousemove`: walks `document.elementFromPoint(e.x, e.y)`, skips its own overlay/label nodes, calls `getBoundingClientRect()`, repositions outline + label.
- On `click` (capture phase, `preventDefault` + `stopImmediatePropagation`): freezes the highlight, builds the payload, posts `io.picker.selected`, deactivates.
- On `Escape` keydown: posts `io.picker.cancelled` and deactivates.

**Suppression rules** (capture-phase, while listening)

- `click`, `mousedown`, `mouseup`, `submit` listeners with `preventDefault()` + `stopImmediatePropagation()`. Without these, picking a `<button>` triggers Alpine handlers in addition to the picker, and picking a submit button in a form would fire the form.
- `keydown` is **not blanket-suppressed** — only the `Escape` key is intercepted (to deactivate the picker). All other keys fall through normally. This matters because users may have global shortcuts in the preview app (e.g. `/` to focus search) and we don't want picker mode to silently break them.
- Picker ignores `<html>` and `<body>` as targets — outline disappears, no chip if user clicks them.

**Alt-hover parent affordance** (v1 substitute for "Pick from layers")

While listening, holding `Alt` while hovering walks one level UP the DOM tree from the element under the cursor. So if the user keeps hitting the leaf `<span>` inside a card, holding Alt and hovering jumps the outline to the parent card. Single keybinding, single line of state, no UI panel.

**Selector generation**

Uses [`@medv/finder`](https://github.com/antonmedv/finder) inlined into picker.js, with these settings:
```js
finder(el, {
  className: (n) => !/^(active|hover|focus)/.test(n),
  idName: () => true,
  seedMinLength: 1,
  optimizedMinLength: 2,
})
```
Biases toward stable selectors (IDs, semantic class names) and away from state-dependent class soup like `.is-active.was-hovered`.

**Payload shape** (posted on `io.picker.selected`)

```json
{
  "type": "io.picker.selected",
  "selector": "main > section.skills > article:nth-of-type(2)",
  "tag": "ARTICLE",
  "attrs": { "id": "", "class": "skill-card" },
  "outerHtml": "<article class=\"skill-card\">...</article>",
  "styles": {
    "color": "rgb(34, 34, 34)",
    "backgroundColor": "rgb(255, 255, 255)",
    "padding": "16px",
    "margin": "0px 0px 12px 0px",
    "fontSize": "14px",
    "fontFamily": "Inter, sans-serif",
    "display": "block",
    "borderRadius": "8px",
    "width": "300px",
    "height": "180px"
  },
  "rect": { "x": 120, "y": 240, "w": 300, "h": 180 },
  "url": "https://.../tasks/preview-app/portfolio-x/",
  "pickedAt": 1715000000000
}
```

`outerHtml` is truncated to 2KB at the source. Computed styles are a fixed allowlist of 10 properties — anything beyond is omitted.

### 2. Server-side HTML rewriting

**File:** `mcp-servers/tasks/routes_tasks.py` (the `preview-app` route)
**Code budget:** ~25 lines.

When the route serves `index.html` (or any HTML response) AND the request URL has `picker=1`:

1. Decode the response body as UTF-8.
2. Find `</head>` (case-insensitive).
3. If found: insert `<script src="/static/picker.js?v={PICKER_JS_VERSION}"></script>` immediately before it.
4. If not found: log a WARNING (`picker injection skipped: no </head> in <slug>/index.html`) and serve the original body untouched.
5. Wrap the whole rewrite in `try/except` — any failure → log + serve original.

`PICKER_JS_VERSION` is a module-level constant (e.g. `PICKER_JS_VERSION = "1"`), bumped manually when picker.js changes. Cache-busts cleanly across deploys.

### 3. Parent-side wiring (preview.html)

**File:** `mcp-servers/tasks/static/preview.html`
**Code budget:** ~120 lines JS + ~40 lines CSS.

**The toggle button**

Lives in the chat input toolbar adjacent to the existing paperclip attach button. Plain text label "Select" (no glyphs per project preference). Two visual states:

- **Off** (default) — neutral border, label "Select".
- **On** (picker active) — accent border + filled background, label "Selecting…".

**State machine** (one closure)

```
       ┌─────┐
       │ off │  ◄── initial
       └──┬──┘
          │ click "Select"
          ▼
   ┌──────────┐
   │  arming  │  (waiting for io.picker.ready from iframe)
   └────┬─────┘
        │ ready received → send activate
        ▼
 ┌────────────┐
 │  selecting │
 └─┬────┬─────┘
   │    │ user picks element  → chip rendered, → off
   │    │ ESC / click "Select" →                → off
   │    │ iframe reload         →               → off
   └────┘
```

The `arming` substate exists because the iframe may still be loading. Parent retries `activate` once on `io.picker.ready`. Timeout in `arming` after 3s → surface inline error and flip button back to Off.

**Iframe URL handling**

Today: `iframe.src = "/tasks/preview-app/" + slug + "/?t=" + Date.now()`.
Change: when picker is on, append `&picker=1`. When picker is off, do not. The query param decides whether the server injects picker.js — preview without picker mode has zero overhead from this feature.

**Chip rendering**

Reuses the existing `pendingAttachments` infrastructure: same chip strip above the chat textarea, same render path, same X-to-remove affordance. New chip variant `"selection"`:

```js
pendingSelection = {
  selector: "...",      // shown as chip label, mid-truncated with ellipsis
  tag: "ARTICLE",
  outerHtml: "...",
  styles: {...},
  rect: {...},
  url: "...",
  pickedAt: 1715000000000,
}
```

**Single-slot, not array.** v1 holds at most one selection chip. Picking a second element replaces the first — no prompt.

The chip pill renders as `[selected: button.cta · X]` — pure text, no decorative glyphs (project preference: plain text labels only).

**State location:** `pendingSelection` is a **separate single-slot variable**, not an entry in the `pendingAttachments` array. Reuse is at the **render-path level only** — the same chip-strip element holds both attachment chips and the selection chip, but they are tracked in distinct state slots. Rationale: attachments and selection have different submit-time semantics (attachments → `files` field, selection → `selection` field), different validation, and different lifecycle.

**Inside `submitChat()`**

Add to the existing FormData append, alongside `files`:
```js
if (pendingSelection) {
  fd.append("selection", JSON.stringify(pendingSelection));
}
```
Cleared in the same `finally{}` as attachments. A failed send still clears the chip.

The rendered user bubble shows the selection chip inline above the message text, mirroring how attachments render today.

**Cross-mode behavior**

- Switching from Chat to Build mode while a chip is held: keep the chip. (v1 does not wire it into the build prompt — out of scope — but the chip is preserved so we don't surprise the user when v2 lands.)
- **User-initiated refresh** (clicking the preview's refresh button) → clear the chip + force picker mode off. The user has explicitly asked for a fresh page; the selector likely no longer matches.
- **Programmatic / app-driven reload** (cache-bust on first build, hot reload, internal navigation that re-fires the iframe `load` event) → keep the chip. URL is in the payload; the model can reason about staleness from that.
- Tab switch (Files / Code / Logs): auto-deactivate picker. Chip is preserved.

### 4. /chat endpoint extension

**File:** `mcp-servers/tasks/routes_tasks.py` (`/chat` handler)
**Code budget:** ~30 lines.

**New optional form field**

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(
    source_task_id: str = Form(...),
    message: str = Form(..., min_length=1, max_length=2000),
    history: str = Form(default="[]"),
    files: list[UploadFile] = File(default_factory=list),
    selection: str | None = Form(default=None),     # NEW
    user: AdminUser = Depends(current_admin),
):
```

**Validation**

- Reject if `selection` raw exceeds **8KB** → `400`. (Picker truncates outerHtml to 2KB; 8KB cap covers JSON overhead and protects against hand-crafted requests.)
- `json.loads()` — `400` on parse failure.
- Validate against Pydantic model:

```python
class SelectionPayload(BaseModel):
    selector: str = Field(..., max_length=400)
    tag: str = Field(..., max_length=40)
    attrs: dict[str, str] = Field(default_factory=dict)
    outerHtml: str = Field(..., max_length=2200)
    styles: dict[str, str] = Field(default_factory=dict)
    rect: dict[str, float] | None = None
    url: str | None = Field(default=None, max_length=2000)
    pickedAt: int | None = None
```

Anything failing → `400`. No silent fallbacks.

**Prompt assembly**

When `selection` is present, insert a `SELECTED ELEMENT` block in the **system prompt** (not the user message — system prompt is cached across turns):

```
SELECTED ELEMENT
The user pointed at this element in their preview. Scope your answer or
edit to this element specifically. Don't change other parts of the page
unless asked.

  selector:  main > section.skills > article:nth-of-type(2)
  tag:       <article class="skill-card">
  url:       https://.../tasks/preview-app/portfolio-x/

  current outerHTML (truncated):
    <article class="skill-card">
      <h3>Frontend</h3>
      <ul>...</ul>
    </article>

  current computed styles (subset):
    color: rgb(34, 34, 34); background: rgb(255, 255, 255);
    padding: 16px; margin: 0 0 12px 0;
    font-size: 14px; font-family: Inter, sans-serif;
    display: block; border-radius: 8px;
    width: 300px; height: 180px;
```

**Token cost** (Haiku 4.5 input pricing): ~900 tokens worst case → ~$0.001 per turn. Negligible. Screenshots explicitly excluded for v1 (would 5–10× this).

**Logging**

Log `selector`, `tag`, parent task ID at INFO when `selection` is present. Skip outerHtml body — too noisy for ops.

**Response handling** — unchanged. Existing `BUILD_SUGGESTION:` sentinel still fires builds.

## Edge cases

| Failure mode | Handling |
|---|---|
| Iframe reloads while picker is active | Parent watches iframe `load` event. On reload while active → reset to `arming`, re-send `activate` after picker.js readies. |
| `pendingSelection` chip across iframe refresh | Kept (URL is in payload). Cleared on user-initiated refresh button. |
| picker.js fails to load | No `io.picker.ready` within 3s → inline error: "Picker failed to load — refresh the preview and try again." Toggle returns to Off. |
| Server can't find `</head>` | Logs WARNING. Serves original HTML untouched. Picker just doesn't appear. |
| Selector goes stale before send | Not re-resolved. Model gets snapshot data + URL — its problem to handle. |
| Form submit / link navigation while picker on | Capture-phase preventDefault on `submit` and `click` (anchor tags). |
| Shadow DOM | Not supported. Outline doesn't appear over shadow-host children. Documented limitation. |
| ESC key — focus split between parent and iframe | Listeners in BOTH. Single ESC dismisses regardless of focus. |
| User leaves Preview tab | Auto-deactivate. Re-enable requires another click. |
| Pathological outerHTML / hand-crafted requests | Source truncates to 2KB; server caps raw `selection` at 8KB; Pydantic per-field max-length. |
| `<html>` / `<body>` as click target | Silently rejected. Outline disappears. |
| picker.js cache-staleness across deploys | `PICKER_JS_VERSION` query param injected; bumped on every change. |
| Cross-origin posture | v1: `parent.postMessage(payload, "*")`; parent validates `event.source === iframe.contentWindow`. v2 (cross-origin): tighten to origin allowlist — no API change. |

## Testing strategy

### Backend pytest (`mcp-servers/tasks/tests/test_chat_selection.py`, new)

- `test_chat_with_valid_selection_includes_block_in_prompt` — POST with valid selection, mock Anthropic, assert system prompt contains "SELECTED ELEMENT" + selector
- `test_chat_with_oversized_selection_returns_400` — 9KB selection → 400
- `test_chat_with_malformed_selection_json_returns_400` — `selection="{not json"` → 400
- `test_chat_with_invalid_selection_field_returns_400` — Pydantic violations → 400
- `test_chat_without_selection_works_unchanged` — regression guard
- `test_chat_with_selection_and_files` — selection + image attachments together

### Iframe-side script tests (Playwright harness)

- `picker_responds_to_activate` — load picker.js, post activate, assert overlay in DOM
- `picker_posts_selection_on_click` — activate, click known element, assert payload shape
- `picker_truncates_outerhtml_at_2kb` — 5KB outerHTML element → outerHtml ≤ 2200
- `picker_alt_hover_walks_parent` — hover span inside article with Alt held, assert outline targets article
- `picker_escape_deactivates` — fire ESC, assert overlay removed and `cancelled` posted
- `picker_ignores_html_body` — hovering nothing → outline hidden
- `picker_capture_phase_suppresses_form_submit` — click submit-type button while active → form action does NOT fire

### Manual checklist (run pre-deploy)

- [ ] Pick deeply nested element — selector is sane and unique
- [ ] Pick leaf, then Alt-hover parent — outline jumps up one level
- [ ] ESC mid-pick — exits cleanly, no orphaned overlay
- [ ] Click "Select" while already selecting — toggles off, no orphaned overlay
- [ ] Refresh preview while chip held — chip survives, picker resets to off
- [ ] Switch to Files tab while picker on — auto-deactivates
- [ ] Send chat with chip → see chip in user bubble → AI reply references the element
- [ ] Send a chat WITHOUT a chip — backwards-compat sanity check

### Explicitly not tested in v1

- Cross-origin postMessage path
- Multi-select
- Build-mode integration

## Files touched

| File | Change |
|---|---|
| `mcp-servers/tasks/static/picker.js` | NEW — picker script (~150 lines + inlined finder) |
| `mcp-servers/tasks/static/preview.html` | Toggle button, chip rendering, postMessage handlers, FormData extension (~160 lines added) |
| `mcp-servers/tasks/routes_tasks.py` | HTML rewriter for `preview-app` route, `selection` field on `/chat`, prompt assembly, validation (~55 lines added) |
| `mcp-servers/tasks/tests/test_chat_selection.py` | NEW — backend tests |
| `mcp-servers/tasks/tests/test_picker_js.py` | NEW — Playwright harness for picker.js |

## Rollout

- Deploy via existing SCP-to-Hetzner flow (`/root/proxy-server/`).
- Bump `PICKER_JS_VERSION` whenever picker.js changes.
- No DB migration. No env var. No new container.
- Behind no feature flag in v1 — the picker is opt-in per click; risk surface is the toggle button itself, which doesn't affect anything until clicked.

## Open questions for review

1. **Alt-hover discoverability:** the parent affordance is invisible until the user discovers Alt. Add a one-line tooltip on the chip ("Hold Alt while hovering to pick parent") or leave undocumented for v1?

## Resolved during spec review (2026-05-06)

- **Chip glyph:** Pure text `[selected: button.cta · X]`. No decorative glyphs (matches project preference).
- **PICKER_JS_VERSION management:** Manual module-level constant for v1. Auto-derivation from mtime is overkill at this scale.
- **`pendingSelection` vs `pendingAttachments`:** Separate single-slot state variable; shared chip-strip render path only.
- **Iframe-refresh chip semantics:** Cleared on user-initiated refresh; preserved on programmatic / app-driven reload.
- **`keydown` suppression scope:** Only `Escape` is intercepted; other keys fall through.
