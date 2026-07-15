# Fusion Chat Page (FastAPI + HTMX, in the tasks-service)

Date: 2026-07-15
Status: Approved direction (Ralph). Python-only stack. Replaces the OWUI
dropdown-pipe access.

## Goal

Give Model Fusion its own place: a "Fusion" entry in the Open WebUI sidebar
(next to App Builder / Video Generation / Cron Jobs) that opens a dedicated
full-page chat. The user chats with Fusion and gets one synthesized answer per
turn (GPT + Claude panel + judge). The current access - Fusion (Quality/Budget)
as models in the OWUI chat dropdown - is REMOVED (the pipe is uninstalled).

## Stack decision (why FastAPI + HTMX)

The whole platform is Python; every existing UI page is served by the
FastAPI tasks-service. Fusion follows suit: the page lives INSIDE the
tasks-service. FastAPI renders the HTML and streams the answer; HTMX
(one small vendored JS file, no CDN, no bundler, no new service) wires the
form and the streaming. We write only Python + HTML. The engine
(`fusion_engine.fuse`) is called IN-PROCESS - no internal HTTP hop.

## What changes vs what's live

- Reused as-is: `fusion_engine.py` (fan-out + judge + streaming), the verified
  registry/presets, the OpenAI + Anthropic keys, `sse_starlette` (already a
  dependency, used by routes_execution).
- Removed: `open-webui-functions/fusion_pipe.py`,
  `scripts/install_fusion_pipe.py` (repo); on prod the `fusion_pipe` function
  row is deleted and OWUI restarted so the dropdown models disappear. The
  internal-secret `/api/fusion/complete` route + its auth helper are removed
  (no internal caller remains).
- Added: `routes_fusion_page.py` (page + send + stream), a vendored
  `htmx.min.js` + `sse.js`, a `fusion.html` shell, a sidebar nav entry, and
  gateway routes for `/fusion*`.

## Architecture / data flow

```
OWUI sidebar: App Builder | Video Generation | Cron Jobs | Fusion (new)
   | click Fusion
   v
GET /fusion            -> tasks-service returns fusion.html (loads vendored htmx + sse ext)
   | user picks Quality/Budget, types, submits the composer form
   v
POST /fusion/send      (current_user)  -> append user msg to their in-memory session,
                                          return an HTML fragment: the user bubble +
                                          an empty assistant bubble that hx-connects
                                          (SSE) to /fusion/stream
   v
GET /fusion/stream     (current_user, SSE via EventSourceResponse)
   -> fusion_engine.fuse(session.messages, preset)  [in-process]
   -> fan out GPT + Claude -> judge -> yield tokens as SSE "message" events
   -> htmx-sse appends each token into the assistant bubble live
   -> on done: append the assistant answer to the session, send an SSE "close"
   v
user sees one synthesized answer stream in; can send the next turn (multi-turn)
```

## Components

### Backend: `mcp-servers/tasks/routes_fusion_page.py` (new)
- `router = APIRouter()` (registered in main.py).
- In-memory per-user ephemeral session store: `_SESSIONS: dict[str, FusionSession]`
  keyed by user email, where FusionSession holds `messages: list[dict]`,
  `preset: str`, `last_used: datetime`. A tiny sweep drops sessions idle > 2h
  (checked lazily on access). NOT persisted (lost on restart - fine for v1).
- `GET /fusion` (current_user) -> `FileResponse("static/fusion.html")`.
- `POST /fusion/send` (current_user, form: `message: str`, `preset: str`) ->
  validate preset in `fusion_engine.PRESETS` (else 400), append
  `{"role":"user","content":message}` to the session, set the session preset,
  return an HTML fragment (user bubble + assistant bubble wired to stream). A
  send while a stream is active for that user is rejected cleanly.
- `GET /fusion/stream` (current_user, SSE) -> `EventSourceResponse` that runs
  `fusion_engine.fuse(session.messages, session.preset)`, yields each text chunk
  as an SSE event whose data is the (HTML-escaped) chunk, and on completion
  appends `{"role":"assistant","content":full}` to the session and emits a
  terminal event so htmx-sse stops listening. Engine errors already degrade
  gracefully (the fuse generator yields a clean message); the stream relays it.
- `POST /fusion/new` (current_user) -> clear the user's session, return the
  empty thread fragment.
- Small HTML-fragment builders (Python functions returning strings) for the
  user bubble, assistant bubble, and empty-thread; kept in this module.

