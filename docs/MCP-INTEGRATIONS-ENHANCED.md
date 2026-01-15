# MCP Integration Research - Enhanced URLs

**Updated:** January 14, 2026
**Based on:** Lukas's MCP-INTEGRATIONS.md + Latest Research

---

## Quick Reference: Best URLs by Service

| Service | Best URL | Protocol | Auth | Status |
|---------|----------|----------|------|--------|
| **GitHub** | `https://api.githubcopilot.com/mcp/` | HTTP | OAuth 2.0 | Official Remote |
| **Linear** | `https://mcp.linear.app/mcp` | HTTP | OAuth 2.1 | Official |
| **GitLab** | `https://gitlab.com/api/v4/mcp` | HTTP | OAuth 2.0 | Official (18.6+) |
| **Notion** | `https://mcp.notion.com/mcp` | HTTP | OAuth 2.1 | Official |
| **Pulumi** | `https://mcp.ai.pulumi.com/mcp` | HTTP | OAuth | Official |
| **HubSpot** | `https://mcp.hubspot.com/anthropic` | HTTP | OAuth | Official |
| **Sentry** | `https://mcp.sentry.dev/mcp` | HTTP | OAuth | Official (NEW!) |
| **Atlassian** | `https://mcp.atlassian.com/v1/sse` | SSE | OAuth 2.1 | Official |
| **Asana** | `https://mcp.asana.com/sse` | SSE | OAuth | Official |
| **Datadog** | Managed (Request Access) | HTTP | API Key | Official Preview |
| **OneDrive/SharePoint** | Microsoft Agent 365 | HTTP | OAuth | Official |

---

## Tier 1: Streamable HTTP - Quick Wins

### 1. GitHub (Official Remote)
```
URL: https://api.githubcopilot.com/mcp/
Protocol: Streamable HTTP
Auth: OAuth 2.0
Tools: 51 tools - repos, PRs, issues, code search, workflows
```

**For GitHub Enterprise Cloud:**
```
URL: https://copilot-api.{your-domain}.ghe.com/mcp
```

