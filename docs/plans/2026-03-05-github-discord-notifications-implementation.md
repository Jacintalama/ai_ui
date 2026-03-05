# GitHub → Discord Notifications — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Post formatted Discord messages when GitHub PRs are opened/merged/closed and when code is pushed.

**Architecture:** Add a `_notify_discord()` helper method to `GitHubWebhookHandler` that posts to Discord via the bot's Send Messages API. Call it from the existing PR and push event handlers. Same pattern as the working Grafana alerts endpoint.

**Tech Stack:** Python httpx, Discord REST API v10, existing webhook-handler FastAPI app

---

### Task 1: Add `_notify_discord()` method and wire into event handlers

**Files:**
- Modify: `webhook-handler/handlers/github.py`

**Step 1: Add httpx import and config import at top of file**

Add after line 3 (`import logging`):

```python
import httpx
from config import settings
```

**Step 2: Add `_notify_discord()` method to `GitHubWebhookHandler` class**

Add at the end of the class (after `_handle_push_event`):

```python
    async def _notify_discord(self, message: str) -> None:
        """Post a notification message to the Discord channel."""
        token = settings.discord_bot_token
        channel_id = settings.discord_alert_channel_id
        if not token or not channel_id:
            return

        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        }

        # Discord message limit
        if len(message) > 2000:
            message = message[:1997] + "..."

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers, json={"content": message})
                if resp.status_code == 200:
                    logger.info("GitHub event notified to Discord")
                else:
                    logger.warning(f"Discord notification failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Discord notification error: {e}")
```

**Step 3: Add Discord notification to `_handle_pull_request_event`**

In `_handle_pull_request_event`, add Discord notification calls. After extracting PR details (line 125-126), add notification before the n8n forwarding logic.

Replace lines 122-194 with:

```python
    async def _handle_pull_request_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle pull request events — forward to n8n for automated review."""
        action = payload.get("action")
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        repo_full_name = repo.get("full_name", "")
        pr_number = pr.get("number")
        title = pr.get("title", "")
        author = pr.get("user", {}).get("login", "unknown")
        html_url = pr.get("html_url", "")
        base_branch = pr.get("base", {}).get("ref", "")

        # Discord notifications for PR events
        if action == "opened":
            await self._notify_discord(
                f"🔀 **New PR #{pr_number}**: {title}\n"
                f"by **{author}** → `{base_branch}`\n{html_url}"
            )
        elif action == "closed" and pr.get("merged", False):
            await self._notify_discord(
                f"✅ **PR #{pr_number} merged**: {title}\n"
                f"by **{author}** into `{base_branch}`\n{html_url}"
            )
            return await self._handle_pr_merged(payload)
        elif action == "closed":
            await self._notify_discord(
                f"❌ **PR #{pr_number} closed**: {title}\n"
                f"by **{author}**\n{html_url}"
            )
            return {"success": True, "message": "PR closed notification sent"}

        if action not in ("opened", "synchronize"):
            logger.info(f"Ignoring PR action: {action}")
            return {"success": True, "message": f"PR action '{action}' not handled"}

        if "/" not in repo_full_name:
            logger.error(f"Invalid repository name: {repo_full_name}")
            return {"success": False, "error": "Invalid repository name"}

        logger.info(f"Forwarding PR #{pr_number}: {title} (action: {action}) to n8n")

        # Build normalized payload for n8n workflow
        n8n_payload = {
            "repo": repo_full_name,
            "pr_number": pr_number,
            "action": action,
            "title": title,
            "author": author,
            "diff_url": pr.get("diff_url", ""),
            "html_url": html_url,
            "base_branch": base_branch,
            "head_branch": pr.get("head", {}).get("ref", ""),
            "body": pr.get("body", "") or "",
        }

        # Forward to n8n — awaits the workflow execution (may take 10-30s)
        if self.n8n:
            try:
                n8n_result = await self.n8n.trigger_workflow(
                    webhook_path="pr-review",
                    payload=n8n_payload,
                )
                if n8n_result:
                    logger.info(f"n8n pr-review workflow completed for PR #{pr_number}")
                    return {
                        "success": True,
                        "message": "PR forwarded to n8n for automated review",
                        "pr_number": pr_number,
                    }
                else:
                    logger.warning(f"n8n pr-review returned no result for PR #{pr_number}")
                    return {
                        "success": True,
                        "message": "PR forwarded to n8n (no response — workflow may not be active)",
                        "pr_number": pr_number,
                    }
            except Exception as e:
                logger.error(f"Failed to forward PR #{pr_number} to n8n: {e}")
                return {
                    "success": False,
                    "error": "Failed to trigger n8n workflow",
                    "pr_number": pr_number,
                }
        else:
            logger.warning("n8n client not configured, cannot forward PR event")
            return {
                "success": False,
                "error": "n8n client not configured",
                "pr_number": pr_number,
            }
```

**Step 4: Add Discord notification to `_handle_push_event`**

In `_handle_push_event`, add Discord notification after the commit info is extracted (around line 325). Add right before the AI analysis call:

Insert after line 325 (`logger.info(f"Analyzing push to {branch}...")`):

```python
        # Discord notification
        latest_msg = commits[-1].get("message", "").split("\n")[0] if commits else ""
        await self._notify_discord(
            f"📦 **Push to `{branch}`**: {len(commits)} commit{'s' if len(commits) != 1 else ''} by **{pusher}**\n"
            f"Latest: {latest_msg}\n"
            f"https://github.com/{repo_full_name}/commits/{branch}"
        )
```

**Step 5: Deploy to server**

```bash
scp webhook-handler/handlers/github.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/github.py
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml build --no-cache webhook-handler && docker compose -f docker-compose.unified.yml up -d webhook-handler"
```

**Step 6: Verify webhook-handler is healthy**

```bash
ssh root@46.224.193.25 "sleep 5 && docker ps --format '{{.Names}}: {{.Status}}' | grep webhook-handler"
```

Expected: `webhook-handler: Up X seconds (healthy)`

**Step 7: Test by pushing a commit**

Make a small commit and push to trigger the GitHub webhook:

```bash
git add webhook-handler/handlers/github.py docs/plans/2026-03-05-github-discord-notifications-design.md docs/plans/2026-03-05-github-discord-notifications-implementation.md
git commit -m "feat: add GitHub PR and push notifications to Discord"
git push proxy-server fix/mcp-network-split
```

Then check Discord for the push notification and webhook-handler logs:

```bash
ssh root@46.224.193.25 "docker logs webhook-handler 2>&1 | grep -iE 'discord|push|github' | tail -10"
```

Expected: "GitHub event notified to Discord" in logs and a message in Discord #general.

**Step 8: Verify no errors**

```bash
ssh root@46.224.193.25 "docker logs webhook-handler 2>&1 | grep -iE 'error|traceback' | tail -5"
```

Expected: No new errors.
