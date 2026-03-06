# Google Workspace & End-to-End Chains Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Google Workspace commands (`/aiui email`, `/aiui sheets`), enhance the Grafana alert chain with code-level diagnosis via GitHub MCP, and enrich PR reviews with codebase context + error history.

**Architecture:** Google Workspace uses n8n workflows (Gmail/Sheets nodes) triggered by new webhook-handler commands. Alert chain extends `grafana_alerts_webhook` in main.py to fetch source code via MCP proxy after Loki diagnosis. PR chain extends `_handle_pull_request_event` in github.py to gather codebase context and Loki error history before AI review.

**Tech Stack:** Python, FastAPI, httpx, n8n (Gmail/Sheets nodes), MCP Proxy, Loki, Open WebUI

---

### Task 1: Add `/aiui email` and `/aiui sheets` commands

**Files:**
- Modify: `webhook-handler/handlers/commands.py`

**Step 1: Add "email" and "sheets" to known_commands**

In `webhook-handler/handlers/commands.py`, find the `known_commands` set at line 78 and update:

```python
        known_commands = {
            "ask", "workflow", "workflows", "status", "help",
            "report", "pr-review", "pr", "mcp", "diagnose", "analyze",
            "email", "sheets",
        }
```

**Step 2: Add dispatch branches in execute method**

In the `execute` method, add before the `elif ctx.subcommand == "help":` line (line 109):

```python
            elif ctx.subcommand == "email":
                await self._handle_email(ctx)
            elif ctx.subcommand == "sheets":
                await self._handle_sheets(ctx)
```

**Step 3: Add _handle_email method**

Add after the `_handle_analyze` method (after line 429):

```python
    async def _handle_email(self, ctx: CommandContext) -> None:
        """Summarize recent emails via n8n Gmail workflow."""
        if not self.n8n or not self.n8n.api_key:
            await ctx.respond("n8n not configured. Cannot access Gmail.")
            return

        logger.info(f"[{ctx.platform}] email summary from {ctx.user_name}")
        await ctx.respond("Fetching email summary... (triggering Gmail workflow)")

        # Try to find and trigger the gmail workflow
        result = await self._trigger_n8n_by_name(
            "gmail-inbox-summary",
            payload={"action": "summary", "limit": 10},
        )

        if result is None:
            await ctx.respond(
                "Gmail workflow not found in n8n. Please create a workflow named "
                "`gmail-inbox-summary` with a Webhook trigger and Gmail node.\n"
                "n8n UI: https://n8n.srv1041674.hstgr.cloud"
            )
            return

        # If n8n returned email data, summarize with AI
        if isinstance(result, dict) and result.get("emails"):
            emails_text = json.dumps(result["emails"], indent=2)[:3000]
            messages = [
                {"role": "system", "content": (
                    "Summarize these emails concisely. For each: sender, subject, "
                    "1-line summary. Group by importance. Be brief."
                )},
                {"role": "user", "content": f"Recent emails:\n{emails_text}"},
            ]
            summary = await self.openwebui.chat_completion(
                messages=messages, model=self.ai_model
            )
            if summary:
                response = f"\U0001f4e7 **Email Summary**\n\n{summary}"
            else:
                response = f"\U0001f4e7 **Email Summary** (raw)\n```\n{emails_text[:1500]}\n```"
        elif isinstance(result, dict) and result.get("summary"):
            response = f"\U0001f4e7 **Email Summary**\n\n{result['summary']}"
        else:
            # n8n returned something — show it
            response = f"\U0001f4e7 **Email Summary**\n\n{json.dumps(result, indent=2)[:1500]}"

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"
        await ctx.respond(response)
```

**Step 4: Add _handle_sheets method**

Add immediately after `_handle_email`:

