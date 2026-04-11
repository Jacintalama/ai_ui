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

3. SUMMARY: Write a concise markdown summary that includes:
   - What is being built or planned
   - Technical decisions made
   - Problems identified and solutions proposed
   - Status updates on ongoing work

   At the end of the summary, include an "## Action Items" section with prioritized items:
   🔴 CRITICAL — Blocking work, needs immediate attention
   🟡 IMPORTANT — Needs to be done soon, assigned to someone
   🟢 NICE-TO-HAVE — Research, exploration, future consideration
   Format each item as: "- [PRIORITY] **[Person]**: [What they need to do]"

You MUST return valid JSON with exactly this key:
{
  "summary": "markdown formatted summary including action items at the end"
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

    Returns {"summary": "..."} or None on failure.
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
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        result = json.loads(content)

        if "summary" not in result:
            logger.error(f"AI response missing 'summary' key: {list(result.keys())}")
            return None

        logger.info(f"AI processing complete for '{title}'")
        return result

    except json.JSONDecodeError as exc:
        logger.error(f"AI returned invalid JSON for '{title}': {exc}")
        return None
    except Exception as exc:
        logger.error(f"AI processing failed for '{title}': {exc}")
        return None
