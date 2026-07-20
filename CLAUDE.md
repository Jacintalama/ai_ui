# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project: IO Platform

## Architecture
- Docker Compose multi-container platform on Hetzner VPS
- Traffic: Cloudflare → Caddy → API Gateway → Backend services
- Key services: Open WebUI, webhook-handler, MCP proxy, n8n, Grafana/Loki

## Commands

### Tests
Two tiers. Most tests run anywhere; the DB tier only runs inside the container.

```bash
# tasks service (146 test files) — from mcp-servers/tasks/
python -m pytest tests/ -q                       # full suite
python -m pytest tests/test_app_smoke.py -q      # one file
python -m pytest tests/ -q -k "regression"       # one pattern
```

`pytest.ini` sets `asyncio_mode = auto`, so async tests need no decorator.

**Expect ~130 errors locally.** Any test using the `db_session` fixture fails at
setup with `asyncpg.connect(...)` because there is no local Postgres. That is
pre-existing and not your change. Confirm by checking the failures say
`ERROR at setup`. To actually run that tier, run it in the container:

```bash
ssh root@46.224.193.25 "docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_x.py -q'"
```

The container has a real DB, and for gitignore/git tests it has the real
bind-mounted work tree, which makes it a stronger check than local.

Other suites: `webhook-handler/tests/` (110 files), `api-gateway/tests/`.

### DB test safety (read before touching db_session)
`tests/conftest.py` guards against a real incident: `AIUI_TEST_DB=1` once
**wiped 9 production projects and all chat history**. Destructive DB tests
require BOTH `AIUI_TEST_DB=1` and a `DATABASE_URL` containing `test`. Never
point them at the prod `openwebui` DB. Only delete rows you created, matched by
unique slug/id.

## App Builder pipeline (the part that spans many files)

A build request becomes a `tasks.items` row, which spawns the Claude Code CLI as
a subprocess. The interesting logic is what happens **after** the agent finishes,
in `routes_execution.py::_run_execution`, in this order:

1. **Regression baseline** (enhances only) — `app_regression.capture_baseline`
   smokes the app and records HEAD *before* the agent runs.
2. Agent runs → `parse_outcome(full_output)`.
3. **AutoFix** — `app_smoke.smoke_app` drives headless Playwright and captures
   `pageerror`, `console.error`, `requestfailed` and main-response status; on
   errors it runs narrow fix passes (max `AUTOFIX_MAX_PASSES`) and re-smokes.
   It is NOT merely a "does the page load" check.
4. **Docs sweep** — `app_docs.sweep_app_docs` writes the README if the agent didn't.
5. **Commit sweep** — `app_git.sweep_app_commit` commits `apps/<slug>/` if the
   agent didn't.
6. **Regression guard** — if the app was clean before and is broken now, roll
   back via `rollback_app_core`.

Every step after the agent **fails open**: a build must never fail because a
post-processing step failed.

### Slug resolution (subtle, has caused silent breakage twice)
Steps 3-6 are all gated on `slug`. Deriving it only from the agent's completion
text silently skips all four on enhances, because the agent rarely repeats the
`apps/<slug>/` path on a tweak. Use `app_regression.effective_slug(extracted,
task_slug)` — prefer what the agent named, fall back to what the task knows.
The `built_app_slug` DB write must keep using the **extracted** value only, or
its anti-clobber guard is defeated.

### Where apps live and how they are served
- Source: `apps/<slug>/` inside this repo, bind-mounted to `/workspace/ai_ui`.
- Publishing inserts a `tasks.published_apps` row; it moves no files. No row → 404.
- Served from disk by `main.py::serve_published_app` via three routes: apex
  `/apps/<slug>/`, wildcard subdomain, and custom domain (on-demand TLS).
- Supabase URL + anon key are **injected at request time** (`_supabase_inject_for`),
  so they are NOT in the app's files. Anything that exports an app must supply them.
- Version history is `git log -- apps/<slug>/` against **this monorepo**. There
  are no per-app repos.

### Testing seams
Post-processing modules expose module-level seams (`_smoke_app`, `_run_git`,
`_rollback`, `_sweep_app_commit`) so tests monkeypatch them instead of running a
browser or git. Follow that pattern; see `tests/test_autofix_loop.py`.

Driving `_run_execution` itself needs the DB tier, so its wiring is not unit
tested. **Verify wiring end to end on the server** — a real build or enhance —
because `python -c "import routes_execution"` will not catch a NameError inside
a function body.

