# Visual Editor deep link (replace "Enhance" in Discord + Slack)

Date: 2026-06-04
Status: Reviewed (security pass applied) — ready for implementation plan; not built, not deployed

> Security review applied (2026-06-04). Resolutions for MF-1..MF-6 are folded into
> Part 2/3 and the Security section below. Gateway finding: the api-gateway does
> not block unauthenticated `/tasks/*`; it forwards them with `X-User-Admin:
> false`. So the request reaches the tasks service — the fix is entirely in the
> tasks service (the edit-page route and capability-authed endpoints must NOT
> depend on `current_admin`). No gateway change required.

## Problem

Today the bots expose an **Enhance** button that opens a text-only modal: the
user types a description and the app is rebuilt. Meanwhile a far richer editor
already exists on the web (`mcp-servers/tasks/static/preview.html`): it has an
element **picker** ("Select"), a side **chat**, selection chips, and applies
changes by POSTing to `/{task_id}/execute`. We want the bot button to open that
web editor instead of the text modal.

A live select-region + side-chat UI **cannot** be built inside Discord or Slack
(they only render modals and message blocks). So the editor must stay on the web
and the bot button must be a **deep link** into it. The catch is authentication
(see Current state).

## Goals

- Replace the **Enhance** button with **🎨 Visual Editor** everywhere Enhance
  appears today (Discord + Slack: build-ready card, published card, My apps).
- The button is a link that opens the existing web editor scoped to that app,
  authenticated without requiring a prior App Builder web login.
- A Discord/Slack user who clicks it can select + chat + apply changes to **only
  their own app**, and only for a short window.

## Non-goals

- No changes to cronjob/scheduler.
- No rebuild of the editor UI itself (it exists and works).
- No new broad/long-lived web sessions for chat users.
- Keep the backend enhance capability that other entry points use; only the
  button + modal entry is removed.

## Current state (verified)

- `preview.html` applies edits via `apiFetch("POST", "/" + taskId + "/execute")`
  and authenticates every API call with `Authorization: Bearer <localStorage
  token>` — i.e. it assumes the user is logged into the App Builder web UI.
- The editor endpoints (`routes_execution.py`: `execute`, `answer`, `cancel`,
  `start_clarify`, `start_plan`) depend on `current_admin` **and** then call
  `_require_role(session, slug, user.email, "editor")`.
- A signed edit token already exists on both sides:
  `webhook-handler/handlers/visual_edit_token.py` (`sign_edit_token(slug, owner)`)
  and `mcp-servers/tasks/visual_edit_token.py` (`verify_edit_token(token, slug)`).
  It is HMAC over `owner:ts:slug` with `OAUTH_STATE_SECRET`, TTL 1800s.
- The bots already build a "Visual edit" link to `/tasks/edit/{slug}?token=…`
  in `build_ready_attachment` (gated on `owner`), **but no route serves
  `/tasks/edit/{slug}`** — that deep link currently 404s. This is the gap.

## Design

Three parts. Part 2 (auth bridge) is the only security-sensitive, genuinely new
work; parts 1 and 3 are small.

### Part 1 — Bots (Discord + Slack)

Replace each **Enhance** button with **🎨 Visual Editor**, a link/URL button to:

```
{tasks_public_url}/tasks/edit/{slug}?token={sign_edit_token(slug, owner)}
```

- Discord: `app_builder_panel.py` — change the Enhance buttons in
  `build_ready_attachment`, `build_published_attachment`, and the My-apps list to
  link buttons (STYLE_LINK + url). Remove the `ENHANCE_PREFIX` button + its
  `is_enhance_button` routing and the enhance modal open. Keep the backend
  enhance handler if a slash command still uses it; otherwise remove dead code.
- Slack: `slack_app_builder_panel.py` — same, using `_link_button(...)`. Remove
  the `ENHANCE_PREFIX` action from the action loop in `slack_interactions.py` and
  the enhance modal (`ENHANCE_MODAL_PREFIX`) submit branch if no longer reachable.
- `owner` is the same resolved email used elsewhere (Discord `_resolve_email_auto`,
  Slack `_resolve_email_for_ctx`), so the token binds to the right identity.

Link buttons require no interaction handler (Discord link buttons send no
interaction; Slack url buttons are acknowledged by the existing fallthrough).

### Part 2 — Tasks backend: `GET /tasks/edit/{slug}` + scoped capability

**New module `mcp-servers/tasks/edit_capability.py`** (`mint_capability`,
`verify_capability`) mirroring the existing token module's HMAC style, with these
EXACT, fully-specified semantics (MF-1, MF-3):

- Domain separation: the signed payload is the colon-joined UTF-8 string
  `edit_cap:{owner}:{slug}:{task_id}:{exp}` with an explicit `edit_cap` **type
  prefix**. `verify_capability` recomputes with the same prefix and rejects
  anything else, so it can never be confused with an edit token or oauth_state
  token (which share `OAUTH_STATE_SECRET`). Also retrofit a `edit_tok:` prefix
  into the existing `visual_edit_token.py` (both sign + verify sides) so all
  three token families are domain-separated. Constant-time compare (`hmac.compare_digest`).
- `exp` is an **absolute Unix timestamp (int)**. `verify_capability` rejects when
  `time.time() >= exp`. TTL via env `EDIT_CAP_TTL_SECONDS` (default 1800), mirroring
  `EDIT_TOKEN_TTL_SECONDS` (MF-3, NH-5).
- Fail closed: empty `OAUTH_STATE_SECRET` → `mint` raises, `verify` returns `None`.
- `verify_capability(cap)` returns the dict `{owner, slug, task_id}` or `None`.

