# Web Search → Knowledge Base MCP Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an MCP web search server that searches the web via Brave Search API, scrapes page content, and saves results to Open WebUI Knowledge Base — usable from both chat and n8n.

**Architecture:** New FastAPI MCP server at `mcp-servers/web-search/` with 3 tool endpoints. Uses Brave Search API for search, httpx+beautifulsoup4 for scraping, and Open WebUI KB API for saving. Registered in MCP proxy for chat access, callable via HTTP for n8n workflows.

**Tech Stack:** Python 3.11, FastAPI, httpx, beautifulsoup4, markdownify, Brave Search API

---

### Task 1: Create the MCP web search server

**Files:**
- Create: `mcp-servers/web-search/main.py`
- Create: `mcp-servers/web-search/requirements.txt`
- Create: `mcp-servers/web-search/Dockerfile`

**Step 1: Create requirements.txt**

```
fastapi==0.109.0
uvicorn==0.27.0
httpx==0.26.0
beautifulsoup4==4.12.3
markdownify==0.13.1
```

**Step 2: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Create main.py**

```python
"""MCP Web Search Server — Search, scrape, and save to Knowledge Base."""
import os
import re
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

logger = logging.getLogger(__name__)

app = FastAPI(title="MCP Web Search", version="1.0.0")

BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080")
OPENWEBUI_API_KEY = os.environ.get("OPENWEBUI_API_KEY", "")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


# ==================== Models ====================

class SearchRequest(BaseModel):
    query: str
    count: int = 5

class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str

class SearchResponse(BaseModel):
    results: list[SearchResult]

class ScrapeRequest(BaseModel):
    url: str

class ScrapeResponse(BaseModel):
    title: str
    url: str
    content_markdown: str
    word_count: int

class SaveToKBRequest(BaseModel):
    query: str
    kb_name: str = "Web Research"
    count: int = 3

class SaveToKBResponse(BaseModel):
    message: str
    kb_name: str
    files_saved: int
    sources: list[str]


# ==================== Helpers ====================

async def brave_search(query: str, count: int = 5) -> list[dict]:
    """Search the web using Brave Search API."""
    if not BRAVE_API_KEY:
        raise HTTPException(status_code=500, detail="BRAVE_SEARCH_API_KEY not configured")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            BRAVE_SEARCH_URL,
            params={"q": query, "count": count},
            headers={"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
        })
    return results[:count]


async def scrape_url(url: str) -> dict:
    """Fetch a URL and convert content to markdown."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AIUI-Bot/1.0)"
        })
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script, style, nav, footer, ads
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()

    # Get title
    title = soup.title.string.strip() if soup.title and soup.title.string else url

    # Find main content (try article, main, then body)
    main = soup.find("article") or soup.find("main") or soup.find("body")
    if not main:
        main = soup

    # Convert to markdown
    content = md(str(main), heading_style="ATX", strip=["img"])

    # Clean up excessive whitespace
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = content.strip()

    word_count = len(content.split())

    return {
        "title": title,
        "url": url,
        "content_markdown": content,
        "word_count": word_count,
    }


async def save_to_knowledge_base(title: str, content: str, kb_name: str) -> str:
    """Upload content as a file to Open WebUI Knowledge Base."""
    if not OPENWEBUI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENWEBUI_API_KEY not configured")

    headers = {"Authorization": f"Bearer {OPENWEBUI_API_KEY}"}
    base = OPENWEBUI_URL

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Find or create KB
        resp = await client.get(f"{base}/api/v1/knowledge/", headers=headers)
        resp.raise_for_status()
        kbs = resp.json()

        kb_id = None
        for kb in kbs:
            if kb.get("name") == kb_name:
                kb_id = kb.get("id")
                break

        if not kb_id:
            resp = await client.post(
                f"{base}/api/v1/knowledge/create",
                headers=headers,
                json={"name": kb_name, "description": f"Auto-created by web search scraper"},
            )
            resp.raise_for_status()
            kb_id = resp.json().get("id")

        # 2. Upload content as markdown file
        safe_title = re.sub(r"[^\w\s-]", "", title)[:80].strip()
        filename = f"{safe_title}.md"
        file_content = f"# {title}\n\n{content}"

        resp = await client.post(
            f"{base}/api/v1/files/",
            headers=headers,
            files={"file": (filename, file_content.encode(), "text/markdown")},
        )
        resp.raise_for_status()
        file_id = resp.json().get("id")

        # 3. Wait for processing
        for _ in range(10):
            resp = await client.get(
                f"{base}/api/v1/files/{file_id}/process/status",
                headers=headers,
            )
            if resp.status_code == 200:
                status = resp.json()
                if status.get("status") == "completed":
                    break
            import asyncio
            await asyncio.sleep(1)

        # 4. Add file to KB
        resp = await client.post(
            f"{base}/api/v1/knowledge/{kb_id}/file/add",
            headers=headers,
            json={"file_id": file_id},
        )
        resp.raise_for_status()

    return kb_id


# ==================== Endpoints ====================

@app.post("/web_search", response_model=SearchResponse)
async def web_search(req: SearchRequest):
    """Search the web using Brave Search. Returns titles, URLs, and snippets."""
    results = await brave_search(req.query, req.count)
    return {"results": results}


@app.post("/web_scrape", response_model=ScrapeResponse)
async def web_scrape(req: ScrapeRequest):
    """Fetch a URL and extract its content as markdown."""
    data = await scrape_url(req.url)
    return data


@app.post("/web_save_to_kb", response_model=SaveToKBResponse)
async def web_save_to_kb(req: SaveToKBRequest):
    """Search the web, scrape top results, and save to Open WebUI Knowledge Base."""
    # 1. Search
    results = await brave_search(req.query, req.count)
    if not results:
        raise HTTPException(status_code=404, detail="No search results found")

    # 2. Scrape and save each result
    sources = []
    files_saved = 0
    for result in results:
        try:
            scraped = await scrape_url(result["url"])
            if scraped["word_count"] < 50:
                continue  # Skip pages with too little content

            await save_to_knowledge_base(
                title=scraped["title"],
                content=scraped["content_markdown"],
                kb_name=req.kb_name,
            )
            sources.append(result["url"])
            files_saved += 1
        except Exception as e:
            logger.error(f"Failed to scrape {result['url']}: {e}")
            continue

    if files_saved == 0:
        raise HTTPException(status_code=500, detail="Failed to scrape any results")

    return {
        "message": f"Saved {files_saved} pages to '{req.kb_name}' knowledge base",
        "kb_name": req.kb_name,
        "files_saved": files_saved,
        "sources": sources,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "brave_configured": bool(BRAVE_API_KEY)}
```

