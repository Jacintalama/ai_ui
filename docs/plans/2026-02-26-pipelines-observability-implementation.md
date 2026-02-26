# Pipelines + Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy an external Pipelines container with LangFuse observability filter so all LLM interactions are traced to LangFuse Cloud.

**Architecture:** Add one Pipelines container (`ghcr.io/open-webui/pipelines:main`) to the Docker Compose stack. Install the official LangFuse v3 filter pipeline inside it. Move `webhook_pipe.py` from in-process to the Pipelines container. Connect Open WebUI to Pipelines as an OpenAI-compatible API endpoint.

**Tech Stack:** Docker Compose, Open WebUI Pipelines, LangFuse Cloud (free tier), Python

**Design doc:** `docs/plans/2026-02-26-pipelines-observability-design.md`

---

### Task 1: Add Pipelines service to Docker Compose

**Files:**
- Modify: `docker-compose.unified.yml:464-519` (add service before NETWORKS section, add volume)

**Step 1: Add the pipelines service**

Insert before the `# NETWORKS` section (after the `db-init` service):

```yaml
  # ===========================================================================
  # PIPELINES - External Pipe/Filter Runner
  # ===========================================================================
  # Runs Pipe Functions and Filters outside the Open WebUI process.
  # Exposes OpenAI-compatible API on port 9099.
  pipelines:
    image: ghcr.io/open-webui/pipelines:main
    container_name: pipelines
    restart: unless-stopped
    volumes:
      - pipelines-data:/app/pipelines
    environment:
      - LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
      - LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
      - LANGFUSE_HOST=${LANGFUSE_BASE_URL}
    networks:
      - backend
```

**Step 2: Add the volume**

Add `pipelines-data:` to the `volumes:` section at the bottom of the file.

**Step 3: Verify YAML is valid**

Run: `cd "/c/Users/alama/Desktop/Lukas Work/IO" && python -c "import yaml; yaml.safe_load(open('docker-compose.unified.yml'))"`
Expected: No output (valid YAML)

If `yaml` module not available, run: `pip install pyyaml` first, or use: `docker compose -f docker-compose.unified.yml config --quiet` on the server.

**Step 4: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: add Pipelines container for external pipe/filter execution"
```

---

### Task 2: Deploy Pipelines container to Hetzner

**Step 1: Sync docker-compose and .env to server**

```bash
scp docker-compose.unified.yml root@ai-ui.coolestdomain.win:/root/proxy-server/docker-compose.unified.yml
```

**Step 2: Sync .env with LangFuse keys**

Either scp the full `.env` or append the keys on the server:

```bash
ssh root@ai-ui.coolestdomain.win 'cat >> /root/proxy-server/.env << "EOF"

# =============================================================================
# LANGFUSE - LLM Observability
# =============================================================================
LANGFUSE_SECRET_KEY="sk-lf-d5d3f40b-ce6c-444f-acc5-1d8422654d8f"
LANGFUSE_PUBLIC_KEY="pk-lf-ecd2a5fa-c51e-4cb0-a125-88de3b03e51e"
LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"
EOF'
```

**Step 3: Start the Pipelines container**

```bash
ssh root@ai-ui.coolestdomain.win 'cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d pipelines'
```

**Step 4: Verify it's running**

```bash
ssh root@ai-ui.coolestdomain.win 'docker logs pipelines 2>&1 | tail -20'
```

Expected: Logs showing Pipelines server started on port 9099.

---

### Task 3: Connect Open WebUI to Pipelines

This is done via the Open WebUI Admin Panel (browser), not code.

**Step 1: Open Admin Panel**

Navigate to `https://ai-ui.coolestdomain.win` -> Admin Panel -> Settings -> Connections

**Step 2: Add OpenAI API connection**

- Click "+" to add a new OpenAI API connection
- URL: `http://pipelines:9099`
- API Key: `0p3n-w3bu!`
- Save

**Step 3: Verify connection**

After saving, Open WebUI should show the Pipelines endpoint as connected. Any pipes loaded in the Pipelines container will appear as selectable models in the chat dropdown.

---

### Task 4: Install LangFuse v3 filter pipeline

**Step 1: Download the filter to the Pipelines volume**

```bash
ssh root@ai-ui.coolestdomain.win 'docker exec pipelines pip install "langfuse>=3.0.0"'
```

**Step 2: Copy the filter file into the Pipelines container**

```bash
ssh root@ai-ui.coolestdomain.win 'docker exec pipelines wget -O /app/pipelines/langfuse_v3_filter_pipeline.py "https://raw.githubusercontent.com/open-webui/pipelines/main/examples/filters/langfuse_v3_filter_pipeline.py"'
```

**Step 3: Restart Pipelines to pick up the new filter**

```bash
ssh root@ai-ui.coolestdomain.win 'docker restart pipelines'
```

