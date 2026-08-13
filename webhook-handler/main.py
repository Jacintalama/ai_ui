"""Webhook Handler Service - Main FastAPI Application."""
import asyncio
import os
import hmac
import time
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
from clients.tasks import TasksClient, TasksAPIError
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
from handlers.slack_interactions import SlackInteractionsHandler
from handlers.discord_commands import DiscordCommandHandler
from voice_bot import start_voice_bot, current_text_channel_id, current_guild_id
from scheduler import (
    init_scheduler, start_scheduler, shutdown_scheduler,
    list_jobs, trigger_job, register_default_jobs,
    daily_health_report, hourly_n8n_workflow_check,
    create_user_cron_job, delete_user_cron_job,
    update_user_cron_job, get_user_jobs,
)
from gateway import pipeline as gateway_pipeline
from gateway.platforms.cli import CliAdapter
from gateway.platforms.telegram import TELEGRAM_MAX_MESSAGE, TelegramAdapter
from gateway.rate_limit import SlidingWindow, client_key
from gateway.registry import PlatformEntry, registry as gateway_registry

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
# Cap the gateway/HTTP DEBUG firehose: it logs every websocket event (full
# GUILD_CREATE payloads) and rotates the container log past useful diagnostics
# in minutes. Voice-layer loggers stay at the root level on purpose.
for _noisy in ("discord.gateway", "discord.client", "discord.http", "websockets"):
    logging.getLogger(_noisy).setLevel(logging.INFO)
