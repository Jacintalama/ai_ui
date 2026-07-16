# App history: make commits real

Date: 2026-07-16
Status: Proposed, grounded in live production evidence (see Evidence).
Part 1 of two. Part 2 (the export bundle) gets its own spec once this lands.

Origin: `docs/ai-coding-market-scan-2026-07-15.md` opportunity 4, reframed by
client feedback on 2026-07-16 from "offer a managed provisioning path" to "the
end user should not get platform locked in". Scoping question answered: the
lock-in we are breaking is **lock-in to IO**, and the bar is "can a competent
developer take what IO hands the user and stand the whole thing back up
without IO?"

## Why this comes first

Investigating what IO would have to hand a user surfaced a prerequisite the
roadmap could not see from the outside: **there is almost no history to hand
over.** You cannot give someone their version history if you never recorded it.

### Evidence (measured live on 46.224.193.25, 2026-07-16)

- 43 of 47 app directories have **zero** commits touching them. Only 4 have
  any, and those 4 are exactly the apps that also exist in the local checkout.
  Their history comes from a single one-off commit,
  `54d026f6d chore: snapshot live VPS state into git`.
- No commit has ever touched `apps/bean-there/`, `apps/aiui-demo/`, or
  `apps/create-me-a-shoe-website-fe02/`.
- 17 entries under `apps/` sit in the working tree as untracked `??`.
- The version timeline and rollback feature (shipped 2026-07-13, specced in
  `2026-07-14-appbuilder-versions-autofix-questions-design.md`) reads
  `git log --max-count=100 -- apps/<slug>/` (`routes_projects.py:550`). With no
  commits it returns an empty list. The feature is effectively non-functional
  for 91% of production apps.

### Two independent root causes, both required to fix

1. **The commit is a prompt, not a step.** `claude_executor.py:174-183` tells
   the build agent "If your work modifies files, you MUST: 1. Stage just the
   files you changed ... 2. Create one commit per task using your summary as the
   message." Nothing verifies it happened. The 2026-07-14 spec assumed "The
   build agent commits per change, so the timeline is populated". That
   assumption does not hold in production.

2. **Prompt-shaped gitignore rules eat real apps.** `_slugify`
   (`routes_aiuibuilder.py:187-192`) derives the slug from the first five words
   of the user's description. `.gitignore` lines 39-51, added 2026-05-27 as
   "snapshot hardening 2026-05-27 (from VPS live line)", include
   `apps/create-me-*/`, `apps/make-the-*/`, `apps/me-a-*/`, `apps/upload-*/`
   and `apps/*smoke*/`. Verified with `git check-ignore -v`, these currently
   swallow 11 real user apps, 8 through `create-me-*` alone
   (`create-me-a-shoe-website-fe02`, `create-me-chicken-joy-landing-afa6`,
   `create-me-door-store-landing-6ae3`, ...).

`git add` on an ignored path is a silent no-op, so cause 2 would defeat the fix
for cause 1. Both land together or neither works.

### Method note (two traps that produce false results here)

- `git check-ignore -q <path>` returns success for **any** non-existent path,
  reporting a phantom match against a blank line. Only a `-v` result showing a
  **non-empty pattern field** is a real match. Additionally, `apps/foo-*/`
  rules carry a trailing slash and so are directory-only: querying without a
  trailing slash makes real matches disappear.
- `git subtree --help` and `git archive --help` fail in the tasks container for
  want of man pages, which reads as "not installed". Both commands work. Test
  capability with a real invocation, never with `--help`.

## Design

### F1. Post-execution commit sweep

A new seam in `routes_execution.py`, called from `_run_execution` immediately
after the existing AutoFix block (`routes_execution.py:283-289`) and under the
same guard (`outcome.kind == "completed" and slug`). After AutoFix, not before,
so the committed tree is the smoke-verified tree and any narrow AutoFix edits
land in the same commit.

```
async def _sweep_app_commit(slug, task_id, actor_email) -> str | None
```

1. `_validate_slug(slug)` (reuse `routes_projects.py:544`), guarding path
   injection before the slug reaches a git argument.
2. `git status --porcelain -- apps/<slug>/`. Empty means the agent already
   committed everything, so return None and do not create a second commit.
3. `git add -- apps/<slug>/`. **Path-scoped. Never `git add -A`, never
   `git add .`** The same working tree holds IO's own platform code and the
   VPS's own drift; a broad add would sweep unrelated changes into a user's app
   commit.
4. Commit with the task summary as the message and the task's actor as author,
   so `VersionEntry.actor_email` and `task_id` (`routes_projects.py:523-524`)
   resolve in the timeline. The message must not begin with "Rollback", which
   `list_app_versions_core` reserves to mark rollback entries.
5. Return the new SHA.

Reuses `_run_git` (`routes_projects.py:531`) rather than adding a second
subprocess helper. If the import direction is awkward, factor `_run_git`,
`REPO_ROOT` and `_validate_slug` into a small shared module and have both
routers call it, with no behaviour change to the existing routes.