### Frontend: `mcp-servers/tasks/static/fusion.html` (new) + vendored JS
- One self-contained HTML page, dark theme matching the other pages: a header,
  a Quality/Budget segmented toggle, a scrolling chat thread, and a composer
  (textarea + Send). Loads two VENDORED scripts from `/tasks/static/vendor/`:
  `htmx.min.js` and `htmx-ext-sse.js` (downloaded into the repo, served
  locally - no live CDN dependency, robust under any CSP).
- The composer form uses `hx-post="/fusion/send"` and swaps the returned
  fragment into the thread; the assistant bubble in that fragment uses
  `hx-ext="sse" sse-connect="/fusion/stream"` to receive the streamed tokens.
  Auth: the page adds `Authorization: Bearer <localStorage token>` to HTMX
  requests via `htmx:configRequest` (a few lines of inline JS - the only JS we
  write; everything else is HTMX attributes). Same-origin as OWUI so the token
  is shared.
- A "New chat" button posts `/fusion/new`. Enter sends, Shift+Enter newline.

### Gateway: `api-gateway/main.py`
- Add `/fusion` (and its subpaths `/fusion/send`, `/fusion/stream`,
  `/fusion/new`) to the prefixes routed to the tasks-service, mirroring how
  `/tasks/*`, `/api/tasks`, `/video-generator` are routed. Confirm the exact
  structure and mirror it.

### Sidebar nav: `mcp-servers/tasks/static/task-panel.js`
- Add a `Fusion` entry to `NAV_ENTRIES`: `allUsers: true`, `href: "/fusion"`,
  a fusion/merge glyph, title "Fusion: ask a panel of models, get one answer".

### Pipe removal
- Delete `open-webui-functions/fusion_pipe.py` and
  `scripts/install_fusion_pipe.py`.
- Simplify `routes_fusion.py`: drop `/api/fusion/complete` + `/models` +
  `_require_internal` (the pipe was their only caller). If nothing remains,
  delete the file and its `include_router` line. (The engine stays.)
- Prod cleanup (deploy step): `DELETE FROM function WHERE id='fusion_pipe'`,
  restart OWUI.

## Error handling

- Not signed in (no/invalid token): gateway/current_user returns 401/403; the
  page shows "please sign in to Open WebUI and reload".
- Engine failures: already handled inside `fuse` (panel drop, all-fail clean
  message, judge-fail best-answer). The stream relays whatever `fuse` yields.
- Stream disconnect mid-turn: the SSE closes; the partial text stays; the
  composer re-enables so the user can retry.
- Unknown preset (shouldn't happen from the toggle): 400 rendered inline.
- Concurrent send while streaming for the same user: rejected with a small
  "still answering..." note (a per-session in-flight flag).

## Testing (pytest, no real LLM calls)

- `routes_fusion_page`: `/fusion/send` requires a user identity (rejects
  missing X-User-Email), 400 on unknown preset, appends the user message to
  the session, returns a fragment containing the sse-connect assistant bubble;
  `/fusion/stream` (with `fusion_engine.fuse` monkeypatched to a fake async
  generator) emits the chunks as SSE and appends the assistant message to the
  session; `/fusion/new` clears the session; the 2h idle sweep helper is a pure
  unit test.
- Session store: append/clear/idle-expiry as pure-function tests.
- `fusion_engine` tests unchanged (stay green). `routes_fusion.py` removal:
  update/delete its tests accordingly.

## Deploy / cleanup sequence

1. Commit the page + routes + vendored JS + nav + gateway change + pipe
   removal.
2. Push main; tar-push changed tasks files + the gateway change + the vendored
   JS + fusion.html.
3. Rebuild tasks (serves /fusion + streams) and the gateway.
4. Uninstall the pipe on prod: `DELETE FROM function WHERE id='fusion_pipe'`,
   restart OWUI; confirm the dropdown models are gone and OWUI is healthy.
5. Verify: sidebar shows Fusion -> /fusion loads the chat -> a real prompt
   streams a synthesized answer (logs show GPT + Claude + judge); multi-turn
   works; the old dropdown models are absent; healthz green.

## Out of scope (future follow-ups)

- Server-saved chat history / multiple named conversations (v1 is in-memory
  ephemeral, per user, cleared on restart or "New chat").
- A custom panel/judge picker UI (presets only in v1).
- Multimodal (image) input.
