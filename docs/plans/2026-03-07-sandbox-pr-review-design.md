# Sandbox PR Review — Claude Code on Server

## Overview

Run Claude Code CLI against the actual PR codebase for high-quality reviews, replacing diff-only analysis. A dedicated `pr-reviewer` container with a persistent git workspace receives review requests from the webhook-handler, runs Claude Code with full repo context and CLAUDE.md guidelines, and returns structured reviews posted to GitHub and Discord.

## Architecture

```
GitHub PR Event
    ↓
webhook-handler (existing, port 8086)
    ├─ POST http://pr-reviewer:3000/review
    ├─ If pr-reviewer unavailable → fallback to Open WebUI review (existing)
    ↓
pr-reviewer container (NEW, port 3000)
    ├─ Persistent git workspace (/workspace/repo)
    ├─ Claude Code CLI (Node.js + npm)
    ├─ ANTHROPIC_API_KEY env var
    ├─ git fetch + checkout PR branch
    ├─ Runs: claude -p "Review PR #N" with CLAUDE.md context
    ├─ Returns: {review_text, status, duration}
    ↓
webhook-handler
    ├─ Posts review as GitHub PR comment
    └─ Posts summary to Discord
```

## PR Reviewer Container

### Dockerfile
- Base: `node:20-slim`
- Install: `git`, Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Lightweight HTTP server (Python or Node) for review requests
- Persistent volume at `/workspace`

### API

Single endpoint:

```
POST /review
Body: {
  "owner": "TheLukasHenry",
  "repo": "proxy-server",
  "pr_number": 123,
  "branch": "feature/xyz",
  "base_branch": "main"
}

Response: {
  "review": "## Summary\n...",
  "status": "success|error",
  "duration_seconds": 45
}
```

### Review Process
1. If repo not cloned → `git clone https://github.com/{owner}/{repo}.git /workspace/{repo}`
2. `git fetch origin`
3. `git checkout {branch}`
4. `git diff {base_branch}...{branch} > /tmp/pr-diff.txt`
5. Run: `claude -p "Review this PR. The diff is at /tmp/pr-diff.txt. Follow CLAUDE.md guidelines." --output-format text`
6. Capture output, return as JSON

### Auth
- `GITHUB_TOKEN` — for git clone (private repo)
- `ANTHROPIC_API_KEY` — for Claude Code API calls

### Resource Limits
- Memory: 512MB (CLI is lightweight, AI runs on Anthropic servers)
- Container idles between reviews

## Webhook Handler Integration

### Changes to `handlers/github.py`

In `_handle_pull_request_event()`, try Claude Code first:

```python
review = await self._request_claude_code_review(owner, repo, pr_number, head_branch, base_branch)
if review is None:
    review = await openwebui.analyze_pull_request(...)  # existing fallback
```

New method `_request_claude_code_review()`:
- POST to `http://pr-reviewer:3000/review` with 120s timeout
- Connection refused or timeout → return None (triggers fallback)
- Success → return review text

### Output
- **GitHub:** PR comment with `🤖 **AI Code Review**\n\n{review}\n\n---\n*Reviewed by Claude Code*`
- **Discord:** Summary notification tagged with `Reviewed by Claude Code` or `Reviewed by Open WebUI`

### No changes needed to
- Caddy routing (pr-reviewer is internal only, on Docker network)
- API Gateway
- Discord bot configuration

## CLAUDE.md (Repo Root)

Claude Code reads this automatically during review:

```markdown
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
```

## Docker Compose Addition

```yaml
pr-reviewer:
  build: ./pr-reviewer
  container_name: pr-reviewer
  restart: unless-stopped
  environment:
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    - GITHUB_TOKEN=${GITHUB_TOKEN}
  volumes:
    - pr-review-workspace:/workspace
  networks:
    - backend
  deploy:
    resources:
      limits:
        memory: 512M
      reservations:
        memory: 256M
  healthcheck:
    test: ["CMD", "curl", "-sf", "http://127.0.0.1:3000/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 15s
```

## Fallback Behavior

| Condition | Behavior |
|-----------|----------|
| pr-reviewer healthy + API key set | Claude Code review |
| pr-reviewer down or unhealthy | Open WebUI review (existing) |
| pr-reviewer timeout (>120s) | Open WebUI review (existing) |
| API key missing/invalid | Container won't start, Open WebUI fallback |

## Cost Estimate

Claude Code PR reviews are lightweight API calls (input: diff + CLAUDE.md, output: review text).
- Estimated ~$0.10-0.50 per review depending on PR size
- At 5-10 PRs/week: ~$5-20/month
- Recommend setting a monthly spending limit on the Anthropic API key