# httpx logs every request URL at INFO, and the Telegram Bot API puts the bot
# token IN the path, so at INFO this writes the token into the container log on
# every single call. WARNING keeps failures visible without the credential.
for _leaky in ("httpx", "httpcore"):
    logging.getLogger(_leaky).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _log_voice_bot_exit(task: "asyncio.Task") -> None:
    """Done-callback for the voice bot task so an early crash (e.g. ElevenLabs
    quota) is logged instead of dying silently until shutdown retrieves it."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Voice bot task exited with error: %r", exc, exc_info=exc)
    else:
        logger.warning("Voice bot task exited unexpectedly without an error")


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
slack_interactions_handler: Optional[SlackInteractionsHandler] = None
discord_client: Optional[DiscordClient] = None
discord_command_handler: Optional[DiscordCommandHandler] = None
loki_client: Optional[LokiClient] = None

# --- Multi-platform gateway --------------------------------------------------
# Registered at import time; each entry stays dormant until its required_env is
# present, so this changes nothing visible until a token exists.
gateway_registry.register(PlatformEntry(
    name="telegram",
    label="Telegram",
    adapter_factory=TelegramAdapter,
    required_env=["TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET"],
    max_message_length=TELEGRAM_MAX_MESSAGE,
    emoji="✈️",
))

gateway_registry.register(PlatformEntry(
    name="cli",
    label="Terminal",
    adapter_factory=CliAdapter,
    # NOT empty, despite there being nothing to configure. An empty list means
    # always enabled, which would have shipped a publicly reachable endpoint
    # switched on: Caddy's /webhook/* rule reaches this service directly,
    # bypassing api-gateway and therefore its auth and its rate limiter, and an
    # unrecognized device writes a pairing-code row. This flag is what makes
    # "deploying changes nothing visible" true for the CLI as well as Telegram.
    required_env=["GATEWAY_CLI_ENABLED"],
    max_message_length=0,   # a terminal has no message cap
    emoji="⌨️",
))

# Telegram re-delivers an update until it sees a 200, and we answer before the
# work is done, so the same update_id can arrive several times. Bounded: this
# is a dedupe window, not a log.
#
# Keyed on (bot_key, update_id), NOT update_id alone. update_id is a per-bot
# counter, so once users bring their own bots a bare integer collides across
# them and silently swallows one person's message. The shared bot uses a fixed
# key so it shares the same window without colliding with anyone.
# The terminal endpoint is the one public path here that no auth stands in
# front of, so it gets its own brakes. Deliberately generous: a person typing
# into a shell will never see these, and a script hammering pairing-code rows
# will. Per IP first because it is the cheapest to refuse; per device second
# because one host behind a shared address must not starve the others.
_CLI_PER_IP = SlidingWindow(limit=30, window_seconds=60)
_CLI_PER_DEVICE = SlidingWindow(limit=20, window_seconds=60)

SHARED_BOT_KEY = "shared"
_gateway_seen_updates: set[tuple[str, int]] = set()
_GATEWAY_SEEN_MAX = 2000

# A user's own bot, one adapter per bot_key, built on first contact.
# Bounded because a cold entry costs one internal call, not because it is a log.
# Entries also expire after _BOT_CACHE_TTL_SECONDS (see below), so a change
# made in the browser (Off, Remove, or an edit that mints a new bot_key) is
# picked up within that window instead of only on a bulk clear.
_bot_adapters: dict[str, tuple] = {}
_BOT_CACHE_MAX = 200

# How long a cached (adapter, config) entry is trusted before a lookup treats
# it as a miss and re-fetches from tasks. This is the window during which a
# bot the user just switched off, removed, or edited may still answer with
# the stale config already in memory.
_BOT_CACHE_TTL_SECONDS = 60

#: Clock the cache reads through. A module-level name (rather than a bare
#: time.monotonic() call at each site) so a test can substitute a fake clock
#: instead of sleeping 60 real seconds.
_monotonic = time.monotonic

#: The gateway's tasks client, set at startup. A module-level name because the
#: per-bot route needs it and reaching into gateway_pipeline._tasks would be
#: touching a private attribute of another module.
gateway_tasks = None


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
    global command_router, slack_command_handler, slack_interactions_handler
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

    # Hand the gateway its tasks client, then register every enabled webhook.
    # Our own client rather than reaching into command_router._tasks_client.
    # That is a private attribute, and a getattr default of None would leave the
    # gateway broken at runtime with nothing said at startup. TasksClient opens a
    # fresh httpx client per call, so a second instance costs nothing.
    global gateway_tasks
    gateway_tasks = TasksClient(
        settings.tasks_url,
        internal_secret=settings.internal_callback_secret,
    )
    gateway_pipeline.configure(gateway_tasks)
    for entry in gateway_registry.enabled():
        adapter = gateway_registry.adapter(entry.name)
        if adapter and not await adapter.connect():
            logger.error("gateway: %s did not connect; its route will 503",
                         entry.name)

    # Let the Slack events handler offer the intent router (it parks/builds via
    # the shared router). Mirrors how the Discord client is attached below.
    if settings.slack_bot_token:
        slack_handler.router = command_router

    # Wire Slack command handler if Slack is configured
    if slack_client:
        slack_command_handler = SlackCommandHandler(
            slack_client=slack_client,
            command_router=command_router,
        )
        slack_interactions_handler = SlackInteractionsHandler(
            slack_client=slack_client,
            command_router=command_router,
        )
        logger.info("Slack slash commands + interactivity enabled")

    # Discord client (only if configured)
    if settings.discord_public_key:
        discord_client = DiscordClient(
            application_id=settings.discord_application_id,
            bot_token=settings.discord_bot_token,
        )
        # Give the router a DiscordClient handle so video runners can attach
        # finished MP4s to the thread (bot-token multipart, outlives interactions).
        if command_router is not None:
            command_router._discord = discord_client
        discord_command_handler = DiscordCommandHandler(
            discord_client=discord_client,
            command_router=command_router,
        )
        logger.info("Discord slash commands enabled")
    else:
        logger.info("Discord integration disabled (no DISCORD_PUBLIC_KEY)")

    # Video thread image-drop intake (drop screenshots into the video thread).
    # Needs a DiscordClient to post replies; if Discord isn't configured the
    # intake stays None and the voice bot simply won't ingest dropped images.
    video_intake = None
    if discord_client is not None and command_router is not None:
        from handlers.video_intake import VideoThreadIntake
        video_intake = VideoThreadIntake(
            command_router, discord_client,
            video_channel_id=os.environ.get("VIDEO_CHANNEL_ID"),
            video_channel_name=os.environ.get("VIDEO_CHANNEL_NAME", "video-generation"),
        )

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

    # Voice bot (Discord voice channel — runs as background task)
    voice_bot_task = None
    if settings.discord_bot_token and settings.elevenlabs_api_key:
        voice_bot_task = asyncio.create_task(start_voice_bot(
            bot_token=settings.discord_bot_token,
            elevenlabs_api_key=settings.elevenlabs_api_key,
            agent_id=settings.elevenlabs_agent_id,
            video_intake=video_intake,
        ))
        voice_bot_task.add_done_callback(_log_voice_bot_exit)
        logger.info("Voice bot starting as background task")
    else:
        logger.info("Voice bot disabled (no DISCORD_BOT_TOKEN or ELEVENLABS_API_KEY)")

    logger.info(f"Webhook handler ready on port {settings.port}")
    logger.info(f"Open WebUI URL: {settings.openwebui_url}")

    yield

    if voice_bot_task and not voice_bot_task.done():
        voice_bot_task.cancel()
        try:
            await voice_bot_task
        except asyncio.CancelledError:
            pass
    shutdown_scheduler()

    # Undo connect() for every enabled gateway adapter (e.g. Telegram's
    # setWebhook). Without this, the documented off-switch (remove the token,
    # recreate the container) leaves the webhook registered at the platform:
    # the route now 503s, but Telegram does not know that and retries every
    # delivery forever, so pending_update_count grows without bound and users
    # get silence instead of an error. One adapter's disconnect failing must
    # not stop the others or the rest of shutdown.
    for entry in gateway_registry.enabled():
        adapter = gateway_registry.adapter(entry.name)
        if not adapter:
            continue
        try:
            await adapter.disconnect()
        except Exception:                                # noqa: BLE001
            logger.error("gateway: %s did not disconnect cleanly", entry.name,
                        exc_info=True)

    logger.info("Shutting down webhook handler...")


app = FastAPI(
    title="Webhook Handler Service",
    description="Receives webhooks and triggers Open WebUI AI analysis",
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/health")
@app.get("/webhook/health")
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

    # Fail closed: never process an unverified webhook. A missing secret is a
    # server misconfiguration, not a reason to skip verification.
    if not settings.github_webhook_secret:
        logger.error("GitHub webhook secret not configured — refusing unverified webhook")
        raise HTTPException(status_code=503, detail="GitHub signature verification not configured")
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

    # Fail closed: the integration is active (slack_handler set), so a missing
    # signing secret is a misconfiguration — reject rather than skip.
    if not settings.slack_signing_secret:
        logger.error("Slack signing secret not configured — refusing unverified request")
        raise HTTPException(status_code=503, detail="Slack signature verification not configured")
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

    # Fail closed: reject when the signing secret is missing.
    if not settings.slack_signing_secret:
        logger.error("Slack signing secret not configured — refusing unverified command")
        raise HTTPException(status_code=503, detail="Slack signature verification not configured")
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


@app.post("/webhook/slack/interactions")
async def slack_interactions_webhook(
    request: Request,
    x_slack_request_timestamp: str = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(None, alias="X-Slack-Signature"),
):
    """
    Handle Slack interactivity (App Builder panel buttons + modal submits).

    Slack sends application/x-www-form-urlencoded with a single `payload` field
    holding the JSON. Button clicks open a modal; modal submits start a build.
    Must ACK within 3 seconds; the build runs in the background.
    """
    if not slack_interactions_handler:
        raise HTTPException(status_code=503, detail="Slack integration not configured")

    body = await request.body()

    # Fail closed: reject when the signing secret is missing.
    if not settings.slack_signing_secret:
        logger.error("Slack signing secret not configured — refusing unverified interaction")
        raise HTTPException(status_code=503, detail="Slack signature verification not configured")
    if not verify_slack_signature(
        body=body,
        timestamp=x_slack_request_timestamp or "",
        signature=x_slack_signature or "",
        signing_secret=settings.slack_signing_secret,
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    form_data = dict(await request.form())
    import json
    try:
        payload = json.loads(form_data.get("payload", "{}"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid interaction payload")

    logger.info(f"Slack interaction: {payload.get('type')}")
    result = await slack_interactions_handler.handle_interaction(payload)
    return JSONResponse(content=result or {}, status_code=200)


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


_gateway_tasks: set = set()


def _spawn_gateway(coro) -> "asyncio.Task":
    """Run background work with a strong reference and a logged exception.

    An unreferenced task can be collected mid-flight (CPython docs) and a raise
    inside one is swallowed unless somebody retrieves it. Both have bitten this
    service before.
    """
    task = asyncio.create_task(coro)
    _gateway_tasks.add(task)

    def _done(t: "asyncio.Task") -> None:
        _gateway_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error("gateway: background handler failed: %r", t.exception(),
                         exc_info=t.exception())

    task.add_done_callback(_done)
    return task


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Inbound Telegram updates.

    Returns 200 before the work happens. Telegram re-delivers anything that does
    not get a fast 200, so a slow model call would otherwise cause the same
    message to be answered several times. Every failure path is also a 200 for
    the same reason: a 4xx or 5xx would make Telegram retry it forever.
    """
    adapter = gateway_registry.adapter("telegram")
    if adapter is None:
        raise HTTPException(status_code=503, detail="Telegram is not configured")

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(content={"ok": True}, status_code=200)

    headers = dict(request.headers)
    if not adapter.verify_webhook(payload, headers):
        logger.warning("gateway: rejected a Telegram update with a bad secret")
        return JSONResponse(content={"ok": True}, status_code=200)

    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        seen_key = (SHARED_BOT_KEY, update_id)
        if seen_key in _gateway_seen_updates:
            return JSONResponse(content={"ok": True}, status_code=200)
        if len(_gateway_seen_updates) >= _GATEWAY_SEEN_MAX:
            _gateway_seen_updates.clear()
        _gateway_seen_updates.add(seen_key)

    try:
        event = adapter.parse_inbound(payload, headers)
    except Exception:  # noqa: BLE001
        # Always 200. Telegram re-delivers anything else forever, so a parse bug
        # would turn one malformed update into an endless retry loop. The
        # adapter is meant to return None rather than raise, and this is the
        # backstop for when it does not.
        logger.exception("gateway: Telegram parse failed, dropping the update")
        return JSONResponse(content={"ok": True}, status_code=200)
    if event is None:
        return JSONResponse(content={"ok": True}, status_code=200)

    _spawn_gateway(gateway_pipeline.handle_event(event, adapter))
    return JSONResponse(content={"ok": True}, status_code=200)


