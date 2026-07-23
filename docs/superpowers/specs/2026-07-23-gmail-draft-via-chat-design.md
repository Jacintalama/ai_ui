# Design: Draft a new email via chat (Gmail, Open WebUI)

Date: 2026-07-23
Status: Approved (design), pending implementation plan
Owner: Ralph Benitez

## Goal

Let an Open WebUI user, in normal chat, ask the assistant to draft a brand-new
email and have that draft appear in the user's own Gmail Drafts folder for them
to review and send manually. The AI never sends. This is the first item of the
chat-agent roadmap (see memory: project_chat_agent_roadmap_2026-07-22).

## Scope

In scope for v1:
- Compose a brand-new draft (to, subject, body; optional cc/bcc) into the
  logged-in user's Gmail Drafts.

Explicitly out of scope for v1 (deliberate decisions):
- No sending. Draft only.
- No reply-drafts. New drafts only. (A reply-draft tool already exists;
  we are not touching it.)
- No changes to Fusion or the free-model / Auto routing.
- No new OAuth architecture. We only fix the existing Gmail connect flow if the
  live smoke test proves it is broken for Open WebUI users.

## Why "extend", not "rebuild"

Almost everything already exists:
- Gmail MCP server (`mcp-servers/gmail/main.py`) with per-user OAuth tokens
  (`gmail_tokens` table, keyed by `user_email`) and tools for list/search/read,
  send, and reply-draft.
- `mcp-proxy` aggregates all MCP servers and is already registered in Open WebUI
  as an OpenAPI tool server (`TOOL_SERVER_CONNECTIONS` -> `mcp-proxy:8000`). A new
  endpoint on the Gmail server is picked up automatically via `/openapi.json`.
- mcp-proxy already resolves the real logged-in Open WebUI user (validated JWT,
  with DB lookup of the `user` table) and forwards identity headers downstream.
- The Gmail server reads identity from `X-User-Email` (falls back to
  `default@local`).

So the only net-new code is one endpoint plus verification and one possible
connect-flow bugfix.

## Components

| Component | Change | File |
|---|---|---|
| Gmail MCP server | Add `gmail_create_draft` endpoint (compose new draft) | `mcp-servers/gmail/main.py` |
| Input model | `CreateDraftInput` (to, subject, body; optional cc, bcc) | same file |
| Tool guidance | Add a line so the model knows: user wants a new draft -> `gmail_create_draft` | same file |
| Tests | Unit test for MIME/base64url draft build + input validation, no network | `mcp-servers/gmail/tests/` |
| mcp-proxy | No code change expected; verify it forwards `X-User-Email` to the new endpoint | verify only |

## Data flow

```
OWUI chat (tool-capable model)
  -> model calls tool  gmail_create_draft{to, subject, body}
  -> mcp-proxy (resolves logged-in user -> sets X-User-Email)
  -> Gmail server: get_user_email(request) -> load that user's OAuth token
  -> Gmail API drafts.create (raw = base64url MIME message)
  -> returns { draft_id, message: "Draft created. Open Gmail to review and send." }
  -> model tells the user; the draft waits in their Gmail Drafts
```

Nothing sends. The draft sits in the user's Gmail Drafts folder.

## Endpoint contract

`POST /gmail_create_draft` (operation_id `gmail_create_draft`)

Input (`CreateDraftInput`):
- `to` (str, required) recipient email address
- `subject` (str, required)
- `body` (str, required) plain-text body
- `cc` (str, optional)
- `bcc` (str, optional)

Behavior:
- Resolve user via `get_user_email(request)`.
- Load a valid token via the existing `get_valid_token(user_email)` (handles
  refresh).
- Build a MIME message, base64url-encode it, and call Gmail
  `users/me/drafts` (POST) with body `{"message": {"raw": <encoded>}}`.
- Return `{ "draft_id": <id>, "message": "Draft created. Open Gmail to review and send it." }`.

## Error handling

- Not connected (no token for that user): return a clear "Connect your Gmail
  first" message plus the connect link. Not a 500.
- Token expired: reuse existing `get_valid_token` refresh path.
- Missing/invalid fields (e.g. empty recipient): 422 with a plain message the
  model can relay.
- Gmail API error: catch, return trimmed API error text, never leak the token.
- Free / non-tool-calling model: the tool is simply never called. We document
  that email needs a tool-capable (paid) model.

## Testing

Unit (offline, no network, no key):
- Build a draft from sample input; assert the MIME `To` and `Subject` headers,
  that the body is correctly base64url-encoded, and that the request wraps it as
  `{"message":{"raw":...}}`.
- Assert validation rejects an empty recipient.

Live smoke (prod, after deploy) - this is the go/no-go:
- In Open WebUI, on a paid (tool-capable) model, prompt: "draft an email to
  <your address> saying hi." Confirm a real draft appears in Gmail Drafts under
  the correct account.

## Known risks

- Identity forwarding: if `list_emails` already works per-user in OWUI today,
  the new draft endpoint inherits the same working identity path. If not, the
  fix is in mcp-proxy identity forwarding, not in the draft endpoint.
- OAuth connect: the known 2-part vs 3-part OAuth state mismatch (webhook-handler
  signs 3-part, connectors verify 2-part) can break the connect step. Only fix
  if the live smoke shows the OWUI connect flow is broken.

## Deploy

Gmail server is a backend MCP service. Follow the project deploy rules
(CLAUDE.md): commit first, push changed files to the VPS, rebuild the
`mcp-gmail` (and, if changed, `mcp-proxy`) service, then run the live smoke.
Do not touch `.env` or `templates.py`.
