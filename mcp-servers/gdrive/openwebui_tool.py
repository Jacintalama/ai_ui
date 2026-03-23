"""
title: Google Drive
author: AIUI Team
version: 0.1.0
description: Browse, search, and read files from your Google Drive. Connect your Drive account to get started.
"""

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        gdrive_url: str = Field(
            default="http://mcp-gdrive:8000",
            description="Google Drive MCP Server URL",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def list_google_drive_files(
        self, folder_id: str = "root", __user__: dict = {}
    ) -> str:
        """
        List files in your Google Drive. Shows file names, types, and IDs.
        Use folder_id='root' for top-level files or provide a folder ID to browse into a folder.
        """
        user_email = __user__.get("email", "default@local")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.valves.gdrive_url}/gdrive_list_files",
                json={"folder_id": folder_id, "page_size": 20},
                headers={"X-User-Email": user_email},
                timeout=30.0,
            )
            data = resp.json()
            if "error" in data:
                return data["error"]
            files = data.get("files", [])
            if not files:
                return "No files found in this folder."
            result = f"Found {len(files)} files:\n\n"
            for f in files:
                result += f"- **{f['name']}** ({f['type']}) — Modified: {f['modified']} — [Open]({f.get('link', '')})\n"
                result += f"  ID: `{f['id']}`\n"
            return result

    async def search_google_drive(self, query: str, __user__: dict = {}) -> str:
        """
        Search for files across your entire Google Drive by name or content.
        Example queries: 'quarterly report', 'budget 2024', 'meeting notes'.
        """
        user_email = __user__.get("email", "default@local")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.valves.gdrive_url}/gdrive_search_files",
                json={"query": query, "page_size": 20},
                headers={"X-User-Email": user_email},
                timeout=30.0,
            )
            data = resp.json()
            if "error" in data:
                return data["error"]
            files = data.get("files", [])
            if not files:
                return f"No files found matching: {query}"
            result = f"Found {len(files)} files for '{query}':\n\n"
            for f in files:
                result += f"- **{f['name']}** ({f['type']}) — Modified: {f.get('modified', '')} — [Open]({f.get('link', '')})\n"
                result += f"  ID: `{f['id']}`\n"
            return result

    async def read_google_drive_file(self, file_id: str, __user__: dict = {}) -> str:
        """
        Read the content of a Google Drive file. Provide the file ID (get it from list or search).
        Supports Google Docs, Sheets, Slides (converted to text), and text files. Max 2MB.
        """
        user_email = __user__.get("email", "default@local")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.valves.gdrive_url}/gdrive_read_file",
                json={"file_id": file_id},
                headers={"X-User-Email": user_email},
                timeout=30.0,
            )
            data = resp.json()
            if "error" in data:
                return data["error"]
            content = data.get("content", "No content available")
            name = data.get("file_name", "unknown")
            truncated = data.get("truncated", False)
            result = f"## {name}\n\n{content}"
            if truncated:
                result += "\n\n*[Content truncated — file exceeds 2MB limit]*"
            return result

    async def connect_google_drive(self, __user__: dict = {}) -> str:
        """
        Get the link to connect your Google Drive account. Run this first before using other Google Drive tools.
        """
        user_email = __user__.get("email", "default@local")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.valves.gdrive_url}/auth/google/status",
                params={"user_email": user_email},
                timeout=10.0,
            )
            data = resp.json()
            if data.get("connected"):
                return f"✅ Google Drive is already connected for **{user_email}**. You can now use the other Google Drive tools (list, search, read)."
            return f"To connect your Google Drive, open this link in your browser:\n\nhttp://localhost:8005/auth/google/start?user_email={user_email}\n\nAfter authorizing, come back and try again."