def _bot_sender_allowed(config: dict, sender_id: str) -> bool:
    """An explicit allow list wins. With none, the bot serves only the account
    that claimed it, and an unclaimed bot serves whoever arrives first so the
    owner can claim their own bot by messaging it."""
    allowed = [p for p in (config.get("allowed_ids") or "").split(",") if p]
    if allowed:
        return sender_id in allowed
    claimed = config.get("owner_platform_user_id") or ""
    if not claimed:
        return True
    return sender_id == str(claimed)


async def _bot_adapter(bot_key: str):
    """(adapter, config) for a user's own bot, or None if there is no such bot.

    Raises TasksAPIError when tasks is unreachable or returns a non-2xx response,
    which the caller turns into a 503 so Telegram redelivers rather than losing
    the message. Other exceptions (code bugs, malformed config rows) are the
    caller's responsibility; a 503 for them would make Telegram retry forever."""
    cached = _bot_adapters.get(bot_key)
    if cached is not None:
        adapter, config, cached_at = cached
        if _monotonic() - cached_at < _BOT_CACHE_TTL_SECONDS:
            return adapter, config
        # Stale: fall through and re-fetch rather than keep serving a config
        # that may have been switched off, removed, or edited in the browser.
        _bot_adapters.pop(bot_key, None)

    if gateway_tasks is None:
        raise RuntimeError("gateway tasks client is not configured yet")

    config = await gateway_tasks.gateway_bot_config(bot_key)
    if config is None:
        return None

    # Bracket access (not .get): an entirely missing key is a different bug
    # than a present-but-empty value, and stays on the KeyError path below,
    # which the caller already turns into a dropped-not-retried 200.
    token = config["token"]
    webhook_secret = config["webhook_secret"]
    if not token or not webhook_secret:
        # Should not be reachable: both columns are NOT NULL and non-empty at
        # the DB level. But TelegramAdapter falls back to the shared bot's
        # settings when either argument is empty (gateway/platforms/telegram.py),
        # so a bad row here would silently make this user's bot authenticate
        # and send as @aiuiteam_bot. Treat it as no bot at all instead.
        logger.error("gateway: bot config for %s has an empty token or webhook "
                     "secret, refusing to build an adapter", bot_key)
        return None

    # NEVER call .connect() on this adapter: it registers the webhook against
    # the KEYLESS /webhook/telegram path, which would point this user's bot at
    # the shared route instead of their own /webhook/telegram/{bot_key}.
    adapter = TelegramAdapter(
        token=token,
        webhook_secret=webhook_secret,
    )
    adapter.name = "telegram"
    adapter.max_message_length = TELEGRAM_MAX_MESSAGE

    if len(_bot_adapters) >= _BOT_CACHE_MAX:
        _bot_adapters.clear()
    _bot_adapters[bot_key] = (adapter, config, _monotonic())
    return adapter, config


