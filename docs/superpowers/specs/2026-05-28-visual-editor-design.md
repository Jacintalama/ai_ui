# Visual editor — design spec

**Date**: 2026-05-28
**Status**: approved (brainstorm), pending implementation plan
**Owner**: Ralph

## Problem

The current App Builder Enhance flow is a Discord modal: the user types one
self-contained change, the bot regenerates, and posts a new "Build ready"
card. The user can't see the preview while typing, can't iterate
conversationally, and has to alt-tab to the public preview URL between turns.
This makes iteration slow and the feedback loop opaque.

## Goal

A standalone webpage, opened from a link button in the Discord "Build ready"
card, that gives the user:

- A live preview of their generated app on the right
- A conversational chat on the left that talks to the same enhance pipeline
- Conversation memory within the page session
- Visible progress when a build is running (the rebuild takes 30–60s)

No element-picker, no direct manipulation editor — just chat with preview.
Element picking is a v2.

## Non-goals (v1)

- Click-to-select visual element picker (GHL Vibe parity)
- Direct manual edits (Webflow-style)
- Cross-session/cross-device persistence of chat history
- Pushing edit results back to Discord (the original Build-ready card stays as-is;
  the slug's files are the source of truth, so a later Publish picks up the latest)
- Real-time LLM token streaming
- Concurrency control between two open editor tabs (documented "last write wins")

## Scope decisions (locked during brainstorm)

| Decision | Choice | Notes |
|---|---|---|
| v1 capability | Chat + side-by-side live preview | No element picker |
| Chat memory | Conversational within the page session | In-memory only, lost on tab close |
| Access control | Signed token in URL (`slug + owner + ts`, 30-min TTL) | Reuses existing `oauth_state.py` 3-part HMAC pattern |
| Layout | Narrow chat (32%) + preview (68%) | Single-column responsive at <800px |
| Build flow | Async job + 1Hz status poll | Robust to 30–60s builds; no HTTP timeout risk |
| Color/brand | Single AIUI cyan (`#22D3EE`) | Matches the v2 Discord brand |

## Architecture

Extends the existing **`tasks`** service (it already owns the slug, the
preview-server route, and the enhance pipeline). No new container. Discord
side gets one new button.

```
DISCORD                            TASKS SERVICE
"Build ready" card                 routes_visual_edit.py
 ├─ Publish        (existing)        ├─ GET  /tasks/edit/<slug>          (page)
 ├─ Enhance        (existing)        ├─ POST /tasks/edit/<slug>/chat     (start build)
 ├─ Open preview ↗ (existing)        ├─ GET  /tasks/edit/<slug>/chat/<id>/status
 └─ Visual edit ↗  (NEW link)        │
    href=/tasks/edit/<slug>          ├─ static/visual-edit.html
        ?token=<signed>              ├─ static/visual-edit.js
                                     │
                                     ├─ visual_edit_jobs.py   (in-memory job registry)
                                     └─ claude_executor.py    (existing, extended)
```

## Components

### Discord side (`webhook-handler`)

| Change | File |
|---|---|
| New constant `VISUAL_EDIT_URL_TEMPLATE` (`/tasks/edit/{slug}?token={tok}`) and helper that signs a token | `handlers/app_builder_panel.py` |
| `build_ready_components(slug, preview_url, owner)` gets a 4th button: `Visual edit ↗` (style 5 link, URL as above) | `handlers/app_builder_panel.py` |
| Callers updated to pass `owner` so the token can be signed bound to the right identity | `handlers/commands.py`, `handlers/discord_commands.py` |

Token uses the existing `handlers/oauth_state.py` (3-part HMAC-SHA256, 600s
TTL today — we'll bump to 1800s / 30 min for this flow, or accept the 10-min
window and let users get a fresh link from Discord). Concrete TTL value
finalized in the implementation plan.

### Tasks service (`mcp-servers/tasks`)

**New modules:**

| Module | Purpose |
|---|---|
| `routes_visual_edit.py` | The three HTTP routes (page, chat, status). Token verification at every endpoint. |
| `visual_edit_jobs.py` | In-process `{build_id: VisualEditJob}` registry. State machine: `queued → thinking → applying → done \| error`. 10-min TTL reaper. |
| `static/visual-edit.html` | The editor SPA shell — narrow chat sidebar + preview iframe. Single page, single script. |
| `static/visual-edit.js` | Browser logic: chat history array, POST chat, poll status, reload iframe on `done`, show error pill on `error`. |
| `visual_edit_token.py` (or thin wrapper inside `routes_visual_edit.py`) | `verify_edit_token(token, slug) -> owner_or_None`. Wraps `oauth_state.verify_state` with the slug-binding check. |

**Modified:**

| File | Why |
|---|---|
| `claude_executor.py` | Add `enhance_with_history(slug, history, prompt) -> EnhanceResult`. Same enhance pipeline as today, but prepends the `history` list (`[{role, content}, ...]`) as conversation context for the LLM. Reuses the atomic write/swap logic. |
| `routes_aiuibuilder.py` | (optional) factor the build-running guts out so both `/enhance` and the new chat endpoint share one internal function. Not strictly required if `claude_executor.enhance_with_history` is the shared seam. |

### Token format

Same as the deployed `oauth_state.py`:

```
<b64url(owner)>.<b64url(ts)>.<b64url(sig)>
```

For visual-edit links the **HMAC payload is `owner:ts:slug`**, not just `owner:ts`,
so a token issued for slug A can't be replayed against slug B. The verify
helper takes `(token, slug)` and re-computes the HMAC over `owner:ts:slug` to
check.

**Why this change:** the existing connect-flow tokens only bind to owner+ts
because the slug isn't relevant there. For visual-edit, a single owner has
many slugs and we don't want one slug's link to grant edit on another.

### HTTP API

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| `GET` | `/tasks/edit/<slug>` | `?token=` | — | `200 text/html` (the SPA) or `403` |
| `POST` | `/tasks/edit/<slug>/chat` | `?token=` | `{prompt: str, history: [{role, content}, …]}` | `202 {build_id}` or `403` / `400` |
| `GET` | `/tasks/edit/<slug>/chat/<build_id>/status` | `?token=` | — | `200 {state, preview_url?, error?}` or `403` / `404` |

`state` is one of: `queued`, `thinking`, `applying`, `done`, `error`.
On `done`, `preview_url` is `/tasks/preview-app/<slug>/?v=<build_id>` (the `?v=`
forces an iframe refresh past browser cache).
On `error`, `error` is `{summary: str, detail: str}` — `summary` is rendered
in the chat pill, `detail` is collapsed/hidden by default.

## Data flow (one chat turn)

```
browser              tasks service                 claude
   |  POST /chat        |                            |
   |   {prompt, history}|                            |
   +------------------->|                            |
   |  verify token      |                            |
   |  allocate build_id |                            |
   |  start asyncio job |                            |
   |<-- 202 {build_id} -+                            |
   |                    |                            |
   | poll status (1Hz)  |                            |
   +------------------->|                            |
   |<-- thinking -------+                            |
   |                    +-- enhance_with_history --->|
   |                    |    (history + prompt)      |
   +------------------->|                            |
   |<-- applying -------+   ... LLM streams ...      |
   |                    |<-- new files --------------+
   |                    | atomic write to apps/<slug>|
   +------------------->|                            |
   |<-- done            |                            |
   |    preview_url:    |                            |
   |    .../?v=<id> ----+                            |
   |                    |                            |
   | reload iframe      |                            |
```

**Conversation state** lives in the browser as a JS array
`[{role: "user" | "assistant", text: str, build_id?: str, status?: "done" | "error"}]`.
Sent with every POST. Server is stateless w.r.t. conversations.

**Iframe cache-bust**: `?v=<build_id>` query string. Browsers re-fetch instead
of serving the previous build from cache.

## Error handling

| Failure | What the user sees | Server behavior |
|---|---|---|
| Bad / missing / expired token (page load) | Centered error: "This editor link has expired. Click **Visual edit** in Discord again." | `403`, no SPA served |
| Token expires mid-session | Inline chat error block + `Get a fresh link` hint | `403` on the chat/status call |
| Build LLM fails | Red status pill in chat: "That edit didn't apply — `<summary>`. Tell me what you wanted differently." | Job → `error`. Previous build's files untouched (atomic swap held back). User can re-prompt. |
| Claude API timeout / error | Same pill, summary = "AI service didn't respond" | Job → `error` |
| Build hangs >5 min | Pill: "Build took too long — try again or simplify the change." | `asyncio.wait_for(..., timeout=300)` in the background task. Job → `error`. |
| Two tabs editing same slug | Last write wins. Iframe shows whichever build's `?v=` finished last. | No lock; documented behavior. |
| Tab refresh / navigate-away mid-build | Build keeps running. Files get written. On next visit the user sees the latest preview, no chat history. | Detached `asyncio.create_task`. |
| Server restart mid-build | "The service restarted — your last change may not have saved. Try again?" | All in-flight jobs lost. Polling → 404, browser shows the message. |
| Poll endpoint hammered | `429` after >1 poll/second per build_id | Defensive rate limit; not load-critical. |
| iframe fails to load | Fallback `Open preview in new tab ↗` button next to the iframe area | — |

## Testing strategy

**Unit (pure functions, no I/O):**

- `test_visual_edit_token.py` — `verify_edit_token(token, slug)`: valid → owner; bad sig / wrong-slug / expired / malformed → None
- `test_visual_edit_jobs.py` — registry: allocate; state transitions; TTL reap; lookup of unknown id is safe
- `test_build_ready_visual_edit_button.py` — `build_ready_components(slug, preview_url, owner)` includes `Visual edit` link with a slug-bound token

**Route tests** (FastAPI `TestClient`, no LLM):

- `test_routes_visual_edit_auth.py` — `GET /tasks/edit/<slug>`: missing / expired / wrong-slug → 403; valid → 200 + HTML
- `test_routes_visual_edit_chat.py` — `POST /chat` returns 202 + `{build_id}`; registers a job; bad token → 403
- `test_routes_visual_edit_status.py` — `GET status` returns the job state; unknown id → 404; bad token → 403

**Integration** (mocks `enhance_with_history`, no Claude calls):

- `test_visual_edit_lifecycle.py`:
  - Happy path: POST chat → poll status → assert sequence `thinking → applying → done`, `preview_url` includes correct `?v=<build_id>`, file written under `apps/<slug>/`
  - Error path: fake raises `RuntimeError` → job → `error`, files NOT touched
  - Timeout path: fake hangs (short test TTL e.g. 50ms) → job → `error: "Build took too long"`

**Explicitly NOT tested in v1:**

- The browser SPA (chat rendering, iframe reload, polling) — manual smoke test on VPS after deploy. Playwright is v2.
- Real Claude API — burns credits, flaky. Mock at the `enhance_with_history` seam.
- Concurrency races — documented "last write wins", not automated.

Total: ~9 new test files, ~25 test cases. Mirrors existing density for
`routes_aiuibuilder.py` and friends.

## Open questions (to settle in implementation plan)

- **Token TTL**: 10 min (current `_TTL_SECONDS`) might be too short for editor sessions. Bump to 30 min by either (a) extending `_TTL_SECONDS` globally, (b) adding a per-flow TTL parameter to `sign_state`, or (c) issuing fresh tokens from a `/refresh` route inside the editor. Decision deferred to plan.
- **`enhance_with_history` history format**: list of `{role, content}` pairs vs. a single concatenated string. Need to look at the existing enhance prompt to see what fits cleanest.
- **Atomic write/swap**: confirm the existing enhance pipeline already does temp-dir → rename. If not, this design adds it.
- **Where the chat input lives in the iframe layout**: bottom of the chat column (default) vs. floating over the preview. Minor; finalize during static HTML implementation.

## Out of scope for v1, candidate for v2

- Click-to-select element picker (postMessage from iframe, selector extraction, scoped prompts)
- Real-time LLM token streaming (SSE)
- Persistent conversation history (per slug + owner, in postgres)
- Multi-user collaboration (CRDT or simple lock)
- Direct manual edits (drag, inline text, color picker)
- A "send to Discord" button that posts the updated preview back to the original thread