**New route `GET /tasks/edit/{slug}`** — must NOT depend on `current_admin`
(it authenticates via the token, and the gateway forwards it with no admin
headers):

1. `owner = verify_edit_token(token, slug)`. If `None` → `403`.
2. Resolve the task/app for `slug` **owned by** `owner` (same ownership lookup
   the editor endpoints use; owner = `assignee_email` or `owner` role). Not found
   / not owner → `403`/`404`.
3. `cap = mint_capability(owner, slug, task_id)` (least privilege: one `task_id`,
   one `owner`, short TTL).
4. Serve `preview.html` in edit mode with `task_id` + `cap` **JSON-encoded** into
   a seed `<script>` (MF-5 — never raw string-interpolate `slug`/`task_id`).
   Response header `Cache-Control: no-store` so no proxy caches a personalized,
   capability-bearing page (NH-4).

**Editor endpoints — alternate, capability-only auth path.** The endpoints the
editor calls — `execute`, `answer`, `cancel`, `start_clarify`, `start_plan`,
`review_plan`, `resume`, and the task GET (MF-6: include plan/review/resume so a
task mid-plan still works) — gain an alt path:

- If a valid `X-Edit-Capability` header is present, **replace** `current_admin`
  entirely (do not wrap it — the gateway sends `X-User-Admin: false`, MF-4) and
  authorize the request **iff** `capability.task_id == path task_id`
  (and `owner`/`slug` match the task). A capability for task A can never act on
  task B. Re-verify the capability on **every** request (no trust carried across
  calls).
- `cancel` currently has **no** `_require_role` ownership check on the admin path
  (MF-2). The capability path MUST enforce `capability.task_id == path task_id`,
  and we additionally harden the admin `cancel` path to check task ownership so
  the two paths are consistent.
- When no capability header is present, behavior is **unchanged**: existing
  `current_admin` + `_require_role("editor")` path for logged-in web users.

### Part 3 — preview.html (small)

`apiFetch` currently reads the bearer from `localStorage`. Add: if the page was
served with the injected edit context (`task_id` + `cap` from the JSON-encoded
seed script), send the capability as the **`X-Edit-Capability`** header (a
distinct header, kept separate from `Authorization` so the two auth paths never
mix — MF-1, open-Q1) and use the injected `task_id`. No change to select/chat/
execute logic. On a `401/403` (capability expired mid-session), show "this edit
session expired — reopen Visual Editor from the bot".

## Security considerations

- **Least privilege:** capability is bound to a single `task_id` + `owner`,
  short TTL, server-verified on every editor request. No broad bearer minting.
- **No new secrets:** reuse `OAUTH_STATE_SECRET`; never log tokens/capabilities.
- **Fail closed:** missing secret, bad/expired token, or ownership mismatch all
  return `403` with no app data.
- **Constant-time compare** for HMAC (as the existing token module does).
- **Scope creep guard:** the capability authorizes only the editor endpoints
  needed (`execute`, `answer`, `cancel`, `start_clarify`, `start_plan`, task GET),
  not the full admin API.
- Token appears in a URL (referrer/history) — acceptable given the 30-min TTL and
  single-app scope; mirrors the existing edit-token design.

## Data flow

```
User clicks "Visual Editor" (Discord/Slack)
  → opens /tasks/edit/{slug}?token=<edit_token>
  → tasks: verify_edit_token → owner; resolve task_id; ownership check
  → mint scoped capability {owner,slug,task_id,exp}
  → serve preview.html (task_id + capability injected)
  → user Selects an element + chats
  → preview.html POST /{task_id}/execute  (X-Edit-Capability)
  → endpoint: verify_capability matches task_id/owner → run edit
```

## Error handling

- Invalid/expired token or wrong owner → `403`, friendly "this edit link expired,
  reopen Visual Editor from the bot" page.
- Capability expired mid-session → editor surfaces "session expired, reopen".
- App not found → `404`.

## Testing

- `edit_capability`: mint→verify round-trip; expired; tampered; wrong task_id;
  missing secret → None.
- `/tasks/edit/{slug}`: valid token serves editor with correct task_id; bad token
  → 403; non-owner → 403.
- Editor endpoint alt-auth: capability for task A rejected on task B; valid
  capability authorizes its own task; admin-bearer path unchanged.
- Bots: builders render a Visual Editor **link** (url set) and no longer emit the
  Enhance action_id/modal.

## Rollout

- Tasks backend first (route + capability + endpoint alt-auth), then bots.
- Deferred deploy (per Ralph): build + test locally, do not deploy until told.
- Deploy order when approved: tasks service, then webhook-handler bots; verify
  the deep link opens the editor and a test edit applies.

## Security review resolutions (2026-06-04)

- MF-1 domain separation → `edit_cap:`/`edit_tok:` type prefixes (Part 2).
- MF-2 `cancel` ownership → capability enforces task_id match + harden admin path.
- MF-3 capability format → fully specified (prefix, absolute `exp`, colon-joined).
- MF-4 gateway → no change needed; tasks endpoints replace `current_admin` when a
  valid `X-Edit-Capability` is present (gateway forwards with admin=false).
- MF-5 XSS → JSON-encode injected `task_id`/`slug` into the seed script.
- MF-6 scope → include `review_plan` + `resume` + task GET in the capability path.
- Applied nice-to-haves: NH-4 `Cache-Control: no-store`, NH-5 env-configurable TTL.
- Deferred (documented, low risk in single-user context): NH-1 one-use/nonce,
  NH-3 startup secret check, NH-6 IP/UA binding.

## Open questions

1. Do any slash commands (e.g. `aiuibuilder enhance`) still call the backend
   enhance handler? If yes, keep the handler and only remove the button + modal
   entry; if no, remove the dead path too. (Resolve during planning by grepping
   usages.)