@app.post("/webhook/telegram/{bot_key}")
async def telegram_webhook_for_bot(bot_key: str, request: Request):
    """Inbound updates on a bot that belongs to one user.

    Same 200-before-the-work contract as the shared route, with two
    deliberate exceptions: an unknown key is a 404 so a stale webhook stops
    costing us a lookup, and tasks being unreachable is a 503 so Telegram
    redelivers instead of us silently eating the message.
    """
    try:
        entry = await _bot_adapter(bot_key)
    except TasksAPIError as exc:
        # .status == 0 is a network failure; 502/503/504 are a restarting or
        # overloaded tasks service. Those are worth a redelivery. Anything
        # else (a 403 from a bad internal secret, a 500 from a decrypt
        # failure) will be just as broken next time, so retrying forever
        # only buries the real error.
        if exc.status in (0, 502, 503, 504):
            logger.warning("gateway: could not load bot config, asking for a retry")
            return JSONResponse(content={"ok": False}, status_code=503)
        logger.error("gateway: bot lookup failed permanently (status %s)", exc.status)
        return JSONResponse(content={"ok": True}, status_code=200)
    except Exception:  # noqa: BLE001
        # Anything else is a bug in us or a malformed row, and it will still be
        # broken on the next attempt. A 503 here would make Telegram retry this
        # message forever, so drop it loudly instead. Same rule the parse
        # handler on the shared route already follows.
        logger.exception("gateway: could not build an adapter for a user bot")
        return JSONResponse(content={"ok": True}, status_code=200)

    if entry is None:
        return JSONResponse(content={"ok": False}, status_code=404)

    adapter, config = entry

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(content={"ok": True}, status_code=200)

    headers = dict(request.headers)
    if not adapter.verify_webhook(payload, headers):
        logger.warning("gateway: rejected an update with a bad secret")
        return JSONResponse(content={"ok": True}, status_code=200)

    if not config.get("enabled"):
        # The user switched their bot off. deleteWebhook stops this at source;
        # anything already in flight lands here.
        return JSONResponse(content={"ok": True}, status_code=200)

    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        seen_key = (bot_key, update_id)
        if seen_key in _gateway_seen_updates:
            return JSONResponse(content={"ok": True}, status_code=200)
        if len(_gateway_seen_updates) >= _GATEWAY_SEEN_MAX:
            _gateway_seen_updates.clear()
        _gateway_seen_updates.add(seen_key)

    try:
        event = adapter.parse_inbound(payload, headers)
    except Exception:  # noqa: BLE001
        logger.exception("gateway: parse failed on a user bot, dropping the update")
        return JSONResponse(content={"ok": True}, status_code=200)
    if event is None:
        return JSONResponse(content={"ok": True}, status_code=200)

    # MessageEvent carries the person on event.source.user_id, NOT on the event
    # itself: source.chat_id is the conversation and source.user_id is the
    # human. On a Telegram DM they happen to be the same number, which is
    # exactly why reading the wrong one would pass every test and be wrong in a
    # group.
    sender_id = str(event.source.user_id or "")
    if not _bot_sender_allowed(config, sender_id):
        logger.info("gateway: a user bot ignored a sender it does not serve")
        return JSONResponse(content={"ok": True}, status_code=200)

    if not config.get("owner_platform_user_id") and sender_id:
        try:
            if await gateway_tasks.gateway_bot_claim(bot_key, sender_id):
                config["owner_platform_user_id"] = sender_id
            else:
                # Someone else owns this bot. Our cached config still says
                # unclaimed, and an unclaimed bot serves everyone, so drop
                # the entry rather than leave the gate open until a restart.
                _bot_adapters.pop(bot_key, None)
        except Exception:  # noqa: BLE001
            # A failed claim leaves the bot unclaimed and still serving. It is
            # a narrowing step, so failing open here loses nothing that was not
            # already open.
            logger.warning("gateway: could not record a bot claim")

    _spawn_gateway(gateway_pipeline.handle_event(event, adapter))
    return JSONResponse(content={"ok": True}, status_code=200)


