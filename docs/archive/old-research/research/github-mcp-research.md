# GitHub MCP Server Research

**Date:** 2026-01-07
**Purpose:** Research for multi-tenant Company GPT implementation (15,000 employees)

---

## Overview

The GitHub MCP Server is GitHub's official Model Context Protocol server that enables AI tools to interact with GitHub's platform through natural language.

## Repository Information

| Property | Value |
|----------|-------|
| **Repository URL** | https://github.com/github/github-mcp-server |
| **Docker Image** | `ghcr.io/github/github-mcp-server` |
| **Remote Server URL** | `https://api.githubcopilot.com/mcp/` |

## Protocol Type

**CRITICAL FINDING: The GitHub MCP server uses STDIO protocol (local) and Streamable HTTP (remote).**

| Deployment | Protocol |
|------------|----------|
| Local (Docker/Binary) | **stdio** |
| Remote (GitHub-hosted) | **HTTP** (Streamable HTTP) |

**This is NOT SSE** - unlike Atlassian MCP which uses SSE and doesn't work with Open WebUI, the GitHub MCP server uses stdio locally which is fully compatible with Open WebUI via mcpo proxy.

## Installation Methods

### Method 1: Docker (Recommended for Local)

```bash
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=<your-token> \
  ghcr.io/github/github-mcp-server
```

### Method 2: Remote Server (GitHub-Hosted)

Configure your MCP host to connect to:
```
https://api.githubcopilot.com/mcp/
```

### Method 3: Build from Source

The server is written in Go and can be built from source.

## Configuration Requirements

### Required Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GITHUB_PERSONAL_ACCESS_TOKEN` | Your GitHub PAT | **Yes** |

### Optional Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_HOST` | For GitHub Enterprise (use `https://` prefix) | github.com |
| `GITHUB_TOOLSETS` | Comma-separated toolsets to enable | Default toolsets |
| `GITHUB_TOOLS` | Specific individual tools to register | All in toolset |
| `GITHUB_READ_ONLY` | Set to `1` for read-only mode | `0` |
| `GITHUB_LOCKDOWN_MODE` | Restrict public repo content | `0` |
| `GITHUB_DYNAMIC_TOOLSETS` | Enable dynamic discovery (beta) | `0` |

### GitHub Personal Access Token Scopes

Required scopes depend on operations:
- `repo` - Full repository access
- `read:org` - Organization access
- `read:user` - User information
- `workflow` - GitHub Actions access

## Available Toolsets

### Default Toolsets (enabled without specification)
- `context` - Context information
- `repos` - Repository operations
- `issues` - Issue management
- `pull_requests` - PR operations
- `users` - User operations

### Full Toolset List

| Toolset | Description |
|---------|-------------|
| `actions` | GitHub Actions workflows |
| `code_security` | Code scanning alerts |
| `dependabot` | Dependabot alerts |
| `discussions` | GitHub Discussions |
| `gists` | Gist operations |
| `git` | Git operations (branches, commits, tags) |
| `issues` | Issue management |
| `labels` | Label management |
| `notifications` | Notification management |
| `orgs` | Organization operations |
| `projects` | GitHub Projects |
| `pull_requests` | Pull request operations |
| `repos` | Repository operations |
| `secret_protection` | Secret protection |
| `security_advisories` | Security advisories |
| `stargazers` | Star operations |
| `users` | User operations |

**Remote-only toolsets:**
- `copilot` - Copilot features
- `copilot_spaces` - Copilot Spaces
- `github_support_docs_search` - GitHub documentation search

Use `--toolsets all` to enable every available toolset.

## Available Tools (51 Total)

### Repository Management
- `create_repository`
- `fork_repository`

### Branch & File Operations
- `create_branch`
- `create_or_update_file`
- `delete_file`
- `push_files`

### Issue Management
- `create_issue`
- `get_issue`
- `update_issue`
- `list_issues`
- `add_issue_comment`
- `get_issue_comments`
- `search_issues`
- `assign_copilot_to_issue`

