# Main chat: skills on new agents, build progress, the MCP tool list

Date: 2026-11-03. Asked for by Lukas on the 2026-10-31 call: Clarence should be
able to make agents with skills, build a site and see what tools exist, all
from the main chat, without knowing where the features live. Video (say it is
working, then hand over the link) is out of scope here; it is being handled
separately.

## 1. Skills on new agents

Today `/agents/make` writes name, role, access and instructions. An agent's
skills are `meta.skillIds`, a list of names from the catalogue in
`agent_skills/` (68 at the time of writing), and nothing on the make path sets
it, so an agent made from the chat has none.

- `create_agent` (open-webui-functions/agent_builder_tool.py) gains `skills`,
  a comma separated list of skill names.
- `MakeAgentIn` gains `skills: list[str] | None`.
- No skills passed: the service suggests up to `SUGGESTED_SKILLS` (3) with
  `agent_skills.search(role + instructions)`.
- Names not in the catalogue are dropped and never invented; the preview says
  which were dropped.
- The preview gains a `Skills:` line, and the skills are part of the proposal
  code, so changing them after the preview means a fresh preview.
- On create they are written as `meta.skillIds`, which the Agents page already
  reads.
- The live tool is the `public.tool` row `agent_builder`. It is updated from
  the repo file and checked by md5 afterwards.

## 2. Build progress in the main chat

`create_app` answers in seconds with "Building X now ... Watch it here:
<base>/tasks/static/preview.html?task=<uuid>". The build then runs for minutes
and the chat says nothing unless asked.

Chosen: the chat page watches the build. `integrations-ui.js` finds that link
in an assistant reply, shows one status line under it, polls
`GET /api/tasks/<uuid>` (the route the build watch page already polls, behind
the gateway's session auth), and when the build settles appends one assistant
message: built with the app link, failed with the reason, or waiting on a
question. Reopening a chat picks up a build in it that has not settled and has
no closing message yet. Written with `{history}` only, like every other write
the page makes, so a title Open WebUI generated is not reverted.

Rejected: the service writing into the chat when the build ends (the page's
next save replaces a history it did not know about), and holding the turn open
for the whole build (minutes of a locked chat, and a timeout).

Known limit: nothing is posted while the chat is closed; it catches up on
reopen.

## 3. The MCP tools, from the main chat

The proxy offers the chat `search_tools`, `describe_tools` and `call_tool`.
None lists everything, so "what tools do you have" is answered by a search
guess. Add `POST /meta/list_tools` to mcp-proxy: each server the caller may
use and its tool names, with the same per-person filtering `/servers` uses.
It appears to the assistant as one more proxy tool.

## Testing

Test first for each piece, red before green. Then live with the test account:
make an agent from the main chat and see its skills on the Agents page; start
one small build and see the closing message arrive; ask "what tools do you
have" and see Trello and GitHub named.

## Delivery

Three PRs on the fork, one per item. Deploy each only after it is approved.