@app.post("/webhook/gateway/cli")
async def gateway_cli(request: Request):
    """The terminal client. Synchronous: the caller is blocked on the answer.

    Unlike Telegram there is no re-delivery to defend against, so there is no
    reason to answer before the work is done.
    """
    adapter = gateway_registry.adapter("cli")
    if adapter is None:
        raise HTTPException(status_code=503, detail="CLI gateway is not available")

    headers = dict(request.headers)

    # Charged before the body is even read, because the cheapest request to
    # refuse is the one nothing has been spent on yet.
    caller = client_key(headers, request.client.host if request.client else "")
    if not _CLI_PER_IP.allow(caller):
        logger.warning("gateway: cli rate limit hit for a caller")
        raise HTTPException(
            status_code=429,
            detail="Too many requests from your network. Wait a minute and try again.")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event = adapter.parse_inbound(payload, headers)
    if event is None:
        raise HTTPException(status_code=400,
                            detail="A 32 character hex device_id and a non-empty "
                                   "text are both required")

    # A second, tighter budget per device. The IP limit alone would let one
    # host behind a shared address starve the others; this one is what a single
    # runaway terminal actually runs into.
    if not _CLI_PER_DEVICE.allow(event.source.chat_id):
        logger.warning("gateway: cli rate limit hit for a device")
        raise HTTPException(
            status_code=429,
            detail="You are sending faster than IO can answer. Wait a moment.")

    reply = await gateway_pipeline.handle_event(event, adapter)
    return JSONResponse(content={"reply": reply}, status_code=200)


