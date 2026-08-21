# mcp-proxy/tenants.py
"""
MCP Proxy Gateway - Tenant and Server Configuration

This module defines:
- Server tiers (HTTP, SSE, stdio, local)
- MCP server configurations
- Tenant access control
- User permissions

Kubernetes deployment: localhost:8080
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
import os
import asyncio


# =============================================================================
# SERVER TIER DEFINITIONS
# =============================================================================
class ServerTier(Enum):
    """MCP Server protocol tiers."""
    HTTP = "http"          # Tier 1: Direct HTTP connection (HubSpot, etc.)
    MCP_HTTP = "mcp_http"  # Tier 1b: MCP Streamable HTTP (Linear, Sentry)
    SSE = "sse"            # Tier 2: Server-Sent Events via mcpo proxy (Atlassian, Asana)
    STDIO = "stdio"        # Tier 3: stdio via mcpo proxy (SonarQube)
    LOCAL = "local"        # Local container in Kubernetes cluster


class AccessClass(Enum):
    """What it costs to let someone use a server.

    `api_key_env` cannot answer this. It is MCP_API_KEY on nearly every server,
    because that is the proxy's own key for reaching the container, not the
    vendor's credential. So the answer has to be declared, and it is declared
    here, next to the server it describes, rather than in a list somewhere else
    that drifts. A list somewhere else is how group_tenant_mapping ended up
    granting five servers that were never deployed.
    """
    #: No vendor credential and no reach into other users' data. Any signed-in
    #: user gets these without a grant.
    PUBLIC = "public"
    #: No vendor credential, but it can see or change things belonging to other
    #: users. Needs an explicit grant even though nothing is being spent.
    RESTRICTED = "restricted"
    #: Runs on one shared vendor token, so using it means acting as the
    #: platform's own account. Needs an explicit grant, and the intended fix is
    #: for the user to connect their own credential instead.
    SHARED = "shared"


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server endpoint."""
    server_id: str
    display_name: str
    tier: ServerTier
    endpoint_url: str
    auth_type: str  # bearer, oauth, api_key
    api_key_env: Optional[str] = None
    enabled: bool = True
    description: str = ""
    #: Defaults to SHARED so a server added without thought is restricted
    #: rather than handed to everyone. Widening is a deliberate edit.
    access_class: "AccessClass" = None  # set in __post_init__


    def __post_init__(self):
        if self.access_class is None:
            self.access_class = AccessClass.SHARED


@dataclass
class TenantConfig:
    """Configuration for a tenant."""
    tenant_id: str
    display_name: str
    mcp_endpoint: str
    mcp_api_key: str
    credentials: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class UserTenantAccess:
    """User's access to a tenant."""
    user_email: str
    tenant_id: str
    access_level: str = "read"  # read, write, admin


# =============================================================================
# KUBERNETES SERVICE URLS (localhost:8080 cluster)
# =============================================================================
# These URLs are for Kubernetes internal service discovery
# Format: http://<service-name>:<port>

# Per-user tool servers, hosted by the tasks service. Each acts as the
# CALLER's own third-party account (credential stored per user, encrypted),
# never the platform's shared token, which is why they are PUBLIC: using one
# spends nothing that belongs to anybody else.
MCP_MYTOOLS_URL = os.getenv("MCP_MYTOOLS_URL", "http://tasks:8210/mytools")

MCP_FILESYSTEM_URL = os.getenv("MCP_FILESYSTEM_URL", "http://mcp-filesystem:8001")
MCP_GITHUB_URL = os.getenv("MCP_GITHUB_URL", "http://mcp-github:8000")
MCPO_SSE_URL = os.getenv("MCPO_SSE_URL", "http://mcpo-sse")
MCPO_STDIO_URL = os.getenv("MCPO_STDIO_URL", "http://mcpo-stdio")


