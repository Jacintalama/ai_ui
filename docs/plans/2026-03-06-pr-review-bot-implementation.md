# PR Review Bot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically post an AI code review as a GitHub comment and Discord summary when a PR is opened or updated.

**Architecture:** Replace the broken n8n forwarding in `_handle_pull_request_event` with direct calls to the existing `OpenWebUIClient` and `GitHubClient`. On PR `opened`/`synchronize`, fetch PR details, run AI analysis, post review comment on GitHub, and send a short summary to Discord.

**Tech Stack:** Python, FastAPI, httpx, Open WebUI API, GitHub API, Discord API

---

### Task 1: Replace n8n forwarding with direct AI review

**Files:**
- Modify: `webhook-handler/handlers/github.py:150-239`

**Step 1: Rewrite `_handle_pull_request_event` method**

Replace lines 150-239 in `webhook-handler/handlers/github.py` with:

```python
async def _handle_pull_request_event(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Handle pull request events - AI review + notifications."""
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
            f"\U0001f500 **New PR #{pr_number}**: {title}\n"
            f"by **{author}** \u2192 `{base_branch}`\n{html_url}"
        )
    elif action == "closed" and pr.get("merged", False):
        await self._notify_discord(
            f"\u2705 **PR #{pr_number} merged**: {title}\n"
            f"by **{author}** into `{base_branch}`\n{html_url}"
        )
        return await self._handle_pr_merged(payload)
    elif action == "closed":
        await self._notify_discord(
            f"\u274c **PR #{pr_number} closed**: {title}\n"
            f"by **{author}**\n{html_url}"
        )
        return {"success": True, "message": "PR closed notification sent"}

    if action not in ("opened", "synchronize"):
        logger.info(f"Ignoring PR action: {action}")
        return {"success": True, "message": f"PR action '{action}' not handled"}

    if "/" not in repo_full_name:
        logger.error(f"Invalid repository name: {repo_full_name}")
        return {"success": False, "error": "Invalid repository name"}

    owner, repo_name = repo_full_name.split("/", 1)

    logger.info(f"Running AI review on PR #{pr_number}: {title} (action: {action})")

    # Fetch PR file summary for AI review
    diff_summary = await self.github.get_pr_files(owner, repo_name, pr_number)

    # Run AI review via Open WebUI
    body = pr.get("body", "") or ""
    review = await self.openwebui.analyze_pull_request(
        title=title,
        body=body,
        diff_summary=diff_summary or "No file changes available",
        labels=[label.get("name", "") for label in pr.get("labels", [])],
        model=self.ai_model,
    )

    result = {
        "success": True,
        "pr_number": pr_number,
        "message": "PR review processed",
    }

    # Post review as GitHub comment
    if review:
        formatted = self.github.format_ai_response(review)
        comment_id = await self.github.post_issue_comment(
            owner=owner,
            repo=repo_name,
            issue_number=pr_number,
            body=formatted,
        )
        if comment_id:
            logger.info(f"AI review posted on PR #{pr_number} (comment {comment_id})")
            result["comment_id"] = comment_id
        else:
            logger.warning(f"Failed to post AI review comment on PR #{pr_number}")

        # Discord summary of the review
        # Take first 200 chars of the review as summary
        summary = review[:200].split("\n")[0]
        await self._notify_discord(
            f"\U0001f50d **AI Review for PR #{pr_number}**: {title}\n"
            f"by **{author}** \u2192 `{base_branch}`\n"
            f"{summary}\n{html_url}"
        )
    else:
        logger.warning(f"AI review unavailable for PR #{pr_number} (Open WebUI error)")
        result["message"] = "PR notification sent but AI review unavailable"

    return result
```

**Step 2: Verify the edit**

Read back the modified file and confirm:
- Lines 150+ contain the new `_handle_pull_request_event`
- No reference to `n8n_payload` or `self.n8n.trigger_workflow` in this method
- `_handle_pr_merged` method still intact after the new code
- `_handle_push_event` still intact (still uses n8n forwarding for push events)

**Step 3: Commit**

```bash
git add webhook-handler/handlers/github.py
git commit -m "feat: auto AI review on PR open, bypass broken n8n

Replace n8n forwarding with direct Open WebUI AI review.
On PR opened/synchronize: fetch files, run AI analysis,
post review as GitHub comment, send Discord summary."
```

---

### Task 2: Deploy and test

**Step 1: Deploy to server**

```bash
scp webhook-handler/handlers/github.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/github.py
```

**Step 2: Rebuild and restart webhook-handler**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml build --no-cache webhook-handler && docker compose -f docker-compose.unified.yml up -d webhook-handler"
```

**Step 3: Verify container is healthy**

```bash
ssh root@46.224.193.25 "docker ps | grep webhook-handler"
```

Expected: webhook-handler running, status healthy

**Step 4: Verify logs show no errors**

```bash
ssh root@46.224.193.25 "docker logs webhook-handler 2>&1 | tail -10"
```

Expected: "Webhook handler ready on port 8086", no tracebacks

**Step 5: Test with a real PR**

Either open a test PR on the repo, or check the webhook-handler logs after the next real PR is opened.

To trigger manually, push a small change to a new branch and open a PR.

Expected in logs:
- "Running AI review on PR #N: ..."
- "AI review posted on PR #N (comment XXXXX)"
- "GitHub event notified to Discord"

Expected on GitHub: AI review comment appears on the PR.
Expected on Discord: Two messages — "New PR" notification + "AI Review" summary.
