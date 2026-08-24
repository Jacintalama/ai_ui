# AI Agents: users build their own assistants

Date: 2026-08-21
Status: design, awaiting review
Sidebar placeholder already shipped in `6138249f9`

## What we are building

A page where any signed-in user names an assistant, writes what it should do in
their own words, chooses whether it can reach the apps they connected, and saves
it. Their agents are listed there to edit or delete.

An agent is private to whoever made it. A small number of platform agents,
created by an admin, are visible to everyone and can be copied but not edited.

## Why it is small

Almost none of this needs building. Open WebUI already stores exactly what an
agent is:

| An agent has | Where it lives |
|---|---|
| instructions | `model.params.system` |
| tools | `model.meta.toolIds` |
| an owner | `model.user_id` |
| privacy | absence of a row in `access_grant` |

And `POST /api/v1/models/create` already creates one **as the calling user**,
gated on a single `workspace.models` permission that is separate from knowledge,
prompts and tools.

So an agent is a model row. There is no new table, and nothing to drift.

Because an agent is a real model, it appears in the model picker and therefore
works in chat, in Discord, in Telegram and on a schedule with no further work.
That is the whole reason for building on Open WebUI's model rather than
inventing an agent runtime: the alternative is re-integrating every one of those
surfaces by hand.

## Architecture: no new backend

The page runs in the browser with the user's own session and calls Open WebUI's
model API directly. No tasks endpoints, no service-to-service authentication,
and no path by which the page can act as anyone other than the person using it,
because it never holds more than their own token.

```
browser (user's session)
   |
   |  GET  /api/v1/models          list, filtered to what they may see
   |  POST /api/v1/models/create   create
   |  POST /api/v1/models/model/update
   |  POST /api/v1/models/model/toggle
   v
Open WebUI  ->  model + access_grant tables
```

The only server-side change is setting `user.permissions.workspace.models` to
true.

This is deliberately unlike the Connections dialog, which needed a tasks backend
because it holds encrypted vendor credentials. Agents hold no secrets, so the
extra hop would buy nothing and cost a second source of truth.

## The prerequisite, and it is the risky part

Private agents require the visibility filter, and it is currently disabled
platform-wide by `BYPASS_MODEL_ACCESS_CONTROL=true` in
`docker-compose.unified.yml`. It cannot simply be turned off:

`utils/models.py::get_filtered_models` says a model with no database row is
**admin-only**. Only 7 of the 130 models anyone sees have a row; the other 123
are discovered live from the OpenAI and OpenRouter connections and from pipes
(Auto, Fusion). Flipping the switch today would take every non-admin from 130
models to 7, with nothing logged.

So, as its own commit, deployed and verified before any agent code exists:

1. Give all 130 models a row and a wildcard read grant
   (`principal_type='user'`, `principal_id='*'`, `permission='read'`, the form
   `get_accessible_resource_ids` matches on and the one the existing channel
   grants use). The 7 that already had rows were granted on 2026-08-21.
2. Record what every user sees now, per user, via a signed-in browser probe.
3. Set `BYPASS_MODEL_ACCESS_CONTROL=false` and rebuild.
4. Re-run the probe. Every user must see the same count as before.
5. If not, set it back to true and rebuild. Recovery is one line and a restart.

Nothing about agents ships until step 4 passes.

## The form

- **Name.** Required, 1 to 60 characters.
- **Instructions.** Required, up to 4000 characters, a plain textarea. What the
  user types is what gets stored in `params.system`. No generation, no rewriting.
- **Base model.** A select of the models they can see, defaulting to the first
  entry of the `ui.default_models` config value, so nobody has to have an
  opinion. If that value is empty, default to the first model the API returns.
- **Use my connected apps.** One switch. On, it adds `server:mcp-proxy` to
  `toolIds`, which gives the agent every tool that user can reach. There is no
  per-tool granularity through that path: mcp-proxy exposes three meta-tools
  (search, describe, call) rather than individual ones, so it is all or nothing.
- **Native tools.** A checkbox each for Gmail, Calendar, Drive, Documents,
  Excel, Dashboard and Memory, which are individually selectable tool ids.

The id is generated as `agent-<slug>-<4 hex>`. It is a primary key shared with
every other model, and two people will both make a "Research Assistant".

## The list

Agents the user owns, each with edit, delete and a link that opens a chat with
it. Platform agents appear in a separate, read-only group with **duplicate to my
own**, which copies the instructions into a new agent they own.

Telling the two apart needs no flag, and this is worth stating because it is not
obvious. Once the visibility filter is on, another user's private agent is not
returned at all. So any agent the API returns that the user does not own is, by
construction, one that carries a wildcard grant: a platform agent. Owner id is
the only test the page needs.

Copying rather than editing is the point: a platform agent improves centrally
for everybody, and a template that gets forked stops improving.

**Verified on production, 2026-08-24.** Two real accounts: the owner created an
agent with the exact body the form sends, which carries no `access_control`
key. The owner then saw 131 models and the other user saw 130, without the
agent. So an agent is private with nothing extra sent.

Two details worth knowing before writing the form. The row stores
`access_control` as `null`, and on older Open WebUI versions null meant
*public*; on this version grants live in the `access_grant` table and no row
means private. And `user.permissions.sharing.models` is false, so the platform
itself refuses to let a non-admin share a model. Privacy does not depend on our
page choosing not to offer it.

## Failure and limits

- **Permission not yet granted.** Say "agents are not switched on for your
  account" rather than surfacing a raw 401.
- **Id collision.** Retry once with a fresh suffix.
- **Instructions too long.** Refused in the form with the count, not by the API
  after a round trip.
- **25 agents per user.** Every agent lands in a model picker; an unbounded list
  is how a picker becomes unusable. Enforced in the page only, and therefore
  advisory: the API is Open WebUI's own and will not enforce it. That is
  accepted, because the cap exists to stop an enthusiastic user cluttering their
  own picker, not to stop an attacker.
- **A failed save never clears the form.** The user typed that; losing it to a
  network blip is the worst outcome on this page.

## Testing

Browser tests in `tests/browser/`, beside the existing cron and sidebar ones:

- an empty name or empty instructions is refused before any request
- the connected-apps switch produces exactly `server:mcp-proxy` in `toolIds`
- each native checkbox adds and removes its own id and no other
- the list shows only agents the user owns, and platform agents in their own
  group
- duplicate copies the instructions into a new agent rather than editing the
  original
- over-long instructions are refused in the form
- a failed save leaves the typed instructions in place

And, during verification rather than in CI, a real create-and-delete round trip
against the live API as a signed-in user. Every browser test here stubs the API,
and a stubbed API is exactly what hid the broken thumbnail path for a whole
deploy: it answered whatever was asked of it.

## Deliberately not in this spec

- **Generating instructions from a description.** Decided against: the user
  writes their own.
- **Per-tool selection.** Needs mcp-proxy to filter its meta-tools per agent,
  which does not exist today.
- **Bring your own API key.** Open WebUI's Direct Connections (`direct.enable`)
  would do it as a config change, but with nine people on one team where the
  platform already pays for the keys it solves no live problem, and I have not
  verified whether that key is encrypted at rest.
- **Knowledge attached to an agent.** `workspace.knowledge` is a separate
  permission and a separate feature. Later, if asked for.

## Order of work

1. Model grants and the bypass flip, verified per user. Revert if it fails.
2. `workspace.models` permission on.
3. The Agents page: form, list, edit, delete.
4. Two or three platform agents, wildcard-granted.
