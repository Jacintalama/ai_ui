"""GitHub webhook event handler."""
from typing import Any, Optional
import logging
import httpx

from clients.openwebui import OpenWebUIClient
from clients.github import GitHubClient
from clients.n8n import N8NClient
from config import settings

logger = logging.getLogger(__name__)


class GitHubWebhookHandler:
    """Handler for GitHub webhook events."""

    def __init__(
        self,
        openwebui_client: OpenWebUIClient,
        github_client: GitHubClient,
        n8n_client: Optional[N8NClient] = None,
        ai_model: str = "gpt-4-turbo",
        ai_system_prompt: str = ""
    ):
        self.openwebui = openwebui_client
        self.github = github_client
        self.n8n = n8n_client
        self.ai_model = ai_model
        self.ai_system_prompt = ai_system_prompt

    async def handle_event(
        self,
        event_type: str,
        payload: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Handle a GitHub webhook event.

        Args:
            event_type: GitHub event type (e.g., 'issues', 'pull_request')
            payload: Webhook payload

        Returns:
            Result dict with success status and details
        """
        if event_type == "issues":
            return await self._handle_issue_event(payload)
        elif event_type == "pull_request":
            return await self._handle_pull_request_event(payload)
        elif event_type == "issue_comment":
            return await self._handle_comment_event(payload)
        elif event_type == "push":
            return await self._handle_push_event(payload)
        elif event_type == "ping":
            return {"success": True, "message": "Pong!"}
        else:
            logger.info(f"Ignoring unsupported event type: {event_type}")
            return {"success": True, "message": f"Event type '{event_type}' not handled"}

    async def _handle_issue_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle issue events (opened, edited, etc.)."""
        action = payload.get("action")

        if action != "opened":
            logger.info(f"Ignoring issue action: {action}")
            return {"success": True, "message": f"Action '{action}' not handled"}

        return await self._analyze_and_comment(payload)

    async def _analyze_and_comment(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Analyze an issue and post AI comment."""
        # Extract issue details
        issue = payload.get("issue", {})
        repo = payload.get("repository", {})

        issue_number = issue.get("number")
        title = issue.get("title", "")
        body = issue.get("body", "")
        labels = [label.get("name", "") for label in issue.get("labels", [])]

        repo_full_name = repo.get("full_name", "")
        if "/" in repo_full_name:
            owner, repo_name = repo_full_name.split("/", 1)
        else:
            logger.error(f"Invalid repository name: {repo_full_name}")
            return {"success": False, "error": "Invalid repository name"}

        logger.info(f"Analyzing issue #{issue_number}: {title}")

        # Get AI analysis
        analysis = await self.openwebui.analyze_github_issue(
            title=title,
            body=body,
            labels=labels,
            model=self.ai_model,
            system_prompt=self.ai_system_prompt
        )

        if not analysis:
            logger.error("Failed to get AI analysis")
            return {"success": False, "error": "Failed to get AI analysis"}

        # Format and post comment
        comment_body = self.github.format_ai_response(analysis)
        comment_id = await self.github.post_issue_comment(
            owner=owner,
            repo=repo_name,
            issue_number=issue_number,
            body=comment_body
        )

        if not comment_id:
            logger.error("Failed to post GitHub comment")
            return {"success": False, "error": "Failed to post comment"}

        logger.info(f"Successfully posted comment {comment_id} on issue #{issue_number}")
        return {
            "success": True,
            "message": "Issue analyzed, comment posted",
            "issue_number": issue_number,
            "comment_id": comment_id
        }

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

    async def _handle_pr_merged(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate and post deployment notes when a PR is merged."""
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        repo_full_name = repo.get("full_name", "")

        if "/" not in repo_full_name:
            return {"success": False, "error": "Invalid repository name"}

        owner, repo_name = repo_full_name.split("/", 1)
        pr_number = pr.get("number")

        logger.info(f"PR #{pr_number} merged in {owner}/{repo_name}, generating deployment notes")

        # Fetch full PR details (files changed, etc.)
        pr_details = await self.github.get_pr_details(owner, repo_name, pr_number)
        if not pr_details:
            logger.error(f"Could not fetch PR #{pr_number} details")
            return {"success": False, "error": "Failed to fetch PR details"}

        # Generate deployment notes via AI
        notes = await self.openwebui.generate_deployment_notes(
            pr_details=pr_details,
            model=self.ai_model,
        )
        if not notes:
            logger.error(f"Could not generate deployment notes for PR #{pr_number}")
            return {"success": False, "error": "Failed to generate deployment notes"}

        # Post as a comment on the PR
        formatted = self.github.format_ai_response(notes)
        comment_id = await self.github.post_issue_comment(owner, repo_name, pr_number, formatted)

        if comment_id:
            logger.info(f"Deployment notes posted to PR #{pr_number} (comment {comment_id})")
            return {
                "success": True,
                "message": "Deployment notes posted",
                "pr_number": pr_number,
                "comment_id": comment_id,
            }
        else:
            logger.error(f"Failed to post deployment notes to PR #{pr_number}")
            return {"success": False, "error": "Failed to post deployment notes comment"}

    async def _handle_comment_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle issue_comment events (created)."""
        action = payload.get("action")

        if action != "created":
            logger.info(f"Ignoring comment action: {action}")
            return {"success": True, "message": f"Comment action '{action}' not handled"}

        comment = payload.get("comment", {})
        issue = payload.get("issue", {})
        repo = payload.get("repository", {})

        # Skip bot comments to avoid infinite loops
        comment_author = comment.get("user", {}).get("login", "")
        if comment.get("user", {}).get("type") == "Bot":
            logger.info(f"Ignoring bot comment from {comment_author}")
            return {"success": True, "message": "Skipped bot comment"}

        comment_body_text = comment.get("body", "")
        issue_number = issue.get("number")
        issue_title = issue.get("title", "")
        issue_body = issue.get("body", "")

        repo_full_name = repo.get("full_name", "")
        if "/" not in repo_full_name:
            logger.error(f"Invalid repository name: {repo_full_name}")
            return {"success": False, "error": "Invalid repository name"}

        owner, repo_name = repo_full_name.split("/", 1)

        logger.info(f"Analyzing comment by {comment_author} on #{issue_number}")

        # Get AI response
        analysis = await self.openwebui.analyze_comment(
            context_title=issue_title,
            context_body=issue_body,
            comment_body=comment_body_text,
            comment_author=comment_author,
            model=self.ai_model,
            system_prompt=self.ai_system_prompt
        )

        if not analysis:
            logger.error("Failed to get AI analysis for comment")
            return {"success": False, "error": "Failed to get AI analysis"}

        # Post reply
        reply_body = self.github.format_ai_response(analysis)
        comment_id = await self.github.post_issue_comment(
            owner=owner,
            repo=repo_name,
            issue_number=issue_number,
            body=reply_body
        )

        if not comment_id:
            logger.error("Failed to post reply comment")
            return {"success": False, "error": "Failed to post comment"}

        logger.info(f"Successfully posted reply {comment_id} on #{issue_number}")
        return {
            "success": True,
            "message": "Comment analyzed, reply posted",
            "issue_number": issue_number,
            "comment_id": comment_id
        }

    async def _handle_push_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle push events — summarize commits."""
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
        pusher = payload.get("pusher", {}).get("name", "unknown")
        commits = payload.get("commits", [])
        repo = payload.get("repository", {})

        if not commits:
            logger.info("Push event with no commits, ignoring")
            return {"success": True, "message": "No commits in push"}

        repo_full_name = repo.get("full_name", "")
        if "/" not in repo_full_name:
            logger.error(f"Invalid repository name: {repo_full_name}")
            return {"success": False, "error": "Invalid repository name"}

        logger.info(f"Analyzing push to {branch} by {pusher} ({len(commits)} commits)")

        # Discord notification
        latest_msg = commits[-1].get("message", "").split("\n")[0] if commits else ""
        await self._notify_discord(
            f"📦 **Push to `{branch}`**: {len(commits)} commit{'s' if len(commits) != 1 else ''} by **{pusher}**\n"
            f"Latest: {latest_msg}\n"
            f"https://github.com/{repo_full_name}/commits/{branch}"
        )

        # Get AI analysis
        analysis = await self.openwebui.analyze_push(
            commits=commits,
            branch=branch,
            pusher=pusher,
            model=self.ai_model,
            system_prompt=self.ai_system_prompt
        )

        if not analysis:
            logger.error("Failed to get AI analysis for push")
            return {"success": False, "error": "Failed to get AI analysis"}

        # For push events, we log the analysis but don't post anywhere by default
        logger.info(f"Push analysis complete for {branch}: {analysis[:200]}...")

        result = {
            "success": True,
            "message": "Push analyzed",
            "branch": branch,
            "commit_count": len(commits),
            "analysis_preview": analysis[:500]
        }

        # Forward to n8n workflow for additional processing
        if self.n8n:
            try:
                logger.info(f"Forwarding push event to n8n github-push workflow")
                n8n_result = await self.n8n.trigger_workflow(
                    webhook_path="github-push",
                    payload=payload
                )
                if n8n_result:
                    result["n8n_result"] = n8n_result
                    logger.info("n8n workflow completed successfully")
                else:
                    result["n8n_result"] = None
                    logger.warning("n8n workflow returned no result (workflow may not be deployed)")
            except Exception as e:
                logger.error(f"Failed to forward to n8n: {e}")
                result["n8n_error"] = str(e)

        return result
