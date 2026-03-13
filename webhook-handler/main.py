"""Webhook Handler Service - Main FastAPI Application."""
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
import httpx
import logging
from typing import Optional
import re

from config import settings
from clients.openwebui import OpenWebUIClient
from clients.github import GitHubClient, verify_github_signature
from clients.mcp_proxy import MCPProxyClient
from clients.n8n import N8NClient
from clients.slack import SlackClient, verify_slack_signature
from clients.discord import DiscordClient, verify_discord_signature
from clients.loki import LokiClient
from handlers.github import GitHubWebhookHandler
from handlers.mcp import MCPWebhookHandler
from handlers.slack import SlackWebhookHandler
from handlers.generic import GenericWebhookHandler
from handlers.automation import AutomationWebhookHandler
from handlers.commands import CommandRouter, CommandContext, VoiceResponseCollector
from handlers.slack_commands import SlackCommandHandler
from handlers.discord_commands import DiscordCommandHandler
from scheduler import (
    init_scheduler, start_scheduler, shutdown_scheduler,
    list_jobs, trigger_job, register_default_jobs,
    daily_health_report, hourly_n8n_workflow_check,
    create_user_cron_job, delete_user_cron_job,
    update_user_cron_job, get_user_jobs,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Global clients (initialized on startup)
openwebui_client: Optional[OpenWebUIClient] = None
github_client: Optional[GitHubClient] = None
github_handler: Optional[GitHubWebhookHandler] = None
mcp_handler: Optional[MCPWebhookHandler] = None
n8n_client: Optional[N8NClient] = None
slack_client: Optional[SlackClient] = None
slack_handler: Optional[SlackWebhookHandler] = None
generic_handler: Optional[GenericWebhookHandler] = None
automation_handler: Optional[AutomationWebhookHandler] = None
command_router: Optional[CommandRouter] = None
slack_command_handler: Optional[SlackCommandHandler] = None
discord_client: Optional[DiscordClient] = None
discord_command_handler: Optional[DiscordCommandHandler] = None
loki_client: Optional[LokiClient] = None


class CreateCronJobRequest(BaseModel):
    job_id: str
    cron_expression: str
    workflow_id: str
    trigger_method: str = "api"
    webhook_path: str = ""
    payload: dict = {}
    description: str = ""
    permanent: bool = False


class UpdateCronJobRequest(BaseModel):
    cron_expression: str = None
    permanent: bool = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize clients on startup."""
    global openwebui_client, github_client, github_handler
    global mcp_handler, n8n_client
    global slack_client, slack_handler, generic_handler, automation_handler
    global command_router, slack_command_handler
    global discord_client, discord_command_handler
    global loki_client

    logger.info("Initializing webhook handler...")

    openwebui_client = OpenWebUIClient(
        base_url=settings.openwebui_url,
        api_key=settings.openwebui_api_key
    )

    github_client = GitHubClient(token=settings.github_token)

    # MCP Proxy client
    mcp_client = MCPProxyClient(
        base_url=settings.mcp_proxy_url,
        user_email=settings.mcp_user_email,
        user_groups=settings.mcp_user_groups
    )
    mcp_handler = MCPWebhookHandler(mcp_client=mcp_client)
    logger.info(f"MCP Proxy URL: {settings.mcp_proxy_url}")

    # n8n client (created before github_handler so it can be passed in)
    n8n_client = N8NClient(
        base_url=settings.n8n_url,
        api_key=settings.n8n_api_key,
        webhook_url=settings.n8n_webhook_url,
    )
    logger.info(f"n8n API URL: {settings.n8n_url}")
    if settings.n8n_webhook_url != settings.n8n_url:
        logger.info(f"n8n Webhook URL: {settings.n8n_webhook_url}")

    # Loki client for log queries
    loki_client = LokiClient(base_url=settings.loki_url)
    logger.info(f"Loki URL: {settings.loki_url}")

    github_handler = GitHubWebhookHandler(
        openwebui_client=openwebui_client,
        github_client=github_client,
        n8n_client=n8n_client,
        ai_model=settings.ai_model,
        ai_system_prompt=settings.ai_system_prompt,
        loki_client=loki_client,
        mcp_client=mcp_client,
    )

    # Slack client (only if configured)
    if settings.slack_bot_token:
        slack_client = SlackClient(bot_token=settings.slack_bot_token)
        slack_handler = SlackWebhookHandler(
            openwebui_client=openwebui_client,
            slack_client=slack_client,
            ai_model=settings.ai_model,
            ai_system_prompt=settings.ai_system_prompt
        )
        logger.info("Slack integration enabled (events)")
    else:
        logger.info("Slack integration disabled (no SLACK_BOT_TOKEN)")

    # Shared command router (used by Slack + Discord slash commands)
    command_router = CommandRouter(
        openwebui_client=openwebui_client,
        n8n_client=n8n_client,
        ai_model=settings.ai_model,
        slack_client=slack_client,
        github_client=github_client,
        mcp_client=mcp_client,
        loki_client=loki_client,
    )

    # Wire Slack command handler if Slack is configured
    if slack_client:
        slack_command_handler = SlackCommandHandler(
            slack_client=slack_client,
            command_router=command_router,
        )
        logger.info("Slack slash commands enabled")

    # Discord client (only if configured)
    if settings.discord_public_key:
        discord_client = DiscordClient(
            application_id=settings.discord_application_id,
            bot_token=settings.discord_bot_token,
        )
        discord_command_handler = DiscordCommandHandler(
            discord_client=discord_client,
            command_router=command_router,
        )
        logger.info("Discord slash commands enabled")
    else:
        logger.info("Discord integration disabled (no DISCORD_PUBLIC_KEY)")

    # Generic handler
    generic_handler = GenericWebhookHandler(
        openwebui_client=openwebui_client,
        ai_model=settings.ai_model
    )

    # Automation handler (delegates to pipe function)
    automation_handler = AutomationWebhookHandler(
        openwebui_client=openwebui_client,
        pipe_model=settings.automation_pipe_model
    )
    logger.info(f"Automation pipe model: {settings.automation_pipe_model}")

    # Scheduler
    init_scheduler()
    register_default_jobs(
        slack_client=slack_client,
        slack_channel=settings.report_slack_channel,
    )
    start_scheduler()

    logger.info(f"Webhook handler ready on port {settings.port}")
    logger.info(f"Open WebUI URL: {settings.openwebui_url}")

    yield

    shutdown_scheduler()
    logger.info("Shutting down webhook handler...")


app = FastAPI(
    title="Webhook Handler Service",
    description="Receives webhooks and triggers Open WebUI AI analysis",
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "webhook-handler",
        "version": "2.0.0"
    }


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: str = Header(None, alias="X-GitHub-Delivery")
):
    """
    Handle GitHub webhook events.

    Validates signature, parses payload, and triggers AI analysis.
    """
    # Get raw body for signature verification
    body = await request.body()

    # Verify signature if secret is configured
    if settings.github_webhook_secret:
        if not x_hub_signature_256:
            logger.warning(f"Missing signature for delivery {x_github_delivery}")
            raise HTTPException(status_code=401, detail="Missing signature")

        if not verify_github_signature(body, x_hub_signature_256, settings.github_webhook_secret):
            logger.warning(f"Invalid signature for delivery {x_github_delivery}")
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(f"Received GitHub event: {x_github_event} (delivery: {x_github_delivery})")

    # Handle the event
    result = await github_handler.handle_event(x_github_event, payload)

    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=500)


@app.post("/webhook/mcp/{server_id}/{tool_name}")
async def mcp_webhook(
    request: Request,
    server_id: str,
    tool_name: str
):
    """
    Execute an MCP tool directly via webhook.

    POST /webhook/mcp/{server_id}/{tool_name}
    Body: JSON with tool arguments
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    logger.info(f"MCP webhook: {server_id}/{tool_name}")

    result = await mcp_handler.handle_tool_request(
        server_id=server_id,
        tool_name=tool_name,
        arguments=payload
    )

    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=500)


