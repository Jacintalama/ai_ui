"""Configuration management for webhook handler."""
import os
from pydantic_settings import BaseSettings
from typing import Optional


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
    n8n_url: str = "https://n8n.srv1041674.hstgr.cloud"
    n8n_api_key: str = ""

    # Slack
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # Discord
    discord_application_id: str = ""
    discord_public_key: str = ""
    discord_bot_token: str = ""

    # Report
    report_github_repo: str = "TheLukasHenry/proxy-server"
    report_slack_channel: str = ""

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
