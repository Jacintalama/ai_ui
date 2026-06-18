import os
import asyncio
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from url_guard import safe_get, UnsafeURLError

logger = logging.getLogger(__name__)

app = FastAPI(title="MCP Web Search Server")

BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080")
OPENWEBUI_API_KEY = os.environ.get("OPENWEBUI_API_KEY", "")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class WebSearchRequest(BaseModel):
    query: str
    count: int = 5


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchResponse(BaseModel):
    results: list[SearchResult]


class WebScrapeRequest(BaseModel):
    url: str


class WebScrapeResponse(BaseModel):
    title: str
    url: str
    content_markdown: str
    word_count: int


class WebSaveToKBRequest(BaseModel):
    query: str
    kb_name: str = "Web Research"
    count: int = 3


class WebSaveToKBResponse(BaseModel):
    kb_id: str
    files_saved: int
    results: list[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _brave_search(query: str, count: int) -> list[SearchResult]:
    """Call the Brave Search API and return a list of SearchResult."""
    if not BRAVE_SEARCH_API_KEY:
        raise HTTPException(status_code=500, detail="BRAVE_SEARCH_API_KEY is not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
                },
                params={"q": query, "count": count},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Brave Search API error: {exc.response.text}",
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Brave Search request failed: {exc}")

    data = resp.json()
    web_results = data.get("web", {}).get("results", [])

    return [
        SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            snippet=r.get("description", ""),
        )
        for r in web_results[:count]
    ]


async def _scrape_url(url: str) -> WebScrapeResponse:
    """Fetch a URL, strip boilerplate, and return markdown content."""
    # SSRF guard: reject private/loopback/link-local/metadata targets — and
    # re-validate every redirect hop (follow_redirects=True would have let a
    # public URL redirect into the internal network).
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await safe_get(
                client,
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                },
            )
            resp.raise_for_status()
        except UnsafeURLError as exc:
            raise HTTPException(status_code=400, detail=f"Unsafe URL: {exc}")
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Failed to fetch URL: {exc.response.status_code}",
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Request to URL failed: {exc}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url

    # Try to find main content area
    main_content = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", {"role": "main"})
        or soup.find("div", class_="content")
        or soup.body
        or soup
    )

    content_markdown = md(str(main_content), strip=["img"]).strip()

    # Clean up excessive whitespace
    lines = [line.rstrip() for line in content_markdown.splitlines()]
    cleaned = "\n".join(lines)
    # Collapse runs of 3+ blank lines into 2
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")

    word_count = len(cleaned.split())

    return WebScrapeResponse(
        title=title,
        url=url,
        content_markdown=cleaned,
        word_count=word_count,
    )


def _kb_headers() -> dict[str, str]:
    """Return authorization headers for the Open WebUI KB API."""
    return {
        "Authorization": f"Bearer {OPENWEBUI_API_KEY}",
        "Accept": "application/json",
    }


async def _get_or_create_kb(client: httpx.AsyncClient, kb_name: str) -> str:
    """Find an existing Knowledge Base by name or create a new one. Returns the KB id."""
    # List existing KBs
    try:
        resp = await client.get(
            f"{OPENWEBUI_URL}/api/v1/knowledge/",
            headers=_kb_headers(),
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to list knowledge bases: {exc}")

    data = resp.json()
    # API returns {"items": [...]} or a flat list
    kbs = data.get("items", data) if isinstance(data, dict) else data
    for kb in kbs:
        if isinstance(kb, dict) and kb.get("name") == kb_name:
            return kb["id"]

    # Create new KB
    try:
        resp = await client.post(
            f"{OPENWEBUI_URL}/api/v1/knowledge/create",
            headers={**_kb_headers(), "Content-Type": "application/json"},
            json={"name": kb_name, "description": f"Auto-created KB for web research"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to create knowledge base: {exc}")

    return resp.json()["id"]


async def _upload_file_to_kb(
    client: httpx.AsyncClient,
    kb_id: str,
    filename: str,
    content: str,
) -> dict:
    """Upload a markdown file to Open WebUI, wait for processing, then add to KB."""
    # Upload file
    try:
        resp = await client.post(
            f"{OPENWEBUI_URL}/api/v1/files/",
            headers={"Authorization": f"Bearer {OPENWEBUI_API_KEY}"},
            files={"file": (filename, content.encode("utf-8"), "text/markdown")},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to upload file: {exc}")

    file_data = resp.json()
    file_id = file_data["id"]

    # Poll for processing completion
    for _ in range(30):
        try:
            status_resp = await client.get(
                f"{OPENWEBUI_URL}/api/v1/files/{file_id}/process/status",
                headers=_kb_headers(),
            )
            status_resp.raise_for_status()
            status = status_resp.json().get("status", "")
            if status == "completed":
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)

    # Add file to KB
    try:
        resp = await client.post(
            f"{OPENWEBUI_URL}/api/v1/knowledge/{kb_id}/file/add",
            headers={**_kb_headers(), "Content-Type": "application/json"},
            json={"file_id": file_id},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to add file to KB: {exc}")

    return {"file_id": file_id, "filename": filename}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/web_search", response_model=WebSearchResponse)
async def web_search(req: WebSearchRequest) -> WebSearchResponse:
    """Search the web using the Brave Search API."""
    results = await _brave_search(req.query, req.count)
    return WebSearchResponse(results=results)


@app.post("/web_scrape", response_model=WebScrapeResponse)
async def web_scrape(req: WebScrapeRequest) -> WebScrapeResponse:
    """Scrape a URL and return clean markdown content."""
    return await _scrape_url(req.url)


@app.post("/web_save_to_kb", response_model=WebSaveToKBResponse)
async def web_save_to_kb(req: WebSaveToKBRequest) -> WebSaveToKBResponse:
    """Search, scrape top results, and save each to an Open WebUI Knowledge Base."""
    if not OPENWEBUI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENWEBUI_API_KEY is not configured")

    # 1. Search
    search_results = await _brave_search(req.query, req.count)
    if not search_results:
        raise HTTPException(status_code=404, detail="No search results found")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 2. Get or create KB
        kb_id = await _get_or_create_kb(client, req.kb_name)

        # 3. Scrape and upload each result
        saved: list[dict] = []
        for result in search_results:
            try:
                scraped = await _scrape_url(result.url)
            except HTTPException:
                logger.warning("Failed to scrape %s, skipping", result.url)
                continue

            # Build a clean filename from the title
            safe_title = "".join(
                c if c.isalnum() or c in (" ", "-", "_") else "_"
                for c in scraped.title[:80]
            ).strip()
            filename = f"{safe_title}.md"

            # Compose file content with metadata header
            file_content = (
                f"# {scraped.title}\n\n"
                f"**Source:** {scraped.url}\n"
                f"**Query:** {req.query}\n\n"
                f"---\n\n"
                f"{scraped.content_markdown}"
            )

            try:
                file_info = await _upload_file_to_kb(client, kb_id, filename, file_content)
                saved.append({
                    "title": scraped.title,
                    "url": scraped.url,
                    "word_count": scraped.word_count,
                    **file_info,
                })
            except HTTPException:
                logger.warning("Failed to save %s to KB, skipping", result.url)
                continue

    return WebSaveToKBResponse(kb_id=kb_id, files_saved=len(saved), results=saved)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "brave_configured": bool(BRAVE_SEARCH_API_KEY),
    }