# =============================================================================
# TIER 1: HTTP SERVERS (Direct Connection - Quick Wins)
# =============================================================================
# These servers support HTTP/REST directly, no proxy needed
# Source: https://github.com/punkpeye/awesome-mcp-servers
TIER1_SERVERS: Dict[str, MCPServerConfig] = {
    # -------------------------------------------------------------------------
    # Issue Tracking & Project Management
    # -------------------------------------------------------------------------
    "linear": MCPServerConfig(
        server_id="linear",
        display_name="Linear",
        tier=ServerTier.MCP_HTTP,
        endpoint_url="https://mcp.linear.app/mcp",
        auth_type="oauth",
        api_key_env="LINEAR_API_KEY",
        description="Issue tracking and project management",
        enabled=bool(os.getenv("LINEAR_API_KEY"))
    ),

    # -------------------------------------------------------------------------
    # CRM & Marketing
    # -------------------------------------------------------------------------
    "hubspot": MCPServerConfig(
        server_id="hubspot",
        display_name="HubSpot",
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.hubspot.com/anthropic",
        auth_type="bearer",
        api_key_env="HUBSPOT_API_KEY",
        description="CRM and marketing automation",
        enabled=bool(os.getenv("HUBSPOT_API_KEY"))
    ),

    # -------------------------------------------------------------------------
    # Infrastructure & DevOps
    # -------------------------------------------------------------------------
    "pulumi": MCPServerConfig(
        server_id="pulumi",
        display_name="Pulumi",
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.ai.pulumi.com/mcp",
        auth_type="bearer",
        api_key_env="PULUMI_ACCESS_TOKEN",
        description="Infrastructure as Code",
        enabled=bool(os.getenv("PULUMI_ACCESS_TOKEN"))
    ),

    # -------------------------------------------------------------------------
    # Source Control & CI/CD
    # -------------------------------------------------------------------------
    "gitlab": MCPServerConfig(
        server_id="gitlab",
        display_name="GitLab",
        tier=ServerTier.HTTP,
        endpoint_url="https://gitlab.com/api/v4/mcp",
        auth_type="oauth",
        api_key_env="GITLAB_TOKEN",
        description="Git repository and CI/CD (requires GitLab 18.6+)",
        enabled=bool(os.getenv("GITLAB_TOKEN"))
    ),
    "github-remote": MCPServerConfig(
        server_id="github-remote",
        display_name="GitHub (Official Remote)",
        tier=ServerTier.HTTP,
        endpoint_url="https://api.githubcopilot.com/mcp/",
        auth_type="oauth",
        api_key_env="GITHUB_TOKEN",
        description="GitHub official remote MCP (51 tools) - repos, PRs, issues, code search",
        enabled=False  # Disabled: we use the local github container instead
    ),

    # -------------------------------------------------------------------------
    # Monitoring & Error Tracking
    # -------------------------------------------------------------------------
    "sentry": MCPServerConfig(
        server_id="sentry",
        display_name="Sentry",
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.sentry.dev/mcp",
        auth_type="bearer",
        api_key_env="SENTRY_AUTH_TOKEN",
        description="Error tracking and monitoring (16 tools)",
        enabled=bool(os.getenv("SENTRY_AUTH_TOKEN"))
    ),
    "datadog": MCPServerConfig(
        server_id="datadog",
        display_name="Datadog",
        tier=ServerTier.HTTP,
        endpoint_url=os.getenv("DATADOG_MCP_URL", "https://mcp.datadoghq.com"),  # Managed endpoint
        auth_type="bearer",
        api_key_env="DATADOG_API_KEY",
        description="Monitoring and observability (Preview - request access)",
        enabled=False  # Requires access request from Datadog
    ),
    "grafana": MCPServerConfig(
        server_id="grafana",
        display_name="Grafana",
        tier=ServerTier.HTTP,
        endpoint_url=os.getenv("GRAFANA_MCP_URL", "https://mcp.grafana.com"),  # Cloud managed
        auth_type="bearer",
        api_key_env="GRAFANA_API_KEY",
        description="Dashboards, alerts, and visualization",
        enabled=False  # Requires Grafana Cloud setup
    ),

    # -------------------------------------------------------------------------
    # Data & Analytics
    # -------------------------------------------------------------------------
    "snowflake": MCPServerConfig(
        server_id="snowflake",
        display_name="Snowflake",
        tier=ServerTier.HTTP,
        endpoint_url=os.getenv("SNOWFLAKE_MCP_URL", ""),  # Tenant-specific
        auth_type="bearer",
        api_key_env="SNOWFLAKE_PAT",
        description="Data warehouse - Cortex AI, SQL, semantic views (GA Nov 2025)",
        enabled=False  # Requires tenant-specific URL
    ),
    "dbt": MCPServerConfig(
        server_id="dbt",
        display_name="dbt",
        tier=ServerTier.HTTP,
        endpoint_url=os.getenv("DBT_MCP_URL", "https://mcp.getdbt.com"),  # Remote MCP
        auth_type="oauth",
        api_key_env="DBT_API_KEY",
        description="Data transformation - models, lineage, metrics",
        enabled=False  # Requires dbt Cloud setup
    ),

    # -------------------------------------------------------------------------
    # Communication (Official endpoints coming)
    # -------------------------------------------------------------------------
    "slack": MCPServerConfig(
        server_id="slack",
        display_name="Slack",
        tier=ServerTier.HTTP,
        endpoint_url=os.getenv("SLACK_MCP_URL", "https://mcp.slack.com"),  # Coming Q1 2026
        auth_type="oauth",
        api_key_env="SLACK_BOT_TOKEN",
        description="Team communication - channels, messages, search (GA Q1 2026)",
        enabled=False  # Official endpoint coming Q1 2026
    ),

    # -------------------------------------------------------------------------
    # Security & Code Quality
    # -------------------------------------------------------------------------
    "snyk": MCPServerConfig(
        server_id="snyk",
        display_name="Snyk",
        tier=ServerTier.HTTP,
        endpoint_url=os.getenv("SNYK_MCP_URL", "https://mcp.snyk.io"),
        auth_type="bearer",
        api_key_env="SNYK_TOKEN",
        description="Security scanning and vulnerability management",
        enabled=False  # Requires Snyk setup
    ),
}

