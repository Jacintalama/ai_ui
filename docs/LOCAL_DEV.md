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

python scripts/dev_check.py        # the layer check on its own (6 PASS lines)
python scripts/dev_e2e.py          # a real agent turn in a browser
python scripts/dev_e2e.py --headed # the same, visibly
```

`up` writes `.env.dev` the first time (`scripts/dev_env.py`, random values,
gitignored). Every compose call passes `--env-file .env.dev`, so the
production `.env` is never read. The compose project is `aiui-dev`, so no
container, network or volume can clash with production names.

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

Set `LOCAL_MODEL=real` and your own `OPENROUTER_API_KEY` in `.env.dev`, never
the production key. Then run `reset` and `up`: Open WebUI keeps its saved
connection after first boot, so a switch needs a fresh volume. `up` warns when
the mode changed since the last run. The agents then run on
`nvidia/nemotron-3-super-120b-a12b:free`. The allowlist holds only the four
free agent-pool ids, and paid escalation is off. The overrides are in
`docker-compose.dev.real.yml`.

## Where App Builder output goes

tasks mounts `dev/workspace`, not the repo, at `/workspace/ai_ui`. It is a git
repo of its own, gitignored, made by `up`. The docs sweep and the commit sweep
write and commit `apps/<slug>/` there, and never into your checkout (checked
2026-10-12).

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