```python
    async def _handle_sheets(self, ctx: CommandContext) -> None:
        """Generate a report and write to Google Sheets via n8n."""
        if not self.n8n or not self.n8n.api_key:
            await ctx.respond("n8n not configured. Cannot access Google Sheets.")
            return

        report_type = ctx.arguments.strip().lower() if ctx.arguments else "daily"
        if report_type not in ("daily", "errors"):
            await ctx.respond("Usage: `/aiui sheets [daily|errors]`")
            return

        logger.info(f"[{ctx.platform}] sheets {report_type} report from {ctx.user_name}")
        await ctx.respond(f"Generating **{report_type}** report for Google Sheets...")

        # Gather data based on report type
        if report_type == "daily":
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            commits, executions, health = await asyncio.gather(
                self._gather_github_commits(today_start),
                self._gather_n8n_executions(today_start),
                self._gather_health(),
            )
            payload = {
                "action": "daily_report",
                "date": now.strftime("%Y-%m-%d"),
                "commits": commits or [],
                "executions": executions or [],
                "health": health,
            }
        else:
            # errors report
            logs = []
            if self._loki_client:
                logs = await self._loki_client.query_error_logs(
                    container_name="", minutes=60, limit=50
                )
            payload = {
                "action": "error_report",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "errors": logs,
                "error_count": len(logs),
            }

        result = await self._trigger_n8n_by_name(
            "sheets-report",
            payload=payload,
        )

        if result is None:
            await ctx.respond(
                "Sheets workflow not found in n8n. Please create a workflow named "
                "`sheets-report` with a Webhook trigger and Google Sheets node.\n"
                "n8n UI: https://n8n.srv1041674.hstgr.cloud"
            )
            return

        # Parse response from n8n
        if isinstance(result, dict) and result.get("sheet_url"):
            await ctx.respond(
                f"\u2705 **{report_type.title()} report** written to Google Sheets!\n"
                f"{result['sheet_url']}"
            )
        else:
            await ctx.respond(
                f"\u2705 **{report_type.title()} report** sent to Google Sheets workflow.\n"
                f"Response: {json.dumps(result, indent=2)[:500]}"
            )
```

**Step 5: Add _trigger_n8n_by_name helper**

Add after `_handle_sheets`:

```python
    async def _trigger_n8n_by_name(
        self, workflow_name: str, payload: dict = None
    ) -> Optional[Any]:
        """Find an n8n workflow by name and trigger it. Returns result or None."""
        try:
            headers = {
                "X-N8N-API-KEY": self.n8n.api_key,
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.n8n.base_url}/api/v1/workflows",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            workflows = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(workflows, list):
                return None

            # Find workflow by name (case-insensitive)
            target = None
            for wf in workflows:
                if wf.get("name", "").lower() == workflow_name.lower():
                    target = wf
                    break

            if not target:
                return None

            # Check if workflow has a webhook trigger
            nodes = target.get("nodes", [])
            webhook_path = None
            for node in nodes:
                if "webhook" in node.get("type", "").lower():
                    webhook_path = node.get("parameters", {}).get("path", "")
                    break

            if webhook_path:
                return await self.n8n.trigger_workflow(
                    webhook_path=webhook_path, payload=payload or {}
                )
            else:
                return await self.n8n.trigger_workflow_by_id(
                    workflow_id=target["id"], payload=payload or {}
                )
        except Exception as e:
            logger.error(f"Error triggering n8n workflow '{workflow_name}': {e}")
            return None
```

**Step 6: Update help text**

In `_handle_help` (line 300), add after the analyze line:

```python
            "`/aiui email` \u2014 Summarize recent emails (via n8n Gmail)\n"
            "`/aiui sheets [daily|errors]` \u2014 Generate report to Google Sheets\n"
```

**Step 7: Commit**

```bash
git add webhook-handler/handlers/commands.py
git commit -m "feat: add /aiui email and /aiui sheets commands for Google Workspace"
```

---

### Task 2: Enhance Alert → Diagnose → Fix chain

**Files:**
- Modify: `webhook-handler/main.py:707-761`

**Step 1: Replace the AI diagnosis block in grafana_alerts_webhook**

In `webhook-handler/main.py`, replace lines 707-761 (the `# AI Diagnosis` block) with an enhanced version that adds code fetching via MCP:

