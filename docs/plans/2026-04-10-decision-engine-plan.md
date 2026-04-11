# Decision Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Decision Engine that classifies action items from meeting transcripts and auto-routes them to the right MCP tool (web-search for research, Discord for approval/questions, claude-analyzer for builds).

**Architecture:** New `decision_engine.py` module in the existing meeting container. After AI processing extracts action items in the summary, the Decision Engine parses them, classifies each one (RESEARCH/BUILD/ASK_USER/INTEGRATE), and routes to the appropriate MCP tool. Research auto-executes, build/integrate need Discord approval, ask-user always prompts.

**Tech Stack:** Python 3.11, httpx, OpenWebUI chat API (for classification), Discord webhook (for notifications/approvals)

---

### Task 1: Create decision_engine.py — classification logic

**Files:**
- Create: `mcp-servers/meetings/decision_engine.py`

**Step 1: Create the decision engine module**

Create `mcp-servers/meetings/decision_engine.py`:

```python
"""Decision Engine — classifies action items and routes to MCP tools."""
import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """You are an action item classifier for a software development team.

Given a meeting summary that contains action items, extract each action item and classify it.

For EACH action item, determine:
1. **type**: One of RESEARCH, BUILD, ASK_USER, INTEGRATE
   - RESEARCH: Needs web search, comparison, investigation (e.g. "compare pricing", "look into alternatives", "research how to...")
   - BUILD: Needs code changes, new features, fixes, deployment (e.g. "implement", "fix", "create", "add", "deploy")
   - ASK_USER: Needs human input, clarification, decision (e.g. "ask about", "confirm with", "check which", "decide on")
   - INTEGRATE: Needs API connection, service setup, tool configuration (e.g. "connect to", "set up", "integrate", "sync with")

2. **assignee**: Who needs to do it (person name, or "team" if unspecified)
3. **description**: What needs to be done (clean, concise)
4. **query**: For RESEARCH — the search query. For others — short description of the action.
5. **priority**: CRITICAL, IMPORTANT, or NICE_TO_HAVE

Return a JSON array:
[
  {"type": "RESEARCH", "assignee": "Lukas", "description": "Compare Gemini vs ElevenLabs pricing for voice bot", "query": "Gemini Live API vs ElevenLabs pricing comparison 2026", "priority": "IMPORTANT"},
  {"type": "BUILD", "assignee": "Jacint", "description": "Fix Caddy routing for meetings container", "query": "Fix Caddy routing", "priority": "CRITICAL"}
]

If no action items found, return an empty array: []

Return ONLY the JSON array, no other text."""


async def classify_action_items(
    openwebui_url: str,
    api_key: str,
    summary: str,
    title: str = "",
    model: str = "gpt-4-turbo",
) -> list[dict] | None:
    """Classify action items from a meeting summary.

    Returns list of classified action items or None on failure.
    """
    if not api_key:
        logger.warning("OPENWEBUI_API_KEY not set — skipping classification")
        return None

    if not summary or len(summary.strip()) < 30:
        logger.info("Summary too short for classification, skipping")
        return None

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{openwebui_url}/api/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": CLASSIFICATION_PROMPT},
                        {"role": "user", "content": f"Meeting: {title}\n\nSummary:\n{summary}"},
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        items = json.loads(content)

        if not isinstance(items, list):
            logger.error(f"AI returned non-list for '{title}': {type(items)}")
            return None

        logger.info(f"Classified {len(items)} action items for '{title}'")
        return items

    except json.JSONDecodeError as exc:
        logger.error(f"AI returned invalid JSON for classification '{title}': {exc}")
        return None
    except Exception as exc:
        logger.error(f"Classification failed for '{title}': {exc}")
        return None


async def execute_research(
    openwebui_url: str,
    api_key: str,
    query: str,
    description: str,
) -> str | None:
    """Execute a RESEARCH action item — search web and save to KB."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Call web-search MCP tool via the meetings container's network
            resp = await client.post(
                f"{openwebui_url.replace('open-webui:8080', 'mcp-web-search:8000')}/web_search",
                headers={"Content-Type": "application/json"},
                json={"query": query, "count": 5},
            )
            if resp.is_success:
                logger.info(f"Research completed: {description}")
                return resp.text[:500]
            else:
                logger.warning(f"Research search failed ({resp.status_code}): {description}")
                return None
    except Exception as exc:
        logger.error(f"Research execution failed: {exc}")
        return None


async def post_to_discord(
    webhook_url: str,
    message: str,
) -> bool:
    """Post a message to Discord via webhook."""
    if not webhook_url:
        logger.warning("DISCORD_WEBHOOK_URL not set — skipping Discord post")
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                webhook_url,
                json={"content": message[:2000]},
            )
            return resp.is_success
    except Exception as exc:
        logger.error(f"Discord post failed: {exc}")
        return False


async def process_action_items(
    openwebui_url: str,
    api_key: str,
    discord_webhook_url: str,
    summary: str,
    title: str = "",
) -> dict:
    """Full pipeline: classify action items then route each one.

    Returns {"processed": N, "results": [...]}
    """
    items = await classify_action_items(openwebui_url, api_key, summary, title)

    if not items:
        return {"processed": 0, "results": []}

    results = []

    for item in items:
        item_type = item.get("type", "UNKNOWN")
        assignee = item.get("assignee", "team")
        description = item.get("description", "")
        query = item.get("query", description)
        priority = item.get("priority", "IMPORTANT")

        emoji = {"CRITICAL": "🔴", "IMPORTANT": "🟡", "NICE_TO_HAVE": "🟢"}.get(priority, "⚪")

        if item_type == "RESEARCH":
            # Auto-execute: search and report
            research_result = await execute_research(openwebui_url, api_key, query, description)
            status = "✅ Researched" if research_result else "⚠️ Research failed"
            await post_to_discord(
                discord_webhook_url,
                f"{emoji} **{status}** — {description}\nAssignee: {assignee}\nQuery: {query}"
            )
            results.append({"item": description, "type": "RESEARCH", "status": "done" if research_result else "failed"})

        elif item_type == "BUILD":
            # Needs approval: post to Discord
            await post_to_discord(
                discord_webhook_url,
                f"{emoji} **🔨 BUILD REQUEST** — {description}\nAssignee: {assignee}\n\n*This requires code changes. Review and action manually or via Claude Code.*"
            )
            results.append({"item": description, "type": "BUILD", "status": "posted_for_approval"})

        elif item_type == "ASK_USER":
            # Always ask: post question to Discord
            await post_to_discord(
                discord_webhook_url,
                f"{emoji} **❓ INPUT NEEDED** — {description}\nAssignee: {assignee}\n\n*Please respond in this channel.*"
            )
            results.append({"item": description, "type": "ASK_USER", "status": "asked"})

        elif item_type == "INTEGRATE":
            # Needs approval: post to Discord
            await post_to_discord(
                discord_webhook_url,
                f"{emoji} **🔗 INTEGRATION REQUEST** — {description}\nAssignee: {assignee}\n\n*This requires connecting to an external service. Review and action manually.*"
            )
            results.append({"item": description, "type": "INTEGRATE", "status": "posted_for_approval"})

        else:
            logger.warning(f"Unknown action type '{item_type}' for: {description}")
            results.append({"item": description, "type": item_type, "status": "skipped"})

    # Post summary to Discord
    total = len(results)
    done = sum(1 for r in results if r["status"] == "done")
    pending = total - done
    await post_to_discord(
        discord_webhook_url,
        f"📋 **Meeting: {title}**\nAction items processed: {total}\n✅ Auto-completed: {done}\n⏳ Pending approval/input: {pending}"
    )

    logger.info(f"Decision engine processed {total} items for '{title}' ({done} done, {pending} pending)")
    return {"processed": total, "results": results}
```