@app.post("/webhook/n8n/{workflow_path:path}")
async def n8n_webhook(
    request: Request,
    workflow_path: str
):
    """
    Forward a webhook payload to an n8n workflow.

    POST /webhook/n8n/{workflow_path}
    Body: JSON payload forwarded to n8n webhook node
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    logger.info(f"n8n webhook forward: {workflow_path}")

    result = await n8n_client.trigger_workflow(
        webhook_path=workflow_path,
        payload=payload
    )

    if result is not None:
        return JSONResponse(content={"success": True, "result": result}, status_code=200)
    else:
        return JSONResponse(
            content={"success": False, "error": f"Failed to trigger n8n workflow: {workflow_path}"},
            status_code=500
        )


@app.post("/webhook/slack")
async def slack_webhook(
    request: Request,
    x_slack_request_timestamp: str = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(None, alias="X-Slack-Signature")
):
    """
    Handle Slack Events API webhooks.

    Validates signature, handles url_verification challenge,
    and routes events to the Slack handler.
    """
    if not slack_handler:
        raise HTTPException(status_code=503, detail="Slack integration not configured")

    body = await request.body()

    # Verify signature if signing secret is configured
    if settings.slack_signing_secret:
        if not verify_slack_signature(
            body=body,
            timestamp=x_slack_request_timestamp or "",
            signature=x_slack_signature or "",
            signing_secret=settings.slack_signing_secret
        ):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(f"Received Slack event: {payload.get('type')}")

    result = await slack_handler.handle_event(payload)

    # URL verification returns the challenge directly
    if "challenge" in result:
        return JSONResponse(content=result, status_code=200)

    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=500)


@app.post("/webhook/slack/commands")
async def slack_commands_webhook(
    request: Request,
    x_slack_request_timestamp: str = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(None, alias="X-Slack-Signature"),
):
    """
    Handle Slack slash commands (/aiui).

    Slack sends application/x-www-form-urlencoded (NOT JSON).
    Must ACK within 3 seconds; actual processing happens in background.
    """
    if not slack_command_handler:
        raise HTTPException(status_code=503, detail="Slack integration not configured")

    body = await request.body()

    # Verify Slack signature
    if settings.slack_signing_secret:
        if not verify_slack_signature(
            body=body,
            timestamp=x_slack_request_timestamp or "",
            signature=x_slack_signature or "",
            signing_secret=settings.slack_signing_secret,
        ):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

    form_data = dict(await request.form())
    logger.info(f"Slack slash command: {form_data.get('command')} {form_data.get('text', '')}")

    result = await slack_command_handler.handle_command(form_data)
    return JSONResponse(content=result, status_code=200)


@app.post("/webhook/discord")
async def discord_webhook(
    request: Request,
    x_signature_ed25519: str = Header(None, alias="X-Signature-Ed25519"),
    x_signature_timestamp: str = Header(None, alias="X-Signature-Timestamp"),
):
    """
    Handle Discord interaction webhooks (/aiui slash command).

    Verifies Ed25519 signature, responds to PINGs, and processes
    application commands with deferred responses.
    """
    if not discord_command_handler:
        raise HTTPException(status_code=503, detail="Discord integration not configured")

    body = await request.body()

    # Verify Discord Ed25519 signature
    if not x_signature_ed25519 or not x_signature_timestamp:
        raise HTTPException(status_code=401, detail="Missing Discord signature headers")

    if not verify_discord_signature(
        body=body,
        signature=x_signature_ed25519,
        timestamp=x_signature_timestamp,
        public_key=settings.discord_public_key,
    ):
        raise HTTPException(status_code=401, detail="Invalid Discord signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(f"Discord interaction type: {payload.get('type')}")

    result = await discord_command_handler.handle_interaction(payload)
    return JSONResponse(content=result, status_code=200)


@app.post("/webhook/voice/{command}")
async def voice_webhook(
    command: str,
    request: Request,
    x_voice_secret: str = Header(None, alias="X-Voice-Secret"),
):
    """Handle tool calls from ElevenLabs voice agent."""
    if not settings.voice_webhook_secret or x_voice_secret != settings.voice_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid voice webhook secret")

    body = await request.json()
    arguments = body.get("arguments", "")
    if body.get("owner") and body.get("repo"):
        arguments = f"{body['owner']}/{body['repo']} {arguments}".strip()

    collector = VoiceResponseCollector()

    ctx = CommandContext(
        user_id="voice-agent",
        user_name="Voice User",
        channel_id=body.get("channel_id", "voice"),
        raw_text=f"{command} {arguments}".strip(),
        subcommand=command,
        arguments=arguments,
        platform="voice",
        respond=collector.respond,
        metadata={"source": "elevenlabs"},
    )

    await command_router.execute(ctx)

    return {
        "spoken_summary": collector.spoken_summary,
        "full_result": collector.full_result,
        "post_to_text_channel": len(collector.full_result) > 500,
    }


@app.post("/webhook/generic")
async def generic_webhook(request: Request):
    """
    Handle generic webhook payloads.

    Accepts any JSON, runs AI analysis, returns result.

    Optional query params:
    - prompt: Custom prompt template (use {payload} placeholder)
    - model: Model override
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    prompt = request.query_params.get("prompt", "")
    model = request.query_params.get("model", "")

    result = await generic_handler.handle_request(
        payload=payload,
        prompt_template=prompt,
        model=model
    )

    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=500)