Fails open, matching the AutoFix precedent: any git failure is appended to the
execution log and swallowed. A build must never fail because the history sweep
failed.

### F2. Gitignore correction

Remove the rules whose shape collides with `_slugify` output, and name the real
junk instead.

**Remove these five** (each can match a real user slug):
`apps/create-me-*/`, `apps/make-the-*/`, `apps/me-a-*/`, `apps/upload-*/`,
`apps/*smoke*/`.

**Keep unchanged** the entries that are already explicit paths and are genuine
junk: `apps/alama-flight/`, `apps/crudsimple/`, `apps/diag-test/`,
`apps/test-crud/`, `apps/test-project/`, `apps/testfly/`. Also keep
`apps/caddy-auth-test-*/` and `apps/landing-page-for-aiui-bot-*/`, whose
prefixes are long enough that a five-word user description will not
realistically produce them.

**Narrow the smoke rule** from `apps/*smoke*/` (which would ignore a user's
smoke-alarm shop) to the three prefixes our harnesses actually generate:
`apps/browser-smoke-*/`, `apps/build-smoke-*/`, `apps/smoke-upload-*/`.

**Newly add** explicit entries for junk that loses its cover when `upload-*`
goes away, plus the two one-offs never covered: `apps/upload-c2f78c78/`,
`apps/upload-da5312a9/`, `apps/e2e-4f3e4b/`, `apps/foo-app/`.

**Add** `apps/_test-*/` as the future-proof home for generated test apps.
`_slugify` collapses every non-alphanumeric run to `-` and strips leading
separators, so a user description can never yield a slug starting with `_`.
This rule is collision-proof by construction.

Residual risk, stated plainly: until the test harnesses are migrated onto the
`_test-` prefix, a user description starting with the exact words "browser
smoke", "build smoke" or "caddy auth test" would still be ignored. That is a
far smaller target than "create me a", which is among the most natural
phrasings this product accepts. New `e2e-<hex>` runs are also uncovered by an
explicit entry and will show up as untracked until the harness migration lands.

Two judgement calls to confirm before implementing:

- `apps/ralph-portfolio/` is currently ignored by an explicit line. Ralph is a
  teammate, so this may be a real app rather than junk. Confirm with him before
  deciding whether it stays ignored.
- `apps/demo/`, `apps/aiui-demo/`, `apps/meeting-notes/` and `apps/ls-invoice/`
  are untracked but not ignored, so the sweep will start committing them on
  their next build with no gitignore change needed. Confirm that is wanted
  rather than adding them to the ignore list.

## Not in scope

- **Backfilling the 43 apps that already have no history.** This task stops the
  loss going forward. A backfill needs a per-directory judgement about junk
  versus real user app and it touches the live box, so it is its own decision.
- **The export bundle** (Part 2): `git subtree split`, `schema.sql` from live
  introspection, `aiui-config.example.js`, README, owner-scoped route.
- **RLS verification and `schema.sql` truthfulness.** Same "the prompt is not a
  guarantee" pattern (`claude_executor.py:271-287` tells the agent RLS is
  mandatory and nothing checks it; the OAuth-only path without a `db_uri` does
  not even receive those instructions). Tracked as market-scan opportunity 2.

## Error handling and safety

- Git failure at any step is non-fatal and logged. The build result is
  unchanged.
- Only `apps/<slug>/` is ever staged.
- The slug is validated before it reaches a git path argument.
- **No push.** The server's repo has diverged from local `main` (server HEAD
  `d8eecd225` versus local `d052b641b`) and makes its own snapshot commits.
  This sweep commits on the box only, matching the existing agent instruction
  "Do NOT push".
- `rollback_app_core` blocks on a dirty tree (`routes_projects.py:667-679`).
  Sweeping on every completed build reduces how often the tree is dirty, so
  this should make rollback more available, not less.

## Testing

Pytest, no real git and no real LLM, following the `_smoke_app` monkeypatch
seam already used for AutoFix (`routes_execution.py:33`):

- Sweep is a no-op when `git status --porcelain` returns empty (the agent
  already committed): asserts no `git commit` is issued.
- Sweep stages and commits when status is non-empty: asserts the git argv is
  path-scoped to `apps/<slug>/` and contains neither `-A` nor `.`.
- Commit message and author derive from the task; the message never begins with
  "Rollback".
- Git failure at add or at commit is swallowed and the execution result is
  unchanged (fail open).
- An invalid slug is rejected before any git call.
- Gitignore: `git check-ignore -v` over the 11 named real app slugs returns a
  non-empty pattern before the change and no match after, and the narrow test
  prefixes still match. This test must assert on the **pattern field with a
  trailing slash on the query**, not on the exit code, for the reason in the
  method note above.

## Deploy

tasks service only, plus the `.gitignore` change. The gitignore needs no
rebuild but must reach the box, because the container reads the bind-mounted
tree at `/workspace/ai_ui`.

Verify live: run one real blank build whose description starts with "create me
a", then confirm `git log --oneline -- apps/<new-slug>/` on the box returns a
commit and the web version-history tab shows it. That single test exercises
both root causes at once.
