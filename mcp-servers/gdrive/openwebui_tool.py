"""
title: Google Drive
author: AIUI Team
version: 0.2.0
description: Browse, search, and read your Google Drive files from chat. Connecting is a one-click inline button. Per-user: each person uses their own Drive. (Read-only for now.)
"""

# Native Open WebUI tool. Model calls these directly; OWUI injects the signed-in
# user via __user__ (per-user). On "not connected" the gdrive server returns a
# message with the /gdrive/auth/google/start URL, which the frontend
# (integrations-ui.js) turns into an inline Connect button. Read-only: the Drive
# OAuth scope is drive.readonly, so there is no create/save yet.

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        gdrive_url: str = Field(default="http://mcp-gdrive:8000")
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    def _email(self, __user__: dict) -> str:
        return (__user__ or {}).get("email", "default@local")

    async def _post(self, path: str, payload: dict, user_email: str) -> dict:
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
            r = await client.post(
                f"{self.valves.gdrive_url}/{path}",
                json=payload,
                headers={"X-User-Email": user_email},
            )
            try:
                return r.json()
            except Exception:
                return {"error": f"Google Drive returned an unexpected response ({r.status_code})."}

    def _fmt_files(self, data: dict, empty_msg: str) -> str:
        if isinstance(data, dict) and data.get("error"):
            return data["error"]  # not connected -> connect URL (frontend buttons it)
        files = data.get("files", []) if isinstance(data, dict) else []
        if not files:
            return empty_msg
        lines = []
        for f in files:
            link = f.get("link") or f.get("webViewLink") or ""
            lines.append(
                f"- **{f.get('name', '(unnamed)')}** ({f.get('type', 'file')})"
                + (f" - modified {f.get('modified')}" if f.get('modified') else "")
                + (f"\n  {link}" if link else "")
                + f"\n  `file_id: {f.get('id')}`"
            )
        return "\n".join(lines)

    async def list_drive_files(self, folder_id: str = "root", max_results: int = 20, __user__: dict = {}) -> str:
        """
        List files in the user's Google Drive. Use folder_id='root' for top-level
        or a folder id to browse into it.

        :param folder_id: Folder to list ('root' for top level).
        :param max_results: How many files to return (max 50).
        :return: A formatted list of files, or a connect prompt if Drive isn't linked.
        """
        data = await self._post("gdrive_list_files",
                                {"folder_id": folder_id, "page_size": max_results},
                                self._email(__user__))
        return self._fmt_files(data, "No files found in this folder.")

    async def search_drive(self, query: str, max_results: int = 20, __user__: dict = {}) -> str:
        """
        Search the user's entire Google Drive by name or content.

        :param query: What to look for, e.g. "quarterly report" or "budget 2026".
        :param max_results: How many results (max 50).
        :return: A formatted list of matching files, or a connect prompt if Drive isn't linked.
        """
        data = await self._post("gdrive_search_files",
                                {"query": query, "page_size": max_results},
                                self._email(__user__))
        return self._fmt_files(data, f"No files matched: {query}")

    async def read_drive_file(self, file_id: str, __user__: dict = {}) -> str:
        """
        Read the text content of a Google Drive file by its id (from a list or
        search result). Use to read or summarize a document.

        :param file_id: The Drive file id (shown as file_id in results).
        :return: The file's text content, or a connect prompt if Drive isn't linked.
        """
        data = await self._post("gdrive_read_file", {"file_id": file_id}, self._email(__user__))
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        name = data.get("name", "(file)")
        content = data.get("content") or data.get("text") or data.get("body") or ""
        return f"**{name}**\n\n{content}" if content else f"**{name}**\n\n(No readable text content.)"