# =============================================================================
# TIER 2: SSE SERVERS (Official Remote or via mcpo-sse proxy)
# =============================================================================
# These servers use Server-Sent Events
TIER2_SERVERS: Dict[str, MCPServerConfig] = {
    "atlassian": MCPServerConfig(
        server_id="atlassian",
        display_name="Atlassian (Jira/Confluence)",
        tier=ServerTier.SSE,
        # Official Atlassian Remote MCP Server (SSE)
        endpoint_url=os.getenv("ATLASSIAN_MCP_URL", "https://mcp.atlassian.com/v1/sse"),
        auth_type="bearer",
        api_key_env="ATLASSIAN_API_KEY",
        description="Jira issues and Confluence pages (Official Remote MCP)",
        enabled=bool(os.getenv("ATLASSIAN_API_KEY"))  # Auto-enable if API key is set
    ),
    "asana": MCPServerConfig(
        server_id="asana",
        display_name="Asana",
        tier=ServerTier.SSE,
        endpoint_url=f"{MCPO_SSE_URL}:8011",
        auth_type="bearer",
        api_key_env="ASANA_TOKEN",
        description="Task and project management",
        enabled=bool(os.getenv("ASANA_TOKEN"))
    ),
}

# =============================================================================
# TIER 3: STDIO SERVERS (via mcpo-stdio proxy)
# =============================================================================
# These servers use stdio protocol, need mcpo to convert to HTTP
# NOTE: SonarQube requires valid credentials (SONARQUBE_TOKEN + URL/ORG)
#       Sentry has been moved to TIER1_SERVERS using HTTP endpoint
TIER3_SERVERS: Dict[str, MCPServerConfig] = {
    # -------------------------------------------------------------------------
    # Code Quality & Security
    # -------------------------------------------------------------------------
    "sonarqube": MCPServerConfig(
        server_id="sonarqube",
        access_class=AccessClass.SHARED,
        display_name="SonarQube",
        tier=ServerTier.STDIO,
        endpoint_url=os.getenv("MCP_SONARQUBE_URL", "http://mcp-sonarqube:8000"),
        auth_type="bearer",
        api_key_env="MCP_API_KEY",  # mcpo uses MCP_API_KEY for auth
        description="Code quality and security analysis",
        enabled=bool(os.getenv("SONARQUBE_TOKEN"))  # Auto-enable if SonarQube token is set
    ),

    # -------------------------------------------------------------------------
    # Project Management
    # -------------------------------------------------------------------------
    "clickup": MCPServerConfig(
        server_id="clickup",
        access_class=AccessClass.SHARED,
        display_name="ClickUp",
        tier=ServerTier.STDIO,
        endpoint_url=os.getenv("MCP_CLICKUP_URL", "http://mcp-clickup:8000"),
        auth_type="bearer",
        api_key_env="MCP_API_KEY",  # mcpo uses MCP_API_KEY for auth
        description="Task and project management - tasks, projects, goals (177+ tools)",
        enabled=bool(os.getenv("CLICKUP_API_TOKEN"))  # Auto-enable if ClickUp token is set
    ),
    "trello": MCPServerConfig(
        server_id="trello",
        access_class=AccessClass.SHARED,
        display_name="Trello",
        tier=ServerTier.STDIO,
        endpoint_url=os.getenv("MCP_TRELLO_URL", "http://mcp-trello:8000"),
        auth_type="bearer",
        api_key_env="MCP_API_KEY",  # mcpo uses MCP_API_KEY for auth
        description="Kanban boards and task management",
        enabled=bool(os.getenv("TRELLO_API_KEY"))  # Auto-enable if Trello key is set
    ),
    "airtable": MCPServerConfig(
        server_id="airtable",
        display_name="Airtable",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8023",
        auth_type="bearer",
        api_key_env="AIRTABLE_API_KEY",
        description="Database and spreadsheet hybrid",
        enabled=False
    ),
    "monday": MCPServerConfig(
        server_id="monday",
        display_name="Monday.com",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8024",
        auth_type="bearer",
        api_key_env="MONDAY_API_KEY",
        description="Work management platform",
        enabled=False
    ),

    # -------------------------------------------------------------------------
    # Cloud & Infrastructure
    # -------------------------------------------------------------------------
    "terraform": MCPServerConfig(
        server_id="terraform",
        display_name="Terraform Cloud",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8025",
        auth_type="bearer",
        api_key_env="TERRAFORM_TOKEN",
        description="Infrastructure as Code - workspaces, runs, state",
        enabled=False
    ),
    "kubernetes": MCPServerConfig(
        server_id="kubernetes",
        display_name="Kubernetes",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8026",
        auth_type="bearer",
        api_key_env="KUBECONFIG_BASE64",
        description="Kubernetes cluster management - pods, deployments, services",
        enabled=False
    ),
    "docker": MCPServerConfig(
        server_id="docker",
        display_name="Docker",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8027",
        auth_type="bearer",
        api_key_env="DOCKER_HOST",
        description="Container management - images, containers, volumes",
        enabled=False
    ),

    # -------------------------------------------------------------------------
    # Databases
    # -------------------------------------------------------------------------
    "postgresql-mcp": MCPServerConfig(
        server_id="postgresql-mcp",
        display_name="PostgreSQL MCP",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8028",
        auth_type="bearer",
        api_key_env="POSTGRES_MCP_URL",
        description="PostgreSQL database access - queries, schema, data",
        enabled=False
    ),
    "mongodb": MCPServerConfig(
        server_id="mongodb",
        display_name="MongoDB",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8029",
        auth_type="bearer",
        api_key_env="MONGODB_URL",
        description="MongoDB database access - documents, collections",
        enabled=False
    ),
    "mysql": MCPServerConfig(
        server_id="mysql",
        display_name="MySQL",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8030",
        auth_type="bearer",
        api_key_env="MYSQL_URL",
        description="MySQL database access - queries, schema",
        enabled=False
    ),
    "bigquery": MCPServerConfig(
        server_id="bigquery",
        display_name="BigQuery",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8031",
        auth_type="oauth",
        api_key_env="GOOGLE_APPLICATION_CREDENTIALS",
        description="Google BigQuery - data warehouse queries",
        enabled=False
    ),

    # -------------------------------------------------------------------------
    # File Storage
    # -------------------------------------------------------------------------
    # google-drive: moved to LOCAL_SERVERS (mcp-gdrive container)
    "onedrive": MCPServerConfig(
        server_id="onedrive",
        display_name="OneDrive",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8033",
        auth_type="oauth",
        api_key_env="MICROSOFT_GRAPH_TOKEN",
        description="Microsoft OneDrive file access",
        enabled=False
    ),
    "sharepoint": MCPServerConfig(
        server_id="sharepoint",
        display_name="SharePoint",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8034",
        auth_type="oauth",
        api_key_env="MICROSOFT_GRAPH_TOKEN",
        description="Microsoft SharePoint document management",
        enabled=False
    ),

    # -------------------------------------------------------------------------
    # Communication
    # -------------------------------------------------------------------------
    "teams": MCPServerConfig(
        server_id="teams",
        display_name="Microsoft Teams",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8035",
        auth_type="oauth",
        api_key_env="MICROSOFT_GRAPH_TOKEN",
        description="Microsoft Teams - channels, messages, meetings (Preview)",
        enabled=False
    ),
    "zoom": MCPServerConfig(
        server_id="zoom",
        display_name="Zoom",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8036",
        auth_type="oauth",
        api_key_env="ZOOM_API_KEY",
        description="Zoom meetings and webinars",
        enabled=False
    ),

    # -------------------------------------------------------------------------
    # Development & Version Control
    # -------------------------------------------------------------------------
    "git": MCPServerConfig(
        server_id="git",
        display_name="Git",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8037",
        auth_type="none",
        api_key_env=None,
        description="Local Git repository access - commits, branches, diffs",
        enabled=False
    ),
    "bitbucket": MCPServerConfig(
        server_id="bitbucket",
        display_name="Bitbucket",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8038",
        auth_type="bearer",
        api_key_env="BITBUCKET_TOKEN",
        description="Bitbucket repositories and pipelines",
        enabled=False
    ),

    # -------------------------------------------------------------------------
    # CI/CD & DevOps
    # -------------------------------------------------------------------------
    "jenkins": MCPServerConfig(
        server_id="jenkins",
        display_name="Jenkins",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8039",
        auth_type="bearer",
        api_key_env="JENKINS_API_TOKEN",
        description="Jenkins CI/CD - jobs, builds, pipelines",
        enabled=False
    ),

    # -------------------------------------------------------------------------
    # Analytics & Data
    # -------------------------------------------------------------------------
    "segment": MCPServerConfig(
        server_id="segment",
        display_name="Segment",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8040",
        auth_type="bearer",
        api_key_env="SEGMENT_API_KEY",
        description="Customer data platform - events, users, tracking",
        enabled=False
    ),
    "fivetran": MCPServerConfig(
        server_id="fivetran",
        display_name="Fivetran",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8041",
        auth_type="bearer",
        api_key_env="FIVETRAN_API_KEY",
        description="Data integration - connectors, syncs",
        enabled=False
    ),

    # -------------------------------------------------------------------------
    # Monitoring (Additional)
    # -------------------------------------------------------------------------
    "new-relic": MCPServerConfig(
        server_id="new-relic",
        display_name="New Relic",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8042",
        auth_type="bearer",
        api_key_env="NEW_RELIC_API_KEY",
        description="Application performance monitoring",
        enabled=False
    ),
    "splunk": MCPServerConfig(
        server_id="splunk",
        display_name="Splunk",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8043",
        auth_type="bearer",
        api_key_env="SPLUNK_TOKEN",
        description="Log management and SIEM",
        enabled=False
    ),
}

