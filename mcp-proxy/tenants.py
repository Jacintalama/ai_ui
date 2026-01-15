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


# =============================================================================
# SERVER TIER DEFINITIONS
# =============================================================================
class ServerTier(Enum):
    """MCP Server protocol tiers."""
    HTTP = "http"      # Tier 1: Direct HTTP connection (Linear, Notion, etc.)
    SSE = "sse"        # Tier 2: Server-Sent Events via mcpo proxy (Atlassian, Asana)
    STDIO = "stdio"    # Tier 3: stdio via mcpo proxy (SonarQube, Sentry)
    LOCAL = "local"    # Local container in Kubernetes cluster


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
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.linear.app/mcp",
        auth_type="oauth",
        api_key_env="LINEAR_API_KEY",
        description="Issue tracking and project management"
    ),

    # -------------------------------------------------------------------------
    # Knowledge & Documentation
    # -------------------------------------------------------------------------
    "notion": MCPServerConfig(
        server_id="notion",
        display_name="Notion",
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.notion.com/mcp",
        auth_type="bearer",
        api_key_env="NOTION_API_KEY",
        description="Workspace and documentation"
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
        description="CRM and marketing automation"
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
        description="Infrastructure as Code"
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
        description="Git repository and CI/CD (requires GitLab 18.6+)"
    ),
    "github-remote": MCPServerConfig(
        server_id="github-remote",
        display_name="GitHub (Official Remote)",
        tier=ServerTier.HTTP,
        endpoint_url="https://api.githubcopilot.com/mcp/",
        auth_type="oauth",
        api_key_env="GITHUB_TOKEN",
        description="GitHub official remote MCP (51 tools) - repos, PRs, issues, code search"
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
        description="Error tracking and monitoring (16 tools)"
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
# TIER 2: SSE SERVERS (via mcpo-sse proxy)
# =============================================================================
# These servers use Server-Sent Events, need mcpo to convert to HTTP
TIER2_SERVERS: Dict[str, MCPServerConfig] = {
    "atlassian": MCPServerConfig(
        server_id="atlassian",
        display_name="Atlassian (Jira/Confluence)",
        tier=ServerTier.SSE,
        endpoint_url=f"{MCPO_SSE_URL}:8010",
        auth_type="bearer",
        api_key_env="ATLASSIAN_TOKEN",
        description="Jira issues and Confluence pages"
    ),
    "asana": MCPServerConfig(
        server_id="asana",
        display_name="Asana",
        tier=ServerTier.SSE,
        endpoint_url=f"{MCPO_SSE_URL}:8011",
        auth_type="bearer",
        api_key_env="ASANA_TOKEN",
        description="Task and project management"
    ),
}

# =============================================================================
# TIER 3: STDIO SERVERS (via mcpo-stdio proxy)
# =============================================================================
# These servers use stdio protocol, need mcpo to convert to HTTP
# NOTE: SonarQube requires valid credentials (SONARQUBE_TOKEN + URL/ORG)
#       Sentry has been moved to TIER1_SERVERS using HTTP endpoint
TIER3_SERVERS: Dict[str, MCPServerConfig] = {
    "sonarqube": MCPServerConfig(
        server_id="sonarqube",
        display_name="SonarQube",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8020",
        auth_type="bearer",
        api_key_env="SONARQUBE_TOKEN",
        description="Code quality and security analysis (requires credentials)",
        enabled=False  # Disabled until SONARQUBE_TOKEN is configured
    ),
}

# Sentry moved to Tier 1 - has direct HTTP endpoint
# Added to TIER1_SERVERS below

# =============================================================================
# LOCAL SERVERS (In-cluster containers)
# =============================================================================
# These run as containers in the Kubernetes cluster
LOCAL_SERVERS: Dict[str, MCPServerConfig] = {
    "github": MCPServerConfig(
        server_id="github",
        display_name="GitHub",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_GITHUB_URL,
        auth_type="bearer",
        api_key_env="MCP_API_KEY",  # mcp-github uses MCP_API_KEY for internal auth
        description="GitHub repositories, issues, PRs (26 tools)"
    ),
    "filesystem": MCPServerConfig(
        server_id="filesystem",
        display_name="Filesystem",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_FILESYSTEM_URL,
        auth_type="api_key",
        api_key_env="MCP_API_KEY",
        description="File and directory access (14 tools)"
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
    """
    Check if user has access to a specific tenant (ASYNC version with database).

    Args:
        user_email: User's email address
        tenant_id: Tenant ID to check access for
        entra_groups: Optional list of Entra ID/Open WebUI groups

    Returns:
        True if user has access, False otherwise

    Priority:
        1. MCP-Admin group (grants access to ALL servers)
        2. Entra ID/Open WebUI groups (if provided and non-empty) - via database lookup
        3. User email lookup in database
    """
    import db  # Import here to avoid circular imports

    # Priority 0: MCP-Admin group grants access to ALL servers (Lukas's requirement)
    if entra_groups and "MCP-Admin" in entra_groups:
        print(f"  [MCP-ADMIN] {user_email} has MCP-Admin -> {tenant_id}: True (ALL ACCESS)")
        return True

    # Priority 1: Group-based access (from Open WebUI groups synced from Entra ID)
    if entra_groups and len(entra_groups) > 0:
        try:
            has_access = await db.group_has_tenant_access(entra_groups, tenant_id)
            print(f"  [GROUP-BASED-DB] {user_email} groups={entra_groups} -> {tenant_id}: {has_access}")
            if has_access:
                return True  # Found access via group, return immediately
            # If no group access, fall through to check email-based access
        except Exception as e:
            print(f"  [GROUP-BASED-DB] Error: {e}")

    # Priority 2: Database lookup by email
    try:
        db_access = await db.user_has_tenant_access(user_email, tenant_id)
        print(f"  [DATABASE] {user_email} -> {tenant_id}: {db_access}")
        return db_access
    except Exception as e:
        print(f"  [DATABASE] Error checking access: {e}")
        return False


async def get_user_tenants_async(user_email: str, entra_groups: Optional[List[str]] = None) -> List[str]:
    """
    Get all tenant IDs a user has access to (ASYNC version with database).

    Args:
        user_email: User's email address
        entra_groups: Optional list of Entra ID/Open WebUI groups

    Returns:
        List of tenant IDs the user has access to

    Sources:
        1. MCP-Admin group (grants ALL servers)
        2. Entra ID/Open WebUI groups (if provided) - via group_tenant_mapping table
        3. User email - via user_tenant_access table
    """
    import db

    tenant_ids = set()

    # Source 0: MCP-Admin grants access to ALL servers (Lukas's requirement)
    if entra_groups and "MCP-Admin" in entra_groups:
        all_server_ids = list(ALL_SERVERS.keys())
        print(f"  [MCP-ADMIN] {user_email} has MCP-Admin -> ALL {len(all_server_ids)} servers")
        return all_server_ids

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

    return list(tenant_ids)
