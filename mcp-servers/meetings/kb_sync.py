"""Auto-push meeting records to OpenWebUI Knowledge Base."""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

KB_NAME = "Meeting Transcripts"
KB_DESCRIPTION = "Fathom meeting summaries with recording links. Auto-populated from team meetings."


def _kb_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def format_meeting_markdown(
    title: str,
    date: str,
    attendees: str | None,
    summary: str | None,
    transcript: str | None,
    fathom_link: str | None,
) -> str:
    """Format a meeting record as markdown for KB upload."""
    parts = [f"# {title}"]
    parts.append(f"Date: {date} | Attendees: {attendees or 'N/A'}")
    parts.append("")

    if summary:
        parts.append("## Summary")
        parts.append(summary)
        parts.append("")

    if transcript:
        parts.append("## Transcript")
        parts.append(transcript)
        parts.append("")

    parts.append("## Recording")
    parts.append(fathom_link if fathom_link else "No recording link available")

    return "\n".join(parts)


async def _get_or_create_kb(client: httpx.AsyncClient, api_key: str, openwebui_url: str) -> str:
    """Find or create the Meeting Transcripts KB. Returns KB id."""
    resp = await client.get(
        f"{openwebui_url}/api/v1/knowledge/",
        headers=_kb_headers(api_key),
    )
    resp.raise_for_status()

    data = resp.json()
    kbs = data.get("items", data) if isinstance(data, dict) else data
    for kb in kbs:
        if isinstance(kb, dict) and kb.get("name") == KB_NAME:
            return kb["id"]

    # Create new KB
    resp = await client.post(
        f"{openwebui_url}/api/v1/knowledge/create",
        headers={**_kb_headers(api_key), "Content-Type": "application/json"},
        json={"name": KB_NAME, "description": KB_DESCRIPTION},
    )
    resp.raise_for_status()
    kb_id = resp.json()["id"]
    logger.info(f"Created KB '{KB_NAME}' with id {kb_id}")
    return kb_id


async def push_to_kb(
    openwebui_url: str,
    api_key: str,
    filename: str,
    content: str,
) -> str | None:
    """Upload a meeting markdown file to OpenWebUI KB. Returns file_id or None on failure."""
    if not api_key:
        logger.warning("OPENWEBUI_API_KEY not set — skipping KB push")
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Get or create KB
            kb_id = await _get_or_create_kb(client, api_key, openwebui_url)

            # Upload file
            resp = await client.post(
                f"{openwebui_url}/api/v1/files/",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (filename, content.encode("utf-8"), "text/markdown")},
            )
            resp.raise_for_status()
            file_id = resp.json()["id"]

            # Poll for processing completion
            for _ in range(30):
                status_resp = await client.get(
                    f"{openwebui_url}/api/v1/files/{file_id}/process/status",
                    headers=_kb_headers(api_key),
                )
                if status_resp.is_success:
                    status = status_resp.json().get("status", "")
                    if status == "completed":
                        break
                await asyncio.sleep(2)

            # Add to KB
            resp = await client.post(
                f"{openwebui_url}/api/v1/knowledge/{kb_id}/file/add",
                headers={**_kb_headers(api_key), "Content-Type": "application/json"},
                json={"file_id": file_id},
            )
            resp.raise_for_status()

            logger.info(f"Pushed to KB: {filename} (file_id={file_id})")
            return file_id

    except Exception as exc:
        logger.error(f"KB push failed for {filename}: {exc}")
        return None
