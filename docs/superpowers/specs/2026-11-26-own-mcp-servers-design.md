# Add your own MCP server

Date: 2026-11-26. Trello: tDLDwreQ (meeting 2026-11-25). Status: design, approved approach 2.

## Why

The 2026-11-25 meeting: people should be able to connect their own systems,
not only the apps we build connectors for. A person who runs an MCP server
(their own, or one a vendor hosts) pastes its address and a token, and its
tools work for them everywhere the platform runs tools: the main chat,
agents, cron jobs and Discord.

It adds to the built connectors and does not replace them. A built connector
knows which tools only read and Jev knows when to suggest it. A custom
server's tools are unknown to us, so the rules around them are stricter.

## Goals

- A person adds a server in Connections with a name, an address and an
  optional token, presses Test, sees the tools it offers, and saves it.
- Its tools are found the way a Trello or GitHub tool is found today: a
  request in their words reaches the right tool without naming the server.
- Works in all four places, because all four reach tools through the same
  gateway (mcp-proxy `/meta/search_tools`, `/meta/describe_tools`,
  `/meta/call_tool`, called by the tasks loop with `X-User-Email`).
- A tool asks before it runs unless it clearly only reads.

## Non-goals (this build)

- Signing in with OAuth to a vendor's hosted server (Notion, Linear). That
  is phase 2, below. Linear already works in phase 1 with a personal API key.
- The old SSE transport. Streamable HTTP only, which is what the current MCP
  spec and the hosted vendor servers use.
- Sharing a server with a team. One person, one server.
- Resources, prompts and sampling. Tools only.

## Anti-goals (a failure even if it works)

- A person's server address reaches our own network: a container name,
  localhost, a private range, a name that resolves to one, or a redirect to
  one.
- Anyone else sees a person's server, its tools, its token or its results.
- A tool that changes something runs without asking on an agent set to Ask,
  or at all on a read-only cron job.
- A token or address shows up in a log, an error, or a response.
- Adding the feature changes anything for a person who never adds a server.

## Constraints

- The card's must haves: private and local addresses refused, token stored
  encrypted like every other connection, unknown tools ask first, each
  person's server and tools visible only to them.
- It must go through our proxy. Open WebUI's Settings > Integrations runs
  from the browser, so it would not work in cron jobs, agents or Discord.
- mcp-proxy's `/meta/*` routes are public and are where the anonymous-caller
  hole was (2026-08-18, `access.py`). Every change there needs a test that a
  caller who is not the owner gets nothing.
- The box has 3.8 GB of RAM and mcp-proxy is capped at 1200M. Nothing here
  may load a second embedding model or hold large per-person state.
- One security check, one copy: reuse `host_guard`, `crypto_utils` and the
  gateway's identity. No second copy of any of them in mcp-proxy.

## Approaches