```python
    # AI Diagnosis with code context — only on FIRING alerts
    if status == "FIRING" and loki_client and openwebui_client:
        try:
            # Step 1: Query Loki for error logs
            all_logs = []
            for cn in container_names:
                logs = await loki_client.query_error_logs(container_name=cn, minutes=5, limit=30)
                all_logs.extend(logs)

            if not container_names:
                all_logs = await loki_client.query_error_logs(container_name="", minutes=5, limit=30)

            if all_logs:
                logs_text = "\n".join(all_logs[:30])
                containers_str = ", ".join(container_names) if container_names else "all"

                # Step 2: Extract file references from error logs
                file_refs = _extract_file_references(logs_text)
                code_context = ""

                # Step 3: Fetch source code via MCP proxy if we have file references
                if file_refs and mcp_handler:
                    code_snippets = []
                    mcp_client_ref = mcp_handler.mcp_client
                    repo_parts = settings.report_github_repo.split("/", 1)
                    if len(repo_parts) == 2 and mcp_client_ref:
                        owner, repo_name = repo_parts
                        for fpath in file_refs[:3]:  # max 3 files
                            try:
                                result = await mcp_client_ref.execute_tool(
                                    server_id="github",
                                    tool_name="get_file_contents",
                                    arguments={
                                        "owner": owner,
                                        "repo": repo_name,
                                        "path": fpath,
                                    },
                                )
                                if result:
                                    content = str(result)[:1500]
                                    code_snippets.append(f"--- {fpath} ---\n{content}")
                            except Exception as e:
                                logger.debug(f"Could not fetch {fpath} via MCP: {e}")

                    if code_snippets:
                        code_context = "\n\nRelevant source code:\n" + "\n".join(code_snippets)

                # Step 4: AI diagnosis with code context
                messages = [
                    {"role": "system", "content": (
                        "You are a DevOps diagnostic assistant. Analyze these container error logs "
                        "and any source code provided. Provide:\n"
                        "1) Root cause - what went wrong (reference specific code if available)\n"
                        "2) Impact - what's affected\n"
                        "3) Suggested fix - specific code changes or commands\n"
                        "Be concise. Max 3-4 sentences per section."
                    )},
                    {"role": "user", "content": (
                        f"Alert: {rule_name}\n"
                        f"Containers: {containers_str}\n"
                        f"Error logs (last 5 minutes):\n{logs_text}"
                        f"{code_context}"
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
                    logger.info("AI diagnosis (with code context) posted to Discord")
                else:
                    logger.warning("AI diagnosis unavailable (Open WebUI error)")
            else:
                logger.info("No error logs found in Loki for diagnosis")
        except Exception as e:
            logger.error(f"AI diagnosis failed: {e}")
```

**Step 2: Add _extract_file_references helper**

Add this function before the `grafana_alerts_webhook` function (before line 610):

```python
import re

def _extract_file_references(logs_text: str) -> list[str]:
    """Extract file paths from error logs/stack traces."""
    patterns = [
        r'File "([^"]+\.py)"',                    # Python tracebacks
        r'at\s+\S+\s+\(([^)]+\.[jt]s):\d+:\d+\)', # Node.js stack traces
        r'(/[\w/.-]+\.\w{1,4}):\d+',               # Generic /path/file.ext:line
        r'([\w/.-]+\.(py|js|ts|go|rs|java)):\d+',  # Relative paths with line numbers
    ]

    files = set()
    for pattern in patterns:
        for match in re.finditer(pattern, logs_text):
            fpath = match.group(1)
            # Skip system/library paths
            if any(skip in fpath for skip in [
                "site-packages", "node_modules", "/usr/lib",
                "/usr/local/lib", "venv", ".venv"
            ]):
                continue
            # Normalize: strip leading /app/ or /root/ common in containers
            for prefix in ["/app/", "/root/proxy-server/", "/root/"]:
                if fpath.startswith(prefix):
                    fpath = fpath[len(prefix):]
                    break
            files.add(fpath)

    return list(files)[:5]
```

