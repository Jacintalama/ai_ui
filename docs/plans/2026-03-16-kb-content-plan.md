# KB Content Upload Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upload 5 topic-based markdown documents to OpenWebUI's "IO Platform" Knowledge Base so the Discord bot answers accurately.

**Architecture:** Create markdown files locally, SCP to server, docker cp into open-webui container, upload via REST API, add to existing KB (id: `99f99858-b6c4-4495-be21-da87001c40ba`).

**Tech Stack:** OpenWebUI REST API, SSH/SCP, Docker exec, curl

**Prerequisites:**
- JWT Token: Generate fresh via `docker exec open-webui python3 -c "import jwt, time; print(jwt.encode({'id':'00fdf98b-a708-4898-a123-5fa65104fd4c','exp':int(time.time())+86400},'8d59229bfefe66b87aa2059223f048233e2768675adc68e52360c4c961b50617',algorithm='HS256'))"`
- KB ID: `99f99858-b6c4-4495-be21-da87001c40ba`
- Server: `root@46.224.193.25`

---

### Task 1: Create and Upload `commands-reference.md`

**Files:**
- Create: `/tmp/kb-docs/commands-reference.md` (local temp)

**Step 1: Create the markdown document**

Content must include all /aiui commands from `webhook-handler/handlers/commands.py`:
- Core: `ask <question>`, `help`, `status`
- Code Analysis: `pr-review <number>`, `analyze [owner/repo]`, `rebuild [owner/repo]`, `health [owner/repo]`, `security [owner/repo]`, `deps [owner/repo]`, `license [owner/repo]`
- Workflows: `workflow <name>`, `workflows`, `diagnose [container]`
- Reporting: `report`, `email`, `sheets [daily|errors]`
- MCP: `mcp <server> <tool> [json_args]`

Each with syntax, description, example.

**Step 2: Upload to OpenWebUI**

```bash
# Copy to server
scp /tmp/kb-docs/commands-reference.md root@46.224.193.25:/tmp/

# Copy into container
ssh root@46.224.193.25 "docker cp /tmp/commands-reference.md open-webui:/tmp/"

# Upload file
ssh root@46.224.193.25 "docker exec open-webui curl -s http://localhost:8080/api/v1/files/ -H 'Authorization: Bearer TOKEN' -F 'file=@/tmp/commands-reference.md'"

# Wait for processing (poll until status=completed)
ssh root@46.224.193.25 "docker exec open-webui curl -s http://localhost:8080/api/v1/files/FILE_ID -H 'Authorization: Bearer TOKEN'"

# Add to KB
ssh root@46.224.193.25 "docker exec open-webui curl -s http://localhost:8080/api/v1/knowledge/99f99858-b6c4-4495-be21-da87001c40ba/file/add -H 'Authorization: Bearer TOKEN' -H 'Content-Type: application/json' -d '{\"file_id\":\"FILE_ID\"}'"
```

Expected: File appears in KB with status "completed"

---

### Task 2: Create and Upload `services-architecture.md`

**Files:**
- Create: `/tmp/kb-docs/services-architecture.md`

**Step 1: Create the markdown document**

Content from `docker-compose.unified.yml` and `Caddyfile`:
- All containers: Open WebUI, API Gateway, Caddy, webhook-handler, n8n, PostgreSQL, Redis, Grafana, Loki, Promtail, Pipelines, MCP Proxy, claude-analyzer, MCP servers
- Port mappings (internal and external)
- Traffic flow diagram: Cloudflare → Caddy (80) → API Gateway (8080) → backends
- Rate limiting: 500/min global, 5000/IP
- Static asset bypass: `/_app/*`, `/static/*` go direct to Open WebUI
- Platform URL: `https://ai-ui.coolestdomain.win`

**Step 2: Upload to OpenWebUI**

Same process as Task 1: scp → docker cp → upload → poll → add to KB.

---

### Task 3: Create and Upload `workflows-reference.md`

**Files:**
- Create: `/tmp/kb-docs/workflows-reference.md`

**Step 1: Create the markdown document**

Content from `n8n-workflows/` directory:
- PR Review Automation — triggers on GitHub PR webhook
- GitHub Push Processor — triggers on push events
- Google Drive → KB Sync — polls Google Drive every 2 min, syncs to OpenWebUI KB
- Gmail Inbox Summary — requires Gmail OAuth credential
- Sheets Report — writes to Google Sheets, requires Sheets OAuth
- n8n UI: `https://n8n.srv1041674.hstgr.cloud`
- Key note: `webhookId` field required for production webhook registration
- How to trigger manually vs webhook

**Step 2: Upload to OpenWebUI**

Same process as Task 1.

---

### Task 4: Create and Upload `skills-reference.md`

**Files:**
- Create: `/tmp/kb-docs/skills-reference.md`

**Step 1: Create the markdown document**

Content from `claude-analyzer/skills/`:
- **Health** (health.md): Score 0-100, evaluates architecture/testing/error handling/docs/tech debt/security/deps. Bands: 90-100 Excellent, 70-89 Good, 50-69 Fair, 30-49 Poor, 0-29 Critical
- **Security** (security.md): OWASP Top 10 + extras. Risk levels: critical/high/medium/low. Checks injection, broken auth, XSS, CSRF, secrets, path traversal, race conditions
- **Deps** (deps.md): Outdated packages, known CVEs. Severity: Critical (CVE), High (major behind), Medium (security patches), Low (minor)
- **License** (license.md): GPL contamination, missing licenses, incompatibilities. Status: clean/warning/violation
- All skills: 5 minute timeout, JSON output

**Step 2: Upload to OpenWebUI**

Same process as Task 1.

---

### Task 5: Create and Upload `deployment-guide.md`

**Files:**
- Create: `/tmp/kb-docs/deployment-guide.md`

**Step 1: Create the markdown document**

Content from project knowledge:
- No git on server, deploy via SCP to `/root/proxy-server/`
- Build command: `docker compose -f docker-compose.unified.yml up -d --build <service>`
- Caddy route summary (all routes from Caddyfile)
- Key env vars by category (auth, database, AI/LLM, voice, monitoring, MCP)
- 3.8GB RAM constraint — avoid building multiple containers simultaneously
- Server: `46.224.193.25`, domain: `ai-ui.coolestdomain.win`

**Step 2: Upload to OpenWebUI**

Same process as Task 1.

---

### Task 6: Verify KB Content and Test Bot

**Step 1: List all KB files**

```bash
ssh root@46.224.193.25 "docker exec open-webui curl -s http://localhost:8080/api/v1/knowledge/99f99858-b6c4-4495-be21-da87001c40ba -H 'Authorization: Bearer TOKEN'"
```

Expected: 6 files listed (mcp-servers.md + 5 new docs)

**Step 2: Test bot accuracy**

Ask the Discord bot these questions and verify accurate answers:
- `/aiui ask What commands are available?` → Should list all /aiui commands
- `/aiui ask What services are running?` → Should list Docker containers
- `/aiui ask How do I deploy changes?` → Should explain SCP + docker compose
- `/aiui ask What MCP servers are available?` → Should list all 11 servers
- `/aiui ask What does the health command check?` → Should explain scoring bands

**Step 3: Commit KB docs to repo**

```bash
mkdir -p kb-docs/
# Copy final versions to repo
git add kb-docs/
git commit -m "docs: add Knowledge Base content for OpenWebUI bot"
```