1. **One "Your servers" tool group.** mcp-proxy gets one new PUBLIC server
   whose two tools are "list my servers and their tools" and "run one". The
   tasks service holds the servers, tokens and calls. Smallest change and the
   proxy barely moves, but the model must think to look ("create an invoice
   in my billing system" never finds it), and every run asks first because
   the runner's name says nothing about what it runs.
2. **The person's tools become real tools, visible only to them (picked).**
   The tasks service holds the servers, tokens and calls, as in 1. mcp-proxy
   adds each caller's own tools to what THAT caller can search, describe and
   call, named after their server. Requests find them like any other tool,
   and read-only tools can run without asking. Costs a careful change to the
   proxy's three meta routes.
3. **mcp-proxy owns all of it.** Dropped: it would need a second copy of the
   token encryption and the address check inside the proxy, which has no
   Fernet key and no connections UI. `oauth_state.py` exists four times and
   keeping security copies in sync is the lesson not to repeat.

The user picked 2 on 2026-11-26.

## The design

### Who owns what

```
tasks (owns the person's servers)          mcp-proxy (routes, per caller)
---------------------------------          ------------------------------
tasks.own_mcp_servers   (rows, encrypted)  /meta/search_tools   + caller's own tools
own_mcp.py              (decisions, pure)  /meta/describe_tools + caller's own tools
routes_own_mcp.py       (add/test/remove,  /meta/call_tool      own-* -> tasks
                         list, call)
own_mcp_client.py       (MCP calls, per
                         person per server)
```

The proxy never sees a token or an address. It asks tasks "what are this
caller's own tools?" and forwards "run this one for this caller".

### 1. Adding a server (Connections panel)

A new card at the end of the Connections grid in
`mcp-servers/gdrive/integrations-ui.js`: **Add your own MCP server**. The
form has:

- **Name** (shown on the card, becomes the tool prefix): 1 to 40 characters.
- **Address**: `https://...` only. Plain `http` is refused, because the
  token travels in a header. This is its own check, run before
  `host_guard.problem`, which accepts `http` (`host_guard.py:119`) because
  n8n and Jira need it.
- **Token** (optional): sent as `Authorization: Bearer <token>`.

**Test** runs the whole check and shows the result without saving:

1. `host_guard.problem(address)` (scheme, no bare names, no private or local
   literals, DNS resolved and every address public).
2. MCP `initialize`, then `tools/list`, with the token, no redirects
   followed, 15 s timeout.
3. The answer lists how many tools there are, each tool's name, and which
   ones the server marks read-only.

**Save** runs the same check again (so a saved server was always checked),
then stores the row. Each saved server is its own card: the name, the host
only (never the full address, since some vendors put the key in the
URL), the tool count, when it was last checked, and **Refresh tools** and
**Remove**.

Limits: 5 servers per person, the first 40 tools of each server (the rest are
listed on the card as not used), a tool's description cut at 600 characters,
its input schema at 8 KB.

### 2. Storage

Migration `075_own_mcp_servers.sql`:

```sql
CREATE TABLE IF NOT EXISTS tasks.own_mcp_servers (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email             TEXT        NOT NULL,
    slug              TEXT        NOT NULL,   -- tool prefix, unique per person
    label             TEXT        NOT NULL,   -- what the person typed
    host              TEXT        NOT NULL,   -- shown on the card
    secrets_encrypted TEXT        NOT NULL,   -- crypto_utils: {"url","token"}
    tools             JSONB       NOT NULL DEFAULT '[]',
    check_ok          BOOLEAN     NOT NULL DEFAULT TRUE,
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (email, slug)
);
CREATE INDEX IF NOT EXISTS own_mcp_servers_email_idx
    ON tasks.own_mcp_servers (email);
```

The address is stored inside the encrypted blob with the token, not in its
own column. `tools` is the snapshot from the last check:
`[{"name", "description", "input_schema", "read_only"}]`.

A separate table rather than `tasks.user_connections`: that table is keyed by
a provider id from the built catalogue (`connections.provider`) and every
route that reads it assumes that, so a dynamic id would touch all of them.

### 3. Naming

A person's tool is called `own-<slug>_<tool>` in the catalogue, for example
`own-acme_create_invoice`.

- `slug`: the name lowercased, non `[a-z0-9]` dropped, cut at 20, unique per
  person (a second "Acme" becomes `acme2`).
- `<tool>`: the server's tool name with anything outside `[A-Za-z0-9_-]`
  replaced by `_`, and the whole catalogue name cut at 64. Two tools that
  collide after cleaning: the second is not used and the card says so.
- No server in `tenants.ALL_SERVERS` may have an id starting with `own-`
  (a test), so an own tool can never shadow or be shadowed by a built one.

Two people can both have `own-acme_create_invoice`. That is fine: every
lookup is by caller first.

### 4. tasks routes

All of them live in a new router, `routes_own_mcp.py`, under its own
prefix `/own-mcp`. NOT under `/connections/...`: `routes_connections`
already has `POST /{provider_id}` and `POST /{provider_id}/test`
(`routes_connections.py:1018,1045`), which would swallow
`/connections/own-mcp` as a provider named "own-mcp".

User-facing, through the api-gateway (`current_user`, the gateway injects
`X-User-Email` after stripping the client's):

- `GET    /own-mcp/servers`: the person's servers as cards (no secrets).
- `POST   /own-mcp/servers/test`: body `{label, url, token}`, the check
  above, nothing stored.
- `POST   /own-mcp/servers`: the same check, then store.
- `POST   /own-mcp/servers/{id}/refresh`: re-list tools, update snapshot.
- `DELETE /own-mcp/servers/{id}`: remove (owner only, else 404).

For mcp-proxy only, requiring BOTH `X-Internal-Secret` (equal to
`INTERNAL_CALLBACK_SECRET`, compared with `hmac.compare_digest`) and
`X-User-Email`:

- `GET  /own-mcp/tools`
- `POST /own-mcp/call`

Why the secret, when `/mytools/*` trusts `X-User-Email` alone: tasks shares
the backend network with about 30 containers (checked 2026-11-26), and
Open WebUI and pipelines run code admins paste in. Without the secret, any
of that could claim a person's email and reach that person's own outside
system with their token. The App Builder's coding agent is not a concern on
production (`AGENT_BACKEND=remote`: builds run on the build host, not in
the tasks container). The `/mytools/*` exposure of the same kind is
pre-existing and out of scope here.

This needs one compose line: `INTERNAL_CALLBACK_SECRET` added to
mcp-proxy's `environment` (it is already in `.env`, which tasks uses; `.env`
itself is not touched). mcp-proxy sends it on these two calls only.

What they return:

- `GET  /own-mcp/tools`: this person's own tools, each
  `{name, description, request_body, server_id: "own-<slug>",
  server_name, read_only}`. Close to a `TOOLS_CACHE` value but NOT one:
  no `original_path`, plus `read_only`. They are never put in
  `TOOLS_CACHE` (section 5).
- `POST /own-mcp/call`: body `{tool_name, arguments}`. Finds the row by
  (email, slug), re-checks https and `host_guard.problem` on the decrypted
  address, calls the tool, returns the result.

### 5. mcp-proxy: the caller's own tools

One new module, `mcp-proxy/own_tools.py`, so `main.py` changes by a few
lines per route:

- `async def for_caller(email) -> dict`: asks tasks `GET /own-mcp/tools`,
  caches the answer per email for 60 s, returns `{}` on any failure (an own
  server that cannot be listed must never break search for built tools).
  Bounded: at most 200 emails cached, oldest dropped.
- **search_tools**: after `require_identified`, the caller's own tools are
  ranked against the query with the fastembed model already loaded for the
  catalogue (embeddings cached by text hash, in memory, bounded), and
  merged into the results by score. If the model is unavailable, the
  keyword fallback ranks them the same way it ranks the rest. The merge
  happens BEFORE the early "No server access configured" return
  (`main.py:890-892`), or a person with only their own servers finds
  nothing.
- **describe_tools**: a name starting `own-` is answered from the caller's
  own tools only, before `TOOLS_CACHE` is consulted. Not there: "Tool not
  found", the same answer as any missing tool, so nobody can learn what
  someone else has.
- **call_tool**: a name starting `own-` is handled at the top of the route,
  right after `require_identified` and before the `TOOLS_CACHE` lookup
  (which reads `original_path` and would fail on an own tool). It must be
  in the caller's own tools (else 404 "not found"), and is forwarded to
  tasks `POST /own-mcp/call` with the caller's email and the secret.
- The turn hint (`agent_tools` HINT, which calls `/meta/search_tools` and
  then `/meta/describe_tools`) gets own tools for free.

**Who is calling.** Two kinds of caller reach `/meta/call_tool`:

- the tasks loop (main chat assistant, agents, cron, Discord), which
  already held any write for approval before calling. From this build it
  sends `X-Internal-Secret` on its `/meta/*` calls (`agent_tools._post_json`).
- a model in Open WebUI calling the proxy directly as a tool server
  (`docker-compose.unified.yml:1079`, session auth), for someone who picked
  a model other than Auto. Nothing on that path can ask first.

For an `own-*` tool that is not read-only (section 7), the proxy runs it
only for the first kind. The second gets: "This tool can change things in
your Acme server, so I only run it where I can ask you first. Switch to
Auto (Free) and ask again." Read-only own tools run for both. Built tools
are unchanged.

`OWN_MCP=0` switches the overlay off: search, describe and call behave
exactly as today. It is an environment switch like `CRON_TOOL_PICK` and
`MAIN_CHAT_TRIAGE`, so flipping it is a PR and a deploy (minutes, through
the Deploy job); never by editing compose on the box. Reverting the PR is
the same speed. A single bad server is handled faster by its owner's
Remove button.

### 6. Calling a person's server

`own_mcp_client.py` in tasks. It shares the protocol code with
`mcp-proxy/mcp_http_client.py` in spirit but not the session cache, which
is keyed per URL there and would hand one person's session to another:

- Session cache keyed by `(email, server id)`, TTL 1 h, re-initialize once on
  401/404/409, bounded in size.
- `httpx` with `follow_redirects=False`. A redirect is answered as "Your
  server tried to send us somewhere else, so I did not follow it."
- `host_guard.problem` before EVERY call, not only at the connect, because a
  name that answered public at the connect can be repointed later
  (the same rule `connections.types_a_url` follows).
- 20 s timeout. The result's `content` text parts are joined and cut at
  20,000 characters; non-text parts are named, not passed.
- Failures come back as a sentence with HTTP 200, the `mytools` rule: "Your
  Acme server did not answer in 20 seconds." Never the address, never the
  token, never the server's raw error body past 160 characters
  (`mytools._vendor_said` is the pattern).
- Every refusal and failure is logged with the server id and the person,
  never the address or token.

### 7. Asking first

An own tool counts as a read only when BOTH:

- the server marked it `annotations.readOnlyHint: true` at the last check,
  and
- `agent_tools.is_write_tool(<tool>)` says read (a write verb in the name
  wins, as everywhere else).

Everything else is a write. That means: an agent on Ask asks, a read-only
cron job refuses it with the existing sentence, an agent on "all" with a full
cron job runs it. No new approval path: `agent_runner` already holds a call
when `is_write_call(name, params)` says write.

`is_write_call` judges the inner `tool_name` of a `call_tool` and has no
caller. For `own-*` names it needs one, because two people's servers can
mark the same name differently. Add an optional `email` argument and an
in-process lookup into the snapshot (`own_mcp.read_only(email, name)`),
filled whenever tasks lists that person's tools and on save/refresh. Unknown
(not in the cache) is a write.

The server's own marking is trusted only for the server's owner. A server
that lies about a tool being read-only can only hurt its own owner's data,
through its owner's agents.

### 8. Jev and the main chat

On Auto, the assistant only runs when Jev picks a tool group, and the
gateway's note (`agent_jev.TOOL_NOTES["server:mcp-proxy"]`) lists the built
apps. For a person with own servers, the note handed to `pick_tools` for
that person adds: "and their own servers: Acme (create_invoice,
list_customers, ...)", up to 8 tool names per server. Without this, "create
an invoice in Acme" goes to the free model, which cannot run anything.

