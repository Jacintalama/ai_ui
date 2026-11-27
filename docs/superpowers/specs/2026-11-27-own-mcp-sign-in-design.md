# Sign in to an MCP server (Notion first)

Date: 2026-11-27. Trello: o9vFFu0S. Status: design, approach 1 (my pick; the
user handed me the how with "what next?"). Builds on
`2026-11-26-own-mcp-servers-design.md` (PR #301, live).

## Why

Notion has waited since 2026-11-24 on a Notion app registration
(NOTION_CLIENT_ID and SECRET) that nobody has done, and our Notion connector
only reads. Notion's hosted MCP server (`https://mcp.notion.com/mcp`) needs
neither: an app registers itself at sign-in (dynamic client registration),
and its tools write as well as read. Checked live 2026-11-27:

- `/.well-known/oauth-protected-resource/mcp` names the authorization server
  `https://mcp.notion.com`; an unauthenticated POST answers 401 with
  `WWW-Authenticate: Bearer resource_metadata="..."`.
- Its metadata has `registration_endpoint`, `code_challenge_methods_supported:
  ["S256"]`, `grant_types: authorization_code, refresh_token`,
  `token_endpoint_auth_methods_supported` including `none`.
- A registration with redirect `https://ai-ui.coolestdomain.win/...` and
  `token_endpoint_auth_method: none` was accepted and returned a client id.

So "Sign in with Notion" can work today with no setup by anybody. The same
standard (the MCP authorization spec: protected-resource metadata, RFC 8414
metadata, RFC 7591 registration, PKCE, RFC 8707 resource) is what Linear and
other vendors' hosted servers use, so building it once for own servers covers
them too.

## Goals

- In Connections, the Notion card offers **Sign in with Notion**: click,
  approve on Notion, back in the chat, and Notion's tools work for that
  person in the main chat, agents, cron and Discord.
- In **Add your own MCP server**, an address whose server asks for a sign-in
  (401 with OAuth metadata) shows **Sign in** instead of a token error, and
  the same flow runs.
- The login stays working: tokens are refreshed before they expire and once
  more on a 401.
- Everything PR #301 guarantees still holds: only the owner sees the tools,
  writes ask first, no address reaches our network, no secret is ever shown.

## Non-goals

- Replacing the paste-a-token Notion connector. It stays, as the fallback and
  for anyone already on it.
- Signing in to servers that do NOT support dynamic registration or the
  `none`/`client_secret_post` client methods (Atlassian Rovo needs an admin
  allowlist; it gets a clear sentence, not a half-working flow).
- The client-id-metadata-document option Notion also offers. Registration is
  enough and is what more servers support.
- OAuth for anything other than an own MCP server.

## Anti-goals

- Account grafting: a callback that attaches somebody's Notion to another
  person's account. State is bound to the person who started, single use,
  15 minutes.
- Any URL learned from a server's metadata (authorization server, token,
  registration, authorize endpoints) reaching our network.
- An access or refresh token in a response, a log line, an error or the card.
- A person who never signs in to anything seeing any change.

## Constraints

- Reuse, do not copy: `oauth_providers.STATES` (state minting and spending,
  PKCE helpers `new_verifier`/`challenge_for`), `host_guard.problem`,
  `crypto_utils`, `own_mcp_store`, `own_mcp_client`, the proxy overlay
  untouched.
- Public callbacks today live at `/connect/{provider}/callback`
  (`routes_connections.public_router`, line ~405). A route like
  `/connect/own-mcp/callback` would be read as provider "own-mcp" by that
  route. The new callback is registered BEFORE `connections` public router in
  `main.py`, or the existing handler dispatches `provider_id == "own-mcp"` to
  it. Builder's choice; a test pins that the real callback reaches it.
- `STATES` is in memory in one process: a tasks restart mid-sign-in loses it
  and the person sees "That sign-in expired. Start it again." Acceptable;
  the existing connectors behave the same.
- The box: 3.8 GB, nothing heavy added.

