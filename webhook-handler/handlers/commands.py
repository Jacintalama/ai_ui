"""Shared command router for slash commands (Slack & Discord)."""
import asyncio
import json
import httpx
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional, Any
import logging

from clients.openwebui import OpenWebUIClient
from clients.n8n import N8NClient
from clients.github import GitHubClient
from clients.mcp_proxy import MCPProxyClient
from config import settings, get_service_endpoints

logger = logging.getLogger(__name__)


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
    ):
        self.openwebui = openwebui_client
        self.n8n = n8n_client
        self.ai_model = ai_model
        self._slack_client = slack_client
        self._github_client = github_client
        self._mcp_client = mcp_client
        self._loki_client = loki_client

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
            "email", "sheets", "rebuild",
            "health", "security", "deps", "license",
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
                "MCP (Model Context Protocol) tools are available for GitHub, Jira, "
                "n8n, filesystem, and 40+ other integrations. If the user's question "
                "could be answered by using an MCP tool, suggest the specific "
                "`/aiui mcp <server> <tool>` command they can run."
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

    async def _handle_help(self, ctx: CommandContext) -> None:
        """Show available commands."""
        help_text = (
            "*Available Commands*\n"
            "`/aiui ask <question>` — Ask the AI a question\n"
            "`/aiui pr-review <number>` — AI review of a GitHub PR\n"
            "`/aiui mcp <server> <tool> [json_args]` — Execute an MCP tool\n"
            "`/aiui workflow <name>` — Trigger an n8n workflow\n"
            "`/aiui workflows` — List active n8n workflows\n"
            "`/aiui report` — Generate end-of-day activity report\n"
            "`/aiui status` — Check service health\n"
            "`/aiui diagnose [container]` \u2014 AI diagnosis of recent errors\n"
            "`/aiui analyze [owner/repo]` \u2014 AI analysis of a GitHub codebase\n"
            "`/aiui email` \u2014 Summarize recent emails (via n8n Gmail)\n"
            "`/aiui sheets [daily|errors]` \u2014 Generate report to Google Sheets\n"
            "`/aiui rebuild [owner/repo]` \u2014 Research solutions & generate rebuild plan\n"
            "`/aiui health [owner/repo]` \u2014 Code quality & architecture health assessment\n"
            "`/aiui security [owner/repo]` \u2014 Deep security audit (OWASP Top 10)\n"
            "`/aiui deps [owner/repo]` \u2014 Check for outdated/vulnerable dependencies\n"
            "`/aiui license [owner/repo]` \u2014 License compliance check\n"
            "`/aiui help` — Show this help message"
        )
        await ctx.respond(help_text)

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
