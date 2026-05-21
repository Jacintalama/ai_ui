# Project: IO Platform

## Architecture
- Docker Compose multi-container platform on Hetzner VPS
- Traffic: Cloudflare → Caddy → API Gateway → Backend services
- Key services: Open WebUI, webhook-handler, MCP proxy, n8n, Grafana/Loki

## Deploying to Hetzner (read before any deploy)
- **Target:** `root@46.224.193.25`, path `/root/proxy-server/`, compose file `docker-compose.unified.yml`.
- **No git on the server** — code is pushed via rsync/scp, then rebuilt with docker compose. Never `git pull` on the server.
- **Prerequisite:** the deploying machine needs SSH access to the server (its key must be authorized). If `ssh root@46.224.193.25` fails, stop — fix access first; don't improvise.
- **Commit first.** The deploy script refuses a dirty working tree.

### Backend services (tasks, api-gateway, MCP servers, Caddy, compose)
Use the orchestrator script — it diffs against the last-deployed SHA, rsyncs only changed files, rebuilds only affected services, and smoke-tests `/healthz` (and will NOT record success if the smoke fails):
```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```
It watches only: `mcp-servers/`, `api-gateway/`, `Caddyfile`, `docker-compose.unified.yml`, `scripts/`.

### Discord bot (webhook-handler) — NOT covered by the script
The orchestrator script does **not** deploy `webhook-handler/`. Deploy it manually, one `scp` per changed file (`scp -r` silently skips files — never use it), then rebuild:
```bash
scp webhook-handler/<changed-file> root@46.224.193.25:/root/proxy-server/webhook-handler/<changed-file>
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

### Hard rules
- **NEVER deploy your local `mcp-servers/tasks/templates.py`.** The server's copy is ahead (more App Builder templates). Pull the server's version before editing, or you'll silently drop templates.
- **NEVER touch, overwrite, or commit `.env`** — the server's `.env` holds the only copy of the real production secrets.
- **Always verify after deploy:** `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz` (tasks) and check `docker compose ... ps webhook-handler` shows `Up` (bot). If a smoke fails, investigate logs — don't re-run blindly.

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
