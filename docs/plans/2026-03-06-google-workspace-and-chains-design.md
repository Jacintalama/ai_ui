# Google Workspace Automation & End-to-End Chains - Design

**Date:** 2026-03-06
**Status:** Approved

## Problem

Individual features (PR review, monitoring, codebase analysis) work standalone but aren't connected. Lukas wants end-to-end chains: "n8n → MCP → WebUI → proxy → n8n." Also needs Google Workspace automation (email → Google Sheets).

## Solution

1. Add Google Workspace automation via n8n workflows (Gmail + Sheets) with Discord commands
2. Connect Alert → Diagnose → Fix chain (Grafana → Loki → GitHub MCP → AI → Discord)
3. Connect PR → Full Analysis chain (PR diff + codebase context + error history → enriched review)

---

## Part 1: Google Workspace Automation

### Architecture

n8n workflows handle Google API auth (built-in OAuth flow). Webhook-handler triggers workflows via `/aiui email` and `/aiui sheets` commands. No Google API credentials in .env needed — auth is managed through n8n UI.

### Flow — Email Summary

```
User: /aiui email
  → webhook-handler triggers n8n "gmail-inbox-summary" workflow
  → n8n: Gmail node reads last 10 unread emails
  → n8n: HTTP node sends to Open WebUI AI for summarization
  → n8n: Returns summary JSON
  → webhook-handler: Posts summary to Discord
```

### Flow — Sheets Report

```
User: /aiui sheets [daily|errors]
  → webhook-handler triggers n8n "sheets-report" workflow
  → n8n: Fetch data (GitHub commits, n8n executions, service health)
  → n8n: Write rows to Google Sheet
  → n8n: Returns sheet URL + row count
  → webhook-handler: Posts confirmation + link to Discord
```

### Setup

1. Open n8n UI (admin@coolestdomain.win / N8nAdmin2026)
2. Create workflows with Gmail/Sheets nodes
3. Authenticate with Google via n8n's OAuth flow (click "Connect")
4. Activate workflows

### Commands

- `/aiui email` — Summarize recent unread emails
- `/aiui sheets [daily|errors]` — Generate report and write to Google Sheet

---

## Part 2: Alert → Diagnose → Fix Chain

### Architecture

Extend existing Grafana alert handler. Currently stops at "AI diagnosis of logs." New steps fetch actual source code from errors and provide code-level fix suggestions.

### Flow

```
Grafana alert fires (FIRING)
  → Step 1: Post alert to Discord (EXISTS)
  → Step 2: Query Loki for error logs (EXISTS)
  → Step 3: AI diagnosis of logs (EXISTS)
  → Step 4: Extract file/module names from error logs (NEW)
  → Step 5: Fetch those files via GitHub MCP / mcp-proxy (NEW)
  → Step 6: AI root cause analysis with code context (NEW)
  → Step 7: Post full report to Discord (NEW - enriched format)
```

### Output Format

```
🚨 Alert: [name]
📋 Errors: [log summary]
🔍 Root Cause: [AI analysis with actual code context]
🔧 Suggested Fix: [specific code changes referencing actual files]
```

### Changes

- Modify: `webhook-handler/main.py` (grafana_alerts_webhook function)
- Add: `_extract_file_references(logs)` helper to parse file paths from stack traces
- Add: MCP proxy call to fetch source files referenced in errors
- Add: Enhanced AI prompt that includes code context

---

## Part 3: PR → Full Analysis Chain

### Architecture

Extend existing PR review handler. Currently only reviews the diff. New steps add codebase context and error history for changed components.

### Flow

```
GitHub PR opened/updated
  → Step 1: Discord notification (EXISTS)
  → Step 2: Fetch PR diff (EXISTS)
  → Step 3: AI review of diff (EXISTS)
  → Step 4: Codebase analysis on changed files' parent dirs (NEW)
  → Step 5: Query Loki for errors related to changed components (NEW)
  → Step 6: Combined AI review with full context (NEW)
  → Step 7: Post enriched review to GitHub + Discord (NEW)
```

### Output Format

```
🔍 AI Review for PR #N: [title]

**Code Review:** [diff analysis]
**Codebase Context:** [what this code does in the broader system]
**Risk Assessment:** [recent errors in affected components]
**Recommendation:** [merge / fix / investigate]
```

### Changes

- Modify: `webhook-handler/handlers/github.py` (_handle_pull_request_event)
- Modify: `webhook-handler/clients/openwebui.py` (enhanced PR analysis prompt)
- Add: Loki query for errors related to changed file paths/services
- Add: GitHub API call for file tree context around changed files

---

## Error Handling

- If n8n Google workflows aren't set up yet, respond "Gmail/Sheets workflow not configured in n8n"
- If GitHub MCP or Loki is unreachable in chains, skip that step and proceed with available data
- If chain enhancement fails, fall back to existing behavior (existing features still work)
- All chain steps are additive — failure in new steps doesn't break existing functionality

## Memory Considerations

- Server has 3.8GB RAM, currently ~840MB available
- No new containers needed — all changes are in webhook-handler code + n8n workflows
- n8n workflows execute on-demand, not persistent memory cost