@app.post("/webhook/automation")
async def automation_webhook(request: Request):
    """
    Handle automation webhook payloads.

    Combines AI reasoning with MCP tool execution via the Webhook Automation
    pipe function running inside Open WebUI.

    Optional query params:
    - source: Origin identifier (e.g., "github", "slack", "manual")
    - instructions: Natural-language instructions for the AI
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    source = request.query_params.get("source", "webhook")
    instructions = request.query_params.get("instructions", "")

    result = await automation_handler.handle_request(
        payload=payload,
        source=source,
        instructions=instructions,
    )

    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=500)


@app.get("/webhook/scheduler/jobs")
async def scheduler_jobs_legacy():
    """List all scheduled jobs (legacy path)."""
    return {"jobs": list_jobs()}


# ---------------------------------------------------------------------------
# Scheduler API routes
# ---------------------------------------------------------------------------

@app.get("/scheduler/jobs")
async def get_scheduler_jobs():
    """List all scheduled jobs with details."""
    jobs = list_jobs()
    return {"jobs": jobs, "count": len(jobs)}


@app.post("/scheduler/jobs/{job_id}/trigger")
async def trigger_scheduler_job(job_id: str):
    """Manually trigger a scheduled job to run immediately."""
    result = trigger_job(job_id)
    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=404)


@app.get("/scheduler/health-report")
async def run_health_report():
    """Run the daily health report on demand and return results."""
    results = await daily_health_report(
        slack_client=slack_client,
        slack_channel=settings.report_slack_channel,
    )
    healthy = sum(1 for r in results if r.get("status") == "healthy")
    return {
        "healthy": healthy,
        "total": len(results),
        "services": results,
    }


@app.get("/scheduler/n8n-check")
async def run_n8n_check():
    """Run the n8n workflow check on demand and return results."""
    result = await hourly_n8n_workflow_check()
    return result


@app.post("/scheduler/jobs")
async def create_cron_job_endpoint(req: CreateCronJobRequest):
    """Create a new user cron job that triggers an n8n workflow on schedule."""
    result = create_user_cron_job(
        job_id=req.job_id,
        cron_expression=req.cron_expression,
        workflow_id=req.workflow_id,
        trigger_method=req.trigger_method,
        webhook_path=req.webhook_path,
        payload=req.payload,
        description=req.description,
        permanent=req.permanent,
        n8n_url=settings.n8n_url,
        n8n_api_key=settings.n8n_api_key,
        min_interval_minutes=settings.scheduler_min_interval_minutes,
        max_user_jobs=settings.scheduler_max_user_jobs,
        default_expiry_hours=settings.scheduler_default_expiry_hours,
    )
    if result.get("success"):
        return JSONResponse(content=result, status_code=201)
    else:
        return JSONResponse(content=result, status_code=400)


@app.delete("/scheduler/jobs/{job_id}")
async def delete_cron_job_endpoint(job_id: str):
    """Delete a user-created cron job."""
    result = delete_user_cron_job(job_id)
    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=404)


@app.patch("/scheduler/jobs/{job_id}")
async def update_cron_job_endpoint(job_id: str, req: UpdateCronJobRequest):
    """Update a user cron job's schedule or permanence."""
    result = update_user_cron_job(
        job_id=job_id,
        cron_expression=req.cron_expression,
        permanent=req.permanent,
        min_interval_minutes=settings.scheduler_min_interval_minutes,
        default_expiry_hours=settings.scheduler_default_expiry_hours,
    )
    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=400)