## Approaches

1. **Sign-in for any own server, Notion as the first button (picked).** The
   own-server row gains an OAuth form of its token; discovery, registration,
   PKCE, exchange and refresh are generic; the Notion card pre-fills
   `https://mcp.notion.com/mcp`. Linear and others come for free.
2. **A Notion-only built connector on the hosted server.** Repeats the
   per-person isolation, address checks and ask-first that own servers
   already have; Linear would need its own copy later.
3. **Register the Notion app (the card's original ask).** No code, but needs
   someone to set it up, and stays read only.

## The design

### 1. What is stored

Migration `076_own_mcp_oauth.sql`:

```sql
-- One registration per authorization server, shared by everybody who signs
-- in to it: registering per person would create thousands of clients.
CREATE TABLE IF NOT EXISTS tasks.own_mcp_clients (
    issuer            TEXT PRIMARY KEY,
    redirect_uri      TEXT NOT NULL,
    secrets_encrypted TEXT NOT NULL,   -- crypto_utils: {"client_id","client_secret"}
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE tasks.own_mcp_servers
    ADD COLUMN IF NOT EXISTS auth TEXT NOT NULL DEFAULT 'token',  -- 'token' | 'oauth'
    -- Its own flag, not check_ok: a good tools/list resets check_ok, and a
    -- login that has ended must stay ended until the person signs in again.
    ADD COLUMN IF NOT EXISTS login_ok BOOLEAN NOT NULL DEFAULT TRUE;
```

An OAuth server's `secrets_encrypted` holds `{"url", "token", "refresh_token",
"expires_at", "issuer", "token_endpoint", "resource"}`, where `token` is the
access token, so every existing reader of `{"url","token"}` keeps working.
A registration whose stored `redirect_uri` differs from today's (the domain
changed) is replaced, not reused.

### 2. Discovery (`own_mcp_oauth.py`, pure parts plus thin I/O)

Given the server URL:

1. POST `initialize` without a token. A 401 with `WWW-Authenticate`
   `resource_metadata="<url>"` names the metadata; else try
   `<origin>/.well-known/oauth-protected-resource<path>` then
   `<origin>/.well-known/oauth-protected-resource`.
2. Read `authorization_servers[0]`; fetch
   `<issuer>/.well-known/oauth-authorization-server`, falling back to
   `/.well-known/openid-configuration`. The document's `issuer` must equal
   the one asked for.
3. Required: `authorization_endpoint`, `token_endpoint`,
   `registration_endpoint`, `S256` in `code_challenge_methods_supported`, and
   `none` or `client_secret_post` in `token_endpoint_auth_methods_supported`.
   Missing any: "Your <label> server needs a sign-in this platform cannot do
   yet (it does not let apps register themselves)."

Every URL fetched or later used (metadata, issuer, token, registration) goes
through the https check and `host_guard.problem` first; the authorize URL
must be https too (the browser opens it, but it must not point at us).
Redirects are not followed. Each fetch 10 s, at most 64 KB read.

### 3. Registration

Look up `own_mcp_clients` by issuer. None (or a stale redirect): POST to the
registration endpoint `{"client_name": "AIUI", "redirect_uris": [REDIRECT],
"grant_types": ["authorization_code", "refresh_token"], "response_types":
["code"], "token_endpoint_auth_method": "none"}` (or `client_secret_post` when
`none` is not offered), and store the answer encrypted. Two people signing in
at once may both register: the second insert loses on the primary key and
reads the winner's row.

`REDIRECT` is `PUBLIC_BASE_URL + "/connect/own-mcp/callback"`.

### 4. The flow

User-facing (`current_user`), in `routes_own_mcp.py`:

- `POST /own-mcp/oauth/start` `{label, url}`: label and address checks as
  today, the 5-server limit, discovery, registration, then
  `STATES.mint(email, verifier=...)` plus a pending entry beside it
  (`{label, url, issuer, token_endpoint, resource, client}`), and returns
  `{"url": authorize_url}` with `response_type=code`, `client_id`,
  `redirect_uri`, `code_challenge` (S256), `state`, `resource` (the server
  URL, RFC 8707) and `scope` from `scopes_supported` when the protected
  resource lists any.
- `POST /own-mcp/servers/test` and `POST /own-mcp/servers`: when the server
  answers 401 with OAuth metadata and no token was given, they answer
  `{"ok": false, "sign_in": true, "problem": "Your <label> server asks you to
  sign in."}` (and 400 with the same sentence on save), so the card can show
  the button.

Public callback, `GET /connect/own-mcp/callback?code&state[&iss][&error]`:

1. `STATES.spend(state)`: unknown, spent or expired: "That sign-in expired.
   Start it again from Connections." The email comes ONLY from the state.
2. `error` present (the person pressed Cancel): "Sign-in was cancelled."
3. `iss` present and not the pending issuer: refuse.
4. Exchange at the token endpoint (`grant_type=authorization_code`, `code`,
   `redirect_uri`, `client_id`, `code_verifier`, `resource`; the client secret
   when registered with one), 15 s, no redirects, 64 KB.
5. `tools/list` with the access token, `own_mcp.snapshot`, then store the row
   with `auth='oauth'` (or replace the access and refresh token on an
   existing row for the same person and URL, so signing in again repairs
   rather than duplicates).
6. Answer the same small page the existing connect callbacks answer (posts
   the "connected" message to the opener, then closes), so "Connect, then
   carry on" in `integrations-ui.js` works unchanged.

### 5. Keeping it signed in

A new `own_mcp_login.py` owns this, because `own_mcp_client` takes a plain
`(url, token)` and never touches the database (builder check, 2026-11-27).
`own_mcp_store.secrets_of` returns the WHOLE decrypted dict (today it drops
every field but url and token), and a new `own_mcp_store.set_secrets(email,
server_id, values)` writes it back. `own_mcp_client` raises a `Refused`
subclass, `LoginNeeded`, on a 401, so the wrapper can tell it apart.
`own_mcp_login.list_tools(email, row)` and `own_mcp_login.call(email, row,
tool, arguments)` are what `routes_own_mcp` (refresh, own_call) and
`connection_sweep.sweep_own` call instead of the client; for a `token` row
they pass straight through. For an `oauth` row, before a call, if
`expires_at` is within 60 s, refresh first (`grant_type=refresh_token`,
`refresh_token`, `client_id`, `resource`); on a 401 from the server, refresh
once and retry once (a 401 is not a sign the tool ran). A new refresh token in
the answer replaces the old one (rotation). Refreshes are serialised per
server id with an `asyncio.Lock`, so two calls do not spend one refresh token
twice. A rotated token is saved before the call goes on, or the next refresh would
spend a dead one. A refresh that fails with `invalid_grant` sets
`login_ok=false` and every call answers "Your <label> login has ended. Sign in
again from Connections." The sweep refreshes too, so a quiet server's login
does not lapse unnoticed.

### 6. Connections

**Notion is reported by the server, so the page needs no second source**
(builder check: the chat's Connect button, "Connect, then carry on" and the
card all read `/api/tasks/connections`, which only knows
`tasks.user_connections`). In `routes_connections`:

- `_describe` reports `notion` as `connected: true, via: "mcp"` when the
  person has a `login_ok` own server whose host is `mcp.notion.com`, and
  `oauth_ready: true` whenever `OWN_MCP_OAUTH` is on, whatever
  `NOTION_CLIENT_ID` says.
- `GET /connections/notion/oauth/start`, when `NOTION_CLIENT_ID` is not set
  and `OWN_MCP_OAUTH` is on, answers the own-MCP authorize URL for label
  "Notion" and `https://mcp.notion.com/mcp`. With the client id set, it
  keeps today's REST sign-in.
- The own-MCP callback page posts the exact message the existing callback
  page posts (`{aiuiOauth: "notion", ok}` for a Notion sign-in), so the
  popup check and the carry-on in `integrations-ui.js` work as they are.

So the chat's Connect Notion button opens the sign-in directly, and after it
the request is answered with Notion, with no page change for that path.

- **Notion card**: its panel leads with **Sign in with Notion** (it can also
  write), opening the popup from `/own-mcp/oauth/start` with label "Notion"
  and `https://mcp.notion.com/mcp`; the paste-a-token form stays below as
  "Or use a Notion integration token (read only)". Once signed in, the card
  reads "Signed in" and the own-server card for it shows as usual.
- **Add your own MCP server**: on `sign_in: true`, the form shows **Sign in**
  beside Test; the token field is not needed.
- Card for an OAuth server: "Signed in" instead of a token, **Sign in again**
  when its login has ended.

### 7. The rest of the platform

- **Triage only** treats a person with a `login_ok` own server at
  `mcp.notion.com` as having Notion, through its own set
  (`_connected_providers(email) | own_notion(email)`), so they are not
  offered Connect again. `routes_agents._connected_providers` itself is NOT
  changed: the agent form, skills, Connect notices and `_can_do_facts` read
  it to mean "the built Notion connector works", and it does not for them.
- The Notion entry's `can` line keeps resting on the built tools (the triage
  test requires every name to be a `mytools` tool); its `cannot` line
  becomes "write or change pages, unless you sign in with Notion".
