# Decision Engine Design

**Date:** 2026-04-10
**Status:** Approved
**Approach:** Add Decision Engine module to existing meeting container

## Problem

The meeting container extracts prioritized action items from transcripts, but they just sit in the summary. Lukas's vision: the AI should actually DO the work — research topics, build features, ask users for input, and connect integrations automatically.

## Goal

After AI extracts action items from a meeting transcript, a Decision Engine classifies each one and routes it to the right MCP tool for automatic execution.

## Architecture

### End-to-End Flow

```
Meeting → Fathom transcript → n8n → POST /meetings/
    → AI cleans transcript, extracts action items
    → Decision Engine classifies each action item
    → Auto-executes research (web-search → KB)
    → Posts build/integrate requests to Discord for approval
    → Asks user questions via Discord
    → Posts results to Discord
    → Everything saved to KB
```

### Decision Engine Flow

```
AI Summary (contains action items)
        ↓
Decision Engine parses action items
        ↓
For each action item, AI classifies:
        ↓
┌──────────────┬──────────────┬──────────────┬──────────────┐
│   RESEARCH   │    BUILD     │   ASK USER   │  INTEGRATE   │
│              │              │              │              │
│ Call         │ Post to      │ Send Discord │ Call MCP     │
│ web-search   │ Discord for  │ message      │ tools        │
│ MCP tool     │ approval     │ asking for   │ (calendar,   │
│ → save to KB │ then build   │ input        │ gmail, etc)  │
└──────────────┴──────────────┴──────────────┴──────────────┘
        ↓
Post status to Discord
```

### Action Type Routing

| Type | Detection Keywords | MCP Tool | Output | Permission |
|---|---|---|---|---|
| RESEARCH | research, compare, explore, investigate, look into | mcp-web-search → web_search + web_save_to_kb | Findings saved to KB, summary to Discord | Auto-execute |
| BUILD | build, create, implement, fix, add, deploy | claude-analyzer or webhook-handler | Plan/code posted to Discord | Needs approval |
| ASK_USER | ask, confirm, check with, clarify, which, decide | Discord message | User's answer | Always ask |
| INTEGRATE | integrate, connect, set up, configure, sync | mcp-calendar, mcp-gmail, mcp-trello, etc. | Integration result to Discord | Needs approval |

### Classification Prompt

The AI classifies each action item:

```
Given this action item: "{action item text}"
Classify as one of: RESEARCH, BUILD, ASK_USER, INTEGRATE

Return JSON:
{
  "type": "RESEARCH",
  "tool": "web-search",
  "query": "the search query to use",
  "assignee": "person name"
}
```

### Permission System

- **Auto-execute:** RESEARCH (safe — just searches and saves to KB)
- **Needs approval:** BUILD, INTEGRATE (posts to Discord first with approval request)
- **Always ask:** ASK_USER (by definition needs human input)

## Files Changed

| File | Change |
|---|---|
| `mcp-servers/meetings/decision_engine.py` | NEW — Parse action items, classify, route to MCP tools |
| `mcp-servers/meetings/main.py` | MODIFY — Add decision engine step after AI processing |

## Environment Variables

- `OPENWEBUI_URL` + `OPENWEBUI_API_KEY` — already configured (AI classification + KB)
- `DISCORD_WEBHOOK_URL` — new env var for posting results/approval requests

## Processing Order in Background Task

1. Save raw transcript to DB (instant, API returns 201)
2. AI process transcript → summary with action items (10-30 sec)
3. Decision Engine → classify + route each action item (10-60 sec per item)
4. Push to KB (30 sec)
5. Post results to Discord

## What Does NOT Get Built (YAGNI)

- No new container
- No new database tables
- No approval tracking database (Discord reactions for now)
- No retry/queue system (logs failures, moves on)
- No UI for managing decisions