**Step 2: Commit**

```bash
git add mcp-servers/meetings/decision_engine.py
git commit -m "feat: add decision engine for action item classification and routing"
```

---

### Task 2: Wire Decision Engine into main.py

**Files:**
- Modify: `mcp-servers/meetings/main.py:15,82-129`

**Step 1: Add import and env var**

After line 15 (`from ai_processor import process_transcript`), add:

```python
from decision_engine import process_action_items
```

After line 22 (`OPENWEBUI_API_KEY = ...`), add:

```python
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
```

**Step 2: Add decision engine step to _process_and_push**

In the `_process_and_push` function, after the AI processing saves the summary (after line 103 `logger.info(f"AI output saved for '{record.title}'")`), add:

```python
    # Step 2: Decision Engine — classify and route action items
    if record.summary:
        logger.info(f"Running decision engine for '{record.title}'...")
        await process_action_items(
            openwebui_url=OPENWEBUI_URL,
            api_key=OPENWEBUI_API_KEY,
            discord_webhook_url=DISCORD_WEBHOOK_URL,
            summary=record.summary,
            title=record.title,
        )
```

**Step 3: Commit**

```bash
git add mcp-servers/meetings/main.py
git commit -m "feat: wire decision engine into meeting processing pipeline"
```

---

### Task 3: Add Discord webhook URL to docker-compose

**Files:**
- Modify: `docker-compose.unified.yml`

**Step 1: Add DISCORD_WEBHOOK_URL to mcp-meetings service**

In the `mcp-meetings` service environment section, add:

```yaml
      - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL:-}
```

**Step 2: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: add DISCORD_WEBHOOK_URL to mcp-meetings service"
```

---

### Task 4: Deploy and test

**Step 1: Set up Discord webhook**

Create a webhook in your Discord server:
- Go to Discord channel settings → Integrations → Webhooks → New Webhook
- Copy the webhook URL

Add to server `.env`:
```bash
ssh root@46.224.193.25
echo 'DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN' >> /root/proxy-server/.env
```

**Step 2: SCP files to server**

```bash
scp mcp-servers/meetings/decision_engine.py mcp-servers/meetings/main.py root@46.224.193.25:/root/proxy-server/mcp-servers/meetings/
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
```

**Step 3: Rebuild and restart**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build mcp-meetings"
```

**Step 4: Test with a transcript containing mixed action items**

```bash
curl -X POST https://ai-ui.coolestdomain.win/meetings/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Decision Engine Test",
    "date": "April 10, 2026",
    "attendees": "Lukas, Ralph, Jacint",
    "transcript": "So we need to research if Gemini Live API is cheaper than ElevenLabs for the voice bot. Ralph can you build a new endpoint for the Trello weekly summary. Also Jacint which calendar service are you using so we can integrate it. And Lukas wants to look into connecting our system with Todoist for task management."
  }'
```

**Step 5: Check Discord for messages**

Expected Discord messages:
- 🟡 **✅ Researched** — Compare Gemini Live API vs ElevenLabs pricing
- 🟡 **🔨 BUILD REQUEST** — Build Trello weekly summary endpoint
- 🟡 **❓ INPUT NEEDED** — Which calendar service is Jacint using
- 🟢 **🔗 INTEGRATION REQUEST** — Connect system with Todoist
- 📋 **Meeting: Decision Engine Test** — Action items processed: 4

**Step 6: Check container logs**

```bash
ssh root@46.224.193.25 "docker compose -f /root/proxy-server/docker-compose.unified.yml logs --tail=20 mcp-meetings"
```

Expected: "Classified 4 action items" and "Decision engine processed 4 items"
