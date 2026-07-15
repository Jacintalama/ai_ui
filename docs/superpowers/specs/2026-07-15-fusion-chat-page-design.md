# Fusion Chat Page (dedicated React SPA)

Date: 2026-07-15
Status: Approved direction (Ralph). Replaces the OWUI dropdown-pipe access.

## Goal

Give Model Fusion its own place: a "Fusion" entry in the Open WebUI sidebar
(next to App Builder / Video Generation / Cron Jobs) that opens a dedicated
full-page chat. The user chats with Fusion there and gets one synthesized
answer per turn (GPT + Claude panel + judge, the engine already deployed).
The current access path - Fusion (Quality/Budget) as models in the OWUI chat
dropdown - is REMOVED (the pipe is uninstalled). The page IS the way in.

## What changes vs what's live

- Live and REUSED as-is: `fusion_engine.py` (fan-out + judge + streaming),
  the verified provider registry, presets, the OpenAI/Anthropic keys.
- Auth flips: `POST /api/fusion/complete` moves from internal-secret (was for
  the pipe) to user auth (`current_user` / X-User-Email via the gateway), since
  the only caller is now the logged-in browser page.
- Removed: `open-webui-functions/fusion_pipe.py`, `scripts/install_fusion_pipe.py`
  (repo); on prod, the `fusion_pipe` function row is deleted and OWUI restarted
  so the dropdown models disappear.
- Added: a React + Vite + Tailwind SPA served by the tasks-service, a sidebar
  nav entry, gateway routes for the page + endpoint.

## Architecture / data flow

```
OWUI sidebar: App Builder | Video Generation | Cron Jobs | Fusion (new)
   | click Fusion
   v
GET /fusion  -> tasks-service returns the SPA index.html (built bundle)
   | React app loads, assets under /fusion/assets/*
   v
user types -> POST /api/fusion/complete  (Bearer = OWUI token from localStorage)
   v
gateway injects X-User-Email -> route authed via current_user
   v
fusion_engine.fuse(messages, preset) -> fan out GPT + Claude -> judge -> stream
   v
tokens stream back (text/plain) -> appended into the assistant bubble live
```

## Components

### Frontend SPA: `mcp-servers/tasks/fusion-ui/` (React + Vite + Tailwind)
- Scaffolded from the official Vite React template (`bun create vite`), then
  Tailwind added. `vite.config` sets `base: "/fusion/"` so built asset URLs
  resolve under the served path.
- Components (small, one job each):
  - `App` - holds the message array + current preset; orchestrates a turn.
  - `ChatThread` - renders the message list; auto-scrolls on new tokens.
  - `MessageBubble` - one user or assistant message (markdown-rendered
    assistant text).
  - `Composer` - textarea + Send (Enter to send, Shift+Enter newline);
    disabled while a turn streams.
  - `PresetToggle` - Quality / Budget segmented control (default Quality).
  - `PanelStatus` - a transient "consulting the {preset} panel..." line shown
    while the panel runs, before the judge stream starts.
- State: client-side only, EPHEMERAL multi-turn (a message array in memory).
  No server-saved chat history in v1. Each turn POSTs the full message list.
- Streaming: `fetch()` the endpoint, read `response.body.getReader()`, decode
  chunks, append into the live assistant bubble. On done, the turn ends.
- Auth: read `localStorage.getItem("token")` (the OWUI JWT, same origin) and
  send `Authorization: Bearer <token>`; the page lives on the OWUI domain so
  the token is shared.
- Dark theme matching the other platform pages.

### Build + serve (no Node in the prod image)
- Build on the dev/deploy machine: `cd fusion-ui && bun install && bun run build`
  -> `fusion-ui/dist/` (index.html + assets/).
- The BUILT dist is committed to the repo and shipped like any other file
  (the deploy stays file-push + Python serve; the prod tasks image never runs
  a bundler).
- tasks-service `main.py`: mount `StaticFiles(directory="fusion-ui/dist")` at
  `/fusion` (html=True so index.html serves at /fusion and assets resolve),
  OR a `@app.get("/fusion")` returning the dist index.html plus a static mount
  for `/fusion/assets`. Follow whichever matches the existing static-mount
  pattern in main.py.

### Backend endpoint (user-authed)
- `routes_fusion.py`: `POST /api/fusion/complete` auth changes from
  `_require_internal` to `current_user` (X-User-Email). Body unchanged
  (`{preset, messages}`), 400 on unknown preset, `StreamingResponse(fuse(...))`.
  `GET /api/fusion/models` (presets list) also becomes `current_user` so the
  page can show which real models each preset uses.
- The internal-secret helper and its import are removed from routes_fusion.py
  (no internal caller remains).

### Gateway (`api-gateway/main.py`)
- Add `/api/fusion` and `/fusion` to the prefixes routed to the tasks-service
  (mirroring how `/api/tasks`, `/api/video-jobs`, `/tasks/*` are routed), so the
  browser can reach both the page and the endpoint. Confirm the exact
  prefix-routing structure and mirror it.

### Sidebar nav (`mcp-servers/tasks/static/task-panel.js`)
- Add a `Fusion` entry to `NAV_ENTRIES`: `allUsers: true`, `href: "/fusion"`,
  a fusion/merge glyph, title "Fusion: ask a panel of models, get one answer".

### Pipe removal
- Delete `open-webui-functions/fusion_pipe.py` and
  `scripts/install_fusion_pipe.py` from the repo.
- Prod cleanup (deploy step): `DELETE FROM function WHERE id='fusion_pipe'` in
  the OWUI DB, then restart OWUI so `Fusion (Quality/Budget)` leave the dropdown.

## Error handling

- Endpoint auth: no token / bad token -> 401/403 from the gateway/current_user;
  the page shows a "please sign in to Open WebUI" message.
- Engine already handles panel failures (dropped), all-fail (clean message),
  judge-fail (best panel answer) - the page just renders whatever streams.
- Network/stream error mid-turn: the page ends the turn, keeps the partial
  text, and shows a small "connection interrupted" note with a Retry.
- Unknown preset (shouldn't happen from the toggle): 400 -> page shows the
  error inline.

## Testing

- Backend (pytest, extend `test_routes_fusion.py`): `/api/fusion/complete` now
  requires a user identity (rejects missing X-User-Email), still streams on a
  valid user, still 400s unknown preset; `/api/fusion/models` returns presets
  for a user. (The engine tests are unchanged and stay green.)
- Frontend: a lightweight component test for the streaming reducer (given a
  sequence of chunks, the assistant bubble text accumulates in order) and the
  preset toggle; Vitest (comes with the Vite React template). Keep it minimal.
- Build: `bun run build` succeeds and produces `dist/index.html` + assets with
  `/fusion/`-based URLs.

## Deploy / cleanup sequence

1. Build the SPA locally, commit `fusion-ui/` + its `dist/`.
2. Push main; tar-push changed tasks files + the new dist + the gateway change.
3. Rebuild tasks (serves the new /fusion + endpoint) and the gateway.
4. Uninstall the pipe on prod: delete the `fusion_pipe` function row, restart
   OWUI; confirm the dropdown models are gone and OWUI is healthy.
5. Verify: sidebar shows Fusion -> /fusion loads the SPA -> a real prompt
   streams a synthesized answer (logs show GPT + Claude + judge); the old
   dropdown models are absent; healthz green.

## Out of scope (future follow-ups)

- Server-saved chat history / multiple named conversations.
- A custom panel/judge picker UI (presets only in v1).
- Multimodal (image) input.
