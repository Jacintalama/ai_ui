# Sandbox PR Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dedicated `pr-reviewer` container that runs Claude Code CLI against actual PR code, with graceful fallback to existing Open WebUI review.

**Architecture:** New `pr-reviewer` Docker container with Node.js + Claude Code CLI + lightweight HTTP server. Webhook-handler POSTs review requests to it. Persistent git workspace volume for fast fetches. Falls back to Open WebUI if container unavailable.

**Tech Stack:** Node.js 20, Express, Claude Code CLI (`@anthropic-ai/claude-code`), Docker, git

---

### Task 1: Create CLAUDE.md in repo root

**Files:**
- Create: `CLAUDE.md`

**Step 1: Write the CLAUDE.md file**

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

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md with project conventions for Claude Code reviews"
```

---

### Task 2: Create pr-reviewer container

**Files:**
- Create: `pr-reviewer/Dockerfile`
- Create: `pr-reviewer/server.js`
- Create: `pr-reviewer/package.json`

**Step 1: Create `pr-reviewer/package.json`**

```json
{
  "name": "pr-reviewer",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "start": "node server.js"
  },
  "dependencies": {
    "express": "^4.21.0"
  }
}
```

**Step 2: Create `pr-reviewer/server.js`**

Express server with two endpoints:

- `GET /health` — returns `{"status": "ok"}`
- `POST /review` — accepts `{owner, repo, pr_number, branch, base_branch}`, clones/fetches repo, checks out PR branch, generates diff, runs `claude -p` with review prompt, returns `{review, status, duration_seconds}`

Key implementation details:
- Git workspace at `/workspace/{owner}/{repo}`
- First request clones, subsequent requests fetch
- Uses `GITHUB_TOKEN` for git auth via `https://{token}@github.com/...`
- Runs Claude Code with `--print` flag and captures stdout
- 120s timeout on claude process
- Returns JSON response with review text or error
- Concurrent review lock (one review at a time to manage memory)

**Step 3: Create `pr-reviewer/Dockerfile`**

```dockerfile
FROM node:20-slim

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app
COPY package.json .
RUN npm install --production
COPY server.js .

RUN mkdir -p /workspace

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://127.0.0.1:3000/health || exit 1

CMD ["node", "server.js"]
```

**Step 4: Commit**

```bash
git add pr-reviewer/
git commit -m "feat: add pr-reviewer container with Claude Code CLI"
```

---

### Task 3: Add pr-reviewer to docker-compose.unified.yml

**Files:**
- Modify: `docker-compose.unified.yml`

**Step 1: Add pr-reviewer service**

Add after the webhook-handler service block:

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

**Step 2: Add volume**

Add to the `volumes:` section at the bottom:

```yaml
  pr-review-workspace:
```

**Step 3: Add PR_REVIEWER_URL to webhook-handler env**

In the webhook-handler service, add environment variable:

```yaml
      - PR_REVIEWER_URL=${PR_REVIEWER_URL:-http://pr-reviewer:3000}
```

**Step 4: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: add pr-reviewer service to docker-compose"
```

---

### Task 4: Add pr_reviewer_url to webhook-handler config

**Files:**
- Modify: `webhook-handler/config.py`

**Step 1: Add setting**

Add after the `n8n_api_key` field (line 37):

```python
    # PR Reviewer (Claude Code)
    pr_reviewer_url: str = "http://pr-reviewer:3000"
