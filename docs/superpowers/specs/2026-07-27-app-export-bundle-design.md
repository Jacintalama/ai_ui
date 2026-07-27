# Take Your App With You, part 2: the export bundle + deploy guide

Date: 2026-07-27
Status: Approved direction (Jacint). Scope decision: **bundle + deploy guide**;
GitHub push and one-click platform deploys are explicitly v2.

Origin: the client's "no platform lock-in" ask (2026-07-16, opportunity 4 of the
market scan) plus Lukas's standup framing (2026-07-27): *"the export would be
for deploying the app to whatever they're choosing... it's important for the AI
to know where it's possible... that's a huge feature and I'm all curious how
you're gonna figure that one out."* Lukas's version upgrades export from
"download my code" to "get my app onto the platform I choose, with the AI
knowing what is possible where."

Part 1 (real version history) shipped 2026-07-16 and is the enabling
dependency: an export with history requires history to exist, and 43 of 47 apps
had none until the commit sweep. History coverage is now 39/49.

## The bar

From the 2026-07-16 scoping decision: **can a competent developer take what IO
hands the user and stand the whole thing back up without IO?** The bundle must
be a working git repository with a working app, not a dead snapshot.

## Why the deploy question is smaller than it sounds

IO apps are static HTML/CSS/JS (12K-49K typical, 3.5M worst case) with
connect-your-own-Supabase. Lukas's hard cases (Docker on Vercel, Kubernetes)
do not exist at today's app complexity: every major static host can run every
app we build. So v1's "AI knows what's possible" is a small, honest capability
table, and it becomes load-bearing only the day IO generates server-side apps.
The GitHub-push hub move (one OAuth unlocks Vercel/Netlify/Cloudflare native
import + Pages) is the natural v2 on top of this bundle.

## Design

One new module, `mcp-servers/tasks/app_export.py`, following the
one-job-per-file convention (`app_smoke.py`, `app_git.py`, `app_regression.py`).

### 1. `analyze_app(slug) -> AppProfile`

A small scan of `apps/<slug>/`:
- `has_index`: `index.html` exists (same publishability bar as `_publish_slug`)
- `uses_supabase`: files reference `window.SUPABASE_URL` / `aiui-config` /
  `createClient`
- `uses_chat_proxy`: files call `/api/chat-proxy` (the platform's LLM proxy for
  built apps). **An exported app cannot reach it** — this must surface as a
  warning, not be silently broken.
- `size_bytes`, `file_count`

Pure function over the filesystem; unit-testable with tmp dirs.

### 2. `DEPLOY_TARGETS` — the capability table

Lukas's "common developer sense" as data, not prose. Entries: GitHub Pages,
Netlify (Drop), Vercel (import), Cloudflare Pages, "your own server (any
static host)". Each entry: name, `supports(profile) -> (bool, reason)`, and
exact steps in markdown. Today all targets support all apps (static); the
`supports` seam is where "Vercel cannot run Docker" lives when app types grow.

`build_deploy_guide(profile) -> str` renders the table + per-app warnings
(chat-proxy, Supabase config) as markdown. Used twice: the README, and the
gallery modal.

### 3. `export_app(slug, actor_email) -> path to zip`

Builds the bundle in a temp directory. **Never modifies `apps/<slug>/` in the
monorepo** — all additions are commits in the temp clone only.

1. `_validate_slug(slug)` (reuse from `routes_projects`), realpath containment.
2. **History extraction**: `git subtree split --prefix=apps/<slug>` on the
   monorepo (verified working in the tasks container 2026-07-16), then clone
   that branch into the temp dir as a standalone repo; delete the temp branch.
   Fallback when the app has no commits: fresh `git init` + copy of tracked
   files + one "Exported from IO" commit, and the README says history was
   unavailable. Export never fails for want of history.
3. **Make it run standalone** (the subtle one): the Supabase URL + anon key are
   injected at request time by `main.py::_supabase_inject_for` and are NOT in
   the app's files — an export that skips this ships a broken app. If
   `tasks.project_supabase` has a row for the slug: write a real
   `aiui-config.js` (the user's own URL + anon key; the anon key is public by
   design and it is their project) and inject
   `<script src="./aiui-config.js"></script>` into the bundle's `index.html`
   head, mirroring the server-side injection. No row: write
   `aiui-config.example.js` with placeholders + README instructions.
