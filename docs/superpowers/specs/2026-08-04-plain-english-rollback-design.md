# Plain-English rollback: "go back to before it broke"

Date: 2026-08-04
Status: Approved direction (Jacint, 2026-08-04).

Origin: Lukas, standup 2026-08-03:

> "If I just tell the LLM *go back to the working part where we didn't start
> doing this feature that broke it*, the LLM usually knows where to go back to
> and does it."

He said this while describing what the App Builder history is *for*. We shipped
the history (2026-07-16) and the rollback button, but the only way to use them
is to read a list of commit SHAs and click one. The sentence he actually said is
not wired to anything.

## What is true today

Measured, not assumed:

| Piece | State | Evidence |
|---|---|---|
| Version list per app | **Exists** | `routes_projects.py:554` `list_app_versions_core` |
| Each version marked ok / error / rollback | **Exists** | same function, cross-references `tasks.items` |
| Rollback by SHA | **Exists** | `routes_projects.py:756` `rollback_app_core` |
| Owner-scoped rollback route | **Exists** | `routes_aiuibuilder.py:739` |
| Plain-English intent routing | **Exists** | `intent_router.py:14` `INTENTS`, live in prod |
| Any way to say it in words | **Missing** | no intent, no picker, no route |

So this is a connection job, not a new subsystem. Every hard part is built.

### The finding that shapes the whole design

`list_app_versions_core` already computes `status` per version:

- `"error"` — a task whose result mentions that commit **failed**
- `"rollback"` — the commit message starts with `Rollback`
- `"ok"` — a normal build or enhance commit

That means **"before it broke" has a deterministic answer.** Find the newest
`error` version; the target is the newest `ok` version older than it. No model
call, no guessing, and the reason can be stated as fact: *"'add cart' failed —
this is the last good version before it."*

The second load-bearing fact: `rollback_app_core` **commits on top of HEAD**
rather than rewriting history (`:759-762`). A rollback is therefore itself
reversible, and the confirm can honestly say so.

## Why not "just ask the model which version"

This repo's most expensive lesson is that a prompt is not a guarantee — see
`docs/superpowers/specs/2026-07-30-app-user-roles-design.md` and the git-commit
bug that silently broke history for 43 of 47 apps. Rollback **mutates the user's
app**. Putting a destructive action solely behind an LLM's judgement would repeat
that mistake with worse blast radius.

The model also has no information advantage. It would see the same thing the
rules see: commit messages, dates, and statuses. It cannot inspect what the app
looked like. Its only genuine edge is **paraphrase** — "before the checkout
thing" matching a commit called "add payment flow", where keyword matching fails.

So: rules decide; the model is a bounded fallback that may only **rank candidates
that are already in the real list**.

## Design

### 1. `rollback_pick.py` — pure, no I/O, in the tasks service

```python
def choose_rollback_target(versions, phrase) -> RollbackChoice
```

Rules in order. The first that matches wins:

| Phrase shape | Rule | `reason` shown to the user |
|---|---|---|
| contains a 7-40 hex SHA in the list | that version | "you named this version" |
| "before the cart" / "before the X" | newest version whose message matches X, take the next older | "the version just before 'add cart'" |
| "before it broke", "when it worked", "before the error" | newest `error`, then newest `ok` older than it | "'add cart' failed — this is the last good one before it" |
| "undo", "one step back", "previous" | the version just before current | "one step back" |
| nothing matches | `needs_user_choice=True` + candidates | — |

`RollbackChoice` is a frozen dataclass: `target` (a `VersionEntry` **taken from
the input list**, never constructed), `reason`, `needs_user_choice`,
`candidates`.

**Invariant, asserted in tests:** when `target` is not None it is identical (by
SHA) to a member of `versions`. The picker cannot name a version that does not
exist.

Pure because it takes the already-fetched list. That makes the whole decision
testable with canned data — no git, no database, no model, no network.

### 2. `GET /{slug}/rollback/resolve?phrase=...` — read-only

Owner-scoped, reusing the existing check on the aiuibuilder rollback route.
Returns the choice plus candidates. **Mutates nothing.** Separate from the
rollback route on purpose: resolving is safe and repeatable, rolling back is not.

### 3. `rollback_app` intent

Added to `INTENTS` and `EXECUTABLE` in `intent_router.py`, extracting two
fields alongside the existing `when`/`task`:

- `app` — the app name if the user named one ("go back on **shop**")
- `point` — the phrase describing where to go back to ("before the cart broke")

### 4. Which app?

Resolved before the confirm, in this order:

1. the user named one, and it matches a project they own
2. they own exactly one app → that one
3. otherwise → ask, listing their apps. **Never** guess between two apps.

### 5. Resolve before confirm, not after

The confirm card must state what will actually happen, so the resolve call
happens **before** parking the intent, and the chosen SHA is parked with it.
The user sees the exact target and the reason, then agrees. On confirm we roll
back to **that pinned SHA** — not to whatever "before it broke" would resolve to
a minute later.

If `needs_user_choice` comes back, webhook-handler asks the model to pick from
the returned candidates and **validates the returned SHA is in that list**
before offering it. An invalid or failed model answer degrades to showing the
list — never to picking arbitrarily.

### Flow

```
"go back to before the cart broke"
      -> classify: rollback_app, app="", point="before the cart broke"
      -> resolve the app (owns exactly one -> "shop")
      -> GET /shop/rollback/resolve?phrase=before the cart broke
      -> picker: newest error = "add cart"; newest ok before it = a3f21c9
      -> confirm card, SHA pinned:
           Rolling back shop to a3f21c9 "add checkout" (Aug 1, 14:22).
           "add cart" failed — this is the last good version before it.
           This is undoable; the newer versions stay in your history.
           [ Roll back ]  [ Show all versions ]  [ Cancel ]
      -> on confirm: existing owner-scoped rollback route, that exact SHA
```

## Error handling

Every failure becomes a sentence, never a stack trace:

- **no versions** — "shop has no saved versions yet, so there's nothing to go
  back to."
- **nothing matched** — show the list. Do not pick.
- **dirty tree (409)** — `rollback_app_core` already returns this. Surfaces as
  "shop has unsaved changes right now — I didn't want to overwrite them."
- **already there (noop)** — `rollback_app_core` returns `{"noop": True}`.
  Say "shop is already at that version" rather than claiming a rollback.
- **not the owner (403)** — "you'd need to be the owner of shop to roll it back."

## Testing

The picker is pure, so the matrix is canned version lists x phrases, with no
LLM and no git. Adversarial cases are the point:

- model returns a SHA **not** in the candidate list → rejected, falls back to the list
- phrase matches nothing → `needs_user_choice`, never an arbitrary pick
- only one version exists → "before it broke" cannot go older; say so
- every version is an error → no `ok` target; say so rather than picking an error
- the newest version is already the target → noop path, honest message
- a `rollback` commit in the history is not itself treated as a good target by
  the "before it broke" rule (it is a marker, not a build)
- **rollback never fires without a confirm** — asserted at the dispatch layer

## Out of scope, stated plainly

- Rolling back anything other than an App Builder app.
- Content-aware phrases ("the blue one"). Neither the rules nor the model can
  see what the app looked like; only commit messages exist. Saying so is better
  than pretending.
- Rolling back a *range* or cherry-picking a single change back out.
- A web UI for this. The version list + rollback button already exist there;
  this spec is about the sentence.