```

**Step 2: Commit**

```bash
git add webhook-handler/config.py
git commit -m "feat: add pr_reviewer_url config setting"
```

---

### Task 5: Integrate Claude Code review into GitHub webhook handler

**Files:**
- Modify: `webhook-handler/handlers/github.py`

**Step 1: Add `_request_claude_code_review` method**

Add this new method to `GitHubWebhookHandler` class, after `_notify_discord`:

```python
    async def _request_claude_code_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        branch: str,
        base_branch: str,
    ) -> Optional[str]:
        """Request a PR review from the Claude Code pr-reviewer container.

        Returns the review text, or None if the service is unavailable.
        """
        pr_reviewer_url = settings.pr_reviewer_url
        if not pr_reviewer_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{pr_reviewer_url}/review",
                    json={
                        "owner": owner,
                        "repo": repo,
                        "pr_number": pr_number,
                        "branch": branch,
                        "base_branch": base_branch,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success" and data.get("review"):
                        logger.info(
                            f"Claude Code review completed for PR #{pr_number} "
                            f"in {data.get('duration_seconds', '?')}s"
                        )
                        return data["review"]
                logger.warning(
                    f"pr-reviewer returned {resp.status_code}: {resp.text[:200]}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.info(f"pr-reviewer unavailable, falling back to Open WebUI: {e}")
            return None
        except Exception as e:
            logger.warning(f"pr-reviewer error: {e}")
            return None
```

**Step 2: Modify `_handle_pull_request_event` to try Claude Code first**

In `_handle_pull_request_event`, replace lines 249-258 (the current Open WebUI review block) with:

```python
        # Try Claude Code review first, fall back to Open WebUI
        head_branch = pr.get("head", {}).get("ref", "")
        review = await self._request_claude_code_review(
            owner, repo_name, pr_number, head_branch, base_branch
        )
        reviewer_name = "Claude Code"

        if review is None:
            # Fallback to existing Open WebUI review
            body = pr.get("body", "") or ""
            review = await self.openwebui.analyze_pull_request(
                title=title,
                body=body,
                diff_summary=(diff_summary or "No file changes available")
                    + codebase_context + error_context,
                labels=[label.get("name", "") for label in pr.get("labels", [])],
                model=self.ai_model,
            )
            reviewer_name = "Open WebUI"
```

**Step 3: Update the Discord notification to show which reviewer ran**

Replace the Discord notification block (lines 282-292) with:

```python
            summary = review[:200].split("\n")[0]
            enrichment = f" | Reviewed by {reviewer_name}"
            if codebase_context:
                enrichment += " + codebase context"
            if error_context:
                enrichment += " + error history"
            await self._notify_discord(
                f"\U0001f50d **AI Review for PR #{pr_number}**: {title}\n"
                f"by **{author}** \u2192 `{base_branch}`{enrichment}\n"
                f"{summary}\n{html_url}"
            )
```

**Step 4: Update the GitHub comment format to show reviewer**

Replace the comment posting block (lines 267-279) with:

```python
        if review:
            formatted = self.github.format_ai_response(
                review + f"\n\n---\n*Reviewed by {reviewer_name}*"
            )
            comment_id = await self.github.post_issue_comment(
                owner=owner,
                repo=repo_name,
                issue_number=pr_number,
                body=formatted,
            )
            if comment_id:
                logger.info(f"AI review posted on PR #{pr_number} (comment {comment_id})")
                result["comment_id"] = comment_id
                result["reviewer"] = reviewer_name
            else:
                logger.warning(f"Failed to post AI review comment on PR #{pr_number}")
```

**Step 5: Commit**

```bash
git add webhook-handler/handlers/github.py
git commit -m "feat: integrate Claude Code pr-reviewer with Open WebUI fallback"
```

---

### Task 6: Deploy and test

**Step 1: Push to PR #11**

```bash
git push proxy-server fix/mcp-network-split
```

**Step 2: Deploy to server**

Copy new and modified files to server:

```bash
scp -r pr-reviewer/ root@46.224.193.25:/root/proxy-server/pr-reviewer/
scp CLAUDE.md root@46.224.193.25:/root/proxy-server/CLAUDE.md
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
scp webhook-handler/handlers/github.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/github.py
```

**Step 3: Set ANTHROPIC_API_KEY on server**

```bash
ssh root@46.224.193.25 "echo 'ANTHROPIC_API_KEY=sk-ant-...' >> /root/proxy-server/.env"
```

Note: This step requires Lukas to provide the API key. If not available yet, skip — the fallback to Open WebUI will activate automatically.

**Step 4: Build and start pr-reviewer**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build pr-reviewer webhook-handler"
```

**Step 5: Verify health**

```bash
ssh root@46.224.193.25 "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'pr-reviewer|webhook'"
```

Expected: Both containers `Up` and `(healthy)`

**Step 6: Test the review endpoint**

```bash
ssh root@46.224.193.25 "curl -sf http://pr-reviewer:3000/health"
```

Expected: `{"status":"ok"}`

**Step 7: Test with a real PR (optional)**

Create a test PR or trigger the webhook manually to verify the full flow.