**Step 4: Verify filter is loaded**

```bash
ssh root@ai-ui.coolestdomain.win 'docker logs pipelines 2>&1 | tail -20'
```

Expected: Logs mentioning "Langfuse Filter" loaded.

**Step 5: Configure Valves in Open WebUI**

Navigate to Admin Panel -> Pipelines (or Workspace -> Functions). Find the "Langfuse Filter" and configure its Valves:

| Valve | Value |
|-------|-------|
| `secret_key` | `sk-lf-d5d3f40b-ce6c-444f-acc5-1d8422654d8f` |
| `public_key` | `pk-lf-ecd2a5fa-c51e-4cb0-a125-88de3b03e51e` |
| `host` | `https://us.cloud.langfuse.com` |
| `pipelines` | `["*"]` |
| `debug` | `true` (initially, to verify it works) |

Note: The filter should auto-read from env vars (`LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`) passed to the Pipelines container, but verify the Valves show the correct values.

---

### Task 5: Test LangFuse observability

**Step 1: Send a test message**

Open a new chat in Open WebUI (`https://ai-ui.coolestdomain.win`). Select any model (e.g., `gpt-5`). Send a simple message like "Hello, what is 2+2?"

**Step 2: Check Pipelines logs**

```bash
ssh root@ai-ui.coolestdomain.win 'docker logs pipelines 2>&1 | tail -30'
```

Expected: Debug logs showing `[DEBUG] inlet called`, trace creation, and `[DEBUG] outlet called` with token counts.

**Step 3: Check LangFuse dashboard**

Navigate to `https://us.cloud.langfuse.com` -> Traces. You should see:

- A new trace with the chat ID
- The model name (e.g., `gpt-5`)
- Token usage (prompt + completion tokens)
- Latency
- The full prompt and response

**Step 4: Turn off debug mode**

Once verified, set the `debug` Valve back to `false` in Admin Panel.

---

### Task 6: Move webhook_pipe.py to Pipelines container

**Step 1: Copy webhook_pipe.py into the Pipelines volume**

```bash
scp open-webui-functions/webhook_pipe.py root@ai-ui.coolestdomain.win:/tmp/webhook_pipe.py
ssh root@ai-ui.coolestdomain.win 'docker cp /tmp/webhook_pipe.py pipelines:/app/pipelines/webhook_pipe.py'
```

**Step 2: Restart Pipelines**

```bash
ssh root@ai-ui.coolestdomain.win 'docker restart pipelines'
```

**Step 3: Verify the pipe appears**

```bash
ssh root@ai-ui.coolestdomain.win 'docker logs pipelines 2>&1 | tail -20'
```

Expected: Logs showing "Webhook Automation" pipe loaded.

**Step 4: Verify in Open WebUI**

Open the model selector in a new chat. "Webhook Automation" should appear as a selectable model (marked as "External").

**Step 5: Configure Valves**

In Admin Panel, find the "Webhook Automation" pipe and set its Valves:

| Valve | Value |
|-------|-------|
| `OPENWEBUI_API_URL` | `http://open-webui:8080` |
| `OPENWEBUI_API_KEY` | (the current working API key from `.env`) |
| `AI_MODEL` | `gpt-5` |
| `MCP_PROXY_URL` | `http://mcp-proxy:8000` |
| `N8N_URL` | `https://n8n.srv1041674.hstgr.cloud` |
| `N8N_API_KEY` | (the n8n API key from `.env`) |

**Step 6: Test webhook automation still works**

Trigger a test webhook or use the "Webhook Automation" model in chat to verify the 4-phase pipeline (fetch tools -> plan -> execute -> summarize) still works.

**Step 7: Disable the old in-process pipe**

Once confirmed working from Pipelines, disable the old `webhook_pipe.py` Pipe Function inside Open WebUI:
- Admin Panel -> Workspace -> Functions -> find "Webhook Automation" -> Disable

**Step 8: Commit**

```bash
git add docs/plans/2026-02-26-pipelines-observability-implementation.md
git commit -m "docs: add Pipelines + Observability implementation plan"
```

---

### Task 7: Verify end-to-end

**Step 1: Verify LangFuse traces for normal chat**

Send 2-3 messages in Open WebUI. Check LangFuse dashboard shows traces with token counts and latency.

**Step 2: Verify LangFuse traces for webhook automation**

Trigger a webhook (e.g., GitHub push) or use the Webhook Automation model in chat. Check LangFuse shows the traces including the internal LLM calls the pipe makes.

**Step 3: Verify existing functionality unchanged**

- MCP tools still work from chat
- Cron jobs still fire (check `docker logs webhook-handler`)
- n8n workflows still trigger
- GitHub webhooks still process

**Step 4: Final commit**

If any adjustments were made during testing, commit them:

```bash
git add -A
git commit -m "feat: deploy Pipelines container with LangFuse observability"
```