**Step 3: Add `import re` at top of main.py**

Add `import re` to the imports at the top of `webhook-handler/main.py` (after line 8):

```python
import re
```

**Step 4: Commit**

```bash
git add webhook-handler/main.py
git commit -m "feat: enhance alert chain with code-level diagnosis via GitHub MCP"
```

---

### Task 3: Enhance PR → Full Analysis chain

**Files:**
- Modify: `webhook-handler/handlers/github.py:150-238`

**Step 1: Add Loki and MCP clients to GitHubWebhookHandler**

In `webhook-handler/handlers/github.py`, update the `__init__` method (lines 17-29) to accept new clients:

```python
    def __init__(
        self,
        openwebui_client: OpenWebUIClient,
        github_client: GitHubClient,
        n8n_client: Optional[N8NClient] = None,
        ai_model: str = "gpt-4-turbo",
        ai_system_prompt: str = "",
        loki_client=None,
        mcp_client=None,
    ):
        self.openwebui = openwebui_client
        self.github = github_client
        self.n8n = n8n_client
        self.ai_model = ai_model
        self.ai_system_prompt = ai_system_prompt
        self._loki_client = loki_client
        self._mcp_client = mcp_client
```

**Step 2: Update GitHubWebhookHandler init in main.py**

In `webhook-handler/main.py`, update the `github_handler` initialization (lines 113-119):

```python
    github_handler = GitHubWebhookHandler(
        openwebui_client=openwebui_client,
        github_client=github_client,
        n8n_client=n8n_client,
        ai_model=settings.ai_model,
        ai_system_prompt=settings.ai_system_prompt,
        loki_client=loki_client,
        mcp_client=mcp_client,
    )
```

**Step 3: Replace _handle_pull_request_event with enriched version**

In `webhook-handler/handlers/github.py`, replace the AI review section (lines 191-238) with an enriched version. Replace from `logger.info(f"Running AI review on PR` through the end of the method:

```python
        logger.info(f"Running AI review on PR #{pr_number}: {title} (action: {action})")

        # Fetch PR file summary for AI review
        diff_summary = await self.github.get_pr_files(owner, repo_name, pr_number)

        # Gather enrichment data in parallel
        codebase_context = ""
        error_context = ""

        try:
            # Extract unique directories from changed files to understand codebase context
            changed_dirs = set()
            if diff_summary:
                for line in diff_summary.split("\n"):
                    if line.startswith("**") and "/" in line:
                        parts = line.strip("* ").split("/")
                        if len(parts) > 1:
                            changed_dirs.add(parts[0])

            # Fetch repo overview for codebase context (reuse existing method)
            if changed_dirs:
                overview = await self.github.get_repo_overview(owner, repo_name)
                if overview:
                    tree = "\n".join(overview.get("tree", [])[:30])
                    desc = overview.get("description", "")
                    lang = overview.get("language", "")
                    codebase_context = (
                        f"\n\nCodebase Context:\n"
                        f"Description: {desc}\n"
                        f"Language: {lang}\n"
                        f"File tree:\n{tree}"
                    )

            # Check Loki for recent errors related to changed components
            if self._loki_client and changed_dirs:
                service_errors = []
                for dir_name in list(changed_dirs)[:3]:
                    logs = await self._loki_client.query_error_logs(
                        container_name=dir_name.replace("_", "-"),
                        minutes=60,
                        limit=10,
                    )
                    if logs:
                        service_errors.append(f"{dir_name}: {len(logs)} errors")
                        service_errors.extend([f"  {l}" for l in logs[:3]])

                if service_errors:
                    error_context = (
                        f"\n\nRecent Error History (last hour):\n"
                        + "\n".join(service_errors)
                    )
        except Exception as e:
            logger.warning(f"PR enrichment failed (non-fatal): {e}")

        # Run enriched AI review via Open WebUI
        body = pr.get("body", "") or ""
        review = await self.openwebui.analyze_pull_request(
            title=title,
            body=body,
            diff_summary=(diff_summary or "No file changes available")
                + codebase_context + error_context,
            labels=[label.get("name", "") for label in pr.get("labels", [])],
            model=self.ai_model,
        )

        result = {
            "success": True,
            "pr_number": pr_number,
            "message": "PR review processed",
        }

        # Post review as GitHub comment
        if review:
            formatted = self.github.format_ai_response(review)
            comment_id = await self.github.post_issue_comment(
                owner=owner,
                repo=repo_name,
                issue_number=pr_number,
                body=formatted,
            )
            if comment_id:
                logger.info(f"AI review posted on PR #{pr_number} (comment {comment_id})")
                result["comment_id"] = comment_id
            else:
                logger.warning(f"Failed to post AI review comment on PR #{pr_number}")

            # Discord summary of the review
            summary = review[:200].split("\n")[0]
            enrichment = ""
            if codebase_context:
                enrichment += " + codebase context"
            if error_context:
                enrichment += " + error history"
            await self._notify_discord(
                f"\U0001f50d **AI Review for PR #{pr_number}**: {title}\n"
                f"by **{author}** \u2192 `{base_branch}`{enrichment}\n"
                f"{summary}\n{html_url}"
            )
        else:
            logger.warning(f"AI review unavailable for PR #{pr_number} (Open WebUI error)")
            result["message"] = "PR notification sent but AI review unavailable"

        return result
```