### Pull Request Operations
- `create_pull_request`
- `get_pull_request`
- `update_pull_request`
- `list_pull_requests`
- `merge_pull_request`
- `get_pull_request_status`
- `get_pull_request_diff`
- `get_pull_request_files`
- `get_pull_request_comments`
- `update_pull_request_branch`

### Code Review
- `create_pending_pull_request_review`
- `add_pull_request_review_comment_to_pending_review`
- `submit_pending_pull_request_review`
- `delete_pending_pull_request_review`
- `create_and_submit_pull_request_review`
- `get_pull_request_reviews`
- `request_copilot_review`

### Code & Security Scanning
- `list_code_scanning_alerts`
- `get_code_scanning_alert`
- `list_secret_scanning_alerts`
- `get_secret_scanning_alert`

### Search
- `search_code`
- `search_issues`
- `search_repositories`
- `search_users`

### Git References
- `get_commit`
- `list_commits`
- `get_tag`
- `list_tags`
- `list_branches`

### Notifications
- `list_notifications`
- `get_notification_details`
- `dismiss_notification`
- `manage_notification_subscription`
- `manage_repository_notification_subscription`
- `mark_all_notifications_read`

### User
- `get_me`

## Running with mcpo for Open WebUI Compatibility

### What is mcpo?

