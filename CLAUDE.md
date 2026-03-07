# Project: IO Platform

## Architecture
- Docker Compose multi-container platform on Hetzner VPS
- Traffic: Cloudflare → Caddy → API Gateway → Backend services
- Key services: Open WebUI, webhook-handler, MCP proxy, n8n, Grafana/Loki

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