4. **`schema.sql` dumped from the live database, not written by the agent**:
   introspection over `information_schema.columns`,
   `pg_class.relrowsecurity`, and `pg_policies` through the existing dual path
   in `routes_db` (Management API for OAuth links, asyncpg for db_uri — so
   OAuth-only projects are covered; there is no pg_dump in the image). Emitted
   as `CREATE TABLE` / `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` /
   `CREATE POLICY`, so RLS state is reported as fact. As of 2026-07-23 zero
   projects are linked, so this path ships mock-tested and dormant.
   Introspection failure: include a README note, keep exporting.
5. **README.md**: what this is, how to run locally (`python -m http.server` or
   just open `index.html`), the deploy guide, the Supabase section, the
   chat-proxy warning when applicable, and the history note.
6. Steps 3-5 land as one commit in the temp repo, authored as the actor
   (`-c user.email=` pattern from `rollback_app_core`).
7. **Zip includes `.git`** — the deliverable is a working repository. Name:
   `<slug>-export-<shortsha>.zip` (`fresh` when no history). Temp file cleaned
   up after streaming (FastAPI `FileResponse` + background cleanup).

Exclusions: `.attachments/` and `.video/` are untracked/ignored so subtree
never carries them; the no-history fallback must skip them explicitly.

### 4. Route + UI

- `GET /api/projects/{slug}/export` on the projects router, same
  admin/capability auth as the neighbouring versions/docs routes, streaming the
  zip. `GET /api/projects/{slug}/export/guide` returns `{markdown}` for the
  modal.
- Gallery (`projects.html`): an Export button beside Docs on each card. Click →
  modal shows the deploy guide (rendered with the vendored marked + DOMPurify,
  the docs-modal pattern, **own element ids** — the dmModal collision from
  2026-07-16 is the cautionary tale) → Download button streams the zip.
- Plain text labels, no emoji/icons, per project preference.

## Error handling — the opposite of the sweeps, on purpose

Every build sweep fails open because a build must never die on post-processing.
Export is user-initiated: the user clicked a button and must get **either a
good bundle or a clear error**, never a silently incomplete one. So:

- Unknown slug / no `index.html` → 404/409 with a plain-words detail.
- A live build/enhance on the slug → 409 ("build in progress"), via the same
  per-slug advisory lock pattern `_create_and_spawn_enhance` and rollback use.
  Never zip a half-written tree.
- git/subtree failure → 500 with the git stderr snippet.
- The only fail-open parts are the *optional enrichments*: schema introspection
  and history extraction degrade to README notes, because a bundle without
  schema.sql is still a good bundle, but a "bundle" missing the app is not.

## Secrets guarantee

`db_uri_encrypted`, service keys, OAuth tokens, and anything from `.env` are
never written to the bundle. Asserted in a test against the actual zip bytes,
not by code inspection. The only credentials ever included are the user's own
Supabase URL + anon key, which are public by construction (they are injected
into every served page today).

## Testing

Unit (seams: `_run_git`, the SQL executor, filesystem via tmp dirs):
- `analyze_app`: detects index/supabase/chat-proxy; empty dir.
- `DEPLOY_TARGETS`: every target renders steps; `supports` honours the profile;
  guide includes the chat-proxy warning iff the profile has it.
- `export_app`: bundle contains `.git`, README, app files; linked-supabase
  bundle contains a real `aiui-config.js` AND the script tag in `index.html`;
  unlinked bundle contains the example file; no-history fallback produces a
  repo with exactly one commit; `.attachments`/`.video` never in the zip;
  secrets never in the zip bytes; monorepo tree untouched after export
  (`git status` clean); zip name carries the sha.
- Route: 404 unknown slug, 409 while live, guide endpoint returns markdown,
  export streams a zip content-type.

End to end on the server (the real proof):
- Export `icecreamery` (has real history): unzip in a clean container dir,
  `git log` shows its actual commits, `python -m http.server` + headless fetch
  of `index.html` returns 200 and the page's own assets load.
- Export an app with no history: bundle opens, README carries the note.

## Out of scope (v2+, in order)

1. **Push to the user's GitHub** — the hub that unlocks Vercel/Netlify/
   Cloudflare native import + Pages with one OAuth.
2. Bot surfaces (Discord/Slack "export my app").
3. One-click platform deploys with per-user platform OAuth.
4. Owner-scoped `aiuibuilder` export route (comes with the bot surfaces).
5. Server-side app types and a real (load-bearing) capability matrix.

## Deploy

tasks service (module + routes) + `projects.html` (button/modal). Verify live
with the two e2e exports above, then `curl -fsS .../tasks/healthz`.
