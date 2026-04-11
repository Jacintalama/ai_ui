# Transcript AI Processing Design

**Date:** 2026-04-07
**Status:** Approved
**Approach:** AI processing inside meeting container (Approach A)

## Problem

The meeting container currently stores whatever n8n sends — either Clarence's manual summary or raw data. Lukas wants the raw Fathom transcript saved, then AI processes it to extract only work-relevant content, fix misspellings, and create prioritized action items.

## Goal

When a raw transcript is posted to the meeting container, AI automatically:
1. Fixes misspelled tech words ("cloud" → "Claude Code")
2. Filters out irrelevant talk (holidays, personal chat)
3. Generates a clean work-focused summary
4. Extracts and ranks action items by priority

## Architecture

### Data Flow

```
Clarence posts raw transcript in Trello MOM
    → n8n sends to POST /meetings/ (raw transcript)
    → Container saves raw to DB, returns 201 immediately
    → Background task: AI processes transcript via OpenWebUI chat API
    → Updates DB: summary + action_items filled with AI output
    → Pushes clean version to OpenWebUI KB
    → Searchable via chat
```

### Processing Order (Background Task)

1. Save raw to DB (instant, API returns 201)
2. Call OpenWebUI chat API with transcript + smart prompt (~10-30 sec)
3. Parse AI response → update summary + action_items in DB
4. Push processed markdown to KB (~30 sec)

### What Gets Stored

| Field | Content |
|---|---|
| `transcript` | Raw Fathom transcript (never modified) |
| `summary` | AI-generated clean summary (work-relevant only, fixed spelling) |
| `action_items` | AI-extracted prioritized list (Critical → Important → Nice-to-have) |
| `kb_file_id` | OpenWebUI KB file ID |

## AI Prompt Design

System prompt for the LLM:

```
You are a meeting transcript analyst for a software development team.

Given a raw meeting transcript, produce a structured analysis:

1. FIX MISSPELLINGS: Correct mispronounced tech words. Examples:
   - "cloud" (when referring to the AI tool) → "Claude Code"
   - "candy" (when referring to reverse proxy) → "Caddy"
   - Common tech terms that sound different when spoken

2. FILTER IRRELEVANT CONTENT: Skip personal chat, holidays, jokes, off-topic discussions. Only keep work-related discussion.

3. SUMMARY: Write a concise summary of work-related topics discussed. Focus on:
   - What is being built or planned
   - Technical decisions made
   - Problems identified and solutions proposed
   - Status updates on ongoing work

4. ACTION ITEMS: Extract and rank by priority:
   🔴 CRITICAL — Blocking work, needs immediate attention
   🟡 IMPORTANT — Needs to be done, assigned to someone
   🟢 NICE-TO-HAVE — Research, exploration, future consideration

   For each item include: WHO needs to do WHAT.

Return as JSON:
{
  "summary": "clean markdown summary",
  "action_items": "prioritized markdown list"
}
```

## Files Changed

| File | Change |
|---|---|
| `mcp-servers/meetings/ai_processor.py` | NEW — calls OpenWebUI chat API, parses response |
| `mcp-servers/meetings/main.py` | MODIFY — run AI processing before KB push in background task |
| `mcp-servers/meetings/kb_sync.py` | NO CHANGE |
| `mcp-servers/meetings/models.py` | NO CHANGE |

## What Does NOT Get Built (YAGNI)

- No re-processing endpoint (add later if needed)
- No prompt configuration UI
- No model selection per meeting
- No separate "processed" vs "raw" fields — summary/action_items ARE the processed output
