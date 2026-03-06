# Monitoring & Alerting Automation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When Grafana alerts fire, automatically query Loki for error logs, run AI diagnosis, and post analysis to Discord. Also add `/aiui diagnose` command for on-demand diagnosis.

**Architecture:** Add a LokiClient that queries `http://loki:3100/loki/api/v1/query_range` for error logs. Hook it into the existing Grafana alert endpoint and add a new `diagnose` slash command. AI analysis runs through the existing OpenWebUIClient.

**Tech Stack:** Python, httpx, Loki LogQL API, Open WebUI chat completions, Discord bot API

---

### Task 1: Create Loki client

**Files:**
- Create: `webhook-handler/clients/loki.py`

**Step 1: Create the Loki client**

Create `webhook-handler/clients/loki.py`:

```python
"""Loki API client for querying container logs."""
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class LokiClient:
    """Client for Loki log queries."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.timeout = 15.0

    async def query_error_logs(
        self,
        container_name: str = "",
        minutes: int = 5,
        limit: int = 50,
    ) -> list[str]:
        """
        Query Loki for recent error logs.

        Args:
            container_name: Container to query. Empty string = all containers.
            minutes: How many minutes back to search.
            limit: Max log lines to return.

        Returns:
            List of log line strings, newest first.
        """
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=minutes)

        # Build LogQL query
        if container_name:
            selector = f'{{container_name="{container_name}"}}'
        else:
            selector = '{container_name=~".+"}'

        query = f'{selector} |~ "(?i)(error|exception|fatal|panic|traceback)"'

        params = {
            "query": query,
            "start": str(int(start.timestamp() * 1_000_000_000)),
            "end": str(int(now.timestamp() * 1_000_000_000)),
            "limit": str(limit),
            "direction": "backward",
        }

        url = f"{self.base_url}/loki/api/v1/query_range"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            # Parse Loki response: data.result[].values[][1]
            lines = []
            for stream in data.get("data", {}).get("result", []):
                container = stream.get("stream", {}).get("container_name", "unknown")
                for value in stream.get("values", []):
                    log_line = value[1] if len(value) > 1 else ""
                    # Prefix with container name if querying all
                    if not container_name:
                        lines.append(f"[{container}] {log_line}")
                    else:
                        lines.append(log_line)

            logger.info(f"Loki query returned {len(lines)} error lines for '{container_name or 'all'}'")
            return lines[:limit]

        except httpx.HTTPStatusError as e:
            logger.error(f"Loki HTTP error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Loki query failed: {e}")
            return []
```

**Step 2: Verify file created**

Read back the file and confirm it has the `LokiClient` class with `query_error_logs` method.

**Step 3: Commit**

```bash
git add webhook-handler/clients/loki.py
git commit -m "feat: add Loki API client for error log queries"
```

---

### Task 2: Add loki_url config and initialize client

**Files:**
- Modify: `webhook-handler/config.py:7-55` (add loki_url field)
- Modify: `webhook-handler/main.py:40-53` (add global loki_client)
- Modify: `webhook-handler/main.py:72-135` (initialize in lifespan)

**Step 1: Add loki_url to Settings**

In `webhook-handler/config.py`, add after line 46 (`discord_alert_channel_id`):

```python
    # Loki
    loki_url: str = "http://loki:3100"
```

**Step 2: Add global loki_client and import in main.py**

In `webhook-handler/main.py`, add import at top (after other client imports around line 16):

```python
from clients.loki import LokiClient
```

Add global variable (after line 53, near other globals):

```python
loki_client: Optional[LokiClient] = None
```

**Step 3: Initialize LokiClient in lifespan**

In `webhook-handler/main.py`, inside the `lifespan` function, add `loki_client` to the global statement (line 75-79), and after the n8n client initialization (after line 104), add:

```python
    # Loki client for log queries
    loki_client = LokiClient(base_url=settings.loki_url)
    logger.info(f"Loki URL: {settings.loki_url}")
```