@app.get("/scheduler/user-jobs")
async def get_user_jobs_endpoint():
    """List all user-created cron jobs with metadata."""
    jobs = get_user_jobs()
    return {"jobs": jobs, "count": len(jobs)}


def _extract_file_references(logs_text: str) -> list[str]:
    """Extract file paths from error logs/stack traces."""
    patterns = [
        r'File "([^"]+\.py)"',
        r'at\s+\S+\s+\(([^)]+\.[jt]s):\d+:\d+\)',
        r'(/[\w/.-]+\.\w{1,4}):\d+',
        r'([\w/.-]+\.(py|js|ts|go|rs|java)):\d+',
    ]

    files = set()
    for pattern in patterns:
        for match in re.finditer(pattern, logs_text):
            fpath = match.group(1)
            if any(skip in fpath for skip in [
                "site-packages", "node_modules", "/usr/lib",
                "/usr/local/lib", "venv", ".venv"
            ]):
                continue
            for prefix in ["/app/", "/root/proxy-server/", "/root/"]:
                if fpath.startswith(prefix):
                    fpath = fpath[len(prefix):]
                    break
            files.add(fpath)

    return list(files)[:5]


@app.post("/webhook/grafana-alerts")
async def grafana_alerts_webhook(request: Request):
    """
    Receive Grafana alert notifications and forward them to Discord.
    When FIRING, also query Loki for error logs and post AI diagnosis.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(f"Grafana alert received: {payload.get('title', 'unknown')}")

    # Build a Discord-friendly message from the Grafana payload
    status = payload.get("status", "unknown").upper()
    title = payload.get("title", "Grafana Alert")
    message_text = payload.get("message", "")
    rule_name = payload.get("ruleName", title)

    emoji = "\U0001f534" if status == "FIRING" else "\u2705"

    lines = [f"{emoji} **{status}: {rule_name}**"]
    if message_text:
        lines.append(message_text[:500])

    # Collect container names from alerts for diagnosis
    container_names = set()
    alerts = payload.get("alerts", [])
    for alert in alerts[:5]:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alert_name = labels.get("alertname", "")
        summary = annotations.get("summary", annotations.get("description", ""))
        severity = labels.get("severity", "")

        alert_line = f"- **{alert_name}**"
        if severity:
            alert_line += f" [{severity}]"
        if summary:
            alert_line += f": {summary}"
        lines.append(alert_line)

        # Collect container_name for Loki query
        cn = labels.get("container_name", "")
        if cn:
            container_names.add(cn)

    if len(alerts) > 5:
        lines.append(f"_... and {len(alerts) - 5} more alerts_")

    external_url = payload.get("externalURL", "")
    if external_url:
        lines.append(f"\n[Open Grafana]({external_url})")

    content = "\n".join(lines)
    if len(content) > 2000:
        content = content[:1997] + "..."

    # Send alert to Discord
    channel_id = settings.discord_alert_channel_id
    bot_token = settings.discord_bot_token

    if not bot_token or not channel_id:
        logger.error("Discord bot token or alert channel ID not configured")
        return JSONResponse(
            content={"success": False, "error": "Discord not configured"},
            status_code=500,
        )

    discord_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                discord_url,
                json={"content": content},
                headers=headers,
            )
            if resp.status_code in (200, 201):
                logger.info(f"Grafana alert forwarded to Discord channel {channel_id}")
            else:
                logger.error(f"Discord API error: {resp.status_code} {resp.text}")
                return JSONResponse(
                    content={"success": False, "error": f"Discord error: {resp.status_code}"},
                    status_code=502,
                )
    except Exception as e:
        logger.error(f"Failed to send alert to Discord: {e}")
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500,
        )

    # AI Diagnosis with code context — only on FIRING alerts
    if status == "FIRING" and loki_client and openwebui_client:
        try:
            # Step 1: Query Loki for error logs
            all_logs = []
            for cn in container_names:
                logs = await loki_client.query_error_logs(container_name=cn, minutes=5, limit=30)
                all_logs.extend(logs)

            if not container_names:
                all_logs = await loki_client.query_error_logs(container_name="", minutes=5, limit=30)

            if all_logs:
                logs_text = "\n".join(all_logs[:30])
                containers_str = ", ".join(container_names) if container_names else "all"

                # Step 2: Extract file references from error logs
                file_refs = _extract_file_references(logs_text)
                code_context = ""

                # Step 3: Fetch source code via MCP proxy if we have file references
                if file_refs and mcp_handler:
                    code_snippets = []
                    mcp_client_ref = mcp_handler.mcp_client
                    repo_parts = settings.report_github_repo.split("/", 1)
                    if len(repo_parts) == 2 and mcp_client_ref:
                        owner, repo_name = repo_parts
                        for fpath in file_refs[:3]:
                            try:
                                result = await mcp_client_ref.execute_tool(
                                    server_id="github",
                                    tool_name="get_file_contents",
                                    arguments={
                                        "owner": owner,
                                        "repo": repo_name,
                                        "path": fpath,
                                    },
                                )
                                if result:
                                    content = str(result)[:1500]
                                    code_snippets.append(f"--- {fpath} ---\n{content}")
                            except Exception as e:
                                logger.debug(f"Could not fetch {fpath} via MCP: {e}")

                    if code_snippets:
                        code_context = "\n\nRelevant source code:\n" + "\n".join(code_snippets)

                # Step 4: AI diagnosis with code context
                messages = [
                    {"role": "system", "content": (
                        "You are a DevOps diagnostic assistant. Analyze these container error logs "
                        "and any source code provided. Provide:\n"
                        "1) Root cause - what went wrong (reference specific code if available)\n"
                        "2) Impact - what's affected\n"
                        "3) Suggested fix - specific code changes or commands\n"
                        "Be concise. Max 3-4 sentences per section."
                    )},
                    {"role": "user", "content": (
                        f"Alert: {rule_name}\n"
                        f"Containers: {containers_str}\n"
                        f"Error logs (last 5 minutes):\n{logs_text}"
                        f"{code_context}"
                    )},
                ]

                diagnosis = await openwebui_client.chat_completion(
                    messages=messages,
                    model=settings.ai_model,
                )

                if diagnosis:
                    diag_content = f"\U0001f50d **AI Diagnosis for: {rule_name}**\n{diagnosis}"
                    if len(diag_content) > 2000:
                        diag_content = diag_content[:1997] + "..."

                    async with httpx.AsyncClient(timeout=15.0) as client:
                        await client.post(
                            discord_url,
                            json={"content": diag_content},
                            headers=headers,
                        )
                    logger.info("AI diagnosis (with code context) posted to Discord")
                else:
                    logger.warning("AI diagnosis unavailable (Open WebUI error)")
            else:
                logger.info("No error logs found in Loki for diagnosis")
        except Exception as e:
            logger.error(f"AI diagnosis failed: {e}")

    return {"success": True, "discord_status": 200}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.debug
    )
