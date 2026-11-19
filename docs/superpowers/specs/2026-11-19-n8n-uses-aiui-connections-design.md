# n8n uses AIUI connections, and GitHub can review a pull request

Date: 2026-11-19. Status: design, awaiting approval. Approach A and building G3 approved by the user 2026-11-19.

## Why

At stand-up on 2026-11-18 Lukas said what he wants as "the end result": a
person's n8n workflows should use the apps that person has already connected
in AIUI (the green connections: Trello, Airtable, GitHub, Google and the
rest) without connecting them again inside n8n. His example: "every morning
go to Google Sheet, and if there is a PR on GitHub, approve it". He said it
could be done in n8n or as an AIUI skill, "whichever way you prefer".

Two things stop that today:

1. n8n has no way to use an AIUI connection for one fixed step. It can run
   a whole agent (`POST /api/tasks/agents/run` with an `iok_` key, since
   2026-10-27), but that is a chat turn: slower, worded differently each
   time, and set up by hand. When AIUI builds a workflow for someone it
   never adds such a step.
2. The GitHub connection cannot approve or review a pull request. It can
   list, read and comment on one, and open one, but not review it.

## Goals

- **G1.** One AIUI route a workflow calls to run ONE tool with the person's
  own connection: `POST /api/tasks/tools/run`, `Authorization: Bearer iok_...`,
  body `{"app": "trello", "tool": "create_card", "args": {...}}`. The answer
  is the tool's own result, the same JSON the chat sees.
- **G2.** When AIUI builds or changes an n8n workflow for someone, it can put
  such a step in for them. The person does not make a key or paste anything:
  AIUI makes the key, stores it in their n8n as a credential, and writes the
  step against that credential.
- **G3.** GitHub gets `review_pull_request`: approve, request changes, or
  comment, on a pull request in a repository the person can reach.
- **G4.** Lukas's example works end to end: a workflow on a morning schedule
  that reads a sheet through AIUI (Google Drive), lists open pull requests
  through AIUI (GitHub), and approves one through AIUI (GitHub).

## Non-goals

- **A separate n8n server per person** (Lukas: "the next step"). Needs a
  decision on where they run and who pays; the AIUI box has 3.8 GB and each
  n8n needs a few hundred MB. Not in this work.
- **Updating the n8n server** from 2.10.3. Ralph's, on Hostinger.
- **Copying vendor credentials into n8n** (approach B, rejected below).
- **New n8n built-in nodes.** The AIUI step is an ordinary `httpRequest` node.
- **A screen for this.** Keys stay on the Agents page under Automation; the
  auto-made key appears there like any other and can be revoked there.

## Anti-goals (would make this a failure even if it works)

- A vendor credential (Trello token, GitHub token, Google refresh token)
  leaves AIUI. The existing rule (`test_a_credential_only_goes_to_its_own_vendor`)
  stands: the only secret that goes to n8n is an AIUI key, which only AIUI
  accepts and the person can revoke in one place.
- A key made to run agents silently gains the power to run any tool.
  Existing keys keep exactly what they could do.
- The route becomes a way to reach this box's own internals or another
  person's accounts. It runs only tools in the catalogue, only as the key's
  owner.
- A workflow step's failure looks like success. A tool that refuses or
  fails answers non-2xx with the tool's own message, so n8n marks the
  execution failed.

## Approaches

- **A. AIUI does the action; n8n only asks (picked by the user, 2026-11-19).**
  n8n calls `tools/run` with an AIUI key; AIUI runs the tool with the
  credential it already holds. Keys stay in one place and revoking a
  connection in AIUI stops every workflow using it. Cost: each step is an
  HTTP call through AIUI rather than n8n's own vendor node.
- **B. Copy the person's vendor credentials into n8n.** Each connection
  becomes an n8n credential and workflows use n8n's built-in nodes. Most
  native in n8n, but every key lives in a second place, today a server we do
  not run, and revoking in AIUI would not stop the copy. Rejected.
- **C. Skills only.** Build Lukas's example as an AIUI skill on a schedule,
  no n8n involved. Already nearly possible once G3 lands, but does not give
  n8n the connections, which is what Lukas called the end result. G3 serves
  this path too, so it is not lost.

## Design

### 1. Keys get a scope (migration 070)

`tasks.automation_key` gains `scopes TEXT[] NOT NULL DEFAULT '{agents}'`.
Every existing key is `{agents}`: it can run agents and nothing else.
`email_for` (used only by `routes_automation`) requires `agents`, so a
tools-only key on `/agents/run` is a 401 like an unknown key.
`tools` is the new scope. `automation_keys.create(email, label, scopes=...)`
takes it; `email_for(key)` becomes `owner_for(key) -> (email, scopes)` (keep
`email_for` as a thin wrapper so `routes_automation` and `routes_automations`
do not change). The Agents page keeps making `{agents}` keys; a key with
`tools` is only made by the link step (section 4). The panel lists the scope
next to each key so a person can see what a key can do.