Also pass loki_client to CommandRouter (modify the CommandRouter init around line 128-135):

```python
    command_router = CommandRouter(
        openwebui_client=openwebui_client,
        n8n_client=n8n_client,
        ai_model=settings.ai_model,
        slack_client=slack_client,
        github_client=github_client,
        mcp_client=mcp_client,
        loki_client=loki_client,
    )
```

**Step 4: Commit**

```bash
git add webhook-handler/config.py webhook-handler/main.py
git commit -m "feat: wire up LokiClient in config and main"
```

---

### Task 3: Add AI diagnosis to Grafana alert endpoint

**Files:**
- Modify: `webhook-handler/main.py:602-699` (grafana_alerts_webhook function)

**Step 1: Add AI diagnosis after Discord alert**

Replace the `grafana_alerts_webhook` function (lines 602-699) with the version below. The key change: after posting the alert to Discord, if status is FIRING, query Loki for error logs, run AI diagnosis, and post a second Discord message.

```python
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

    # AI Diagnosis — only on FIRING alerts
    if status == "FIRING" and loki_client and openwebui_client:
        try:
            # Query Loki for each alerting container
            all_logs = []
            for cn in container_names:
                logs = await loki_client.query_error_logs(container_name=cn, minutes=5, limit=30)
                all_logs.extend(logs)

            # If no specific container, query all
            if not container_names:
                all_logs = await loki_client.query_error_logs(container_name="", minutes=5, limit=30)

            if all_logs:
                logs_text = "\n".join(all_logs[:30])
                containers_str = ", ".join(container_names) if container_names else "all"

                messages = [
                    {"role": "system", "content": (
                        "You are a DevOps diagnostic assistant. Analyze these container error logs and provide:\n"
                        "1) Root cause - what went wrong\n"
                        "2) Impact - what's affected\n"
                        "3) Suggested fix - specific commands or config changes\n"
                        "Be concise. Max 3-4 sentences per section."
                    )},
                    {"role": "user", "content": (
                        f"Alert: {rule_name}\n"
                        f"Containers: {containers_str}\n"
                        f"Error logs (last 5 minutes):\n{logs_text}"
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
                    logger.info("AI diagnosis posted to Discord")
                else:
                    logger.warning("AI diagnosis unavailable (Open WebUI error)")
            else:
                logger.info("No error logs found in Loki for diagnosis")
        except Exception as e:
            logger.error(f"AI diagnosis failed: {e}")

    return {"success": True, "discord_status": 200}
```

**Step 2: Verify the edit**

Read back `main.py` starting at the grafana endpoint and confirm the AI diagnosis block is present after the Discord alert send.

**Step 3: Commit**

```bash
git add webhook-handler/main.py
git commit -m "feat: AI diagnosis on Grafana FIRING alerts via Loki logs"
```

---

### Task 4: Add /aiui diagnose command

**Files:**
- Modify: `webhook-handler/handlers/commands.py:37-48` (add loki_client to __init__)
- Modify: `webhook-handler/handlers/commands.py:76-79` (add "diagnose" to known_commands)
- Modify: `webhook-handler/handlers/commands.py:86-109` (add diagnose to execute dispatch)
- Add `_handle_diagnose` method after `_handle_help` method

**Step 1: Add loki_client to CommandRouter.__init__**

In `commands.py`, modify the `__init__` method (around line 40-48) to accept and store loki_client:

```python
    def __init__(
        self,
        openwebui_client: OpenWebUIClient,
        n8n_client: N8NClient,
        ai_model: str = "gpt-4-turbo",
        slack_client=None,
        github_client: Optional[GitHubClient] = None,
        mcp_client: Optional[MCPProxyClient] = None,
        loki_client=None,
    ):
        self.openwebui = openwebui_client
        self.n8n = n8n_client
        self.ai_model = ai_model
        self._slack_client = slack_client
        self._github_client = github_client
        self._mcp_client = mcp_client
        self._loki_client = loki_client
```