# Sentry moved to Tier 1 - has direct HTTP endpoint
# Added to TIER1_SERVERS above

# =============================================================================
# LOCAL SERVERS (In-cluster containers)
# =============================================================================
# These run as containers in the Kubernetes cluster
MCP_EXCEL_URL = os.getenv("MCP_EXCEL_URL", "http://mcp-excel:8000")
MCP_DASHBOARD_URL = os.getenv("MCP_DASHBOARD_URL", "http://mcp-dashboard:8000")
MCP_GITHUB_JACINTALAMA_URL = os.getenv("MCP_GITHUB_JACINTALAMA_URL", "http://mcp-github-jacintalama:8000")
MCP_NOTION_URL = os.getenv("MCP_NOTION_URL", "http://mcp-notion:8000")
MCP_N8N_URL = os.getenv("MCP_N8N_URL", "http://mcp-n8n:8000")
MCP_SCHEDULER_URL = os.getenv("MCP_SCHEDULER_URL", "http://mcp-scheduler:8000")
MCP_GDRIVE_URL = os.getenv("MCP_GDRIVE_URL", "http://mcp-gdrive:8000")
MCP_GMAIL_URL = os.getenv("MCP_GMAIL_URL", "http://mcp-gmail:8000")
MCP_MEETING_KB_URL = os.getenv("MCP_MEETING_KB_URL", "http://meeting-kb:8200")
MCP_CALENDAR_URL = os.getenv("MCP_CALENDAR_URL", "http://mcp-calendar:8000")
MCP_WEB_SEARCH_URL = os.getenv("MCP_WEB_SEARCH_URL", "http://mcp-web-search:8000")