The note is unchanged, byte for byte, for anyone without own servers, so
the calibrated cut (`PURPOSE_TOOLS`, `agent_jev.py:716-764`) still holds for
them. For people with own servers the cut is re-measured with
`scripts/jev_checks_calibrate.py` as part of this build, on: requests that
need an own tool ("create an invoice in Acme"), requests that need a built
app with the longer note in place ("what's on my Trello board"), and
ordinary questions that need nothing ("what is 15% of 80"). If the cut
moves, it moves only for the longer note.

Cron jobs always keep the gateway (`SCHEDULE_KEEPS`), so they need nothing.

### 9. Health

Refresh, and the existing connection sweep's schedule, re-list each server.
Three failed checks in a row set `check_ok = false`; the card reads "Not
answering since <time>" and the tools stay listed (a server down for an hour
should not make agents forget it exists), each call answering the sentence
from section 6.

## Phase 2 (not this build): sign in to a vendor's hosted server

Checked 2026-11-26:

- **Notion** (`mcp.notion.com/mcp`): OAuth with dynamic client registration,
  so "Sign in with Notion" needs no Notion app registration. This could
  unblock o9vFFu0S.
- **Linear** (`mcp.linear.app/mcp`): dynamic registration, and it also
  accepts a personal API key as the bearer token, so it works in phase 1.
