"""Shared command router for slash commands (Slack & Discord)."""
import asyncio
import json
import shlex
import httpx
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional, Any
import logging
import os

from clients.tasks import TasksClient, TasksAPIError
from handlers.app_builder_panel import (
    build_apps_select_components,
    build_project_menu_components,
    build_schedule_list,
    build_schedules_dashboard,
    build_schedule_card,
)
from handlers import onboarding

from clients.openwebui import OpenWebUIClient
from clients.n8n import N8NClient
from clients.github import GitHubClient
from clients.mcp_proxy import MCPProxyClient
from config import settings, get_service_endpoints

logger = logging.getLogger(__name__)

BUILD_POLL_SECONDS = 12
BUILD_MAX_POLLS = 150  # ~30 min at 12s
BUILD_MAX_CONSECUTIVE_ERRORS = 5

OUTREACH_POLL_SECONDS = 12
OUTREACH_MAX_POLLS = 80   # ~16 min, > agent EXECUTION_TIMEOUT_SECONDS (600s) + n8n
OUTREACH_MAX_CONSECUTIVE_ERRORS = 5
# Public host for building preview links (matches the tasks service's
# AIUI_PUBLIC_DOMAIN default; the domain is otherwise hardcoded elsewhere here).
PUBLIC_DOMAIN = os.environ.get("AIUI_PUBLIC_DOMAIN", "ai-ui.coolestdomain.win")


@dataclass
class CommandContext:
    """Platform-agnostic command context."""
    user_id: str
    user_name: str
    channel_id: str
    raw_text: str
    subcommand: str
    arguments: str
    platform: str  # "slack" or "discord"
    respond: Callable[[str], Awaitable[None]]
    metadata: dict = field(default_factory=dict)
    notify_channel: Optional[Callable[[str], Awaitable[None]]] = None
    # (message, slug, preview_url) -> post a rich channel message (e.g. with a
    # Publish button). Set by the Discord layer; None on other platforms.
    notify_channel_rich: Optional[Callable[[str, str, str, str], Awaitable[None]]] = None
    # (public_url) -> edit the publish reply to show the live URL + Enhance/Unpublish
    # buttons. Set by the Discord layer; None elsewhere.
    on_published: Optional[Callable[[str], Awaitable[None]]] = None
    # (message, components) -> edit the interaction reply to include Discord
    # components (the apps dropdown or a per-project menu). Set by the Discord
    # layer; None on other platforms.
    respond_components: Optional[Callable[[str, list], Awaitable[None]]] = None
    # (msg_dict) -> post a full message dict (content/embeds/components) to the
    # channel as a fresh bot-token message that outlives the interaction window.
    # Used to land the outreach review overview. Set by the Discord layer; None
    # on other platforms.
    notify_channel_msg: Optional[Callable[[dict], Awaitable[None]]] = None
    # (msg_dict) -> edit the interactive message in place (content/embeds/
    # components). Used by the outreach select/edit/send handlers so the review
    # overview updates without spawning a new message. Set by the Discord layer
    # (Task 8 wires an UPDATE_MESSAGE closure); None on other platforms.
    edit_message: Optional[Callable[[dict], Awaitable[None]]] = None


class VoiceResponseCollector:
    """Collects command output for voice webhook responses."""

    def __init__(self):
        self.messages: list[str] = []

    async def respond(self, msg: str) -> None:
        self.messages.append(msg)

    @property
    def full_result(self) -> str:
        return "\n\n".join(self.messages)

    @property
    def spoken_summary(self) -> str:
        """Last message, stripped of markdown for speech."""
        if not self.messages:
            return "No response."
        text = self.messages[-1]
        import re
        text = re.sub(r'[*_`#\[\]()]', '', text)
        text = re.sub(r'\n+', '. ', text)
        if len(text) > 500:
            text = text[:497] + "..."
        return text


# Health endpoints to check for the status command
SERVICE_ENDPOINTS = get_service_endpoints()


