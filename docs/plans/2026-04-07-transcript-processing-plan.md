# Transcript AI Processing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add AI processing to the meeting container so raw transcripts are automatically cleaned, summarized, and have action items extracted and prioritized.

**Architecture:** When a meeting is POSTed with a transcript, a background task calls OpenWebUI's chat API (gpt-4-turbo) to process the raw transcript into a clean summary + prioritized action items, saves the result to DB, then pushes the processed version to KB.

**Tech Stack:** Python 3.11, FastAPI, httpx, OpenWebUI chat API (gpt-4-turbo)

---

### Task 1: Create ai_processor.py

**Files:**
- Create: `mcp-servers/meetings/ai_processor.py`

**Step 1: Create the AI processor module**

Create `mcp-servers/meetings/ai_processor.py`:

```python
"""AI transcript processor — calls OpenWebUI chat API to clean and analyze meeting transcripts."""
import json
import logging

import httpx

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a meeting transcript analyst for a software development team (AIUI).

Given a raw meeting transcript, produce a structured analysis.

RULES:
1. FIX MISSPELLINGS: Correct mispronounced tech words. Common fixes:
   - "cloud" (when referring to the AI tool) → "Claude" or "Claude Code"
   - "candy" (when referring to reverse proxy) → "Caddy"
   - "eleven labs" / "11 labs" → "ElevenLabs"
   - "open web UI" → "Open WebUI"
   - Any tech term that sounds wrong when spoken — fix to correct spelling

2. FILTER IRRELEVANT CONTENT: Skip entirely:
   - Personal chat (holidays, trips, hobbies, jokes)
   - Small talk and greetings
   - Off-topic discussions not related to work
   Only keep discussion about building, planning, debugging, researching, or deciding on technical work.

3. SUMMARY: Write a concise summary of work-related topics discussed. Focus on:
   - What is being built or planned
   - Technical decisions made
   - Problems identified and solutions proposed
   - Status updates on ongoing work

4. ACTION ITEMS: Extract and rank by priority with assignee:
   🔴 CRITICAL — Blocking work, needs immediate attention
   🟡 IMPORTANT — Needs to be done soon, assigned to someone
   🟢 NICE-TO-HAVE — Research, exploration, future consideration

   Format each item as: "- [PRIORITY] **[Person]**: [What they need to do]"

You MUST return valid JSON with exactly these two keys:
{
  "summary": "markdown formatted summary",
  "action_items": "markdown formatted prioritized list"
}

Return ONLY the JSON object, no other text."""


async def process_transcript(
    openwebui_url: str,
    api_key: str,
    transcript: str,
    title: str = "",
    model: str = "gpt-4-turbo",
) -> dict | None:
    """Process a raw transcript through OpenWebUI chat API.

    Returns {"summary": "...", "action_items": "..."} or None on failure.
    """
    if not api_key:
        logger.warning("OPENWEBUI_API_KEY not set — skipping AI processing")
        return None

    if not transcript or len(transcript.strip()) < 50:
        logger.info("Transcript too short for AI processing, skipping")
        return None

    user_message = f"Meeting: {title}\n\nRaw Transcript:\n{transcript}"

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
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Parse JSON from response — handle markdown code blocks
        content = content.strip()
        if content.startswith("```"):
            # Remove ```json and ``` wrapping
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        result = json.loads(content)

        if "summary" not in result or "action_items" not in result:
            logger.error(f"AI response missing required keys: {list(result.keys())}")
            return None

        logger.info(f"AI processing complete for '{title}'")
        return result

    except json.JSONDecodeError as exc:
        logger.error(f"AI returned invalid JSON for '{title}': {exc}")
        logger.debug(f"Raw AI response: {content[:500]}")
        return None
    except Exception as exc:
        logger.error(f"AI processing failed for '{title}': {exc}")
        return None
