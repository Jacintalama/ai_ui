# Open App Builder, Video Generation, Cron Jobs and Graph to non-admin users

Date: 2026-08-11
Status: Approved (Jacint, 2026-08-11). Root cause proven before writing this —
see Evidence.

Origin: Jacint, 2026-08-11 — regular users cannot reach App Builder, Video
Generation, Cron Jobs or the Graph. The reported cause was "the access of this
is admin". That turned out to be wrong in an important way.

## What is actually true

**The backends are not the gate.** Every endpoint behind all four features
already answers a regular user. Measured against the live server by calling
`tasks:8210` with `X-User-Email` set and `X-User-Admin: false`:

```
                    non-admin   admin
App Builder page       200       200
App Builder data       200       200
Video Gen page         200       200
Video Gen data         200       200
Cron Jobs page         200       200
Cron Jobs data         200       200
Graph page             200       200
Graph data             200       200
```

`routes_knowledge_graph.py`, `routes_schedules.py` and `routes_aiuibuilder.py`
contain **zero** `current_admin` dependencies; the single hit in
`routes_video.py` is a docstring.

**The gate is the sidebar menu, via a chain of three facts:**

1. Our nav injector anchors on exactly one element —
   `task-panel.js:1351`: `document.querySelector('a[href="/workspace"]')`.
2. Open WebUI v0.11.0 renders that link only for admins or users holding at
   least one workspace permission. From upstream
   `src/lib/components/layout/Sidebar.svelte`, `isMenuItemVisible('workspace')`:

   ```
   $user?.role === 'admin'
   || permissions.workspace.models
   || permissions.workspace.knowledge
   || permissions.workspace.prompts
   || permissions.workspace.tools
   || permissions.workspace.skills
   ```

3. Our database sets **all five to `false`** for non-admins (`config` table,
   key `user.permissions`).

So a regular user has no Workspace link, the injector finds no anchor, and
**none of the four entries are injected** — even though three of them already
carry `allUsers: true`. The flags are correct; the code returns before reading
them.

### Two independent bugs

| | Effect |
|---|---|
| **A** — injector depends on a link non-admins never see | hides all four |
| **B** — Cron Jobs entry has no `allUsers: true` | hides Cron Jobs even after A |

Both must be fixed. Fixing only A leaves Cron Jobs admin-only; fixing only B
changes nothing at all.

**No VPS drift:** `task-panel.js` is byte-identical across repo, server and the
running container (`ee515c14a0d75e237425dbc826c66869`, CRLF-normalized).

**Blast radius:** 4 non-admin users (`alamajacint@`, `github@test.com`,
`ivandermuega@`, `kimcalicoy24@`). They own **zero** App Builder projects, which
is consistent with never having been able to reach the feature.

## Changes

### Part 1 — anchor chain (unblocks all four)

Replace the single-selector lookup with an ordered chain, first match wins:

```
1. a[href="/workspace"]   admins — unchanged position, under Workspace
2. a[href="/notes"]       non-admins — permissions.features.notes is true
3. a[href="/calendar"]    permissions.features.calendar is true today
4. first sidebar nav link last resort
```

Insertion, ordering and the per-entry `data-` dedupe are untouched, so SPA
re-renders still cannot double-inject. **The admin experience is byte-identical**
— same anchor, same position.

Rejected alternatives:

- **Grant a workspace permission.** One config toggle, no code, but it exposes
  Open WebUI's Models / Knowledge / Prompts / Tools pages to every user — a
  product change nobody asked for — and leaves the single point of failure in
  place, so the next permission tweak or upstream change breaks it again.
- **Inject a standalone nav section.** Fully independent of upstream, but far
  more invasive to a SPA's DOM and the most likely to break visually on the next
  Open WebUI upgrade.

### Part 2 — Cron Jobs for everyone

Add `allUsers: true` to the Cron Jobs entry in `NAV_ENTRIES`.

### Part 3 — a per-user cap on schedules (new, and required by Part 2)

Cron Jobs is not like the other three: **each schedule spawns a Claude Code
agent run.** `create_schedule` currently validates only that the cron expression
parses and that `kind` is known — there is no count limit and no minimum
interval, so `* * * * *` (an agent run every minute, forever) is accepted.
Concurrency is capped at 3 by a module-level semaphore purely to avoid OOM on a
3.8GB box. Opening that to everyone unbounded is a self-DoS risk.

The webhook-handler's own cron system already enforces exactly this shape
(`max_user_jobs=10`, `min_interval_minutes`); the tasks one never did.

In `create_schedule`:

- read `X-User-Admin` (the header exists — the gateway sets it — but
  `routes_schedules.py` does not currently read it);
- for callers that are **neither operator nor admin**:
  - reject an 11th schedule: *"You already have 10 scheduled tasks. Delete one
    first."*
  - reject repeats under 15 minutes: *"The shortest repeat is every 15
    minutes."*
- operator (`X-Cron-Secret`) and admins stay exempt, so
  `scripts/manage_schedules.py` is unaffected.

Interval is computed by asking croniter for the next three fire times and taking
the smallest gap, so `*/5` and comma lists are caught — not just the literal
`* * * * *`.

Live usage today is one user with 4 schedules (2 enabled), so the cap affects
nobody currently.

## Testing

Part 3 is ordinary Python and gets real unit tests: the interval calculation is
pure (every-minute rejected, `*/5` rejected, `*/15` accepted, hourly and daily
accepted), plus cap behaviour and proof that the operator and admin paths stay
exempt.

Part 2 is asserted against the parsed `NAV_ENTRIES` config — all four entries
must carry `allUsers`.

**Part 1 has an honest gap.** `task-panel.js` is browser JS and this repo has no
JS test harness; nothing exercises it. A static assertion that the selector list
contains a non-workspace fallback is worth having but is not proof. The only
real proof is loading the page as a non-admin, which needs an account we do not
have. Verification is therefore: create a temporary non-admin account, check the
sidebar in a real browser, delete the account. Anything less is an assertion,
not evidence — and asserting a UI fix without seeing it is the failure mode this
repo has been bitten by repeatedly.

## Out of scope

- Open WebUI's own workspace permissions stay `false`. This change deliberately
  does not alter what users can do *inside* Open WebUI.
- The `automations: false` feature permission (Open WebUI's own scheduled tasks)
  is left as-is; it is a separate product surface from our Cron Jobs page.
- Retrofitting caps onto schedules that already exist. The cap applies at
  creation; the 4 existing rows are well under it.