# Last voice-started build (single voice identity by design). Lets the agent's
# build_status tool answer "is my build done?" even after a session reconnect.
_last_voice_build: dict = {}


async def _hydrate_last_voice_build() -> None:
    """On a cache miss (e.g. after a handler restart), rehydrate the last voice
    build from the durable store so build_status / answer_build still work.
    Best-effort: any error (or a mocked router without the method) is a no-op."""
    if _last_voice_build.get("task_id"):
        return
    try:
        entry = await command_router.recall_voice_build()
    except Exception:  # noqa: BLE001 - never break a voice turn
        return
    if entry and entry.get("task_id"):
        _last_voice_build.clear()
        _last_voice_build.update(entry)


async def _post_to_discord_channel(
    channel_id: str, content: str, components: list | None = None,
) -> None:
    """Plain bot-token channel message (same pattern as the alert forwarder)."""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {settings.discord_bot_token}",
        "Content-Type": "application/json",
    }
    payload: dict = {"content": content[:1990]}
    if components:
        payload["components"] = components
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()


def _voice_discord_id() -> str | None:
    """Discord id of the voice user (reverse lookup of the email map)."""
    email = (settings.voice_user_email or "").strip().lower()
    if not email:
        return None
    for did, mapped in settings.discord_user_email_map.items():
        if mapped == email:
            return did
    return None


def _thread_link_components(guild_id: str, thread_id: str) -> list:
    """A link button that jumps to the user's private App Builder thread."""
    return [{
        "type": 1,
        "components": [{
            "type": 2, "style": 5, "label": "Open my App Builder thread",
            "url": f"https://discord.com/channels/{guild_id}/{thread_id}",
        }],
    }]


def _voice_notify_channel():
    """notify_channel for voice-started builds. The target is resolved at
    NOTIFY time (builds finish minutes later): the active voice session's
    text channel when one exists, else the alert channel. Messages carry a
    link button to the user's App Builder thread when resolvable."""
    if not settings.discord_bot_token:
        return None

    async def notify(msg: str) -> None:
        channel_id = current_text_channel_id() or settings.discord_alert_channel_id
        if not channel_id:
            logger.warning("voice notify dropped (no channel configured): %s", msg[:80])
            return
        components = None
        try:
            did = _voice_discord_id()
            gid = current_guild_id()
            if did and gid and command_router is not None:
                tid = await command_router.get_user_builder_thread(did)
                if tid:
                    components = _thread_link_components(gid, str(tid))
        except Exception as exc:  # noqa: BLE001 — button is best-effort
            logger.debug(f"voice notify thread button skipped: {exc}")
        await _post_to_discord_channel(channel_id, msg, components)

    return notify