- **Jev**: nothing new; own servers are already in the gateway note.
- **Ask first**: unchanged. Whatever Notion marks `readOnlyHint` and reads by
  name runs without asking; everything else asks.

### 8. Kill switch

`OWN_MCP_OAUTH=0` on tasks hides the button and refuses `/oauth/start`; rows
already signed in keep working. Like the others: a PR and a deploy.

## Tests (statements, not names)

- State: a callback with someone else's state, a spent state, an expired one,
  and none at all each store nothing; the email is never read from the query.
- Discovery: http metadata, a metadata URL or token endpoint on a private
  address, an issuer that does not match, no registration endpoint, no S256:
  each a sentence, nothing registered.
- Registration reused across two people; a changed redirect replaces it; a
  race reads the winner.
- Exchange: the verifier and resource are sent; a token response echoed in an
  error never reaches the person; tokens stored encrypted, never returned.
- Refresh: before expiry, once on a 401, rotation kept, two calls share one
  refresh, `invalid_grant` ends the login with the sentence.
- The `/connect/own-mcp/callback` request reaches this handler, not the
  connections one.
- Test and Save on a 401-with-metadata server answer `sign_in: true`.
- Triage counts a Notion own server as connected; `_connected_providers`
  does not.
- `/api/tasks/connections` reports Notion connected via mcp, and its
  oauth/start answers the own-MCP URL when no Notion client id is set.
- A rotated refresh token is saved before the call continues; an ended
  login stays ended after a good tools/list.
- E2E with the company account: Sign in with Notion, then in the main chat
  "what pages do I have in Notion" (read) and "create a page called AIUI
  test" on an agent set to Ask (asks, then creates); Remove at the end.

## Left to the builder

- Callback routing: register before the connections public router, or
  dispatch inside it.
- Where the pending entry lives beside `STATES` (a dict keyed by state with
  the same TTL is enough).
- Exact copy on the cards, in the voice of the existing panels.

## Calls I made (for review)

- Generic sign-in, Notion first, over a Notion-only connector.
- One registration per authorization server, shared, not one per person.
- Notion's connected state comes from the server (`/api/tasks/connections`),
  so the chat's Connect button and carry-on need no page change.
- Only triage counts a Notion own server as "Notion"; the agent form and
  skills do not, because the built connector's tools still need its token.
- A separate `login_ok` flag for an ended login.
- The paste-a-token Notion connector stays as a fallback.
- Servers without self-registration get a sentence, not a half flow.
- A tasks restart mid-sign-in means "start again", as with the existing
  connectors.