## Deploying to Hetzner (read before any deploy)
- **Target:** `root@46.224.193.25`, path `/root/proxy-server/`, compose file `docker-compose.unified.yml`.
- **No git on the server** — code is pushed via rsync/scp, then rebuilt with docker compose. Never `git pull` on the server.
- **Prerequisite:** the deploying machine needs SSH access to the server (its key must be authorized). If `ssh root@46.224.193.25` fails, stop — fix access first; don't improvise.
- **Commit first.** The deploy script refuses a dirty working tree.
- **CRLF:** this repo checks out CRLF on Windows. After any `scp`, run
  `sed -i 's/\r$//'` on the server, or a compose value becomes `true\r` and
  silently reads as false.

### Backend services (tasks, api-gateway, MCP servers, Caddy, compose)
Use the orchestrator script — it diffs against the last-deployed SHA, rsyncs only changed files, rebuilds only affected services, and smoke-tests `/healthz` (and will NOT record success if the smoke fails):
```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```
It watches only: `mcp-servers/`, `api-gateway/`, `Caddyfile`, `docker-compose.unified.yml`, `scripts/`.

It needs `rsync`, which is absent from Git Bash on Windows. Fallback: one `scp`
per changed file, rebuild the service, then update `.deploy-state` by hand.
`.deploy-state` is **JSON** (`{"sha": ..., "deployed_at": ..., "deployed_by": ...}`)
and the script parses `['sha']`; writing a bare SHA breaks the next deploy.

Note `.gitignore` and `webhook-handler/` are NOT in the watched list, so changes
to them need a manual `scp` even when the script runs.

### Discord bot (webhook-handler) — NOT covered by the script
The orchestrator script does **not** deploy `webhook-handler/`. Deploy it manually, one `scp` per changed file (`scp -r` silently skips files — never use it), then rebuild:
```bash
scp webhook-handler/<changed-file> root@46.224.193.25:/root/proxy-server/webhook-handler/<changed-file>
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

### Server realities that are not in git
- **Docker's data-root is on the attached volume** (`/mnt/HC_Volume_106271703/docker`,
  moved 2026-07-20). A systemd drop-in makes docker require that mount, so it
  refuses to start rather than come up on an empty data-root.
- **Prod Caddy is a HOST systemd service** (`/etc/caddy/Caddyfile`), not the
  compose container. The repo `Caddyfile` is inert for routing.
- The server's git tree diverges from `main` and makes its own snapshot commits.
  Teammates edit files directly on the box, so **hash-sweep server vs repo
  (CRLF-normalized) before any repo-wins deploy** or you will silently revert
  their work.
- Stopping Docker rewrites iptables and **resets SSH sessions**. Run migrations
  detached (`systemd-run --unit=NAME --collect /root/script.sh`), never
  interactively.

### Hard rules
- **NEVER deploy your local `mcp-servers/tasks/templates.py`.** The server's copy is ahead (more App Builder templates). Pull the server's version before editing, or you'll silently drop templates.
- **NEVER touch, overwrite, or commit `.env`** — the server's `.env` holds the only copy of the real production secrets.
- **Always verify after deploy:** `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz` (tasks) and check `docker compose ... ps webhook-handler` shows `Up` (bot). If a smoke fails, investigate logs — don't re-run blindly.

## The prompt is not a guarantee
Several "guarantees" here are instructions to the agent that nothing verifies.
The git commit and the README were both in that state and were both broken in
production; they now have sweeps that check. **Still unverified: RLS**
(`claude_executor.py` tells the agent RLS is mandatory, and the OAuth-only path
without a `db_uri` does not even receive those instructions) **and `schema.sql`**
(the agent is asked to write it; nothing checks it matches the live DB).

When adding a feature whose correctness lives in a prompt, treat it as
unimplemented until something asserts the outcome.

## Code Review Guidelines
- Flag security issues: command injection, XSS, SQL injection, secrets in code
- Check error handling: all external calls (HTTP, DB) must have try/except
- Verify Docker compatibility: code runs in containers, not local dev
- Check env var usage: no hardcoded credentials, use os.environ
- Python style: async/await for I/O, httpx for HTTP clients, type hints
- Memory awareness: server has 3.8GB RAM, flag memory-heavy patterns

## What NOT to flag
- Missing type hints on existing code (only flag on new code)
- Import ordering style
- Docstring format preferences