LOCAL_SERVERS: Dict[str, MCPServerConfig] = {
    "google-drive": MCPServerConfig(
        server_id="google-drive",
        access_class=AccessClass.PUBLIC,
        display_name="Google Drive",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_GDRIVE_URL,
        auth_type="none",
        api_key_env=None,
        description="Browse, search, and read files from your Google Drive (4 tools)",
        enabled=True,
    ),
    "gmail": MCPServerConfig(
        server_id="gmail",
        display_name="Gmail",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_GMAIL_URL,
        auth_type="none",
        api_key_env=None,
        description="Search, read, and send emails from your Gmail (5 tools)",
        # Gmail is served to Open WebUI via the native OWUI tool (draft/connect),
        # not the meta-tools. Disabled here so the model cannot call the raw
        # gmail_send_email through call_tool (which sent + rendered as a popup).
        # The native tool talks to mcp-gmail directly, so it is unaffected.
        enabled=False,
    ),
    "calendar": MCPServerConfig(
        server_id="calendar",
        access_class=AccessClass.PUBLIC,
        display_name="Google Calendar",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_CALENDAR_URL,
        auth_type="none",
        api_key_env=None,
        description="Create events, send invites, manage Google Calendar (5 tools)",
        enabled=True,
    ),
    "web-search": MCPServerConfig(
        server_id="web-search",
        access_class=AccessClass.PUBLIC,
        display_name="Web Search",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_WEB_SEARCH_URL,
        auth_type="none",
        api_key_env=None,
        description="Search the web, scrape pages, save to Knowledge Base (3 tools)",
        enabled=True,
    ),
    "github": MCPServerConfig(
        server_id="github",
        access_class=AccessClass.SHARED,
        display_name="GitHub",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_GITHUB_URL,
        auth_type="bearer",
        api_key_env="MCP_API_KEY",  # mcp-github uses MCP_API_KEY for internal auth
        description="GitHub repositories, issues, PRs (26 tools)",
        enabled=bool(os.getenv("GITHUB_TOKEN"))  # Requires valid PAT to function
    ),
    "filesystem": MCPServerConfig(
        server_id="filesystem",
        access_class=AccessClass.PUBLIC,
        display_name="Filesystem",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_FILESYSTEM_URL,
        auth_type="api_key",
        api_key_env="MCP_API_KEY",
        description="File and directory access (14 tools)"
    ),
    "excel": MCPServerConfig(
        server_id="excel",
        access_class=AccessClass.PUBLIC,
        display_name="Excel Creator",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_EXCEL_URL,
        auth_type="none",
        api_key_env=None,
        description="Create Excel spreadsheets with data, formulas, and charts (2 tools)"
    ),
    "dashboard": MCPServerConfig(
        server_id="dashboard",
        access_class=AccessClass.PUBLIC,
        display_name="Executive Dashboard",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_DASHBOARD_URL,
        auth_type="none",
        api_key_env=None,
        description="Create executive dashboards with KPI cards and interactive charts (2 tools)"
    ),
    "notion": MCPServerConfig(
        server_id="notion",
        display_name="Notion",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_NOTION_URL,
        auth_type="bearer",
        api_key_env="MCP_API_KEY",
        description="Workspace and documentation",
        enabled=bool(os.getenv("NOTION_API_KEY"))
    ),
    "n8n": MCPServerConfig(
        server_id="n8n",
        access_class=AccessClass.SHARED,
        display_name="n8n Workflows",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_N8N_URL,
        auth_type="bearer",
        api_key_env="MCP_API_KEY",
        description="AI-driven n8n workflow creation, management, and execution (20 tools)",
        enabled=bool(os.getenv("N8N_API_KEY"))
    ),
    "scheduler": MCPServerConfig(
        server_id="scheduler",
        access_class=AccessClass.RESTRICTED,
        display_name="Scheduler",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_SCHEDULER_URL,
        auth_type="bearer",
        api_key_env="MCP_API_KEY",
        description="Create and manage cron jobs that trigger n8n workflows on a schedule (4 tools)",
        enabled=True,
    ),
    "my-clickup": MCPServerConfig(
        server_id="my-clickup",
        access_class=AccessClass.PUBLIC,
        display_name="ClickUp (your account)",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MYTOOLS_URL + "/clickup",
        auth_type="none",
        api_key_env=None,
        description="ClickUp acting as the signed-in user's own account. Requires "
                    "them to have connected ClickUp under Connections.",
        enabled=True,
    ),
    "my-github": MCPServerConfig(
        server_id="my-github",
        access_class=AccessClass.PUBLIC,
        display_name="GitHub (your account)",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MYTOOLS_URL + "/github",
        auth_type="none",
        api_key_env=None,
        description="GitHub acting as the signed-in user's own account. Requires "
                    "them to have connected GitHub under Connections.",
        enabled=True,
    ),
    "my-trello": MCPServerConfig(
        server_id="my-trello",
        access_class=AccessClass.PUBLIC,
        display_name="Trello (your account)",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MYTOOLS_URL + "/trello",
        auth_type="none",
        api_key_env=None,
        description="Trello acting as the signed-in user's own account. Requires "
                    "them to have connected Trello under Connections.",
        enabled=True,
    ),
    "my-notion": MCPServerConfig(
        server_id="my-notion",
        access_class=AccessClass.PUBLIC,
        display_name="Notion (your account)",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MYTOOLS_URL + "/notion",
        auth_type="none",
        api_key_env=None,
        description="Notion acting as the signed-in user's own account. Requires "
                    "them to have connected Notion under Connections.",
        enabled=True,
    ),
    "my-n8n": MCPServerConfig(
        server_id="my-n8n",
        access_class=AccessClass.PUBLIC,
        display_name="n8n (your account)",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MYTOOLS_URL + "/n8n",
        auth_type="none",
        api_key_env=None,
        description="n8n acting as the signed-in user's own account. Requires "
                    "them to have connected n8n under Connections.",
        enabled=True,
    ),
    "my-airtable": MCPServerConfig(
        server_id="my-airtable",
        access_class=AccessClass.PUBLIC,
        display_name="Airtable (your account)",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MYTOOLS_URL + "/airtable",
        auth_type="none",
        api_key_env=None,
        description="Airtable acting as the signed-in user's own account. Requires "
                    "them to have connected Airtable under Connections.",
        enabled=True,
    ),
    "my-hubspot": MCPServerConfig(
        server_id="my-hubspot",
        access_class=AccessClass.PUBLIC,
        display_name="HubSpot (your account)",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MYTOOLS_URL + "/hubspot",
        auth_type="none",
        api_key_env=None,
        description="HubSpot acting as the signed-in user's own account. Requires "
                    "them to have connected HubSpot under Connections.",
        enabled=True,
    ),
    "my-zapier": MCPServerConfig(
        server_id="my-zapier",
        access_class=AccessClass.PUBLIC,
        display_name="Zapier (your account)",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MYTOOLS_URL + "/zapier",
        auth_type="none",
        api_key_env=None,
        description="Zapier acting as the signed-in user's own account. Requires "
                    "them to have connected Zapier under Connections.",
        enabled=True,
    ),
    "meeting-kb": MCPServerConfig(
        server_id="meeting-kb",
        access_class=AccessClass.PUBLIC,
        display_name="Meeting Knowledge Base",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MEETING_KB_URL,
        auth_type="none",
        api_key_env=None,
        description="Search and browse meeting summaries (3 tools)",
        enabled=True,
    ),
}