[mcpo](https://github.com/open-webui/mcpo) is Open WebUI's MCP-to-OpenAPI proxy server that converts stdio-based MCP servers into RESTful OpenAPI endpoints.

### Basic mcpo Configuration for GitHub MCP

```bash
# Using Docker image with mcpo
uvx mcpo --port 8000 --api-key "your-secret-key" -- \
  docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=<your-token> \
  ghcr.io/github/github-mcp-server
```

### Multi-Server Configuration (config.json)

For deploying alongside other MCP servers:

```json
{
  "mcpServers": {
    "github": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
        "ghcr.io/github/github-mcp-server"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

Run with:
```bash
uvx mcpo --port 8000 --api-key "your-secret-key" --config config.json
```

### Open WebUI Integration

After starting mcpo, configure in Open WebUI:

1. **User Tool Server**: Settings > User Settings > Tool Servers
2. **Global Tool Server**: Admin Settings > Tool Servers

Add the mcpo endpoint: `http://localhost:8000`

---

## Open WebUI External Tool Configuration (Step-by-Step)

### How to Add GitHub MCP as External Tool

**Navigate to:** Admin Panel → Settings → External Tools (or Tool Servers)

### Configuration Values

| Field | Value | Notes |
|-------|-------|-------|
| **Name** | `GitHub` | Display name in tool list |
| **URL** | `http://host.docker.internal:8002` | Use `host.docker.internal` when Open WebUI runs in Docker |
| **API Key** | `test-key` | Must match `MCP_API_KEY` in docker-compose.yml |

### Alternative URLs

| Scenario | URL |
|----------|-----|
| Open WebUI in Docker | `http://host.docker.internal:8002` |
| Open WebUI native (not Docker) | `http://localhost:8002` |
| Kubernetes (same namespace) | `http://mcp-github:8000` |

### Verification Steps

1. After adding, check if GitHub tools appear in chat
2. Test with: "List my GitHub repositories"
3. Check container logs: `docker logs io-mcp-github-1`

### Available Tools After Configuration

Once connected, these tools become available in Open WebUI:

| Tool | Description |
|------|-------------|
| `create_or_update_file` | Create or update files in repos |
| `search_repositories` | Search GitHub repos |
| `create_repository` | Create new repository |
| `get_file_contents` | Read file contents |
| `push_files` | Push multiple files |
| `create_issue` | Create new issue |
| `create_pull_request` | Create PR |
| `fork_repository` | Fork a repo |
| `create_branch` | Create new branch |
| `list_commits` | List commits |
| `list_issues` | List issues |
| `update_issue` | Update existing issue |
| `add_issue_comment` | Add comment to issue |
| `search_code` | Search code across repos |
| `search_issues` | Search issues |
| `search_users` | Search GitHub users |
| `get_issue` | Get issue details |
| `get_pull_request` | Get PR details |
| `list_pull_requests` | List PRs |
| `create_pull_request_review` | Create PR review |

### Our Docker Setup

**docker-compose.yml service:**
```yaml
mcp-github:
  build: ./mcp-servers/github
  environment:
    - GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_TOKEN}
    - MCP_API_KEY=${MCP_API_KEY:-test-key}
  ports:
    - "8002:8000"
  restart: unless-stopped
```

**.env file requirements:**
```
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
MCP_API_KEY=test-key
```

**Dockerfile (mcp-servers/github/Dockerfile):**
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs && apt-get clean
RUN pip install --no-cache-dir mcpo
WORKDIR /app
EXPOSE 8000
CMD mcpo --port 8000 --api-key "$MCP_API_KEY" -- npx -y @modelcontextprotocol/server-github
```

### Security Best Practices

1. **Always use `--api-key`** when exposing mcpo
2. **Use read-only mode** for general users: `GITHUB_READ_ONLY=1`
3. **Enable lockdown mode** for public repos: `GITHUB_LOCKDOWN_MODE=1`
4. **Limit toolsets** to only what's needed

## Multi-Tenant Considerations for Company GPT

### Per-User Token Management

For 15,000 employees, consider:

1. **Service Account Approach**: Single service account with appropriate org-level permissions
2. **User Token Delegation**: Each user provides their own GitHub PAT
3. **OAuth App**: Create GitHub OAuth app for user authentication

### Toolset Restrictions

For enterprise deployment, recommend enabling only:
```
GITHUB_TOOLSETS=repos,issues,pull_requests,code_security
```

### Read-Only Mode

For most users, enable read-only:
```
GITHUB_READ_ONLY=1
```

## Security Features

- **Lockdown Mode**: Restricts content from untrusted contributors in public repositories
- **Content Sanitization**: Enabled by default to protect against prompt injection attacks
- **Tool-Specific Configuration**: Use `X-MCP-Tools` header for granular tool control

## References

- [GitHub MCP Server Repository](https://github.com/github/github-mcp-server)
- [mcpo - MCP to OpenAPI Proxy](https://github.com/open-webui/mcpo)
- [Open WebUI MCP Documentation](https://docs.openwebui.com/features/plugin/tools/openapi-servers/mcp/)
- [GitHub MCP Server Changelog](https://github.blog/changelog/2025-12-10-the-github-mcp-server-adds-support-for-tool-specific-configuration-and-more/)
- [Complete Tool List Gist](https://gist.github.com/didier-durand/2970be82fec6c84d522f7953ac7881b4)

---

## Verification Results

**Date Tested:** 2026-01-07

| Step | Result |
|------|--------|
| Docker container started | ✅ Success - `io-mcp-github-1` running |
| mcpo exposing OpenAPI | ✅ Success - Swagger UI at http://localhost:8002/docs |
| Connection verification | ✅ Success - "Connection successful" in Open WebUI |
| External Tool added | ✅ Success - GitHub appears in Admin → Settings → External Tools |

**Screenshot:** `.playwright-mcp/github-mcp-added.png`

---

## Summary

| Aspect | Finding |
|--------|---------|
| **Protocol** | stdio (local) / Streamable HTTP (remote) - **NOT SSE** |
| **Open WebUI Compatible** | Yes, via mcpo proxy |
| **Installation** | Docker recommended |
| **Authentication** | GitHub Personal Access Token |
| **Tools Available** | 51 tools across 17+ toolsets |
| **Enterprise Ready** | Yes - supports read-only mode, lockdown mode, toolset restrictions |