**Sources:**
- [GitHub MCP Server](https://github.com/github/github-mcp-server)
- [GitHub Changelog](https://github.blog/changelog/2025-04-04-github-mcp-server-public-preview/)

---

### 2. Linear (Issue Tracking)
```
URL: https://mcp.linear.app/mcp
Protocol: Streamable HTTP
Auth: OAuth 2.1 + Dynamic Client Registration
Features: Issues, projects, comments, teams
```

**Sources:**
- [Linear MCP Docs](https://linear.app/docs/mcp)

---

### 3. GitLab (DevOps Platform)
```
URL: https://gitlab.com/api/v4/mcp
Protocol: HTTP (direct, no dependencies)
Auth: OAuth 2.0
Features: Repositories, issues, MRs, CI/CD, pipelines
Requirement: GitLab 18.6+ (supports MCP 2025-03-26 spec)
```

**Sources:**
- [GitLab MCP Docs](https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/)

---

### 4. Notion (Knowledge Management)
```
URL: https://mcp.notion.com/mcp
Protocol: Streamable HTTP
Auth: OAuth + Bearer Token
Features: Pages, databases, blocks, search
```

**Sources:**
- [Notion MCP Server](https://github.com/makenotion/notion-mcp-server)

---

### 5. Pulumi (Infrastructure as Code)
```
URL: https://mcp.ai.pulumi.com/mcp
Protocol: Streamable HTTP
Auth: OAuth
Features: Registry queries, CLI commands, resource management
```

**Sources:**
- [Pulumi Remote MCP Server](https://www.pulumi.com/blog/remote-mcp-server/)

---

### 6. HubSpot (CRM)
```
URL: https://mcp.hubspot.com/anthropic
Protocol: HTTP
Auth: OAuth
Features: Contacts, deals, companies, analytics
Note: First major CRM with production MCP (June 2025)
```

**Sources:**
- [Salesforce Ben](https://www.salesforceben.com/salesforce-model-context-protocol-explained-how-mcp-bridges-ai-and-your-crm/)

---

### 7. Sentry (Error Tracking) - UPDATED!
```
URL: https://mcp.sentry.dev/mcp  (NOT /sse!)
Protocol: Streamable HTTP with SSE fallback
Auth: OAuth
Features: 16 tools - errors, issues, performance
```

**Previous URL (deprecated):** `https://mcp.sentry.dev/sse`
**New URL (better):** `https://mcp.sentry.dev/mcp`

**CLI Setup:**
```bash
claude mcp add --transport http sentry https://mcp.sentry.dev/mcp
```

**Sources:**
- [Sentry MCP Docs](https://docs.sentry.io/product/sentry-mcp/)
- [Sentry Blog](https://blog.sentry.io/yes-sentry-has-an-mcp-server-and-its-pretty-good/)

---

### 8. Snowflake (Data Warehouse)
```
URL: Snowflake-managed endpoint (tenant-specific)
Protocol: Streamable HTTP
Auth: Programmatic Access Token (PAT)
Features: Cortex AI, SQL, object management, semantic views
Status: GA November 4, 2025
```

**Sources:**
- [Snowflake MCP Docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)

---

### 9. dbt (Data Transformation)
```
URL: Remote MCP Service (GA)
Protocol: Streamable HTTP
Auth: OAuth
Features: Models, lineage, metrics, dbt commands
Note: Merged with Fivetran (Oct 2025)
```

**Sources:**
- [dbt Coalesce 2025](https://www.selectstar.com/resources/dbt-coalesce-2025)

---

## Tier 2: SSE Protocol (Requires mcpo Proxy)

### 10. Atlassian (Jira/Confluence)

**Option A: Official SSE (requires mcpo)**
```
URL: https://mcp.atlassian.com/v1/sse
Protocol: SSE
Auth: OAuth 2.1
```

**Option B: sooperset/mcp-atlassian (Recommended - supports HTTP!)**
```bash
docker run -d --name mcp-atlassian -p 9000:9000 \
  -e ATLASSIAN_OAUTH_ENABLE=true \
  ghcr.io/sooperset/mcp-atlassian:latest \
  --transport streamable-http --port 9000 -vv
```
**Endpoint:** `http://localhost:9000/mcp`

**Sources:**
- [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian)
- [Atlassian Remote MCP](https://www.atlassian.com/blog/announcements/remote-mcp-server)

---

### 11. Asana (Task Management)
```
URL: https://mcp.asana.com/sse
Protocol: SSE
Auth: OAuth
Features: Tasks, projects, goals
```

**Sources:**
- [Claude Connectors](https://claude.com/connectors)

---

### 12. Slack (Communication)

**Official (Beta - Request Access):**
```
URL: Coming Q1 2026
Protocol: SSE
Auth: OAuth
```

**Community Option (korotovsky/slack-mcp-server):**
```bash
# Supports stdio, SSE, and HTTP transports
npm install -g @modelcontextprotocol/server-slack
```

**Sources:**
- [Slack MCP Docs](https://docs.slack.dev/ai/mcp-server/)
- [korotovsky/slack-mcp-server](https://github.com/korotovsky/slack-mcp-server)

---

## Tier 3: Monitoring & Observability

### 13. Datadog (Monitoring)

**Official Remote MCP (Preview - Request Access):**
```
URL: Managed by Datadog (request access via docs)
Protocol: Streamable HTTP
Auth: API Key + App Key
```

**Community (shelfio/datadog-mcp):**
```bash
npx @shelfio/datadog-mcp \
  --apiKey=your_api_key \
  --appKey=your_app_key \
  --site=datadoghq.com
```

**Datadog Sites:**
- `datadoghq.com` (US)
- `datadoghq.eu` (EU)
- `us3.datadoghq.com`
- `us5.datadoghq.com`

**Sources:**
- [Datadog MCP Docs](https://docs.datadoghq.com/bits_ai/mcp_server/)
- [shelfio/datadog-mcp](https://github.com/shelfio/datadog-mcp)

---

### 14. Grafana (Visualization)
```
URL: Grafana Cloud MCP (managed)
Protocol: HTTP
Auth: API Key
Features: Dashboards, alerts, queries
```

---

### 15. SonarQube (Code Quality)
```
Package: @sonarsource/sonarqube-mcp-server
Protocol: stdio (needs mcpo)
Auth: API Key + URL + Org
```

**Sources:**
- [SonarQube MCP](https://www.sonarsource.com/products/sonarqube/mcp-server/)

---

## Tier 4: Microsoft Ecosystem

### 16. OneDrive & SharePoint (Official)

**Microsoft Agent 365 (Enterprise):**
```
URL: Tenant-specific via Microsoft Agent 365
Protocol: HTTP
Auth: OAuth (Entra ID)
Features: Upload, search, metadata, lists
```

**Community (ftaricano/mcp-onedrive-sharepoint):**
```bash
# Uses Microsoft Graph API
# Device code flow authentication
```

**Sources:**
- [Microsoft MCP Reference](https://learn.microsoft.com/en-us/microsoft-agent-365/mcp-server-reference/odspremoteserver)
- [GitHub - mcp-onedrive-sharepoint](https://github.com/ftaricano/mcp-onedrive-sharepoint)

---

### 17. Microsoft Teams (Preview)
```
URL: Teams AI Library (preview)
Protocol: HTTP
Auth: OAuth (Entra ID)
Status: Preview - limited availability
```

**Sources:**
- [Microsoft Teams AI Library](https://techcommunity.microsoft.com/blog/microsoftteamsblog/what%E2%80%99s-new-in-microsoft-teams--may-2025---build-edition/4414706)

---

## Tier 5: File Storage

### 18. Google Drive
```
Package: @modelcontextprotocol/server-gdrive (stdio)
Protocol: stdio (needs mcpo)
Auth: OAuth
Features: List, read, search files, edit Sheets
```

**Community Options:**
- [isaacphi/mcp-gdrive](https://github.com/isaacphi/mcp-gdrive)
- [felores/gdrive-mcp-server](https://github.com/felores/gdrive-mcp-server)

---

## Changes from Current tenants.py

| Service | Current URL | Better URL | Change Required |
|---------|-------------|------------|-----------------|
| **Sentry** | `https://mcp.sentry.dev/sse` | `https://mcp.sentry.dev/mcp` | YES - Use /mcp |
| **GitHub** | Local container | `https://api.githubcopilot.com/mcp/` | Optional - Official remote available |
| **Atlassian** | mcpo-sse proxy | sooperset Docker with HTTP | Optional - Better option |

---

## Implementation Priority for Lukas

### Week 1: Quick Wins (HTTP - No Proxy)
1. Linear - `https://mcp.linear.app/mcp`
2. GitLab - `https://gitlab.com/api/v4/mcp`
3. Notion - `https://mcp.notion.com/mcp`
4. Pulumi - `https://mcp.ai.pulumi.com/mcp`
5. HubSpot - `https://mcp.hubspot.com/anthropic`
6. **Sentry** - Update to `https://mcp.sentry.dev/mcp`

### Week 2: With Proxy/Docker
7. Atlassian - sooperset Docker with streamable-http
8. Asana - mcpo proxy
9. Slack - Wait for GA or use community

### Week 3+: Cloud/Enterprise
10. Datadog - Request access to official remote
11. OneDrive/SharePoint - Microsoft Agent 365
12. Snowflake - Tenant-specific setup

---

## Sources

### Official Documentation
- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
- [GitHub MCP Server](https://github.com/github/github-mcp-server)
- [Sentry MCP Docs](https://docs.sentry.io/product/sentry-mcp/)
- [Datadog MCP Docs](https://docs.datadoghq.com/bits_ai/mcp_server/)
- [Microsoft MCP Reference](https://learn.microsoft.com/en-us/microsoft-agent-365/mcp-server-reference/odspremoteserver)

### Community Resources
- [Awesome MCP Servers](https://github.com/punkpeye/awesome-mcp-servers)
- [PulseMCP Directory](https://www.pulsemcp.com/servers)
- [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian)