# =============================================================================
# COMBINED SERVER REGISTRY
# =============================================================================
ALL_SERVERS: Dict[str, MCPServerConfig] = {
    **TIER1_SERVERS,
    **TIER2_SERVERS,
    **TIER3_SERVERS,
    **LOCAL_SERVERS,
}


def resolve_user_servers(granted, is_admin: bool, servers=None) -> set:
    """The servers a caller may use. One expression, applied on every path.

        admin:     enabled n everything
        non-admin: enabled n (PUBLIC u granted)

    The `enabled` intersection is taken here, on the way out, rather than at
    each grant source. That is the whole fix for the admin path, which returned
    `list(ALL_SERVERS.keys())` and so handed out 37 servers that have no
    container. `enabled` was honoured in six other places and missed in that
    one, which is the same shape as the auth hole before it: one rule written
    several times, wrong in some of them.

    A grant naming a server that is not registered is dropped rather than
    trusted. group_tenant_mapping still names linear, atlassian, slack, gitlab
    and hubspot, none of which were ever deployed.
    """
    servers = ALL_SERVERS if servers is None else servers
    enabled = {sid for sid, cfg in servers.items() if cfg.enabled}
    if is_admin:
        return enabled

    public = {sid for sid in enabled
              if servers[sid].access_class is AccessClass.PUBLIC}
    # The wall. A SHARED server spends one vendor credential that belongs to
    # the platform, so a grant must not be a way onto it: group membership is
    # not a decision anyone made about spending somebody else's account.
    # kimcalicoy24 held exactly such a grant through MCP-GitHub and had been
    # making GitHub calls as the platform, invisibly.
    #
    # RESTRICTED is deliberately still grantable. That class is about reach
    # into other users' data, not about whose credential pays, and handing it
    # to someone is a real decision an admin can make.
    grantable = {sid for sid in set(granted or ())
                 if sid in enabled
                 and servers[sid].access_class is not AccessClass.SHARED}
    return public | grantable


def get_server(server_id: str) -> Optional[MCPServerConfig]:
    """Get server configuration by ID."""
    return ALL_SERVERS.get(server_id)


def get_all_servers() -> Dict[str, MCPServerConfig]:
    """Get all configured servers."""
    return ALL_SERVERS


