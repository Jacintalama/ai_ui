# Knowledge Base Content Plan

**Date:** 2026-03-16
**Goal:** Populate OpenWebUI Knowledge Base ("IO Platform") with platform documentation so the Discord bot gives accurate answers instead of guessing.

## Approach

Topic-based documents — 6 focused markdown files uploaded to the existing "IO Platform" KB (id: `99f99858-b6c4-4495-be21-da87001c40ba`). Smaller focused docs give better RAG retrieval accuracy.

## Documents

### 1. `mcp-servers.md` (DONE)
All 11 MCP servers with endpoints, descriptions, API keys, tenant access matrix, and Discord commands.

### 2. `commands-reference.md`
All 18+ `/aiui` slash commands grouped by category:
- **Core:** ask, help, status
- **Code Analysis:** pr-review, analyze, rebuild, health, security, deps, license
- **Workflows:** workflow, workflows, diagnose
- **Reporting:** report, email, sheets
- **MCP Tools:** mcp (with server/tool syntax)

Each command includes: syntax, description, example usage, what it returns.

### 3. `services-architecture.md`
- All Docker containers with ports and purposes
- Traffic flow: Cloudflare → Caddy → API Gateway → backends
- Rate limiting (500/min global, 5000/IP)
- Static asset bypass explanation
- Internal vs external port mapping

### 4. `workflows-reference.md`
- 5 n8n workflows: PR Review, GitHub Push Processor, Google Drive → KB Sync, Gmail Inbox Summary, Sheets Report
- Trigger mechanism for each
- Required OAuth credentials
- `webhookId` requirement for production webhooks
- n8n UI access info

### 5. `skills-reference.md`
- 4 Claude analyzer skills: health, security, deps, license
- Scoring bands (0-100 for health)
- What each skill evaluates
- Output format (JSON structure)
- Timeout: 5 minutes each

### 6. `deployment-guide.md`
- Deploy via SCP (no git on server)
- `docker compose -f docker-compose.unified.yml up -d --build <service>`
- Caddy route overview
- Key environment variables by category
- 3.8GB RAM constraint

## Upload Process

For each document:
1. Create markdown content
2. Copy file into `open-webui` container
3. Upload via `POST /api/v1/files/`
4. Poll processing status
5. Add to KB via `POST /api/v1/knowledge/{kb_id}/file/add`

## Success Criteria

- All 6 docs in KB and indexed
- Discord bot (`/aiui ask`) returns accurate answers about commands, services, and architecture