class CommandRouter:
    """Platform-agnostic command dispatcher for /aiui commands."""

    def __init__(
        self,
        openwebui_client: OpenWebUIClient,
        n8n_client: N8NClient,
        ai_model: str = "gpt-4-turbo",
        slack_client=None,
        github_client: Optional[GitHubClient] = None,
        mcp_client: Optional[MCPProxyClient] = None,
        loki_client=None,
        discord_user_email_map: Optional[dict] = None,
        tasks_client: Optional[TasksClient] = None,
    ):
        self.openwebui = openwebui_client
        self.n8n = n8n_client
        self.ai_model = ai_model
        self._slack_client = slack_client
        self._github_client = github_client
        self._mcp_client = mcp_client
        self._loki_client = loki_client

        # New collaborators — read from settings only when not injected.
        if discord_user_email_map is None or tasks_client is None:
            from config import settings
            self._discord_user_email_map = (
                dict(discord_user_email_map)
                if discord_user_email_map is not None
                else dict(settings.discord_user_email_map)
            )
            self._tasks_client = tasks_client or TasksClient(
                base_url=settings.tasks_url,
                internal_secret=settings.internal_callback_secret,
            )
        else:
            self._discord_user_email_map = dict(discord_user_email_map)
            self._tasks_client = tasks_client

        # Strong refs to fire-and-forget background tasks (e.g. _watch_build).
        # asyncio only weak-references running tasks, so without this a long
        # watcher could be GC'd mid-flight. Each task removes itself on done.
        self._background_tasks: set = set()

    @staticmethod
    def parse_command(text: str) -> tuple[str, str]:
        """
        Parse command text into (subcommand, arguments).

        Examples:
            "ask what is MCP" -> ("ask", "what is MCP")
            "workflow pr-review" -> ("workflow", "pr-review")
            "status" -> ("status", "")
            "" -> ("status", "")
            "what is MCP" -> ("ask", "what is MCP")
        """
        text = text.strip()
        if not text:
            return ("status", "")

        parts = text.split(None, 1)
        subcommand = parts[0].lower()
        arguments = parts[1] if len(parts) > 1 else ""

        known_commands = {
            "ask", "workflow", "workflows", "status", "help",
            "report", "pr-review", "pr", "mcp", "diagnose", "analyze",
            "email", "sheets", "rebuild", "web-search",
            "health", "security", "deps", "license",
            "cronjob", "aiuibuilder",
        }
        if subcommand in known_commands:
            return (subcommand, arguments)

        # Unknown subcommand — treat entire text as an ask query
        return ("ask", text)

    async def execute(self, ctx: CommandContext) -> None:
        """Dispatch a command to the appropriate handler."""
        try:
            if ctx.subcommand == "ask":
                await self._handle_ask(ctx)
            elif ctx.subcommand == "workflow":
                await self._handle_workflow(ctx)
            elif ctx.subcommand == "workflows":
                await self._handle_workflows(ctx)
            elif ctx.subcommand == "status":
                await self._handle_status(ctx)
            elif ctx.subcommand == "report":
                await self._handle_report(ctx)
            elif ctx.subcommand in ("pr-review", "pr"):
                await self._handle_pr_review(ctx)
            elif ctx.subcommand == "mcp":
                await self._handle_mcp(ctx)
            elif ctx.subcommand == "cronjob":
                await self._handle_cronjob(ctx)
            elif ctx.subcommand == "aiuibuilder":
                await self._handle_aiuibuilder(ctx)
            elif ctx.subcommand == "diagnose":
                await self._handle_diagnose(ctx)
            elif ctx.subcommand == "analyze":
                await self._handle_analyze(ctx)
            elif ctx.subcommand == "rebuild":
                await self._handle_rebuild(ctx)
            elif ctx.subcommand in ("health", "security", "deps", "license"):
                await self._handle_skill(ctx, ctx.subcommand)
            elif ctx.subcommand == "email":
                await self._handle_email(ctx)
            elif ctx.subcommand == "sheets":
                await self._handle_sheets(ctx)
            elif ctx.subcommand == "web-search":
                await self._handle_web_search(ctx)
            elif ctx.subcommand == "help":
                await self._handle_help(ctx)
            else:
                await ctx.respond(f"Unknown command: `{ctx.subcommand}`. Try `/aiui help`.")
        except Exception as e:
            logger.error(f"Command error ({ctx.subcommand}): {e}", exc_info=True)
            await ctx.respond(f"Error processing command: {e}")

    def _build_ask_system_prompt(self) -> str:
        """Build a context-aware system prompt listing available capabilities."""
        capabilities = [
            "You are AIUI, an AI assistant for a software team. Be concise and actionable.",
            "You are responding to a slash command from a chat platform.",
            "",
            "The user has access to these commands via /aiui:",
            "- `/aiui pr-review <number>` — AI-powered review of a GitHub PR",
            "- `/aiui mcp <server> <tool> [args]` — Execute any MCP tool directly",
            "- `/aiui workflow <name>` — Trigger an n8n automation workflow",
            "- `/aiui workflows` — List available n8n workflows",
            "- `/aiui report` — End-of-day activity summary",
            "- `/aiui status` — Service health check",
        ]

        if self._mcp_client:
            capabilities.append("")
            capabilities.append(
                "MCP (Model Context Protocol) tools are available: Web Search (search & save to KB), "
                "Google Drive, Gmail, GitHub, n8n, Filesystem, Excel, Dashboard, Scheduler, "
                "and 30+ other integrations. If the user's question could be answered by "
                "using an MCP tool, suggest the specific `/aiui mcp <server> <tool>` command."
            )

        if self.n8n.api_key:
            capabilities.append("")
            capabilities.append(
                "n8n workflows are available for automation (PR review, health checks, "
                "deployment status). If the question relates to automating something, "
                "mention they can trigger workflows or ask to see available ones."
            )

        return "\n".join(capabilities)

    async def _handle_ask(self, ctx: CommandContext) -> None:
        """Send a question to the AI and return the response."""
        if not ctx.arguments:
            await ctx.respond("Usage: `/aiui ask <question>`")
            return

        logger.info(f"[{ctx.platform}] ask from {ctx.user_name}: {ctx.arguments[:80]}")

        messages = [
            {"role": "system", "content": self._build_ask_system_prompt()},
            {"role": "user", "content": ctx.arguments},
        ]

        response = await self.openwebui.chat_completion(
            messages=messages,
            model=self.ai_model,
        )

        if not response:
            await ctx.respond("Failed to get AI response. The AI service may be unavailable.")
            return

        # Truncate to platform limits (Slack 3000, Discord 2000)
        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[: limit - 20] + "\n\n... (truncated)"

        await ctx.respond(response)

    async def _handle_workflow(self, ctx: CommandContext) -> None:
        """Trigger an n8n workflow by name (looks up ID via API, then executes)."""
        if not ctx.arguments:
            await ctx.respond("Usage: `/aiui workflow <name>` — triggers an n8n workflow by name.")
            return

        if not self.n8n.api_key:
            await ctx.respond("n8n API not configured (no API key).")
            return

        workflow_name = ctx.arguments.strip()
        logger.info(f"[{ctx.platform}] workflow trigger from {ctx.user_name}: {workflow_name}")

        # Look up workflow ID by name
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.n8n.base_url}/api/v1/workflows",
                    headers={"X-N8N-API-KEY": self.n8n.api_key},
                )
                resp.raise_for_status()
                data = resp.json()

            wf_list = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(wf_list, list):
                wf_list = []

            # Case-insensitive name match
            match = next(
                (w for w in wf_list if w.get("name", "").lower() == workflow_name.lower()),
                None,
            )

            if not match:
                available = [w.get("name") for w in wf_list if w.get("active")]
                names_str = ", ".join(f"`{n}`" for n in available) if available else "none"
                await ctx.respond(
                    f"Workflow `{workflow_name}` not found.\n"
                    f"Active workflows: {names_str}"
                )
                return

            if not match.get("active"):
                await ctx.respond(f"Workflow `{match['name']}` exists but is **inactive**. Activate it in n8n first.")
                return

            workflow_id = match["id"]

            # Check if workflow has a webhook trigger node — use webhook path if so
            webhook_path = None
            for node in match.get("nodes", []):
                if "webhook" in node.get("type", "").lower() and "respond" not in node.get("name", "").lower():
                    webhook_path = node.get("parameters", {}).get("path")
                    break

            # If nodes weren't in the list response, fetch full workflow to find webhook path
            if webhook_path is None:
                try:
                    detail_resp = await httpx.AsyncClient(timeout=15.0).__aenter__()
                    full_resp = await detail_resp.get(
                        f"{self.n8n.base_url}/api/v1/workflows/{workflow_id}",
                        headers={"X-N8N-API-KEY": self.n8n.api_key},
                    )
                    await detail_resp.__aexit__(None, None, None)
                    if full_resp.status_code == 200:
                        full_data = full_resp.json()
                        for node in full_data.get("nodes", []):
                            if "webhook" in node.get("type", "").lower() and "respond" not in node.get("name", "").lower():
                                webhook_path = node.get("parameters", {}).get("path")
                                break
                except Exception as e:
                    logger.warning(f"Could not fetch workflow details: {e}")

        except Exception as e:
            logger.error(f"Error looking up workflow: {e}")
            await ctx.respond(f"Failed to look up workflow: {e}")
            return

        # Trigger via webhook path if available, otherwise via API execute
        payload = {
            "triggered_by": ctx.user_name,
            "platform": ctx.platform,
            "channel": ctx.channel_id,
        }

        if webhook_path:
            logger.info(f"Triggering workflow '{match['name']}' via webhook path: {webhook_path}")
            result = await self.n8n.trigger_workflow(webhook_path=webhook_path, payload=payload)
        else:
            logger.info(f"Triggering workflow '{match['name']}' via API (id={workflow_id})")
            result = await self.n8n.trigger_workflow_by_id(workflow_id=workflow_id, payload=payload)

        if result is not None:
            summary = str(result)[:500]
            await ctx.respond(f"Workflow `{match['name']}` triggered successfully.\n```\n{summary}\n```")
        else:
            await ctx.respond(f"Failed to trigger workflow `{match['name']}`. Check n8n status.")

    async def _handle_status(self, ctx: CommandContext) -> None:
        """Check service health and report status."""
        logger.info(f"[{ctx.platform}] status check from {ctx.user_name}")

        async def _check(name: str, url: str, client: httpx.AsyncClient) -> str:
            try:
                resp = await client.get(url)
                if resp.status_code < 400:
                    return f"  {name}: healthy ({resp.status_code})"
                return f"  {name}: unhealthy ({resp.status_code})"
            except Exception:
                return f"  {name}: unreachable"

        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[_check(name, url, client) for name, url in SERVICE_ENDPOINTS.items()]
            )

        lines = ["*Service Status*\n"] + list(results)
        await ctx.respond("\n".join(lines))

    @staticmethod
    def _help_text() -> str:
        return (
            "**Here's what I can do**\n"
            "• \U0001f680 **Build an app** — describe a website and I'll build it.\n"
            "• ⏰ **Schedule a task** — run something on a repeat (e.g. "
            "*summarize my emails every morning*).\n"
            "• \U0001f4ac **Ask a question** — just type `/aiui ask <your question>`.\n"
            "\nTip: tap a button in the **AIUI App Builder** panel — no commands needed.\n"
            "\n_Advanced (for technical users):_ `/aiui aiuibuilder`, `/aiui mcp`, `/aiui pr-review`, "
            "`/aiui analyze`, `/aiui security`, `/aiui web-search`."
        )

    async def _handle_help(self, ctx: CommandContext) -> None:
        """Show available commands."""
        text = self._help_text()
        if ctx.platform != "slack" and ctx.respond_components is not None:
            await ctx.respond_components(text, onboarding.welcome_components_discord())
            return
        await ctx.respond(text)

    async def _handle_diagnose(self, ctx: CommandContext) -> None:
        """Query Loki for error logs and run AI diagnosis."""
        if not self._loki_client:
            await ctx.respond("Loki not configured. Cannot run diagnosis.")
            return

        container_name = ctx.arguments.strip() if ctx.arguments else ""
        target = container_name or "all containers"

        logger.info(f"[{ctx.platform}] diagnose '{target}' from {ctx.user_name}")
        await ctx.respond(f"Diagnosing **{target}**... (querying last 5 minutes of error logs)")

        logs = await self._loki_client.query_error_logs(
            container_name=container_name,
            minutes=5,
            limit=50,
        )

        if not logs:
            await ctx.respond(f"No recent errors found for **{target}** in the last 5 minutes.")
            return

        logs_text = "\n".join(logs[:30])

        messages = [
            {"role": "system", "content": (
                "You are a DevOps diagnostic assistant. Analyze these container error logs and provide:\n"
                "1) Root cause - what went wrong\n"
                "2) Impact - what's affected\n"
                "3) Suggested fix - specific commands or config changes\n"
                "Be concise. Max 3-4 sentences per section."
            )},
            {"role": "user", "content": (
                f"Container: {target}\n"
                f"Error logs (last 5 minutes, {len(logs)} lines):\n{logs_text}"
            )},
        ]

        diagnosis = await self.openwebui.chat_completion(
            messages=messages,
            model=self.ai_model,
        )

        if not diagnosis:
            # Fallback: show raw logs
            raw = logs_text[:1500]
            await ctx.respond(
                f"AI diagnosis unavailable. Raw error logs for **{target}**:\n```\n{raw}\n```"
            )
            return

        response = f"\U0001f50d **Diagnosis for {target}** ({len(logs)} errors, last 5 min)\n\n{diagnosis}"

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"

        await ctx.respond(response)

    async def _handle_analyze(self, ctx: CommandContext) -> None:
        """Extract business requirements from a GitHub repository."""
        # Parse owner/repo from arguments, default to configured repo
        repo_arg = ctx.arguments.strip() if ctx.arguments else ""
        if repo_arg and "/" in repo_arg:
            parts = repo_arg.split("/", 1)
            owner, repo = parts[0], parts[1]
        elif repo_arg:
            await ctx.respond(
                f"Invalid format: `{repo_arg}`. Use `/aiui analyze owner/repo`"
            )
            return
        else:
            parts = settings.report_github_repo.split("/", 1)
            if len(parts) != 2:
                await ctx.respond("No default repository configured.")
                return
            owner, repo = parts

        logger.info(f"[{ctx.platform}] analyze {owner}/{repo} from {ctx.user_name}")
        await ctx.respond(
            f"Analyzing **{owner}/{repo}**... (extracting business requirements, this may take 1-3 minutes)"
        )

        # Try claude-analyzer container first
        result = await self._request_claude_analysis(owner, repo)

        if result:
            report = result.get("report", "")
            stories = result.get("user_stories", [])
            duration = result.get("duration_seconds", 0)

            response = f"**Business Requirements: {owner}/{repo}**\n\n{report}"

            if stories:
                story_lines = "\n".join(
                    f"- As a **{s.get('role', '?')}**, I want {s.get('feature', '?')}, so that {s.get('benefit', '?')}."
                    for s in stories[:10]
                )
                response += f"\n\n**User Stories**\n{story_lines}"

            response += f"\n\n_Analyzed in {duration}s by Claude Code CLI_"
        else:
            # Fallback to Open WebUI analysis
            if not self._github_client:
                await ctx.respond("Claude analyzer unavailable and GitHub not configured.")
                return

            overview = await self._github_client.get_repo_overview(owner, repo)
            if not overview:
                await ctx.respond(f"Failed to fetch repository `{owner}/{repo}`.")
                return

            analysis = await self.openwebui.analyze_codebase(
                repo_overview=overview, model=self.ai_model
            )
            if analysis:
                response = f"**Analysis of {owner}/{repo}** (Open WebUI fallback)\n\n{analysis}"
            else:
                desc = overview.get("description", "No description")
                lang = overview.get("language", "Unknown")
                tree_preview = "\n".join(overview.get("tree", [])[:20])
                response = (
                    f"AI analysis unavailable. Raw info for **{owner}/{repo}**:\n"
                    f"**Description:** {desc}\n**Language:** {lang}\n"
                    f"```\n{tree_preview}\n```"
                )

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"
        await ctx.respond(response)

    async def _request_claude_analysis(
        self, owner: str, repo: str, branch: str = "main"
    ) -> Optional[dict]:
        """Request business requirements analysis from claude-analyzer container."""
        analyzer_url = settings.claude_analyzer_url
        if not analyzer_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=360.0) as client:
                resp = await client.post(
                    f"{analyzer_url}/analyze",
                    json={"owner": owner, "repo": repo, "branch": branch},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        return data
                logger.warning(
                    f"claude-analyzer /analyze returned {resp.status_code}: {resp.text[:200]}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.info(f"claude-analyzer unavailable, falling back to Open WebUI: {e}")
            return None
        except Exception as e:
            logger.warning(f"claude-analyzer error: {e}")
            return None

    async def _handle_rebuild(self, ctx: CommandContext) -> None:
        """Research solutions and generate rebuild plan for a GitHub repository."""
        repo_arg = ctx.arguments.strip() if ctx.arguments else ""
        if repo_arg and "/" in repo_arg:
            parts = repo_arg.split("/", 1)
            owner, repo = parts[0], parts[1]
        elif repo_arg:
            await ctx.respond(
                f"Invalid format: `{repo_arg}`. Use `/aiui rebuild owner/repo`"
            )
            return
        else:
            parts = settings.report_github_repo.split("/", 1)
            if len(parts) != 2:
                await ctx.respond("No default repository configured.")
                return
            owner, repo = parts

        logger.info(f"[{ctx.platform}] rebuild {owner}/{repo} from {ctx.user_name}")
        await ctx.respond(
            f"Researching solutions for **{owner}/{repo}**... "
            f"(Phase 1: web search for existing solutions, Phase 2: plan/PRD generation. "
            f"This takes 3-5 minutes)"
        )

        result = await self._request_claude_rebuild(owner, repo)

        if not result:
            await ctx.respond(
                "Rebuild analysis failed. Claude analyzer may be unavailable or busy.\n"
                "Try again in a few minutes, or run `/aiui analyze` first to warm the cache."
            )
            return

        recommendation = result.get("recommendation", "unknown")
        solutions = result.get("solutions", [])
        plan = result.get("plan", "")
        prd = result.get("prd")
        duration = result.get("duration_seconds", 0)

        # Build Discord response
        if recommendation == "custom-build":
            emoji = "\U0001f528"  # hammer
            header = f"{emoji} **Rebuild Analysis: {owner}/{repo}**\n\n"
            header += f"**Recommendation: Custom Build**\n"
            header += f"{result.get('research_summary', '')[:300]}\n"
            if prd:
                response = header + f"\n**PRD Summary**\n{prd[:800]}"
            else:
                response = header + f"\n{plan[:800]}"
        else:
            emoji = "\U0001f50d"  # magnifying glass
            header = f"{emoji} **Rebuild Analysis: {owner}/{repo}**\n\n"
            top_solution = solutions[0]["name"] if solutions else "Unknown"
            header += f"**Recommendation: {recommendation.replace('-', ' ').title()} — {top_solution}**\n\n"

            sol_lines = []
            for i, s in enumerate(solutions[:3], 1):
                pros = ", ".join(s.get("pros", [])[:3])
                cons = ", ".join(s.get("cons", [])[:2])
                sol_lines.append(
                    f"{i}. **{s['name']}** ({s.get('type', '?')}, {s.get('fit_score', '?')}/100)\n"
                    f"   Pros: {pros}\n"
                    f"   Cons: {cons}\n"
                    f"   Effort: {s.get('effort', '?')}"
                )
            response = header + "\n".join(sol_lines)
            if plan:
                response += f"\n\n**Plan**\n{plan[:400]}"

        response += f"\n\n_Completed in {duration}s by Claude Code CLI_"

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"
        await ctx.respond(response)

    async def _request_claude_rebuild(
        self, owner: str, repo: str, branch: str = "main"
    ) -> Optional[dict]:
        """Request rebuild analysis from claude-analyzer container."""
        analyzer_url = settings.claude_analyzer_url
        if not analyzer_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=960.0) as client:
                resp = await client.post(
                    f"{analyzer_url}/rebuild",
                    json={"owner": owner, "repo": repo, "branch": branch},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        return data
                logger.warning(
                    f"claude-analyzer /rebuild returned {resp.status_code}: {resp.text[:200]}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.info(f"claude-analyzer /rebuild unavailable: {e}")
            return None
        except Exception as e:
            logger.warning(f"claude-analyzer /rebuild error: {e}")
            return None

    async def _handle_skill(self, ctx: CommandContext, skill_name: str) -> None:
        """Run a generic Claude analyzer skill on a GitHub repository."""
        repo_arg = ctx.arguments.strip() if ctx.arguments else ""
        if repo_arg and "/" in repo_arg:
            parts = repo_arg.split("/", 1)
            owner, repo = parts[0], parts[1]
        elif repo_arg:
            await ctx.respond(
                f"Invalid format: `{repo_arg}`. Use `/aiui {skill_name} owner/repo`"
            )
            return
        else:
            parts = settings.report_github_repo.split("/", 1)
            if len(parts) != 2:
                await ctx.respond("No default repository configured.")
                return
            owner, repo = parts

        skill_labels = {
            "health": ("\U0001f3e5", "Health Report"),
            "security": ("\U0001f512", "Security Audit"),
            "deps": ("\U0001f4e6", "Dependency Report"),
            "license": ("\u2696\ufe0f", "License Report"),
        }
        emoji, label = skill_labels.get(skill_name, ("\U0001f527", skill_name.title()))

        logger.info(f"[{ctx.platform}] {skill_name} {owner}/{repo} from {ctx.user_name}")
        await ctx.respond(
            f"Running **{label}** on **{owner}/{repo}**... "
            f"(This takes 2-5 minutes)"
        )

        result = await self._request_skill(owner, repo, skill_name)

        if not result:
            await ctx.respond(
                f"{label} failed. Claude analyzer may be unavailable or busy.\n"
                "Try again in a few minutes."
            )
            return

        results = result.get("results", {})
        cached = result.get("cached", False)
        duration = result.get("duration_seconds", 0)
        cache_note = " (cached)" if cached else ""

        response = self._format_skill_response(
            skill_name, owner, repo, results, emoji, label, duration, cache_note
        )

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"
        await ctx.respond(response)

    def _format_skill_response(
        self, skill_name: str, owner: str, repo: str,
        results: dict, emoji: str, label: str,
        duration: float, cache_note: str,
    ) -> str:
        """Format skill results for Discord/Slack."""
        header = f"{emoji} **{label}: {owner}/{repo}**\n\n"

        if skill_name == "health":
            score = results.get("score", "?")
            bar = self._score_bar(score) if isinstance(score, (int, float)) else ""
            summary = results.get("summary", "No summary available.")
            findings = results.get("findings", [])
            recs = results.get("recommendations", [])

            body = f"**Score: {score}/100** {bar}\n\n{summary}\n\n"
            if findings:
                body += f"\U0001f4cb **Findings ({len(findings)})**\n"
                for f in findings[:8]:
                    sev_icon = {
                        "critical": "\U0001f534", "high": "\U0001f534",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2",
                    }.get(f.get("severity", ""), "\u26aa")
                    body += f"{sev_icon} {f.get('title', 'Unknown')}\n"
                if len(findings) > 8:
                    body += f"... +{len(findings) - 8} more\n"
            if recs:
                body += f"\n\U0001f4a1 **Top Recommendations**\n"
                for i, r in enumerate(recs[:5], 1):
                    body += f"{i}. {r}\n"

        elif skill_name == "security":
            risk = results.get("risk_level", "unknown").upper()
            summary = results.get("summary", "No summary available.")
            vulns = results.get("vulnerabilities", [])
            positives = results.get("positive_findings", [])

            body = f"**Risk Level: {risk}**\n\n{summary}\n\n"
            if vulns:
                body += f"\U0001f6a8 **Vulnerabilities ({len(vulns)})**\n"
                for v in vulns[:8]:
                    sev_icon = {
                        "critical": "\U0001f534", "high": "\U0001f534",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2",
                    }.get(v.get("severity", ""), "\u26aa")
                    loc = f" ({v['location']})" if v.get("location") else ""
                    body += f"{sev_icon} **{v.get('severity', '').upper()}**: {v.get('title', 'Unknown')}{loc}\n"
                if len(vulns) > 8:
                    body += f"... +{len(vulns) - 8} more\n"
            if positives:
                body += f"\n\u2705 **Done Well**\n"
                for p in positives[:3]:
                    body += f"- {p}\n"

        elif skill_name == "deps":
            total = results.get("total_deps", "?")
            outdated = results.get("outdated_count", "?")
            vuln = results.get("vulnerable_count", "?")
            issues = results.get("issues", [])

            body = f"**Total: {total} | Outdated: {outdated} | Vulnerable: {vuln}**\n\n"
            if issues:
                for iss in issues[:10]:
                    sev_icon = {
                        "critical": "\U0001f534", "high": "\U0001f534",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2",
                    }.get(iss.get("severity", ""), "\u26aa")
                    cves = ", ".join(iss.get("cves", []))
                    cve_text = f" ({cves})" if cves else ""
                    body += f"{sev_icon} **{iss.get('package', '?')}** {iss.get('current_version', '?')} \u2192 {iss.get('latest_version', '?')}{cve_text}\n"
                if len(issues) > 10:
                    body += f"... +{len(issues) - 10} more\n"

        elif skill_name == "license":
            status = results.get("status", "unknown")
            status_icon = {"clean": "\u2705", "warning": "\u26a0\ufe0f", "violation": "\U0001f6d1"}.get(status, "\u2753")
            dist = results.get("distribution", {})
            risks = results.get("risks", [])

            dist_text = " | ".join(f"{k} ({v})" for k, v in list(dist.items())[:6])
            body = f"**Status: {status_icon} {status.upper()}**\n\n"
            if dist_text:
                body += f"\U0001f4ca **Distribution:** {dist_text}\n\n"
            if risks:
                for r in risks[:6]:
                    sev_icon = {
                        "critical": "\U0001f534", "high": "\U0001f534",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2",
                    }.get(r.get("severity", ""), "\u26aa")
                    body += f"{sev_icon} **{r.get('package', '?')}** ({r.get('license', '?')}) \u2014 {r.get('risk_type', '?')}\n"
                if len(risks) > 6:
                    body += f"... +{len(risks) - 6} more\n"

        else:
            body = json.dumps(results, indent=2)[:1000]

        return header + body + f"\n\n_Completed in {duration}s{cache_note} by Claude Code CLI_"

    @staticmethod
    def _score_bar(score: int, width: int = 10) -> str:
        filled = round(score / 100 * width)
        return "\u2588" * filled + "\u2591" * (width - filled)

    async def _request_skill(
        self, owner: str, repo: str, skill_name: str, branch: str = "main"
    ) -> Optional[dict]:
        """Request a skill run from claude-analyzer container."""
        analyzer_url = settings.claude_analyzer_url
        if not analyzer_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=960.0) as client:
                resp = await client.post(
                    f"{analyzer_url}/skill",
                    json={"owner": owner, "repo": repo, "branch": branch, "skill": skill_name},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        return data
                logger.warning(
                    f"claude-analyzer /skill/{skill_name} returned {resp.status_code}: {resp.text[:200]}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.info(f"claude-analyzer /skill/{skill_name} unavailable: {e}")
            return None
        except Exception as e:
            logger.warning(f"claude-analyzer /skill/{skill_name} error: {e}")
            return None

    async def _handle_email(self, ctx: CommandContext) -> None:
        """Summarize recent emails via n8n Gmail workflow."""
        if not self.n8n or not self.n8n.api_key:
            await ctx.respond("n8n not configured. Cannot access Gmail.")
            return

        logger.info(f"[{ctx.platform}] email summary from {ctx.user_name}")
        await ctx.respond("Fetching email summary... (triggering Gmail workflow)")

        result = await self._trigger_n8n_by_name(
            "gmail-inbox-summary",
            payload={"action": "summary", "limit": 10},
        )

        if result is None:
            await ctx.respond(
                "Gmail workflow not found in n8n. Please create a workflow named "
                "`gmail-inbox-summary` with a Webhook trigger and Gmail node.\n"
                "n8n UI: https://ai-ui.coolestdomain.win/n8n"
            )
            return

        if isinstance(result, dict) and result.get("status") == "error":
            response = (
                "\u274c **Email workflow error**\n\n"
                "The Gmail workflow ran but returned no data. Likely causes:\n"
                "- Gmail OAuth credential not connected in n8n\n"
                "- OAuth token expired — re-authorize in n8n Credentials\n\n"
                f"Check: https://ai-ui.coolestdomain.win/n8n"
            )
        elif isinstance(result, dict) and "emails" in result:
            emails = result["emails"]
            if not emails:
                response = "\U0001f4e7 **Email Summary**\n\nNo unread emails found."
            else:
                emails_text = json.dumps(emails, indent=2)[:3000]
                messages = [
                    {"role": "system", "content": (
                        "Summarize these emails concisely. For each: sender, subject, "
                        "1-line summary. Group by importance. Be brief."
                    )},
                    {"role": "user", "content": f"Recent emails:\n{emails_text}"},
                ]
                summary = await self.openwebui.chat_completion(
                    messages=messages, model=self.ai_model
                )
                if summary:
                    response = f"\U0001f4e7 **Email Summary**\n\n{summary}"
                else:
                    response = f"\U0001f4e7 **Email Summary** (raw)\n```\n{emails_text[:1500]}\n```"
        elif isinstance(result, dict) and result.get("summary"):
            response = f"\U0001f4e7 **Email Summary**\n\n{result['summary']}"
        else:
            response = f"\U0001f4e7 **Email Summary**\n\n{json.dumps(result, indent=2)[:1500]}"

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"
        await ctx.respond(response)

    async def _handle_sheets(self, ctx: CommandContext) -> None:
        """Generate a report and write to Google Sheets via n8n."""
        if not self.n8n or not self.n8n.api_key:
            await ctx.respond("n8n not configured. Cannot access Google Sheets.")
            return

        report_type = ctx.arguments.strip().lower() if ctx.arguments else "daily"
        if report_type not in ("daily", "errors"):
            await ctx.respond("Usage: `/aiui sheets [daily|errors]`")
            return

        logger.info(f"[{ctx.platform}] sheets {report_type} report from {ctx.user_name}")
        await ctx.respond(f"Generating **{report_type}** report for Google Sheets...")

        if report_type == "daily":
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            commits, executions, health = await asyncio.gather(
                self._gather_github_commits(today_start),
                self._gather_n8n_executions(today_start),
                self._gather_health(),
            )
            payload = {
                "action": "daily_report",
                "date": now.strftime("%Y-%m-%d"),
                "commits": commits or [],
                "executions": executions or [],
                "health": health,
            }
        else:
            logs = []
            if self._loki_client:
                logs = await self._loki_client.query_error_logs(
                    container_name="", minutes=60, limit=50
                )
            payload = {
                "action": "error_report",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "errors": logs,
                "error_count": len(logs),
            }

        result = await self._trigger_n8n_by_name(
            "sheets-report",
            payload=payload,
        )

        if result is None:
            await ctx.respond(
                "Sheets workflow not found in n8n. Please create a workflow named "
                "`sheets-report` with a Webhook trigger and Google Sheets node.\n"
                "n8n UI: https://ai-ui.coolestdomain.win/n8n"
            )
            return

        if isinstance(result, dict) and result.get("status") == "error":
            await ctx.respond(
                f"\u274c **Sheets workflow error**\n\n"
                "The sheets-report workflow ran but returned no data. Likely causes:\n"
                "- Google Sheets OAuth credential not connected\n"
                "- Sheet ID not configured (still has placeholder)\n"
                "- OAuth token expired\n\n"
                "Check: https://ai-ui.coolestdomain.win/n8n"
            )
        elif isinstance(result, dict) and result.get("sheet_url"):
            await ctx.respond(
                f"\u2705 **{report_type.title()} report** written to Google Sheets!\n"
                f"{result['sheet_url']}"
            )
        else:
            await ctx.respond(
                f"\u2705 **{report_type.title()} report** sent to Google Sheets workflow.\n"
                f"Response: {json.dumps(result, indent=2)[:500]}"
            )

    async def _trigger_n8n_by_name(
        self, workflow_name: str, payload: dict = None
    ) -> Optional[Any]:
        """Find an n8n workflow by name and trigger it. Returns result or None."""
        try:
            headers = {
                "X-N8N-API-KEY": self.n8n.api_key,
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.n8n.base_url}/api/v1/workflows",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            workflows = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(workflows, list):
                return None

            target = None
            for wf in workflows:
                if wf.get("name", "").lower() == workflow_name.lower():
                    target = wf
                    break

            if not target:
                return None

            nodes = target.get("nodes", [])
            webhook_path = None
            for node in nodes:
                if "webhook" in node.get("type", "").lower():
                    webhook_path = node.get("parameters", {}).get("path", "")
                    break

            if webhook_path:
                return await self.n8n.trigger_workflow(
                    webhook_path=webhook_path, payload=payload or {}
                )
            else:
                return await self.n8n.trigger_workflow_by_id(
                    workflow_id=target["id"], payload=payload or {}
                )
        except Exception as e:
            logger.error(f"Error triggering n8n workflow '{workflow_name}': {e}")
            return None

    async def _handle_report(self, ctx: CommandContext) -> None:
        """Generate an end-of-day report with AI summary."""
        logger.info(f"[{ctx.platform}] report from {ctx.user_name}")
        await ctx.respond("Generating report... (gathering data from GitHub, n8n, and services)")

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        # Gather data from all sources in parallel
        commits, executions, health = await asyncio.gather(
            self._gather_github_commits(today_start),
            self._gather_n8n_executions(today_start),
            self._gather_health(),
        )

        # Build prompt
        date_str = now.strftime("%B %d, %Y")
        sections = [f"Generate an end-of-day report for {date_str}.\n"]

        if commits is not None:
            commit_lines = [f"- `{c['sha']}` {c['author']}: {c['message']}" for c in commits]
            sections.append(f"## GitHub Commits ({len(commits)})\n" + ("\n".join(commit_lines) if commit_lines else "No commits today."))
        else:
            sections.append("## GitHub Commits\nGitHub data unavailable (no token configured).")

        if executions is not None:
            exec_lines = [f"- {e['workflow_name']}: {e['status']} (started {e['started']})" for e in executions]
            sections.append(f"## n8n Executions ({len(executions)})\n" + ("\n".join(exec_lines) if exec_lines else "No executions today."))
        else:
            sections.append("## n8n Executions\nn8n data unavailable (no API key configured).")

        health_lines = [f"- {h['service']}: {h['status']}" for h in health]
        sections.append(f"## Service Health\n" + "\n".join(health_lines))

        prompt_text = "\n\n".join(sections)

        # Get AI summary
        messages = [
            {"role": "system", "content": (
                "You are a concise daily report generator for a software team. "
                "Summarize the day's activity from GitHub commits, n8n workflow executions, "
                "and service health data. Be brief — bullet points, not paragraphs. "
                "Highlight anything notable: failures, large changes, unusual patterns."
            )},
            {"role": "user", "content": prompt_text},
        ]

        response = await self.openwebui.chat_completion(
            messages=messages,
            model=self.ai_model,
        )

        if not response:
            # Fallback to raw data
            response = f"*Daily Report — {date_str}*\n(AI summary unavailable)\n\n{prompt_text}"

        # Truncate for platform limits
        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"

        await ctx.respond(response)

        # Also post to Slack channel if configured
        if settings.report_slack_channel and self._slack_client:
            try:
                await self._slack_client.post_message(
                    channel=settings.report_slack_channel,
                    text=response,
                )
            except Exception as e:
                logger.error(f"Failed to post report to Slack channel: {e}")

    async def _handle_pr_review(self, ctx: CommandContext) -> None:
        """Fetch a GitHub PR and run AI review on it."""
        if not ctx.arguments:
            await ctx.respond("Usage: `/aiui pr-review <pr_number>`")
            return

        # Parse PR number
        pr_arg = ctx.arguments.strip().lstrip("#")
        if not pr_arg.isdigit():
            await ctx.respond(f"Invalid PR number: `{ctx.arguments}`. Use `/aiui pr-review 10`")
            return
        pr_number = int(pr_arg)

        if not self._github_client:
            await ctx.respond("GitHub integration not configured (no GITHUB_TOKEN).")
            return

        logger.info(f"[{ctx.platform}] pr-review #{pr_number} from {ctx.user_name}")
        await ctx.respond(f"Reviewing PR #{pr_number}... (fetching data and running AI analysis)")

        # Parse owner/repo
        parts = settings.report_github_repo.split("/", 1)
        if len(parts) != 2:
            await ctx.respond(f"Invalid repository config: `{settings.report_github_repo}`")
            return
        owner, repo = parts

        # Fetch PR details and diff in parallel
        pr_details, diff_summary = await asyncio.gather(
            self._github_client.get_pr_details(owner, repo, pr_number),
            self._github_client.get_pr_files(owner, repo, pr_number),
        )

        if not pr_details:
            await ctx.respond(f"Failed to fetch PR #{pr_number}. Check the PR number and GitHub access.")
            return

        # Run AI review
        response = await self.openwebui.analyze_pull_request(
            title=pr_details["title"],
            body=pr_details.get("body", ""),
            diff_summary=diff_summary or "No diff available",
            labels=[],
            model=self.ai_model,
        )

        if not response:
            # Fallback to raw data
            files_str = diff_summary or "No files"
            response = (
                f"*PR #{pr_number}: {pr_details['title']}*\n"
                f"Author: {pr_details['author']} | "
                f"Branch: `{pr_details['branch']}` -> `{pr_details['base']}`\n"
                f"Changes: {pr_details.get('total_changes', 0)} lines across "
                f"{len(pr_details.get('files_changed', []))} files\n\n"
                f"```\n{files_str[:1500]}\n```\n\n"
                f"(AI review unavailable)"
            )

        # Prepend PR header
        header = f"*Review: PR #{pr_number} — {pr_details['title']}*\n"
        response = header + response

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"

        await ctx.respond(response)

    async def _handle_web_search(self, ctx: CommandContext) -> None:
        """Search the web and save results to Knowledge Base."""
        if not ctx.arguments:
            await ctx.respond(
                "Usage: `/aiui web-search <query>`\n"
                "Example: `/aiui web-search Bitcoin price today`\n"
                "Searches the web and saves results to Knowledge Base."
            )
            return

        query = ctx.arguments.strip()
        await ctx.respond(f"Searching for **{query}**... saving to Knowledge Base.")

        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "http://mcp-web-search:8000/web_save_to_kb",
                    json={"query": query, "kb_name": "Web Research", "count": 3},
                )
                resp.raise_for_status()
                result = resp.json()

            files_saved = result.get("files_saved", 0)
            sources = result.get("results", [])
            source_list = "\n".join(f"- [{s.get('title', 'Link')[:60]}]({s.get('url', '')})" for s in sources)

            await ctx.respond(
                f"Saved **{files_saved} pages** to Knowledge Base **\"Web Research\"**\n\n"
                f"**Sources:**\n{source_list}"
            )
        except Exception as e:
            logger.error(f"Web search error: {e}", exc_info=True)
            await ctx.respond(f"Web search failed: {e}")

    async def _handle_mcp(self, ctx: CommandContext) -> None:
        """Execute an MCP tool via the MCP Proxy."""
        if not self._mcp_client:
            await ctx.respond("MCP Proxy not configured.")
            return

        if not ctx.arguments:
            await ctx.respond(
                "Usage: `/aiui mcp <server> <tool> [json_args]`\n"
                "Example: `/aiui mcp github get_me`\n"
                "Example: `/aiui mcp n8n list_workflows`"
            )
            return

        parts = ctx.arguments.split(None, 2)
        if len(parts) < 2:
            await ctx.respond("Need at least server and tool name. Usage: `/aiui mcp <server> <tool> [json_args]`")
            return

        server_id = parts[0]
        tool_name = parts[1]
        tool_args = {}

        if len(parts) > 2:
            try:
                tool_args = json.loads(parts[2])
            except json.JSONDecodeError:
                await ctx.respond(f"Invalid JSON arguments: `{parts[2]}`")
                return

        logger.info(f"[{ctx.platform}] mcp {server_id}/{tool_name} from {ctx.user_name}")
        await ctx.respond(f"Executing MCP tool `{server_id}/{tool_name}`...")

        result = await self._mcp_client.execute_tool(
            server_id=server_id,
            tool_name=tool_name,
            arguments=tool_args,
        )

        if result is not None:
            result_str = json.dumps(result, indent=2, default=str)
            limit = 2000 if ctx.platform == "discord" else 3000
            code_limit = limit - 100  # room for header
            if len(result_str) > code_limit:
                result_str = result_str[:code_limit - 20] + "\n... (truncated)"
            await ctx.respond(f"*MCP Result:* `{server_id}/{tool_name}`\n```\n{result_str}\n```")
        else:
            await ctx.respond(f"MCP tool `{server_id}/{tool_name}` failed. Check the server/tool name.")

    async def _handle_cronjob(self, ctx: CommandContext) -> None:
        """Discord → user-scoped cron schedule CRUD via tasks service."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return

        try:
            tokens = shlex.split(ctx.arguments) if ctx.arguments else []
        except ValueError:
            await ctx.respond(
                'Couldn\'t parse args. Wrap cron and prompt in double quotes: '
                '`/aiui cronjob create "0 8 * * *" "summarize emails"`'
            )
            return

        action = tokens[0] if tokens else ""
        rest = tokens[1:]

        try:
            if action == "list":
                schedules = await self._tasks_client.list_schedules(email, platform="discord")
                if not schedules:
                    await ctx.respond(
                        "**Your schedules**\n"
                        "no schedules yet. Create one with "
                        '`/aiui cronjob create "<cron>" "<prompt>"`.'
                    )
                    return
                lines = ["**Your schedules**"]
                for s in schedules:
                    state = "on" if s.get("enabled") else "off"
                    lines.append(
                        f"`{s['id']}` `{s['cron_expr']}` — {s['name']} [{state}]"
                    )
                reply = "\n".join(lines)
                if len(reply) > 1990:
                    reply = reply[:1980] + "\n... +more"
                await ctx.respond(reply)

            elif action == "create":
                if len(rest) < 2:
                    await ctx.respond(
                        'Need 2 args: `create "<cron>" "<prompt>"`. '
                        'Example: `/aiui cronjob create "0 8 * * *" "summarize unread emails"`'
                    )
                    return
                cron_expr = rest[0]
                prompt = " ".join(rest[1:])
                name = f"discord-{ctx.user_name}-{cron_expr[:20]}"
                result = await self._tasks_client.create_schedule(
                    email, name=name, cron=cron_expr, prompt=prompt,
                )
                await ctx.respond(
                    f"Schedule created: `{result['id']}`\n"
                    f"`{cron_expr}` — {prompt[:200]}"
                )

            elif action == "delete":
                if not rest:
                    await ctx.respond("Need a schedule id: `delete <id>`")
                    return
                schedule_id = rest[0]
                await self._tasks_client.delete_schedule(email, schedule_id)
                await ctx.respond(f"Deleted `{schedule_id}`.")

            else:
                await ctx.respond(
                    "Usage: `/aiui cronjob <list|create|delete>`"
                )

        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))

    async def _handle_aiuibuilder(self, ctx: CommandContext) -> None:
        """Discord/Slack → App Builder project list / status / open URL."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return

        # Action is the first word; the remainder is parsed per-action so a
        # build description can contain spaces/quotes without shlex choking.
        parts = (ctx.arguments or "").strip().split(None, 1)
        action = parts[0].lower() if parts else ""
        remainder = parts[1] if len(parts) > 1 else ""

        if action == "templates":
            try:
                catalog = await self._tasks_client.list_templates(email)
            except TasksAPIError as e:
                await ctx.respond(self._format_build_error(e))
                return
            if not catalog:
                await ctx.respond("No templates available right now.")
                return
            lines = ["**App Builder templates** — `aiui aiuibuilder build <template> <description>`"]
            for t in catalog:
                key = t.get("key")
                if not key:
                    continue  # tolerate a malformed row rather than KeyError
                note = f" — {t['note']}" if t.get("note") else ""
                lines.append(f"`{key}` — {t.get('label', key)}: {t.get('description', '')}{note}")
            reply = "\n".join(lines)
            if len(reply) > 1990:
                reply = reply[:1980] + "\n... +more"
            await ctx.respond(reply)
            return

        if action == "build":
            # Resolve an optional leading template key from the RAW remainder,
            # before quote-stripping, so `build portfolio "a designer"` works.
            rem = (remainder or "").strip()
            sub = rem.split(None, 1)
            first = (sub[0] if sub else "").lower()
            after = sub[1] if len(sub) > 1 else ""

            # Catalog lets us recognize template keys; resilient — a failure
            # just means a template-less build (the user still gets an app).
            label_by_key: dict[str, str] = {}
            try:
                label_by_key = {
                    t["key"]: t.get("label", t["key"])
                    for t in await self._tasks_client.list_templates(email)
                    if t.get("key")
                }
            except TasksAPIError:
                label_by_key = {}

            if first in label_by_key:
                template_key = first
                description = after.strip().strip('"').strip()
                if not description:
                    description = f"a {label_by_key[first]}"
            else:
                template_key = None
                description = rem.strip('"').strip()

            if not description:
                await ctx.respond(
                    'Usage: `aiuibuilder build [template] <description>` — e.g. '
                    '`aiuibuilder build portfolio a UX designer named Maya`. '
                    'See `aiuibuilder templates`.'
                )
                return
            await self._start_build(
                ctx, email, template_key, description,
                template_label=label_by_key.get(template_key) if template_key else None,
            )
            return

        try:
            rest = shlex.split(remainder) if remainder else []
        except ValueError:
            await ctx.respond("Couldn't parse args. Try `aiuibuilder list`.")
            return

        try:
            if action == "list":
                projects = await self._tasks_client.list_projects(email)
                if not projects:
                    await ctx.respond("**Your apps**\nno projects yet.")
                    return
                lines = ["**Your apps**"]
                for p in projects:
                    pub = p.get("public_url") or "(not published)"
                    lines.append(f"`{p['slug']}` — {p['name']} [{p['role']}] {pub}")
                reply = "\n".join(lines)
                if len(reply) > 1990:
                    reply = reply[:1980] + "\n... +more"
                if ctx.respond_components is not None:
                    await ctx.respond_components(reply, build_apps_select_components(projects))
                else:
                    await ctx.respond(reply)

            elif action == "status":
                if not rest:
                    await ctx.respond("Usage: `aiuibuilder status <slug>`")
                    return
                slug = rest[0]
                status = await self._tasks_client.get_project_status(email, slug)
                lines = [
                    f"**{status['name']}** (`{status['slug']}`)",
                    f"Role: {status['role']}",
                    f"Published: {'yes' if status.get('published') else 'no'}",
                ]
                if status.get("public_url"):
                    lines.append(f"URL: {status['public_url']}")
                if status.get("last_commit_at"):
                    lines.append(f"Last commit: {status['last_commit_at']}")
                await ctx.respond("\n".join(lines))

            elif action == "open":
                if not rest:
                    await ctx.respond("Usage: `aiuibuilder open <slug>`")
                    return
                slug = rest[0]
                status = await self._tasks_client.get_project_status(email, slug)
                if not status.get("published"):
                    await ctx.respond(
                        f"`{slug}` isn't published yet. Click **Publish** on its build "
                        "message, or rebuild it to get a fresh Publish button."
                    )
                    return
                await ctx.respond(f"`{slug}` → {status['public_url']}")

            else:
                await ctx.respond("Usage: `/aiui aiuibuilder <build|templates|list|status|open> [args]`")

        except TasksAPIError as e:
            if e.status == 404:
                await ctx.respond("Project not found or not yours.")
            elif e.status == 0:
                await ctx.respond("Tasks service unreachable, try again.")
            else:
                await ctx.respond(f"Tasks API error ({e.status}).")

    async def _start_build(
        self, ctx: CommandContext, email: str, template_key: str | None,
        description: str, *, template_label: str | None = None,
    ) -> None:
        """Start a one-shot build and wire the result watcher.

        Shared by the `/aiui aiuibuilder build` text path and the App Builder
        channel button/modal path. `description` must be non-empty (callers
        validate). `template_label`, when given, is named in the ack."""
        try:
            result = await self._tasks_client.start_build(
                email, description, template_key=template_key)
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        slug = result["slug"]
        task_id = result["task_id"]
        tnote = f" (from the {template_label} template)" if template_label else ""
        await ctx.respond(
            f"Building `{slug}`{tnote} … I'll post the link here when it's ready "
            "(usually a few minutes)."
        )
        if ctx.notify_channel is not None:
            watcher = asyncio.create_task(self._watch_build(ctx, email, task_id, slug))
            self._background_tasks.add(watcher)
            watcher.add_done_callback(self._background_tasks.discard)

    async def run_panel_build(
        self, ctx: CommandContext, template_key: str | None, description: str,
    ) -> None:
        """App Builder channel entry (a button+modal submit). Resolves the
        caller's email, validates, then starts the build. The template key is
        explicit (from the clicked button), so — unlike the free-text `build`
        path — a Blank build whose first word matches a template key is never
        misread as a template build."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        description = (description or "").strip()
        if not description:
            await ctx.respond("Please describe the app you want to build.")
            return
        await self._start_build(ctx, email, template_key, description)

    async def run_panel_publish(self, ctx: CommandContext, slug: str) -> None:
        """App Builder channel entry for the Publish button. Resolves the
        caller's email and publishes their built app, then posts the live URL.
        Ownership is enforced server-side (only the app's owner can publish)."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            result = await self._tasks_client.publish_app(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_publish_error(e))
            return
        url = (result.get("public_url") or "").strip()
        if ctx.on_published is not None and url:
            try:
                await ctx.on_published(url)
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("on_published failed slug=%s: %s", slug, exc)
        url_part = f" Live at {url}" if url else ""
        await ctx.respond(f"\U0001f389 Published!{url_part}")

    async def run_panel_enhance(self, ctx: CommandContext, slug: str, prompt: str) -> None:
        """App Builder Enhance: edit an existing app from a typed change, then
        watch it like a build and post the updated preview."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        prompt = (prompt or "").strip()
        if not prompt:
            await ctx.respond("Tell me what to change.")
            return
        try:
            result = await self._tasks_client.enhance_app(email, slug, prompt)
        except TasksAPIError as e:
            await ctx.respond(self._format_enhance_error(e))
            return
        task_id = result["task_id"]
        await ctx.respond(
            f"Updating `{slug}` … I'll post the new preview here when it's ready."
        )
        if ctx.notify_channel is not None:
            watcher = asyncio.create_task(self._watch_build(ctx, email, task_id, slug))
            self._background_tasks.add(watcher)
            watcher.add_done_callback(self._background_tasks.discard)

    async def run_panel_unpublish(self, ctx: CommandContext, slug: str) -> None:
        """App Builder Unpublish: take a live app offline."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.unpublish_app(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_unpublish_error(e))
            return
        await ctx.respond(f"`{slug}` is offline now (unpublished).")

    async def run_panel_delete(self, ctx: CommandContext, slug: str) -> None:
        """App Builder Delete: permanently remove an app (after confirm)."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.delete_app(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_delete_error(e))
            return
        await ctx.respond(f"`{slug}` has been deleted.")

    async def run_panel_menu(self, ctx: CommandContext, slug: str) -> None:
        """App Builder dropdown selection → post that app's ephemeral action menu.
        Fetches fresh status so the menu reflects current publish state."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            status = await self._tasks_client.get_project_status(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_status_error(e))
            return
        name = status.get("name", slug)
        published = bool(status.get("published"))
        public_url = (status.get("public_url") or "").strip()
        # Omit the preview link entirely if no public domain is configured,
        # rather than emit a broken "https:///..." URL.
        preview_url = f"https://{PUBLIC_DOMAIN}/tasks/preview-app/{slug}/" if PUBLIC_DOMAIN else ""
        header = f"**{name}** (`{slug}`) — {'published' if published else 'not published'}"
        owner = await self._resolve_email_for_ctx(ctx) or ""
        components = build_project_menu_components(
            slug, published=published, public_url=public_url,
            preview_url=preview_url, owner=owner,
        )
        if ctx.respond_components is not None:
            await ctx.respond_components(header, components)
        else:
            await ctx.respond(header)

    async def run_panel_status(self, ctx: CommandContext, slug: str) -> None:
        """App Builder Status button → post the app's status text (same shape as
        the `aiuibuilder status <slug>` text action)."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            status = await self._tasks_client.get_project_status(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_status_error(e))
            return
        lines = [
            f"**{status.get('name', slug)}** (`{status.get('slug', slug)}`)",
            f"Role: {status.get('role', '?')}",
            f"Published: {'yes' if status.get('published') else 'no'}",
        ]
        if status.get("public_url"):
            lines.append(f"URL: {status['public_url']}")
        if status.get("last_commit_at"):
            lines.append(f"Last commit: {status['last_commit_at']}")
        await ctx.respond("\n".join(lines))

    async def run_schedule_list(self, ctx: CommandContext) -> None:
        """My-schedules button → render the user's schedules + action buttons."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            schedules = await self._tasks_client.list_schedules(email, platform="discord")
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))
            return
        out = build_schedule_list(schedules)
        if out["components"] and ctx.respond_components is not None:
            await ctx.respond_components(out["content"], out["components"])
        else:
            await ctx.respond(out["content"])

    async def run_schedule_create(
        self, ctx: CommandContext, *, name: str, cron: str, prompt: str,
        delivery_channel_id: str | None = None, run_once: bool = False,
    ) -> None:
        """Confirm button → create the schedule for the user, delivering results
        to their private thread."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.create_schedule(
                email, name=name, cron=cron, prompt=prompt,
                delivery_channel_id=delivery_channel_id, run_once=run_once,
            )
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))
            return
        await ctx.respond(
            f"✅ Scheduled — {name}.\nResults will appear in your private thread."
        )

    async def run_schedule_action(
        self, ctx: CommandContext, action: str, schedule_id: str,
    ) -> None:
        """Run-now / Pause / Resume / Delete for a single schedule."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            if action == "run":
                await self._tasks_client.run_schedule_now(email, schedule_id)
                msg = "▶️ Running now — results will appear in your private thread."
            elif action == "pause":
                await self._tasks_client.pause_schedule(email, schedule_id)
                msg = "⏸ Paused."
            elif action == "resume":
                await self._tasks_client.resume_schedule(email, schedule_id)
                msg = "▶️ Resumed."
            elif action == "del":
                await self._tasks_client.delete_schedule(email, schedule_id)
                msg = "🗑 Deleted."
            else:
                msg = "Unknown action."
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))
            return
        await ctx.respond(msg)

    async def _resolve_email(self, discord_id: str) -> str | None:
        """Resolve a Discord user's email: static env map first (operator-set),
        then the DB link store. None if unlinked or the tasks service is down."""
        email = self._discord_user_email_map.get(discord_id)
        if email:
            return email
        try:
            return await self._tasks_client.resolve_link(discord_id)
        except TasksAPIError:
            return None

    async def _resolve_email_for_ctx(self, ctx: CommandContext) -> str | None:
        """Platform-aware email resolution for build/connector flows. Slack reads
        the caller's profile email via the Web API (needs the users:read.email
        scope); voice uses the operator-set VOICE_USER_EMAIL (single identity);
        Discord keeps the static-map + DB-link-store path unchanged."""
        if ctx.platform == "voice":
            return (settings.voice_user_email or "").strip().lower() or None
        if ctx.platform == "slack":
            if self._slack_client is None:
                return None
            try:
                return await self._slack_client.get_user_email(ctx.user_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("slack get_user_email failed user=%s: %s", ctx.user_id, e)
                return None
        return await self._resolve_email(ctx.user_id)

    async def _resolve_email_auto(self, discord_id: str) -> str:
        """Identity for the schedule/connector flow, which is open to anyone who
        can see the channel: a real email when mapped/linked (so connector-backed
        tasks keep working), else a stable synthetic identity — no linking step."""
        return await self._resolve_email(discord_id) or f"discord-{discord_id}@aiui.local"

    @staticmethod
    def _not_linked_text(ctx: CommandContext) -> str:
        """The 'no email' message, worded for the caller's platform."""
        if ctx.platform == "slack":
            return onboarding.not_linked_text_slack()
        return onboarding.not_linked_text_discord()

    async def _respond_not_linked(self, ctx: CommandContext) -> None:
        """Friendly, self-service not-linked response. On Discord, render the
        Link button inline when the context supports components; otherwise send
        plain text. On Slack, send the plain-language wording (auto-read; no
        button to offer)."""
        if ctx.platform != "slack" and ctx.respond_components is not None:
            await ctx.respond_components(
                onboarding.not_linked_text_discord(), onboarding.link_button_row(),
            )
            return
        await ctx.respond(self._not_linked_text(ctx))

    async def run_schedule_edit(
        self, ctx: CommandContext, schedule_id: str, *,
        name: str, cron: str, prompt: str,
    ) -> None:
        """Edit-modal submit → update the schedule's time/prompt for this user."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.update_schedule(
                email, schedule_id, name=name, cron=cron, prompt=prompt)
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))
            return
        await ctx.respond(f"✅ Updated — {name}.")

    async def get_schedule_for_edit(self, discord_id: str, schedule_id: str) -> dict | None:
        """Return {what, when} for the Edit-modal prefill, or None if not found /
        not linked. The schedule's name is '<when-in-English>: <what>'."""
        email = await self._resolve_email(discord_id)
        if not email:
            return None
        try:
            schedules = await self._tasks_client.list_schedules(email, platform="discord")
        except TasksAPIError:
            return None
        for s in schedules:
            if str(s.get("id")) == schedule_id:
                name = s.get("name") or ""
                when, sep, what = name.partition(": ")
                if not sep:
                    return {"what": name, "when": ""}
                return {"what": what, "when": when}
        return None

    async def dashboard_payload(self, discord_id: str) -> dict | None:
        """The Schedules dashboard message payload for a user's private thread,
        or None if they're not linked."""
        email = await self._resolve_email(discord_id)
        if not email:
            return None
        try:
            schedules = await self._tasks_client.list_schedules(email, platform="discord")
        except TasksAPIError:
            schedules = []
        return build_schedules_dashboard(schedules)

    async def run_schedule_card(self, ctx: CommandContext, schedule_id: str) -> None:
        """Dropdown select → render a single schedule's clean card."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            schedules = await self._tasks_client.list_schedules(email, platform="discord")
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))
            return
        sched = next((s for s in schedules if str(s.get("id")) == schedule_id), None)
        if not sched:
            await ctx.respond("Couldn't find that schedule — it may have been deleted.")
            return
        card = build_schedule_card(sched)
        if ctx.respond_components is not None:
            await ctx.respond_components("", card["components"], embeds=card["embeds"])
        else:
            await ctx.respond(f"📅 {(sched.get('prompt') or '')[:200]}")

    async def get_user_thread(self, discord_id: str) -> str | None:
        return await self._tasks_client.get_user_thread(discord_id)

    async def set_user_thread(self, discord_id: str, thread_id: str) -> bool:
        return await self._tasks_client.set_user_thread(discord_id, thread_id)

    async def get_user_builder_thread(self, discord_id: str) -> str | None:
        return await self._tasks_client.get_user_builder_thread(discord_id)

    async def set_user_builder_thread(self, discord_id: str, thread_id: str) -> bool:
        return await self._tasks_client.set_user_builder_thread(discord_id, thread_id)

    async def request_link(self, discord_id: str, username: str, email: str) -> dict:
        return await self._tasks_client.request_link(discord_id, username, email)

    async def approve_link(self, discord_id: str, decided_by: str = "") -> dict:
        return await self._tasks_client.approve_link(discord_id, decided_by=decided_by)

    async def reject_link(self, discord_id: str) -> bool:
        return await self._tasks_client.reject_link(discord_id)

    # ------------------------------------------------------------------ #
    # Cron-job management methods                                          #
    # ------------------------------------------------------------------ #

    def _cron_email_or_none(self, ctx: CommandContext) -> str | None:
        return self._discord_user_email_map.get(ctx.user_id)

    async def run_cron_create(self, ctx: CommandContext, *, cron_expr: str,
                              name: str, prompt: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        prompt = (prompt or "").strip()
        if not prompt:
            await ctx.respond("Please include a prompt — what should the job do?")
            return
        name = (name or "").strip() or f"discord-{ctx.user_name}-{cron_expr[:20]}"
        try:
            result = await self._tasks_client.create_schedule(
                email, name=name, cron=cron_expr, prompt=prompt,
            )
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))
            return
        from handlers import cronjob_panel as cp
        await ctx.respond(
            f"✅ Scheduled **{name}** — {cp.describe_cron(cron_expr)}\n"
            f"`{result.get('id','?')}` · {prompt[:200]}"
        )

    async def run_cron_list(self, ctx: CommandContext) -> None:
        from handlers import cronjob_panel as cp
        email = self._cron_email_or_none(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            schedules = await self._tasks_client.list_schedules(email, platform="discord")
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))
            return
        if not schedules:
            await ctx.respond("You have no schedules yet. Click **⏰ Schedule a task** to make one.")
            return
        if ctx.respond_components:
            await ctx.respond_components("**Your schedules** — pick one to manage:",
                                         cp.build_schedules_select(schedules))
        else:
            await ctx.respond("\n".join(cp.format_schedule_line(s) for s in schedules))

    async def _cron_menu_for(self, ctx: CommandContext, email: str,
                             schedule_id: str, prefix: str = "") -> None:
        from handlers import cronjob_panel as cp
        schedules = await self._tasks_client.list_schedules(email, platform="discord")
        match = next((s for s in schedules if str(s["id"]) == str(schedule_id)), None)
        if not match:
            await ctx.respond("That schedule no longer exists.")
            return
        if ctx.respond_components:
            await ctx.respond_components(prefix + cp.format_schedule_line(match),
                                         cp.build_schedule_menu(match))
        else:
            await ctx.respond(prefix + cp.format_schedule_line(match))

    async def run_cron_menu(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._cron_menu_for(ctx, email, schedule_id)
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))

    async def run_cron_runnow(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.run_now_schedule(email, schedule_id)
            await ctx.respond("▶️ Triggered — it will run shortly.")
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))

    async def run_cron_pause(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.disable_schedule(email, schedule_id)
            await self._cron_menu_for(ctx, email, schedule_id, prefix="⏸ Paused.\n")
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))

    async def run_cron_resume(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.enable_schedule(email, schedule_id)
            await self._cron_menu_for(ctx, email, schedule_id, prefix="▶ Resumed.\n")
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))

    async def run_cron_delete(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.delete_schedule(email, schedule_id)
            await ctx.respond("🗑 Schedule deleted.")
        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))


    @staticmethod
    def _format_status_error(e: TasksAPIError) -> str:
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 404:
            return "Project not found or not yours."
        return f"Tasks API error ({e.status})."

    def _format_enhance_error(self, e: TasksAPIError) -> str:
        """Enhance-flavored error text."""
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 409:
            return "An update is already in progress — try again in a minute."
        if e.status in (401, 403):
            return "Only the app's owner or an editor can change it."
        if e.status == 404:
            return "No app found to enhance (build it first)."
        if e.status in (400, 422):
            return "Couldn't start the update — check your description."
        return f"Couldn't start the update (error {e.status})."

    def _format_unpublish_error(self, e: TasksAPIError) -> str:
        """Unpublish-flavored error text."""
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status in (401, 403):
            return "Only the app's owner can unpublish it."
        if e.status == 404:
            return "It's not live right now."
        return f"Couldn't unpublish (error {e.status})."

    def _format_delete_error(self, e: TasksAPIError) -> str:
        """Delete-flavored error text."""
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status in (401, 403):
            return "Only the app's owner can delete it."
        if e.status == 404:
            return "That app doesn't exist (already deleted?)."
        return f"Couldn't delete (error {e.status})."

    def _format_publish_error(self, e: TasksAPIError) -> str:
        """Publish-flavored error text."""
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 401:
            return "I couldn't verify your account — tap 🔗 Link my account and try again."
        if e.status == 403:
            return "Only the app's owner can publish it."
        if e.status == 404:
            return "Project not found or not yours."
        if e.status in (400, 422):
            return "This app isn't publishable yet (it needs an index.html)."
        return f"Couldn't publish (error {e.status})."

    def _format_tasks_error(self, e: TasksAPIError) -> str:
        """Map a TasksAPIError to a Discord-friendly reply.

        Never echoes the request body, secrets, or other users' identifiers.
        """
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 404:
            return "No such schedule: not found"
        if e.status == 400:
            msg = e.message
            if "cron_expr" in msg:
                return f"Invalid cron: {msg}"
            if "interval" in msg.lower():
                return "Min interval is 5 min."
            if "max" in msg.lower() or "quota" in msg.lower():
                return "You hit the max schedules limit."
            return "Bad request — check your input."
        if e.status == 401 or e.status == 403:
            return "Permission denied by tasks service."
        return f"Tasks API error ({e.status})."

    def _format_build_error(self, e: TasksAPIError) -> str:
        """Build-flavored error text (NOT the schedule-flavored _format_tasks_error)."""
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 429:
            return "A build is already running — try again in a few minutes."
        if e.status in (401, 403):
            return onboarding.not_linked_text_discord()
        if e.status in (400, 422):
            return "Couldn't start the build — check your description and try again."
        return f"Couldn't start the build (error {e.status})."

    async def _watch_build(
        self, ctx: CommandContext, email: str, task_id: str, slug: str,
        *, poll_seconds: int | None = None, max_polls: int | None = None,
    ) -> None:
        """Poll the build until it terminates, then post the result to the
        channel — on success via ctx.notify_channel_rich (a Publish button) when
        set, else ctx.notify_channel (both bot-token messages that outlive the
        interaction window). Defensive: transient errors don't kill the loop."""
        if ctx.notify_channel is None:
            return

        async def _notify(msg: str) -> None:
            # Never let a notify failure crash the watcher (it runs as a
            # detached task — an unhandled raise would die silently).
            try:
                await ctx.notify_channel(msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("watch_build notify failed task=%s: %s", task_id, exc)

        poll_seconds = BUILD_POLL_SECONDS if poll_seconds is None else poll_seconds
        max_polls = BUILD_MAX_POLLS if max_polls is None else max_polls
        errors = 0
        for _ in range(max_polls):
            await asyncio.sleep(poll_seconds)
            try:
                st = await self._tasks_client.get_build_status(email, task_id)
                errors = 0
            except TasksAPIError as e:
                errors += 1
                logger.warning("watch_build status error (%s) task=%s", e.status, task_id)
                if errors >= BUILD_MAX_CONSECUTIVE_ERRORS:
                    await _notify(
                        f"Lost track of `{slug}` — check `/aiui aiuibuilder status {slug}`."
                    )
                    return
                continue
            status = st.get("status")
            if status == "completed":
                url = st.get("preview_url") or ""
                msg = f"`{slug}` is ready (preview): {url}".rstrip()
                if ctx.notify_channel_rich is not None:
                    try:
                        await ctx.notify_channel_rich(msg, slug, url, email)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("watch_build rich notify failed task=%s: %s", task_id, exc)
                        await _notify(msg)
                else:
                    await _notify(msg)
                return
            if status == "needs_input":
                detail = (st.get("error") or "").strip()
                ask = f" It needs to know: {detail}" if detail else ""
                await _notify(
                    f"`{slug}` needs more detail to finish.{ask} "
                    "Continue it in the App Builder, or run `build` again with a "
                    "more specific description."
                )
                return
            if status == "failed":
                await _notify(
                    f"Build failed for `{slug}`. Open the App Builder to retry."
                )
                return
        await _notify(
            f"`{slug}` is still building — check `/aiui aiuibuilder status {slug}`."
        )

    async def run_panel_outreach(
        self, ctx: CommandContext, role: str, location: str,
        jobdesc: str, count: int,
    ) -> None:
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        if not (jobdesc or "").strip():
            await ctx.respond("Please paste the job description so I know what to send.")
            return
        manual = ctx.platform == "discord"
        try:
            result = await self._tasks_client.start_outreach(email, {
                "role": role, "location": location, "jobdesc": jobdesc,
                "count": count, "mode": "manual" if manual else "auto"})
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        task_id = result["task_id"]
        where = f"{role}" + (f" · {location}" if location else "")
        if manual:
            await ctx.respond(
                f"\U0001f50e Searching GitHub for **{where}** … I'll post the list "
                "here to review when it's ready (usually a minute or two).")
        else:
            await ctx.respond(
                f"\U0001f50e Searching GitHub for **{where}** … I'll post the results "
                "in your thread when it's done (usually a minute or two).")
        if ctx.notify_channel is not None:
            coro = (self._watch_outreach_review(ctx, email, task_id, role, location)
                    if manual else self._watch_outreach(ctx, email, task_id))
            w = asyncio.create_task(coro)
            self._background_tasks.add(w)
            w.add_done_callback(self._background_tasks.discard)

    async def _watch_outreach(
        self, ctx: CommandContext, email: str, task_id: str,
        *, poll_seconds: int | None = None, max_polls: int | None = None,
    ) -> None:
        if ctx.notify_channel is None:
            return

        async def _notify(msg: str) -> None:
            try:
                await ctx.notify_channel(msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("watch_outreach notify failed task=%s: %s", task_id, exc)

        poll_seconds = OUTREACH_POLL_SECONDS if poll_seconds is None else poll_seconds
        max_polls = OUTREACH_MAX_POLLS if max_polls is None else max_polls
        errors = 0
        for _ in range(max_polls):
            await asyncio.sleep(poll_seconds)
            try:
                st = await self._tasks_client.get_outreach_status(email, task_id)
                errors = 0
            except TasksAPIError as e:
                errors += 1
                logger.warning("watch_outreach status error (%s) task=%s", e.status, task_id)
                if errors >= OUTREACH_MAX_CONSECUTIVE_ERRORS:
                    await _notify("Lost track of the outreach run — try again.")
                    return
                continue
            status = st.get("status")
            if status == "completed":
                text = (st.get("text") or "").strip() or "Outreach complete."
                url = st.get("sheet_url") or ""
                await _notify(f"✅ {text}" + (f"\n\U0001f449 {url}" if url else ""))
                return
            if status == "failed":
                text = (st.get("text") or "").strip()
                await _notify("⚠️ Outreach didn't complete. "
                              + (text or "Try a broader role or remove the location."))
                return
        await _notify("Outreach is still running — check back shortly.")

    async def _watch_outreach_review(
        self, ctx: CommandContext, email: str, task_id: str,
        role: str, location: str,
    ) -> None:
        """Discord manual mode: poll the find until it reaches ``review``, then
        post the interactive overview (embed + select/edit/send components) to
        the channel as a fresh bot-token message that outlives the interaction
        window. Slack keeps the auto-send path via ``_watch_outreach``."""
        from handlers import recruiting_review as rr
        if ctx.notify_channel is None:
            return

        async def _notify_text(msg: str) -> None:
            try:
                await ctx.notify_channel(msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("watch_outreach_review notify failed task=%s: %s", task_id, exc)

        async def _notify_msg(msg: dict) -> None:
            try:
                if ctx.notify_channel_msg is not None:
                    await ctx.notify_channel_msg(msg)
                else:
                    # No rich poster wired — degrade to the embed's text summary
                    # so the result still lands somewhere.
                    embeds = msg.get("embeds") or []
                    desc = embeds[0].get("description", "") if embeds else ""
                    await ctx.notify_channel(desc or "Engineers ready to review.")
            except Exception as exc:  # noqa: BLE001
                logger.error("watch_outreach_review rich notify failed task=%s: %s", task_id, exc)

        for _ in range(OUTREACH_MAX_POLLS):
            await asyncio.sleep(OUTREACH_POLL_SECONDS)
            try:
                st = await self._tasks_client.get_outreach_candidates(email, task_id)
            except TasksAPIError as e:
                logger.warning("watch_outreach_review status error (%s) task=%s", e.status, task_id)
                continue
            status = st.get("status")
            if status == "running":
                continue
            if status == "review":
                msg = rr.build_review_message(
                    task_id, st.get("candidates", []), role=role, location=location)
                await _notify_msg(msg)
                return
            await _notify_text((st.get("text") or "").strip() or "No engineers found.")
            return
        await _notify_text("Outreach search timed out — try again.")

    async def run_outreach_select(
        self, ctx: CommandContext, task_id: str,
        selected_ids: Optional[list[str]], role: str = "", location: str = "",
    ) -> None:
        """Apply a recipient selection (``selected_ids``) or just refresh
        (``selected_ids is None``), then re-render the overview in place."""
        from handlers import recruiting_review as rr
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            if selected_ids is None:
                st = await self._tasks_client.get_outreach_candidates(email, task_id)
            else:
                st = await self._tasks_client.patch_outreach_candidate(
                    email, task_id, "_", {"selected_ids": selected_ids})
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        msg = rr.build_review_message(
            task_id, st.get("candidates", []), role=role, location=location)
        if ctx.edit_message is not None:
            await ctx.edit_message(msg)

    async def run_outreach_edit_submit(
        self, ctx: CommandContext, task_id: str, cid: str, email_val: str,
        subject: str, body: str, role: str = "", location: str = "",
    ) -> None:
        """Save an edited candidate (email/subject/body) then re-render the
        overview in place."""
        from handlers import recruiting_review as rr
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        from handlers.discord_commands import _valid_email
        ev = (email_val or "").strip()
        if ev and not _valid_email(ev):
            # bounce invalid email without mutating the candidate
            try:
                st = await self._tasks_client.get_outreach_candidates(email, task_id)
            except TasksAPIError:
                return
            if ctx.edit_message is not None:
                msg = rr.build_review_message(task_id, st.get("candidates", []), role="", location="")
                msg = {**msg, "content": f"⚠️ `{ev}` doesn't look like a valid email — not saved."}
                await ctx.edit_message(msg)
            return
        try:
            st = await self._tasks_client.patch_outreach_candidate(
                email, task_id, cid,
                {"email": email_val, "subject": subject, "body": body})
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        msg = rr.build_review_message(
            task_id, st.get("candidates", []), role=role, location=location)
        if ctx.edit_message is not None:
            await ctx.edit_message(msg)

    async def run_outreach_send(self, ctx: CommandContext, task_id: str) -> None:
        """Send to the selected candidates. On success, lock the message with
        the sent summary; otherwise surface why nothing went out."""
        from handlers import recruiting_review as rr
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            st = await self._tasks_client.send_outreach(email, task_id)
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        if st.get("status") == "sent":
            await ctx.edit_message(rr.build_sent_message(st.get("text", "Sent."),
                                                         st.get("sheet_url", "")))
            return
        # not sent (e.g. nothing selected / transient send error): keep the
        # interactive overview intact and show the reason as a content line.
        if ctx.edit_message is not None:
            msg = rr.build_review_message(task_id, st.get("candidates", []),
                                          role="", location="")
            msg = {**msg, "content": "⚠️ " + (st.get("text") or "Pick at least one engineer first.")}
            await ctx.edit_message(msg)
        else:
            await ctx.respond(st.get("text") or "Pick at least one engineer first.")

    async def _handle_workflows(self, ctx: CommandContext) -> None:
        """List active n8n workflows."""
        if not self.n8n.api_key:
            await ctx.respond("n8n API not configured (no API key).")
            return

        logger.info(f"[{ctx.platform}] workflows list from {ctx.user_name}")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.n8n.base_url}/api/v1/workflows",
                    headers={"X-N8N-API-KEY": self.n8n.api_key},
                )
                resp.raise_for_status()
                data = resp.json()

            wf_list = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(wf_list, list):
                wf_list = []

            active = [w for w in wf_list if w.get("active")]
            inactive = [w for w in wf_list if not w.get("active")]

            lines = [f"*n8n Workflows ({len(wf_list)} total, {len(active)} active)*\n"]
            for w in active:
                lines.append(f"  `{w.get('name', 'unnamed')}` — active")
            for w in inactive:
                lines.append(f"  `{w.get('name', 'unnamed')}` — inactive")

            await ctx.respond("\n".join(lines))
        except Exception as e:
            logger.error(f"Error listing n8n workflows: {e}")
            await ctx.respond(f"Failed to list workflows: {e}")

    async def _gather_github_commits(self, since: str) -> Optional[list[dict]]:
        """Fetch today's commits. Returns None if not configured."""
        if not self._github_client:
            return None

        parts = settings.report_github_repo.split("/", 1)
        if len(parts) != 2:
            logger.error(f"Invalid REPORT_GITHUB_REPO: {settings.report_github_repo}")
            return []
        return await self._github_client.get_commits_since(owner=parts[0], repo=parts[1], since=since)

    async def _gather_n8n_executions(self, since: str) -> Optional[list[dict]]:
        """Fetch today's n8n executions. Returns None if not configured."""
        if not self.n8n.api_key:
            return None

        all_execs = await self.n8n.get_recent_executions(limit=50)
        # Filter to today only
        return [e for e in all_execs if e.get("started", "") >= since]

    async def _gather_health(self) -> list[dict]:
        """Check health of all services."""
        async def _check(name: str, url: str, client: httpx.AsyncClient) -> dict:
            try:
                resp = await client.get(url)
                status = "healthy" if resp.status_code < 400 else "unhealthy"
            except Exception:
                status = "unreachable"
            return {"service": name, "status": status}

        async with httpx.AsyncClient(timeout=10.0) as client:
            return list(await asyncio.gather(
                *[_check(name, url, client) for name, url in SERVICE_ENDPOINTS.items()]
            ))