---

### Task 2: Add to Docker Compose and MCP proxy config

**Files:**
- Modify: `docker-compose.unified.yml`
- Modify: `mcp-proxy/config/mcp-servers.json`

**Step 1: Add mcp-web-search service to docker-compose.unified.yml**

Add after the mcp-gmail service:

```yaml
  # ===========================================================================
  # MCP WEB SEARCH - Search, Scrape, Save to Knowledge Base
  # ===========================================================================
  mcp-web-search:
    build: ./mcp-servers/web-search
    container_name: mcp-web-search
    restart: unless-stopped
    environment:
      - BRAVE_SEARCH_API_KEY=${BRAVE_SEARCH_API_KEY:-}
      - OPENWEBUI_URL=http://open-webui:8080
      - OPENWEBUI_API_KEY=${OPENWEBUI_API_KEY:-}
    networks:
      - backend
    depends_on:
      - open-webui
    deploy:
      resources:
        limits:
          memory: 128M
```

**Step 2: Register in mcp-servers.json**

Add to the servers list in `mcp-proxy/config/mcp-servers.json`:

```json
{
  "name": "web-search",
  "type": "HTTP",
  "url": "http://mcp-web-search:8000",
  "description": "Search the web, scrape pages, save to Knowledge Base",
  "auth": { "type": "none" }
}
```

---

### Task 3: Get Brave Search API key and deploy

**Step 1: Get free Brave Search API key**

Go to https://brave.com/search/api/ → sign up → get free API key (2000 queries/month).

**Step 2: Add to server .env**

```bash
ssh root@46.224.193.25 "echo 'BRAVE_SEARCH_API_KEY=<your-key>' >> /root/proxy-server/.env"
```

**Step 3: SCP files to server**

```bash
scp -r mcp-servers/web-search root@46.224.193.25:/root/proxy-server/mcp-servers/web-search
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
scp mcp-proxy/config/mcp-servers.json root@46.224.193.25:/root/proxy-server/mcp-proxy/config/mcp-servers.json
```

**Step 4: Build and start**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build mcp-web-search && docker compose -f docker-compose.unified.yml restart mcp-proxy"
```

**Step 5: Test**

```bash
ssh root@46.224.193.25 "curl -s -X POST http://mcp-web-search:8000/web_search -H 'Content-Type: application/json' -d '{\"query\": \"Bitcoin price today\"}'"
```

Expected: JSON with search results.

**Step 6: Test in Open WebUI chat**

Type: "Search for Bitcoin price and save it to knowledge base"

The AI should call the web_search tool, then web_save_to_kb, and confirm it saved.

---

### Task 4: Create n8n scheduled workflow (optional)

**Step 1: Create n8n workflow**

In n8n dashboard, create a new workflow:

1. **Cron trigger** — daily at 9am
2. **HTTP Request node** — POST to `http://mcp-web-search:8000/web_save_to_kb` with body: `{"query": "Bitcoin price today", "kb_name": "Daily Market Data"}`
3. **Discord notification** — Post result to alert channel

This is a dashboard config, not code.