**Step 2: Add "diagnose" to known_commands**

In `parse_command` (line 76-79), add "diagnose" to the set:

```python
        known_commands = {
            "ask", "workflow", "workflows", "status", "help",
            "report", "pr-review", "pr", "mcp", "diagnose",
        }
```

**Step 3: Add diagnose to execute dispatch**

In the `execute` method (around line 86-109), add before the `else` clause:

```python
            elif ctx.subcommand == "diagnose":
                await self._handle_diagnose(ctx)
```

**Step 4: Add _handle_diagnose method**

Add this method after `_handle_help` (after line 306):

```python
    async def _handle_diagnose(self, ctx: CommandContext) -> None:
        """Query Loki for error logs and run AI diagnosis."""
        if not self._loki_client:
            await ctx.respond("Loki not configured. Cannot run diagnosis.")
            return

        container_name = ctx.arguments.strip() if ctx.arguments else ""
        target = container_name or "all containers"

        logger.info(f"[{ctx.platform}] diagnose '{target}' from {ctx.user_name}")
        await ctx.respond(f"Diagnosing **{target}**... (querying last 5 minutes of error logs)")

        logs = await self._loki_client.query_error_logs(
            container_name=container_name,
            minutes=5,
            limit=50,
        )

        if not logs:
            await ctx.respond(f"No recent errors found for **{target}** in the last 5 minutes.")
            return

        logs_text = "\n".join(logs[:30])

        messages = [
            {"role": "system", "content": (
                "You are a DevOps diagnostic assistant. Analyze these container error logs and provide:\n"
                "1) Root cause - what went wrong\n"
                "2) Impact - what's affected\n"
                "3) Suggested fix - specific commands or config changes\n"
                "Be concise. Max 3-4 sentences per section."
            )},
            {"role": "user", "content": (
                f"Container: {target}\n"
                f"Error logs (last 5 minutes, {len(logs)} lines):\n{logs_text}"
            )},
        ]

        diagnosis = await self.openwebui.chat_completion(
            messages=messages,
            model=self.ai_model,
        )

        if not diagnosis:
            # Fallback: show raw logs
            raw = logs_text[:1500]
            await ctx.respond(
                f"AI diagnosis unavailable. Raw error logs for **{target}**:\n```\n{raw}\n```"
            )
            return

        response = f"\U0001f50d **Diagnosis for {target}** ({len(logs)} errors, last 5 min)\n\n{diagnosis}"

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"

        await ctx.respond(response)
```

**Step 5: Update help text**

In `_handle_help` (around line 293-306), add the diagnose command to help text:

```python
            "`/aiui diagnose [container]` \u2014 AI diagnosis of recent errors\n"
```

**Step 6: Commit**

```bash
git add webhook-handler/handlers/commands.py
git commit -m "feat: add /aiui diagnose command for on-demand error analysis"
```

---

### Task 5: Deploy and test

**Step 1: Deploy all changed files**

```bash
scp webhook-handler/clients/loki.py root@46.224.193.25:/root/proxy-server/webhook-handler/clients/loki.py
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
scp webhook-handler/handlers/commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
```

**Step 2: Rebuild and restart**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml build --no-cache webhook-handler && docker compose -f docker-compose.unified.yml up -d webhook-handler"
```

**Step 3: Verify healthy**

```bash
ssh root@46.224.193.25 "docker logs webhook-handler 2>&1 | tail -10"
```

Expected: "Loki URL: http://loki:3100" in logs, no tracebacks.

**Step 4: Test /aiui diagnose**

Run `/aiui diagnose` on Discord (no container = all containers).
Expected: Either "No recent errors" or an AI diagnosis of any current errors.

Run `/aiui diagnose open-webui` on Discord.
Expected: Diagnosis scoped to open-webui container.