```

**Step 2: Commit**

```bash
git add mcp-servers/meetings/ai_processor.py
git commit -m "feat: add AI transcript processor for meeting analysis"
```

---

### Task 2: Wire AI processing into the background task

**Files:**
- Modify: `mcp-servers/meetings/main.py:13-14,83-108`

**Step 1: Add import**

In `mcp-servers/meetings/main.py`, after line 14 (`from kb_sync import ...`), add:

```python
from ai_processor import process_transcript
```

**Step 2: Update _push_meeting_to_kb to run AI processing first**

Replace the entire `_push_meeting_to_kb` function (lines 83-108) with:

```python
async def _process_and_push(record: MeetingRecord):
    """Background task: AI process transcript, update DB, then push to KB."""
    # Step 1: AI process transcript if it exists and summary is empty
    if record.transcript and len(record.transcript.strip()) > 50 and not record.summary:
        logger.info(f"AI processing transcript for '{record.title}'...")
        result = await process_transcript(
            openwebui_url=OPENWEBUI_URL,
            api_key=OPENWEBUI_API_KEY,
            transcript=record.transcript,
            title=record.title,
        )

        if result and _session_maker:
            async with _session_maker() as session:
                db_record = await session.execute(
                    select(MeetingRecord).where(MeetingRecord.id == record.id)
                )
                rec = db_record.scalar_one_or_none()
                if rec:
                    rec.summary = result["summary"]
                    rec.action_items = result["action_items"]
                    await session.commit()
                    await session.refresh(rec)
                    # Use updated record for KB push
                    record = rec
                    logger.info(f"AI output saved for '{record.title}'")

    # Step 2: Push to KB (uses AI-processed summary if available)
    content = format_meeting_markdown(
        title=record.title,
        date=str(record.date),
        attendees=record.attendees,
        summary=record.summary,
        action_items=record.action_items,
        transcript=record.transcript,
        fathom_link=record.fathom_link,
    )
    slug = record.title.lower().replace(" ", "-")[:50]
    date_slug = record.date[:10] if len(record.date) >= 10 else record.date
    filename = f"meeting-{date_slug}-{slug}.md"

    file_id = await push_to_kb(OPENWEBUI_URL, OPENWEBUI_API_KEY, filename, content)

    if file_id and _session_maker:
        async with _session_maker() as session:
            result = await session.execute(
                select(MeetingRecord).where(MeetingRecord.id == record.id)
            )
            rec = result.scalar_one_or_none()
            if rec:
                rec.kb_file_id = file_id
                await session.commit()
```

**Step 3: Update references from _push_meeting_to_kb to _process_and_push**

In `create_meeting` (line 156), change:
```python
    asyncio.create_task(_push_meeting_to_kb(record))
```
to:
```python
    asyncio.create_task(_process_and_push(record))
```

In `update_meeting` (line 235), change:
```python
    asyncio.create_task(_push_meeting_to_kb(record))
```
to:
```python
    asyncio.create_task(_process_and_push(record))
```

**Step 4: Commit**

```bash
git add mcp-servers/meetings/main.py
git commit -m "feat: wire AI transcript processing into meeting save flow"
```

---

### Task 3: Deploy and test

**Step 1: SCP files to server**

```bash
scp mcp-servers/meetings/ai_processor.py mcp-servers/meetings/main.py root@46.224.193.25:/root/proxy-server/mcp-servers/meetings/
```

**Step 2: Rebuild and restart**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build mcp-meetings"
```

**Step 3: Test with a raw transcript**

```bash
curl -X POST https://ai-ui.coolestdomain.win/meetings/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "AI Processing Test",
    "date": "April 7, 2026",
    "attendees": "Lukas, Ralph, Jacint",
    "transcript": "So yeah the cloud code thing is working now. I fixed the candy file to route the meetings. Ralph you need to fix the eleven labs voice thing it is still not working in tagalog. Also we should go to boracay next month that would be fun. Jacint can you research how to make the proxy server faster. Oh and we talked about getting pizza for lunch tomorrow.",
    "fathom_link": null
  }'
```

Expected: Returns 201 with `summary: null` (processing happens async).

**Step 4: Wait 30 seconds, then verify**

```bash
curl -s https://ai-ui.coolestdomain.win/meetings/?search=AI+Processing+Test
```

Expected:
- `summary` filled with clean work-related summary (no Boracay, no pizza)
- `action_items` with prioritized list (Ralph: fix ElevenLabs, Jacint: research proxy)
- `kb_file_id` populated
- Misspellings fixed: "cloud code" → "Claude Code", "candy" → "Caddy", "eleven labs" → "ElevenLabs"

**Step 5: Check logs**

```bash
ssh root@46.224.193.25 "docker compose -f /root/proxy-server/docker-compose.unified.yml logs --tail=20 mcp-meetings"
```

Expected: "AI processing complete" and "Pushed to KB" messages.