def get_servers_by_tier(tier: ServerTier) -> Dict[str, MCPServerConfig]:
    """Get all servers of a specific tier."""
    return {k: v for k, v in ALL_SERVERS.items() if v.tier == tier}


async def user_has_server_access_async(user_email: str, server_id: str,
                                        entra_groups: Optional[List[str]] = None) -> bool:
    """
    Check if user has access to a specific server (ASYNC - uses database).
    Maps server_id to tenant_id for backward compatibility.
    """
    # Map server to tenant (for now, server_id == tenant_id)
    return await user_has_tenant_access_async(user_email, server_id, entra_groups)

# =============================================================================
# GROUP TO TENANT MAPPING - NOW IN DATABASE
# =============================================================================
# Group-tenant mappings are stored in the `group_tenant_mapping` table.
# Use db.get_tenants_from_groups() for lookups.
#
# To manage mappings:
#   INSERT INTO group_tenant_mapping (group_name, tenant_id) VALUES ('Tenant-NewClient', 'github');
#   DELETE FROM group_tenant_mapping WHERE group_name = 'Tenant-OldClient';
#
# See db.py for helper functions:
#   - db.get_tenants_from_groups(groups) -> list of tenant IDs
#   - db.group_has_tenant_access(groups, tenant_id) -> bool
#   - db.add_group_tenant_mapping(group_name, tenant_id) -> bool
#   - db.remove_group_tenant_mapping(group_name, tenant_id) -> bool
#   - db.get_all_group_mappings() -> dict of all mappings
# =============================================================================

TENANTS: Dict[str, TenantConfig] = {
    "google": TenantConfig(
        tenant_id="google",
        display_name="Google",
        mcp_endpoint=MCP_FILESYSTEM_URL,
        mcp_api_key="test-key",
        credentials={"jira_url": "https://google.atlassian.net"}
    ),
    "microsoft": TenantConfig(
        tenant_id="microsoft",
        display_name="Microsoft",
        mcp_endpoint=MCP_FILESYSTEM_URL,
        mcp_api_key="test-key",
        credentials={"jira_url": "https://microsoft.atlassian.net"}
    ),
    "github": TenantConfig(
        tenant_id="github",
        display_name="GitHub",
        mcp_endpoint=MCP_GITHUB_URL,
        mcp_api_key="test-key",
        credentials={}
    )
}

# =============================================================================
# USER-TENANT ACCESS - NOW IN DATABASE
# =============================================================================
# User-tenant mappings are stored in the `user_tenant_access` table.
# Use db.get_user_tenants() for lookups.
#
# To manage access:
#   INSERT INTO user_tenant_access (user_email, tenant_id, access_level)
#   VALUES ('newuser@company.com', 'github', 'read');
#
# See db.py for helper functions:
#   - db.get_user_tenants(email) -> list of tenant IDs
#   - db.user_has_tenant_access(email, tenant_id) -> bool
#   - db.add_user_tenant_access(email, tenant_id, access_level) -> bool
# =============================================================================

async def get_tenants_from_entra_groups_async(groups: List[str]) -> List[str]:
    """
    Get tenant IDs from Entra ID/Open WebUI groups (ASYNC - uses database).

    Args:
        groups: List of Entra ID/Open WebUI group names (e.g., ["MCP-Google", "MCP-GitHub"])

    Returns:
        List of unique tenant IDs the user has access to
    """
    import db
    if not groups:
        return []
    return await db.get_tenants_from_groups(groups)


async def get_user_tenants_configs_async(user_email: str, entra_groups: Optional[List[str]] = None) -> List[TenantConfig]:
    """
    Get all tenants a user has access to as TenantConfig objects (ASYNC - uses database).

    Args:
        user_email: User's email address
        entra_groups: Optional list of Entra ID groups

    Returns:
        List of TenantConfig objects the user has access to
    """
    tenant_ids = await get_user_tenants_async(user_email, entra_groups)
    return [TENANTS[tid] for tid in tenant_ids if tid in TENANTS]


def get_tenant(tenant_id: str) -> Optional[TenantConfig]:
    """Get tenant config by ID."""
    return TENANTS.get(tenant_id)


def user_has_tenant_access(user_email: str, tenant_id: str,
                           entra_groups: Optional[List[str]] = None) -> bool:
    """
    DEPRECATED: Use user_has_tenant_access_async() instead.

    This sync version cannot use database lookups. Returns False by default.
    Only use this if you absolutely cannot use async code.
    """
    print(f"  [DEPRECATED] user_has_tenant_access() called - use async version")
    print(f"  [DEPRECATED] {user_email} -> {tenant_id}: returning False (use async)")
    return False


async def user_has_tenant_access_async(user_email: str, tenant_id: str,
                                        entra_groups: Optional[List[str]] = None) -> bool:
    """May this user use this server?

    Deliberately a membership test against get_user_tenants_async rather than
    its own walk of the grant sources. It used to be its own copy, and that is
    how a per-user server ended up searchable and then refused on execution:
    search asked one function, /meta/call_tool asked the other, and only the
    first had been taught about access classes.

    The same shape produced the two bugs before it. The anonymous-caller hole
    was one condition written three times and wrong in two, and the missing
    `enabled` filter was one rule honoured in six places and skipped in the
    seventh. There is now one place that decides, and this asks it.
    """
    allowed = await get_user_tenants_async(user_email, entra_groups)
    result = tenant_id in set(allowed)
    print(f"  [ACCESS] {user_email} -> {tenant_id}: {result}")
    return result