- **Atlassian** (Rovo MCP): dynamic registration only for client domains the
  customer's Atlassian admin allowlists. Does not cleanly unblock Jira
  (HY6URSeJ).

Phase 2 adds an OAuth path to the same row (register, PKCE, `oauth_state`
signed state, refresh), starting with Notion. Its own design when we get
there.

## Tests (each one a statement, not a name in the source)

Isolation, the most important group:

- Person B searching with A's exact tool words gets none of A's tools.
- B describing or calling `own-acme_create_invoice` (A's) gets "not found",
  identical to a tool that does not exist.
- An unidentified caller is refused before the overlay is consulted.
- `DELETE` and `refresh` on someone else's id answer 404.

Addresses: `http://`, `localhost`, `127.0.0.1`, `10.x`, `169.254.169.254`,
a bare name (`mcp-proxy`), `localtest.me` (public name, private answer), and
a public server answering 302 to a private address: all refused, and the
refusal never repeats the address.

Secrets: no route returns the token or full address; a failure from a server
that echoes the token in its error body does not pass it on.

Callers: `/own-mcp/tools` and `/own-mcp/call` refuse a request without the
right `X-Internal-Secret`, even with a valid `X-User-Email`. A write own
tool called on `/meta/call_tool` without the secret (the direct Open WebUI
path) is refused with the "switch to Auto" sentence and never reaches tasks;
a read-only one runs. Built tools on that path answer exactly as today.

Behaviour: own tools appear in search ranked with built ones; read-only rule
(readOnlyHint plus verb) holds the right calls; the `OWN_MCP=0` switch
restores today's answers byte for byte; a tasks outage leaves built-tool
search unchanged; 5-server and 40-tool limits.

End to end on the server: a small public test MCP server (one read tool, one
write tool), added from the Connections panel with a company account, used
from the main chat, from an agent on Ask (the write asks), and from a
read-only cron job (the write is refused).

## Left to the builder

- The exact card copy in the Connections panel, matching the existing cards.
- Where the embedding cache for own tools sits inside `own_tools.py`, and its
  bound.
- Whether `own_mcp_client.py` imports protocol helpers from a shared copy or
  carries its own small parser (no shared package between the two services
  today; keep it small either way).
- The exact wording of the sentences the person and the model see, in the
  voice of the existing `mytools` refusals.

## Calls I made (for review)

- Own tools refused on the direct Open WebUI path unless read-only
  (section 5), so "asks before it runs" stays true everywhere.
- An internal secret on the two proxy-facing routes (section 4).
- A separate table, not `tasks.user_connections` (section 2).
- Address and token encrypted together; the card shows only the host.
- Limits: 5 servers, 40 tools, 600-character descriptions, 8 KB schemas.
- Streamable HTTP only; https only.
- The kill switch is an environment switch, like the others.
- Jev's note changes only for people with own servers, re-measured for them.