**Step 4: Commit**

```bash
git add webhook-handler/handlers/github.py webhook-handler/main.py
git commit -m "feat: enrich PR review with codebase context and error history"
```

---

### Task 4: Create n8n workflow JSON templates

**Files:**
- Create: `n8n-workflows/gmail-inbox-summary.json`
- Create: `n8n-workflows/sheets-report.json`

**Step 1: Create Gmail workflow template**

Create `n8n-workflows/gmail-inbox-summary.json` with a webhook-triggered workflow that reads Gmail and returns a summary. This is a template — the user must authenticate with Google in the n8n UI.

```json
{
  "name": "gmail-inbox-summary",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "gmail-inbox-summary",
        "responseMode": "responseNode",
        "options": {}
      },
      "name": "Webhook",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [220, 300]
    },
    {
      "parameters": {
        "operation": "getAll",
        "returnAll": false,
        "limit": 10,
        "filters": {
          "readStatus": "unread"
        },
        "options": {}
      },
      "name": "Gmail",
      "type": "n8n-nodes-base.gmail",
      "typeVersion": 2.1,
      "position": [440, 300],
      "credentials": {
        "gmailOAuth2": {
          "id": "CONFIGURE_IN_UI",
          "name": "Gmail account"
        }
      }
    },
    {
      "parameters": {
        "jsCode": "const emails = $input.all().map(item => ({\n  from: item.json.from?.text || item.json.from || 'unknown',\n  subject: item.json.subject || 'No subject',\n  date: item.json.date || '',\n  snippet: (item.json.snippet || item.json.textPlain || '').substring(0, 200)\n}));\nreturn [{ json: { emails, count: emails.length } }];"
      },
      "name": "Format Emails",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [660, 300]
    },
    {
      "parameters": {
        "options": {
          "responseCode": 200
        },
        "respondWith": "json",
        "responseBody": "={{ JSON.stringify($json) }}"
      },
      "name": "Respond",
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.1,
      "position": [880, 300]
    }
  ],
  "connections": {
    "Webhook": { "main": [[{ "node": "Gmail", "type": "main", "index": 0 }]] },
    "Gmail": { "main": [[{ "node": "Format Emails", "type": "main", "index": 0 }]] },
    "Format Emails": { "main": [[{ "node": "Respond", "type": "main", "index": 0 }]] }
  },
  "settings": { "executionOrder": "v1" }
}
```

**Step 2: Create Sheets workflow template**

Create `n8n-workflows/sheets-report.json`:

```json
{
  "name": "sheets-report",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "sheets-report",
        "responseMode": "responseNode",
        "options": {}
      },
      "name": "Webhook",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [220, 300]
    },
    {
      "parameters": {
        "jsCode": "const data = $input.first().json.body || $input.first().json;\nconst date = data.date || new Date().toISOString().split('T')[0];\nconst action = data.action || 'daily_report';\n\nlet rows = [];\nif (action === 'daily_report') {\n  rows.push([date, 'DAILY REPORT', '', '']);\n  (data.commits || []).forEach(c => rows.push([date, 'commit', c.sha || '', c.message || '']));\n  (data.executions || []).forEach(e => rows.push([date, 'workflow', e.workflow_name || '', e.status || '']));\n  (data.health || []).forEach(h => rows.push([date, 'health', h.service || '', h.status || '']));\n} else {\n  rows.push([date, 'ERROR REPORT', `${data.error_count || 0} errors`, '']);\n  (data.errors || []).slice(0, 20).forEach(e => rows.push([date, 'error', e.substring(0, 200), '']));\n}\n\nreturn rows.map(r => ({ json: { date: r[0], type: r[1], detail: r[2], extra: r[3] } }));"
      },
      "name": "Format Data",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [440, 300]
    },
    {
      "parameters": {
        "operation": "append",
        "documentId": { "__rl": true, "mode": "id", "value": "CONFIGURE_SHEET_ID" },
        "sheetName": { "__rl": true, "mode": "name", "value": "Sheet1" },
        "columns": {
          "mappingMode": "autoMapInputData"
        },
        "options": {}
      },
      "name": "Google Sheets",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4.5,
      "position": [660, 300],
      "credentials": {
        "googleSheetsOAuth2Api": {
          "id": "CONFIGURE_IN_UI",
          "name": "Google Sheets account"
        }
      }
    },
    {
      "parameters": {
        "options": {
          "responseCode": 200
        },
        "respondWith": "json",
        "responseBody": "={{ JSON.stringify({ success: true, rows_written: $input.all().length, sheet_url: 'https://docs.google.com/spreadsheets/d/CONFIGURE_SHEET_ID' }) }}"
      },
      "name": "Respond",
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.1,
      "position": [880, 300]
    }
  ],
  "connections": {
    "Webhook": { "main": [[{ "node": "Format Data", "type": "main", "index": 0 }]] },
    "Format Data": { "main": [[{ "node": "Google Sheets", "type": "main", "index": 0 }]] },
    "Google Sheets": { "main": [[{ "node": "Respond", "type": "main", "index": 0 }]] }
  },
  "settings": { "executionOrder": "v1" }
}
```

**Step 3: Commit**

```bash
git add n8n-workflows/gmail-inbox-summary.json n8n-workflows/sheets-report.json
git commit -m "feat: add n8n workflow templates for Gmail and Google Sheets"
```

---

### Task 5: Deploy and test

**Step 1: Deploy changed files**

```bash
scp webhook-handler/handlers/commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
scp webhook-handler/handlers/github.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/github.py
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
```

**Step 2: Rebuild and restart webhook-handler**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml build --no-cache webhook-handler && docker compose -f docker-compose.unified.yml up -d webhook-handler"
```

**Step 3: Verify healthy**

```bash
ssh root@46.224.193.25 "docker logs webhook-handler 2>&1 | tail -5"
```

Expected: "Webhook handler ready on port 8086"

**Step 4: Import n8n workflow templates**

```bash
ssh root@46.224.193.25 "docker exec n8n n8n import:workflow --input=/home/node/.n8n/gmail-inbox-summary.json 2>&1 || echo 'Manual import needed'"
```

Or manually: Open n8n UI → Import from file → select the workflow JSON.

**Step 5: Test commands on Discord**

- `/aiui email` — should respond with "Gmail workflow not found" until n8n workflow is configured with Google OAuth
- `/aiui sheets daily` — should respond with "Sheets workflow not found" until configured
- `/aiui help` — should list new commands

**Step 6: Push to PR**

```bash
git push proxy-server fix/mcp-network-split
```

Create PR #11 with all changes.
