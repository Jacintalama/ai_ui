# Published AI Apps Design

Date: 2026-04-28
Status: Approved for implementation planning
Branch: feat/decision-engine-loop-preview

## Summary

Add a public publishing layer for AI-built apps in the task builder. Admins can
build and enhance apps in the existing preview flow, then publish a stable public
snapshot at:

```text
{project-slug}.ai-ui.coolestdomain.win
```

Example:

```text
meeting-notes.ai-ui.coolestdomain.win
```

Publishing must support backend apps, not only static HTML apps. Public apps are
open to anyone with the URL. Enhancements do not change the public app
automatically; the admin must click Republish after approving the preview.

## Current Context

The current builder already has these pieces:

- Build tasks create app files under `apps/<slug>/`.
- `tasks.items.built_app_slug` stores the app slug.
- The preview page can list files, start an app subprocess, and iframe the app
  through `/tasks/preview-app/`.
- Enhance chat can create follow-up BUILD tasks against an existing slug.
- Caddy currently routes `/tasks/preview-app/*` to one preview process on port
  9100.

The missing layer is a stable public publishing system. Preview is an internal,
editable view. Public publishing needs separate state, separate routing, and a
stable snapshot that does not change while enhancements are still being reviewed.

## Locked Decisions

| Area | Decision |
| --- | --- |
| Public URL format | `{project-slug}.ai-ui.coolestdomain.win` |
| Outside custom domains | Out of scope for now |
| Access model | Public only; anyone with the URL can open it |
| Static app support | Required |
| Backend app support | Required |
| Publish model | Snapshot publish layer |
| Enhancement behavior | Preview changes only until admin clicks Republish |
| Runtime model | Start on demand with idle shutdown |
| Idle timeout | 30 minutes by default |

## Goals

1. Let admins publish a completed AI-built app to a public subdomain.
2. Keep public apps stable while preview/enhancement work continues.
3. Support backend apps built with Node, Python, SQLite, Prisma, and similar
   local app stacks.
4. Provide clear Publish, Republish, Unpublish, and Open Public App controls.
5. Make builder communication templates easier for non-developers to understand.
6. Improve generated app defaults so apps have readable labels, empty states,
   and user-facing error messages.

## Non-Goals

- No outside custom domains such as `app.customer.com`.
- No login protection or password protection for public apps.
- No full version history or rollback UI in the first implementation.
- No always-running public app fleet in the first implementation.
- No public editing or public builder access.
- No multi-tenant billing or quota model.

## User Workflow

1. Admin creates a BUILD task.
2. The AI builder produces an app under `apps/<slug>/`.
3. Admin opens Preview and tests the app.
4. Admin clicks Publish.
5. System creates or replaces the public snapshot at
   `published-apps/<slug>/current/`.
6. Public URL becomes available at `{slug}.ai-ui.coolestdomain.win`.
7. Later enhancements update only the editable preview app under `apps/<slug>/`.
8. Admin clicks Republish when the preview result is ready for public users.
9. Admin can click Unpublish to take the public subdomain offline.

## Publishing Behavior

Publishing uses snapshots, not the live editable app folder.

```text
Editable app:
  apps/meeting-notes/

Public snapshot:
  published-apps/meeting-notes/current/

Public URL:
  meeting-notes.ai-ui.coolestdomain.win
```

Publish and Republish copy the editable folder into the snapshot folder. The
public runner always starts from the snapshot folder. This prevents half-finished
enhancements from leaking to public users.

If a public app is unpublished, the snapshot can remain on disk for future
republish, but public routing must return a clean "App not published" page.

## Domain and Routing

Caddy should accept wildcard subdomains under `ai-ui.coolestdomain.win` and send
them to the tasks service public-app router.

Conceptual Caddy route:

```caddyfile
*.ai-ui.coolestdomain.win {
    reverse_proxy tasks:8210
}
```

The exact route must be integrated carefully with the existing main host routing
so `ai-ui.coolestdomain.win` continues to serve the platform.

DNS needs a wildcard record:

```text
*.ai-ui.coolestdomain.win -> VPS / Cloudflare target
```

The tasks service public router extracts the hostname, maps it to a published
app slug, starts the app if needed, and proxies the request to that running app
process.

Reserved subdomains must be blocked:

```text
www
api
admin
app
tasks
mcp
grafana
n8n
auth
webhook
calendar
gmail
gdrive
```

Reserved names cannot be published as app slugs.

## Data Model

Add a new table in the `tasks` schema:

```text
tasks.published_apps
```

Fields:

| Column | Purpose |
| --- | --- |
| `id` | Primary key |
| `slug` | Public subdomain and app slug |
| `source_task_id` | Build task that owns the app |
| `snapshot_path` | Path to the current published snapshot |
| `status` | `published` or `unpublished` |
| `public_url` | Full public URL |
| `created_at` | First publish record creation |
| `published_at` | First successful publish time |
| `republished_at` | Most recent snapshot replacement |
| `unpublished_at` | Most recent unpublish time |
| `updated_at` | Last record update |

Recommended constraints:

- Unique `slug`.
- Status check: `published`, `unpublished`.
- Slug validation in application code:
  - lowercase letters, numbers, hyphens
  - cannot start or end with hyphen
  - cannot be a reserved subdomain

## API Design

Add authenticated admin APIs:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/tasks/{task_id}/publish/status` | Return publish state for preview UI |
| `POST` | `/api/tasks/{task_id}/publish` | First publish from editable app |
| `POST` | `/api/tasks/{task_id}/republish` | Replace public snapshot |
| `POST` | `/api/tasks/{task_id}/unpublish` | Mark public app unpublished |

Public router:

| Method | Path | Purpose |
| --- | --- | --- |
| `ANY` | Host `{slug}.ai-ui.coolestdomain.win`, path `/*` | Proxy to published app |

API responses should use plain language suitable for the UI:

```json
{
  "slug": "meeting-notes",
  "status": "published",
  "public_url": "https://meeting-notes.ai-ui.coolestdomain.win",
  "has_unpublished_changes": false,
  "message": "Published at meeting-notes.ai-ui.coolestdomain.win"
}
```

## Public Runner

The public runner starts apps on demand from `published-apps/<slug>/current/`.

Runtime detection should reuse the preview runner's logic:

1. Node app: `package.json` with `dev` or `start`.
2. Python app: `server.py`, `main.py`, or `app.py`.
3. Static app: `index.html`.

Differences from preview:

- Public apps use a separate port range, for example `9200-9299`.
- More than one public app may run at a time, limited by available ports and
  memory.
- Each request updates `last_accessed_at` in memory.
- A background idle reaper stops apps with no traffic for 30 minutes.
- Startup errors render a friendly "App failed to start" page.
- Missing records or unpublished records render a friendly "App not published"
  page.

## Proxy Behavior

Request flow:

```text
Browser
  -> meeting-notes.ai-ui.coolestdomain.win
  -> Caddy wildcard route
  -> tasks public router
  -> lookup slug "meeting-notes"
  -> ensure snapshot process is running
  -> proxy request to localhost/public-app-port
```

The public router must preserve:

- path
- query string
- method
- body
- common headers needed by the app

The public router should set or forward:

- `Host`
- `X-Forwarded-Host`
- `X-Forwarded-Proto`
- `X-Forwarded-For`

## Security and Containment

Backend publishing means generated code becomes reachable by public traffic.
The first implementation is pragmatic, but it must still reduce avoidable risk.

Minimum first-version controls:

- Run public app subprocesses with the snapshot directory as `cwd`.
- Pass a minimal environment. Do not pass platform secrets such as
  `ANTHROPIC_API_KEY`, `DATABASE_URL`, OAuth secrets, or Open WebUI secrets.
- Block reserved subdomains.
- Keep public publish APIs authenticated through the existing admin path.
- Do not expose `/api/tasks/*` through public app subdomains.
- Copy snapshots with an allowlist/exclusion list:
  - exclude `.git`
  - exclude `.env`
  - exclude `node_modules`
  - exclude caches such as `__pycache__`, `.pytest_cache`
- Keep public app startup logs internal.

Known limitation:

Running generated backend apps as subprocesses in the tasks container is not
strong isolation. A future hardening phase should run each public app in a
restricted container or sandbox. For this first version, this is acceptable only
because publishing is admin-controlled and generated by the internal builder,
not arbitrary external users.

## Preview UI

Add publish controls to `preview.html` near the current Preview/Enhance workflow.

States:

| State | UI |
| --- | --- |
| Never published | Show Publish |
| Published and current | Show Open Public App and Unpublish |
| Preview newer than snapshot | Show Republish, Open Public App, Unpublish |
| Unpublished | Show Publish or Republish |
| Startup failure | Show public URL plus "App failed to start" message |

Plain status copy:

- "Not published"
- "Published at meeting-notes.ai-ui.coolestdomain.win"
- "Preview has changes not yet published"
- "Public app is offline until someone opens it"
- "Public app failed to start. Check the app logs before republishing."

Republish warning:

```text
Republish will replace what public users see with the current preview version.
```

## Builder Communication Templates

Improve the builder prompts and result formats so admins understand what is
happening without reading developer logs.

Clarify template:

- Ask one question at a time.
- Prefer choices.
- Use user-facing wording.
- Explain why the answer matters only when needed.

Plan template:

- Start with "What the app will do" in plain language.
- Then list screens/features.
- Then list technical details.
- Then list tests.

Completion template:

- Lead with what changed.
- Tell the admin where to see it.
- Tell the admin what to do next:
  - Preview
  - Publish
  - Republish
  - Ask for another change

Enhance completion must explicitly say:

```text
This is updated in preview. Public users will not see it until you click
Republish.
```

Chat template:

- Keep normal chat lightweight.
- Only produce `BUILD_SUGGESTION:` when the user clearly asks for a change.
- Avoid developer-only language unless the admin asks for technical detail.

## Generated App Templates

Improve the default app style and copy that the builder encourages Claude to
produce.

Generated apps should include:

- Clear page title.
- Obvious primary action button.
- Helpful empty state.
- Plain error messages.
- Labels on form fields.
- Confirmation for destructive actions.
- Mobile-safe layout.
- No developer-only text such as "TODO", "sample", "debug", or "lorem ipsum".

For backend apps:

- Show loading states while fetching.
- Show user-friendly API failure messages.
- Avoid exposing stack traces in the browser.
- Use relative API paths so the app works behind preview and public subdomains.

## Testing Plan

Backend tests:

- Publish creates a `published_apps` record.
- Publish rejects missing `built_app_slug`.
- Publish rejects reserved slugs.
- Publish creates a snapshot from `apps/<slug>/`.
- Republish replaces the snapshot.
- Unpublish changes status and public route returns "not published".
- Public router maps host to slug.
- Public runner starts static apps from snapshot.
- Public runner starts Node apps from snapshot.
- Public runner starts Python apps from snapshot.
- Startup failure returns a friendly page.

Frontend/manual checks:

- Preview page shows Publish for never-published apps.
- Publish returns public URL.
- Open Public App opens the subdomain.
- Enhance changes preview only.
- Republish updates public snapshot.
- Unpublish takes public URL offline.

Deployment checks:

- Wildcard DNS exists for `*.ai-ui.coolestdomain.win`.
- Caddy wildcard route does not break `ai-ui.coolestdomain.win`.
- Public runner port range is reachable only inside Docker/backend network.
- Public app does not receive platform secrets in its environment.

## Rollout Plan

1. Add database migration and models for `published_apps`.
2. Add snapshot copy service and slug validation.
3. Add publish status, publish, republish, and unpublish APIs.
4. Add public runner with port allocation and idle reaper.
5. Add public host router/proxy.
6. Add Caddy wildcard route.
7. Add preview UI controls.
8. Improve builder communication templates.
9. Improve generated app guidance in build/enhance prompts.
10. Verify with one static app and one backend app.

## Open Risks

- Backend apps can consume memory or hang on startup. The runner needs timeouts,
  port limits, and idle shutdown.
- Generated backend apps are not strongly sandboxed in the first version.
- Wildcard DNS and Caddy host matching must not interfere with the main platform
  host.
- Some generated apps may hardcode `/tasks/preview-app/` assumptions. Builder
  prompts should tell apps to use relative URLs.

## Success Criteria

1. A completed backend app can be published at
   `meeting-notes.ai-ui.coolestdomain.win`.
2. Public users can open the URL without logging in.
3. If the app is idle, first request starts it on demand.
4. After 30 idle minutes, the public process shuts down.
5. Enhancing the app changes only preview.
6. Public app updates only after Republish.
7. Unpublish makes the public URL show a clean unavailable page.
8. Builder messages clearly tell the admin what happened and what to click next.