@app.post("/webhook/voice/{command}")
async def voice_webhook(
    command: str,
    request: Request,
    x_voice_secret: str = Header(None, alias="X-Voice-Secret"),
):
    """Handle tool calls from ElevenLabs voice agent.

    Three App Builder commands are special-cased (explicit body fields, build
    memory); everything else is the generic command-router passthrough.
    """
    if (not settings.voice_webhook_secret or not x_voice_secret
            or not hmac.compare_digest(x_voice_secret, settings.voice_webhook_secret)):
        raise HTTPException(status_code=401, detail="Invalid voice webhook secret")

    body = await request.json()
    collector = VoiceResponseCollector()

    def _ctx(subcommand: str, arguments: str) -> CommandContext:
        return CommandContext(
            user_id="voice-agent",
            user_name="Voice User",
            channel_id=body.get("channel_id", "voice"),
            raw_text=f"{subcommand} {arguments}".strip(),
            subcommand=subcommand,
            arguments=arguments,
            platform="voice",
            respond=collector.respond,
            metadata={"source": "elevenlabs"},
            notify_channel=_voice_notify_channel(),
        )

    if command == "list_templates":
        await command_router.execute(_ctx("aiuibuilder", "templates"))
    elif command == "start_build":
        result = await command_router.run_voice_build(
            _ctx("aiuibuilder", "build"),
            body.get("template_key"),
            body.get("description") or "",
        )
        if result:
            _last_voice_build.clear()
            _last_voice_build.update({
                "task_id": result.get("task_id", ""),
                "slug": result.get("slug", ""),
                "email": (settings.voice_user_email or "").strip().lower(),
            })
    elif command == "build_status":
        await _hydrate_last_voice_build()
        task_id = (body.get("task_id") or "").strip() or _last_voice_build.get("task_id", "")
        if not task_id:
            await collector.respond(
                "I haven't started any build for you yet — ask me to build "
                "something first."
            )
        else:
            await command_router.run_voice_build_status(
                _ctx("aiuibuilder", "build-status"),
                _last_voice_build.get("email")
                or (settings.voice_user_email or "").strip().lower(),
                task_id,
                slug=_last_voice_build.get("slug", ""),
            )
    elif command == "answer_build":
        await _hydrate_last_voice_build()
        answer = (body.get("answer") or "").strip()
        task_id = (body.get("task_id") or "").strip() or _last_voice_build.get("task_id", "")
        email = (_last_voice_build.get("email")
                 or (settings.voice_user_email or "").strip().lower())
        if not answer:
            await collector.respond(
                "What should I tell the builder? Say your answer and I'll pass it on."
            )
        elif not task_id:
            await collector.respond(
                "I don't have a paused build to answer — ask me to build "
                "something first."
            )
        else:
            await command_router.run_voice_answer_build(
                _ctx("aiuibuilder", "answer-build"),
                email, task_id, answer,
                slug=_last_voice_build.get("slug", ""),
            )
    else:
        arguments = body.get("arguments", "")
        if body.get("owner") and body.get("repo"):
            arguments = f"{body['owner']}/{body['repo']} {arguments}".strip()
        await command_router.execute(_ctx(command, arguments))

    return {
        "spoken_summary": collector.spoken_summary,
        "full_result": collector.full_result,
        "post_to_text_channel": len(collector.full_result) > 500,
    }


class ScheduleResultIn(BaseModel):
    channel_id: str
    schedule_name: str = ""
    status: str = ""
    result: str = ""
    schedule_id: str = ""
    platform: str = "discord"
    video_job_id: str = ""
    video_user_email: str = ""


def _to_slack_mrkdwn(text: str) -> str:
    """Convert common Markdown to Slack mrkdwn so AI output renders correctly.

    Slack uses *bold* (single asterisk), not Markdown's **bold**, and
    <url|label> links, not [label](url). Without this, **bold** shows literal
    asterisks. Discord renders standard Markdown natively, so this is Slack-only.
    """
    # [label](url) -> <url|label> (do links first so their parens are untouched).
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)
    # Markdown headings at line start -> a bold line.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", r"*\1*", text)
    # **bold** / __bold__ -> *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"*\1*", text)
    return text