async def get_user_tenants_async(user_email: str, entra_groups: Optional[List[str]] = None) -> List[str]:
    """
    Get all tenant IDs a user has access to (ASYNC version with database).

    Args:
        user_email: User's email address
        entra_groups: Optional list of Entra ID/Open WebUI groups

    Returns:
        List of tenant IDs the user has access to

    Admins (MCP-Admin group, or Open WebUI role=admin) get every ENABLED
    server. Everyone else gets the enabled PUBLIC servers plus whatever
    group_tenant_mapping and user_tenant_access grant them. See
    resolve_user_servers for the single expression that decides.
    """
    import db

    tenant_ids = set()

    # If groups not provided via headers, look them up from database
    if not entra_groups or len(entra_groups) == 0:
        try:
            entra_groups = await db.get_user_groups(user_email)
            print(f"  [DB-GROUPS] Looked up groups for {user_email}: {entra_groups}")
        except Exception as e:
            print(f"  [DB-GROUPS] Error looking up groups: {e}")
            entra_groups = []

    # An admin of the platform is an admin of its tools. Only the MCP-Admin
    # *group* was ever consulted here, so two platform admins resolved to 4
    # servers and 0 servers respectively while other accounts saw everything.
    is_admin = bool(entra_groups and "MCP-Admin" in entra_groups)
    if not is_admin:
        try:
            is_admin = await db.is_openwebui_admin(user_email)
        except Exception as e:
            print(f"  [ADMIN-CHECK] Error: {e}")

    # Source 1: Group-based access (from group_tenant_mapping table)
    if entra_groups and len(entra_groups) > 0:
        try:
            group_tenants = await db.get_tenants_from_groups(entra_groups)
            tenant_ids.update(group_tenants)
            print(f"  [GROUP-BASED-DB] {user_email} -> {len(group_tenants)} tenants from groups")
        except Exception as e:
            print(f"  [GROUP-BASED-DB] Error: {e}")

    # Source 2: Database lookup by email (from user_tenant_access table)
    try:
        db_tenants = await db.get_user_tenants(user_email)
        tenant_ids.update(db_tenants)
        print(f"  [DATABASE] {user_email} -> {len(db_tenants)} tenants from database")
    except Exception as e:
        print(f"  [DATABASE] Error: {e}")

    # The grants above are raw and may name servers that are disabled or were
    # never deployed. resolve_user_servers is the only thing that decides.
    resolved = resolve_user_servers(tenant_ids, is_admin=is_admin)
    print(f"  [RESOLVED] {user_email} admin={is_admin} "
          f"granted={len(tenant_ids)} -> {len(resolved)} usable servers")
    return list(resolved)


# =============================================================================
# SYNCHRONOUS WRAPPER FUNCTIONS
# =============================================================================
# These are sync wrappers for use in non-async contexts (like mcp_server.py)
# They use asyncio.run() to execute the async database functions.
# =============================================================================

def _get_or_create_event_loop():
    """Get the current event loop or create a new one."""
    try:
        loop = asyncio.get_running_loop()
        return loop, False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop, True


def user_has_server_access(user_email: str, server_id: str,
                           entra_groups: Optional[List[str]] = None) -> bool:
    """
    Check if user has access to a specific server (SYNC wrapper).

    This is a synchronous wrapper around user_has_server_access_async().
    Use this in non-async contexts like FastMCP sync handlers.

    Args:
        user_email: User's email address
        server_id: Server ID to check access for
        entra_groups: Optional list of Entra ID/Open WebUI groups

    Returns:
        True if user has access, False otherwise
    """
    try:
        loop, created = _get_or_create_event_loop()
        if created:
            result = loop.run_until_complete(
                user_has_server_access_async(user_email, server_id, entra_groups)
            )
            loop.close()
            return result
        else:
            # Already in async context, need to use asyncio.run_coroutine_threadsafe
            # or just return the async call result
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    user_has_server_access_async(user_email, server_id, entra_groups)
                )
                return future.result(timeout=10)
    except Exception as e:
        print(f"  [SYNC-WRAPPER] user_has_server_access error: {e}")
        return False


def get_tenants_from_entra_groups(groups: List[str]) -> List[str]:
    """
    Get tenant IDs from Entra ID/Open WebUI groups (SYNC wrapper).

    This is a synchronous wrapper around get_tenants_from_entra_groups_async().
    Use this in non-async contexts.

    Args:
        groups: List of Entra ID/Open WebUI group names

    Returns:
        List of tenant IDs the groups grant access to
    """
    try:
        loop, created = _get_or_create_event_loop()
        if created:
            result = loop.run_until_complete(
                get_tenants_from_entra_groups_async(groups)
            )
            loop.close()
            return result
        else:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    get_tenants_from_entra_groups_async(groups)
                )
                return future.result(timeout=10)
    except Exception as e:
        print(f"  [SYNC-WRAPPER] get_tenants_from_entra_groups error: {e}")
        return []
