"""Configuration management for webhook handler."""
import logging
import os
from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional

logger = logging.getLogger(__name__)


def parse_discord_user_email_map(raw: str) -> dict[str, str]:
    """Parse DISCORD_USER_EMAIL_MAP env var.

    Format: comma-separated `<snowflake_id>:<email>` pairs.
    Drops entries with non-numeric IDs or missing colons (logs at DEBUG).
    Lowercases emails. Warns on duplicate emails (silent cross-user risk).
    Returns the count via logger.info, never the contents.
    """
    if not raw:
        return {}
    out: dict[str, str] = {}
    seen_emails: dict[str, str] = {}  # email -> first discord_id that claimed it
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            logger.debug("DISCORD_USER_EMAIL_MAP: skipping malformed entry")
            continue
        did, _, email = entry.partition(":")
        did = did.strip()
        email = email.strip().lower()
        if not did.isdigit():
            logger.debug("DISCORD_USER_EMAIL_MAP: non-numeric ID dropped")
            continue
        if not email:
            continue
        if email in seen_emails:
            logger.warning(
                "DISCORD_USER_EMAIL_MAP: duplicate email — two Discord IDs "
                "claim the same account (silent cross-user impersonation risk)"
            )
        seen_emails[email] = did
        out[did] = email
    logger.info(f"DISCORD_USER_EMAIL_MAP: loaded {len(out)} entries")
    return out


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Service
    port: int = 8086
    debug: bool = False

    # GitHub
    github_webhook_secret: str = ""
    github_token: str = ""

    # Open WebUI
    openwebui_url: str = "http://open-webui:8080"
    openwebui_api_key: str = ""

    # AI Settings
    ai_model: str = "gpt-4-turbo"
    ai_system_prompt: str = "You are a helpful AI assistant that analyzes GitHub issues and suggests solutions. Be concise and actionable."

    # MCP Proxy
    mcp_proxy_url: str = "http://mcp-proxy:8000"
    mcp_user_email: str = "webhook-handler@system"
    mcp_user_groups: str = "MCP-Admin"

    # Automation Pipe
    automation_pipe_model: str = "webhook_automation.webhook-automation"

    # n8n
    n8n_url: str = "http://n8n:5678"
    n8n_webhook_url: str = "http://n8n:5678"
    n8n_api_key: str = ""

    # Claude Analyzer (PR Review, BRE, Security, etc.)
    claude_analyzer_url: str = "http://claude-analyzer:3000"

    # Slack
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # Discord
    discord_application_id: str = ""
    discord_public_key: str = ""
    discord_bot_token: str = ""
    discord_alert_channel_id: str = ""
    discord_user_email_map_raw: str = Field(default="", alias="DISCORD_USER_EMAIL_MAP")

    @property
    def discord_user_email_map(self) -> dict[str, str]:
        if not hasattr(self, "_discord_map_cache"):
            self._discord_map_cache = parse_discord_user_email_map(
                self.discord_user_email_map_raw
            )
        return self._discord_map_cache

    # Voice (ElevenLabs)
    voice_webhook_secret: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "pFZP5JQG7iQjIQuC4Bku"
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_agent_id: str = ""

    # Loki
    loki_url: str = "http://loki:3100"

    # Report
    report_github_repo: str = "TheLukasHenry/proxy-server"
    report_slack_channel: str = ""

    # Scheduler guardrails
    scheduler_min_interval_minutes: int = 1
    scheduler_max_user_jobs: int = 10
    scheduler_default_expiry_hours: int = 24

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()


def get_service_endpoints() -> dict[str, str]:
    """Single source of truth for health check endpoints."""
    return {
        "open-webui": f"{settings.openwebui_url}/api/config",
        "mcp-proxy": f"{settings.mcp_proxy_url}/health",
        "n8n": f"{settings.n8n_url}/healthz",
        "webhook-handler": f"http://localhost:{settings.port}/health",
    }