### 1b. What a `tools` key may run (decided by the user, 2026-11-19)

Nobody watches a workflow run to say yes, so a `tools` key does not get the
whole catalogue:

- **Read tools: always.** Whether a tool reads or writes uses the same
  classification the chat uses to decide what asks first (the builder finds
  it in `agent_tools` / `mytools` and reuses it, never a second list).
- **A write tool: only once approved.** `automation_key` also gains
  `allowed_writes TEXT[] NOT NULL DEFAULT '{}'`, entries `"app.tool"`. When
  AIUI's `create_workflow` or `update_workflow` succeeds (a write the person
  already approved in the chat), every AIUI step in it that names a write
  tool is added to the person's AIUI key. Approving the workflow is approving
  its steps.
- **Never:** any `n8n` tool and `link_aiui`, whatever the list says, so a
  key in n8n cannot change n8n or mint more keys.
- A write not on the list answers 403: "This step was not approved in AIUI.
  Ask AIUI to add it to the workflow, and it will ask you first."

### 2. The route: `POST /api/tasks/tools/run`

New module `routes_tool_run.py`, mounted beside `routes_automation`.

```
POST /api/tasks/tools/run
Authorization: Bearer iok_...
{"app": "github", "tool": "review_pull_request",
 "args": {"owner": "x", "repo": "y", "pull_number": 7, "event": "APPROVE"}}
```

- 401: no key, revoked key, or not an `iok_` key. 403: the key has no
  `tools` scope (message says to link n8n again from the chat).
- 404: unknown app or tool; the body lists the tools that app has, so a
  wrong name is fixable from the n8n execution log.
- The person has not connected the app: 409 with the same sentence the chat
  gives ("You have not connected your Trello account yet..."). `_call`
  reports this through the same `_err` as every failure, so the route asks
  `mytools._secrets_for` first to tell the two apart.
- Runs through the same function the chat uses: `mytools._call(provider,
  tool, email, args)` for every app in `mytools.PROVIDER_TOOLS`. Same
  prepare steps, same host guard, same result shape. A result that
  `mytools._err` produced answers 422 with that message; anything else 200.
- **Google apps** (Lukas's sheet): Drive, Gmail and Calendar are separate
  services, reached the way `email_poller` reaches Gmail: POST
  `<SERVICE_URL>/<tool>` with `X-User-Email: <owner>`. Only an allowlist,
  read tools only in this work: `gdrive_search_files`, `gdrive_list_files`,
  `gdrive_read_file` (a Sheet comes back as CSV), `gmail_search_emails`,
  `gmail_read_email` and `calendar_list_events` (names checked against the
  services 2026-11-19). Google writes are a later step.
- Concurrency: the same semaphore as `/agents/run` (`AUTOMATION_CONCURRENCY`,
  2), so a workflow looping over 500 rows queues instead of flooding.
- `last_used_at` is touched like `/agents/run` does.
- Each run is logged (`logger.info` with email hash, app, tool, status) but
  arguments and results are NOT logged; they can be mail and file content.
- Through the gateway: no change. Everything under `/api/tasks` reaches
  tasks with `Authorization` untouched; an `iok_` key fails the session
  check, so `X-User-Email` arrives empty, and unauthenticated calls are
  capped at 1000 a minute per IP (`api-gateway/main.py:515`).

### 3. GitHub `review_pull_request`

In `mytools.GITHUB_TOOLS`:

```
POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews
args: owner, repo, pull_number (required),
      event: APPROVE | REQUEST_CHANGES | COMMENT (required),
      body (required for REQUEST_CHANGES and COMMENT, optional for APPROVE)
```

- `_github_prepare` refuses, before the call, `REQUEST_CHANGES` or
  `COMMENT` with no body (GitHub answers 422 otherwise), and an `event` not
  in the three.
- GitHub forbids approving or requesting changes on your own pull request
  (422 "Can not approve your own pull request"). That message is turned into
  a sentence the person understands: "GitHub does not let you approve your
  own pull request. Someone else has to review it." Checked from the 422
  body, not guessed in advance (no extra read call).
- It is a write, so in the chat it asks first like every write
  (`agent_tools` verbs already include "approve"; the builder checks that
  `review_pull_request` is classed as a write).
- `app_triage.APPS["github"]`: `can` gains "list and read pull requests,
  and approve, review or comment on one"; `tools` gains
  `review_pull_request` (and the existing PR tools it now names), so
  `tests/test_triage_recommends_apps.py` keeps every `can` line resting on a
  real tool.

### 4. Linking AIUI into the person's n8n

A new n8n tool, `link_aiui`, no arguments. It cannot be a composite
(`Tool.run` only gets a GET function and the args, and this must POST and
know the email), so it gets its own handler beside `_call`, dispatched by
name the way composites are:

1. Make a key for the person with scope `{tools}`, label
   "n8n (made by AIUI)".
2. Create an n8n credential on the person's own n8n (`POST /api/v1/credentials`,
   type `httpHeaderAuth`, name "AIUI", data `{name: "Authorization",
   value: "Bearer iok_..."}`), using the n8n connection they already have.
   This sends an AIUI key to the n8n the person connected, which is the
   point of it; no vendor credential goes anywhere.
