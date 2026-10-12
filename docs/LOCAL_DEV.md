# Local dev stack

A local copy of the platform at **http://localhost:8090**: Postgres, Redis,
Open WebUI, the API gateway, tasks, Caddy and a scripted fake model. It has its
own secrets and no production data. Use it to try a change before it goes to
the server.

## Prerequisites

- Docker Desktop. `dev_up.sh` starts it if it is not running.
- Git Bash, to run the scripts from the repo root.
- Python 3 on the host, with `cryptography` (for `dev_env.py`) and
  `playwright` plus its Chromium (for `dev_e2e.py`).
- Port 8090 free on 127.0.0.1.

## Commands

```bash
bash scripts/dev_up.sh up          # build, start, seed, then check each layer
bash scripts/dev_up.sh down        # stop; the data is kept
bash scripts/dev_up.sh reset       # delete the aiui-dev volumes (asks first)
bash scripts/dev_up.sh logs tasks  # follow one service's logs
bash scripts/dev_up.sh model       # which model mode, and which compose files
bash scripts/dev_up.sh config      # the compose config exactly as up sees it

python scripts/dev_check.py        # the layer check on its own (6 PASS lines)
python scripts/dev_e2e.py          # a real agent turn in a browser
python scripts/dev_e2e.py --headed # the same, visibly
```

`up` writes `.env.dev` the first time (`scripts/dev_env.py`, random values,
gitignored). Every compose call in `dev_up.sh` passes `--env-file .env.dev`
and `-p aiui-dev`. The dev compose files interpolate only `DEV_` names
(`DEV_POSTGRES_PASSWORD`, `DEV_WEBUI_SECRET_KEY`, `DEV_AIUI_FERNET_KEY`,
`DEV_CRON_SHARED_SECRET`, and `DEV_OPENROUTER_API_KEY` in real mode), each
with `:?`, and the production `.env` has no `DEV_` names. So a plain
`docker compose -f docker-compose.dev.yml up`, which reads the repo-root
`.env`, stops with "run bash scripts/dev_up.sh up" instead of starting on
production values (`scripts/test_dev_env.py` checks both). The compose
project is `aiui-dev`, so no container, network or volume can clash with
production names, and `-p` keeps it so even with `COMPOSE_PROJECT_NAME` set
in your shell.

An `.env.dev` from before the `DEV_` names is migrated in place by the next
`up` (or `down`, `reset`): each value moves to its `DEV_` name unchanged, so
the Postgres volume keeps its password and encrypted rows stay readable.

`python scripts/dev_env.py --force` regenerates every value. On a stack that
has already run that breaks it (Postgres keeps its first password, old
encrypted rows no longer decrypt), so follow it with
`bash scripts/dev_up.sh reset`, then `up`.

The tasks code defaults that name production are overridden. Production's
n8n (`N8N_WEBHOOK_BASE`, `WEEKLY_RECAP_WEBHOOK`) and `api.openai.com`
(`OPENAI_API_BASE`) become `.invalid` hosts, which never resolve.
`CRON_SHARED_SECRET` is set (empty would skip the `/cron/weekly-recap` auth
check). The public-link settings (`AIUI_PUBLIC_DOMAIN`, `AIUI_SERVER_IP`,
`PUBLIC_BASE_URL`) point at localhost. Slack, Discord and Telegram calls
need a bot token from the local database, which has none unless you link
one.

## Signing in

Open http://localhost:8090 and sign in as `DEV_ADMIN_EMAIL` with
`DEV_ADMIN_PASSWORD`, both from `.env.dev`. The seed makes three agents for
that admin: Ada, Mia and Dev. Running the seed again creates nothing new.

## The fake model

Every agent turn goes tasks, then Open WebUI, then `dev/fake-llm`. It answers
after 1.5 s (`FAKE_DELAY_MS`). A keyword anywhere in the message picks a scene:

| Message contains | Answer | What the page shows (2026-10-12) |
|---|---|---|
| nothing special | `<Name> here. You said: <text>` | the bubble about 1.8 s after send |
| `scene:slow` | the same, after 5 s | not run by `dev_e2e.py` |
| `scene:tool` | calls the first offered tool, then `<Name> used a tool.` | `<Name> here. No tool was offered.`: the agents' tools (`server:mcp-proxy`, `gmail`) do not exist locally, so no tool reaches the model |
| `scene:fail` | HTTP 500 | "Ada could not answer. Something went wrong on our side. Nothing was changed." The office shows "Last run failed", and the roster shows Failed until the next good turn |
| `scene:pass` | `PASS` (the room protocol) | not run by `dev_e2e.py` |

`dev_e2e.py` asserts the plain turn and the office, and prints what the
`scene:tool` and `scene:fail` turns show. Screenshots go to `dev/out/`.

## A real model

Set `LOCAL_MODEL=real` and your own `DEV_OPENROUTER_API_KEY` in `.env.dev`, never
the production key. Then run `reset` and `up`: Open WebUI keeps its saved
connection after first boot, so a switch needs a fresh volume. `up` warns when
the mode changed since the last run. The agents then run on
`nvidia/nemotron-3-super-120b-a12b:free`. The allowlist holds only the four
free agent-pool ids, and paid escalation is off. The overrides are in
`docker-compose.dev.real.yml`.

## Where App Builder output goes

tasks mounts `dev/workspace`, not the repo, at `/workspace/ai_ui`. It is a git
repo of its own, gitignored, made by `up`. Anything tasks writes or commits
under `/workspace/ai_ui`, including the docs sweep and the commit sweep on
`apps/<slug>/`, lands there and cannot reach your checkout. Evidence, from
2026-10-12: a probe app, `apps/zz-iso-probe/`, was committed into
`dev/workspace` (commit `fba238c`, still in its reflog) and then reset; this
checkout has no such path and no commit touching it. No full App Builder build has run locally (there is
no build key), so the sweeps have not been exercised end to end here.

## Not in the local stack

- The Discord, Slack and Telegram bots (`webhook-handler`).
- `mcp-proxy` and the MCP servers, so agents have no tools.
- Pipelines and the `auto_router` pipe.
- Video and Remotion (`VIDEO_ENABLED=false`).
- n8n, which is on Hostinger even in production.
- Grafana and Loki.
- The agent SSH key.
- A build key for the Claude Code CLI. App Builder builds have nothing to run
  on locally (untested).

## Troubleshooting

- **The first `up` is slow.** Open WebUI runs its migrations on a fresh volume.
  `up` waits up to 10 minutes for `/api/config`.
- **`/health` answers but the page does not.** Caddy answers `/health` itself.
  `dev_check.py` tells you which layer is down. Then run `dev_up.sh logs <svc>`.
- **Ada and Mia are missing.** The seed runs only once per email
  (`routes_agents.seed_for_email`). Its first run marks the email done even if
  it created nothing, and later runs print `seeded=False created=0`. Run
  `reset`, then `up`. This is why the seed waits for the model to be listed.
- **"model ... not listed; not seeding".** Open WebUI is still on the other
  mode's connection. Run `reset`, or edit Admin > Settings > Connections.
- **A What's New dialog covers the page.** A fresh admin sees it once.
  `dev_e2e.py` closes it.
- **The roster says Failed after a good answer.** It catches up within a few
  seconds.
- **A commit sweep says "Author identity unknown".** Run `up` again. It sets
  the identity in `dev/workspace/.git/config`.
- **The script fails with `$'\r': command not found`.** `scripts/dev_up.sh`
  must be checked out with LF line endings (`.gitattributes` does this).