def _format_schedule_result(
    name: str, status: str, result: str, platform: str = "discord"
) -> str:
    """Format a finished scheduled-task result as a clean, quiet message (<=1990).

    `name` is platform-specific: Discord passes ``"<when>: <prompt>"`` while Slack
    passes the bare prompt. Only Discord names carry a ``"<when>: <prompt>"``
    structure, so the ``": "`` split is gated on ``platform == "discord"``. For
    any other platform (e.g. Slack) the whole name is the title with no footer,
    so a prompt that happens to contain ``": "`` (e.g. ``"remind me: drink water"``)
    renders intact.
    """
    try:
        if platform == "discord" and ": " in name:
            _when, title = name.split(": ", 1)
        else:
            title = name
    except Exception:
        title = name
    body = (result or "").strip() or "_(no output)_"
    if status == "completed":
        # Successful runs deliver ONLY the output, no prompt echo, no footer.
        text = body
    else:
        # Failed/skipped runs still name the schedule so the user knows what broke.
        text = f"⚠️ **{title}** — {status}\n\n{body}"
    if platform == "slack":
        text = _to_slack_mrkdwn(text)
    return text[:1990]


@app.post("/internal/schedule-result")
async def schedule_result(
    body: ScheduleResultIn,
    x_internal_secret: str = Header(None, alias="X-Internal-Secret"),
):
    """Post a finished scheduled-task result into the user's Discord thread.

    Secret-gated: only the tasks container (which holds INTERNAL_CALLBACK_SECRET)
    may call this. Fails closed when the secret is unset.
    """
    expected = settings.internal_callback_secret
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Invalid internal secret")
    if body.platform == "slack":
        if slack_client is None:
            raise HTTPException(status_code=503, detail="Slack not configured")
        text = _format_schedule_result(
            body.schedule_name, body.status, body.result, platform="slack"
        )
        blocks = None
        if body.schedule_id and body.status not in ("completed", "skipped"):
            from handlers.slack_schedule_panel import build_retry_blocks
            blocks = build_retry_blocks(body.schedule_id)
        ts = await slack_client.post_message(
            channel=body.channel_id, text=text, blocks=blocks
        )
        if not ts:
            logger.error(
                "Slack schedule-result delivery failed schedule_id=%s channel=%s status=%s",
                body.schedule_id,
                body.channel_id,
                body.status,
            )
            raise HTTPException(status_code=502, detail="Slack delivery failed")
        return {"status": "delivered"}
    if discord_client is None:
        raise HTTPException(status_code=503, detail="Discord not configured")
    message = _format_schedule_result(
        body.schedule_name, body.status, body.result, platform="discord"
    )
    # A completed video schedule: try to attach the finished MP4 directly.
    # Any problem (download failure, oversized blob, post failure) falls
    # through to the plain text post below, so delivery never gets worse.
    if body.video_job_id and body.video_user_email:
        from handlers.commands import VIDEO_ATTACH_MAX_MB
        tasks_client = getattr(command_router, "_tasks_client", None)
        if tasks_client is not None:
            try:
                blob = await tasks_client.download_video_bytes(
                    body.video_user_email, body.video_job_id)
                if len(blob) <= VIDEO_ATTACH_MAX_MB * 1024 * 1024:
                    ok = await discord_client.post_channel_file(
                        body.channel_id,
                        [(f"{(body.schedule_name or 'video')[:60]}.mp4", blob, "video/mp4")],
                        content=message)
                    if ok:
                        return {"status": "delivered"}
            except Exception as exc:  # noqa: BLE001
                logger.warning("schedule video attach failed job=%s: %s",
                               body.video_job_id, exc)
    # On a failed run, attach a one-click Retry (reuses the run-now handler).
    components = None
    if body.schedule_id and body.status not in ("completed", "skipped"):
        from handlers.app_builder_panel import build_retry_components
        components = build_retry_components(body.schedule_id)
    await discord_client.post_channel_message(body.channel_id, message, components=components)
    return {"status": "delivered"}


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