3. Remember the credential id on our side, in the person's n8n connection
   row's metadata (or a one-column table if the row has no metadata; the
   builder picks), so later builds reuse it rather than minting a key per
   workflow.
4. If step 2 fails, revoke the key made in step 1. No orphan keys.
5. Return the credential id and name.

Asking first: it is a write (makes a key and a credential), so it asks like
any other.

**Who can see the credential (builder's call, 2026-11-19).** n8n creates a
credential under the n8n user whose API key made it, and keeps it private to
that user unless shared. Each AIUI person connects n8n with their own API
key, so their AIUI credential is theirs alone even on a shared server. Reuse
is by the id remembered for that AIUI person, never by name, so two people
on one server cannot pick up each other's. Two people who share one n8n
account or API key share everything on it already; the PR says so.

**If the n8n key may not create credentials (builder's call).** `link_aiui`
revokes the key it made and stops with a sentence saying which n8n
permission is missing. It never shows the AIUI key in the chat.

**Reuse.** If an AIUI credential id is remembered, `link_aiui` returns it
without making anything. If the person deleted it in n8n, a workflow using it
fails in n8n with n8n's own "credential not found"; asking AIUI to "link
again" makes a new one (an argument `again: true` forces it and revokes the
old key).

### 5. The AIUI step in a built workflow

`n8n_nodes` gains one shape, `aiui_tool`: an `n8n-nodes-base.httpRequest`
node at the typeVersion the live survey found (4.2), method POST, URL
`<PUBLIC_BASE>/api/tasks/tools/run`, `authentication: genericCredentialType`,
`genericAuthType: httpHeaderAuth`, `credentials: {httpHeaderAuth: {id, name:
"AIUI"}}`, JSON body `{"app": ..., "tool": ..., "args": ...}`. Its summary
tells the model to call `link_aiui` first when it has no AIUI credential id
and to use this node for any app the person has connected in AIUI rather than
n8n's own vendor nodes.

`_n8n_check` gains one refusal, in the existing style (the refusal carries the
right shape): an `httpRequest` node whose URL is `tools/run` but which names
no credential, since n8n would accept it and fail on every run.

`PUBLIC_BASE` comes from an env var (`AIUI_PUBLIC_URL`, default
`https://ai-ui.coolestdomain.win`), never from the request, so a model cannot
point a step somewhere else by changing the host.

### 6. What the person sees

"Every morning at 8, read my Leads sheet and approve any open PR on
jacint/ai_ui that has 'ready' in the title":

1. AIUI asks "Link AIUI to your n8n?" (first time only), they say yes.
2. AIUI asks to create the workflow: Schedule 8:00, AIUI step (Drive read),
   AIUI step (GitHub list PRs), IF, AIUI step (GitHub review APPROVE).
3. The workflow appears in their n8n, inactive, as built workflows already
   are; switching it on is the existing `activate_workflow`.

## Constraints

- Server has 3.8 GB RAM: no new service, no new container.
- Every external call has try/except and a timeout (`mytools._call` already
  does; the Google path and the n8n credential call must too).
- Merging is deploying. The unit and browser tiers must stay green.
- n8n is Ralph's lane (`n8n_nodes.py`, `_n8n_prepare`, `_n8n_check` were all
  his on 2026-11-17 to 19). Section 5 adds to his catalogue; tell him in the
  PR and keep his refusal style.

## Testing

- Unit: a read runs; an unapproved write is 403; it runs after a built
  workflow names it; an `n8n` tool is 403 even if listed; scope gating (an `{agents}` key gets 403 on tools/run, a `{tools}`
  key gets 403 on agents/run unless it also has `agents`); unknown app/tool
  404 lists tools; not connected 409; `_err` result 422; Google allowlist
  refuses a write tool; `review_pull_request` prepare refusals and the
  own-PR 422 translation; `link_aiui` revokes its key when n8n refuses;
  `aiui_tool` shape passes `_n8n_check`, a credential-less one is refused.
- DB tier (container): migration 070 applies and existing keys read
  `{agents}`.
- Live, after deploy: on Ralph's n8n (the only connected one, with his OK)
  or ours, link, build a two-step workflow (manual trigger, AIUI step
  `github.list_my_repos`), run it once, see the repos in the execution, then
  delete the workflow, the credential and revoke the key.

## Left to the builder

- Where the n8n credential id is remembered (connection metadata vs table).
- Response timeout for a slow tool (match `/agents/run`'s).
