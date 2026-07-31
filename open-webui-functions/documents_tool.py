"""
title: Documents
author: AIUI Team
version: 0.1.0
description: Create real Word (.docx) or PDF files from chat and optionally save them to your Google Drive. Ask for any document, report, letter, or "export this conversation".
"""

# Native Open WebUI tool. The model writes the document content as markdown
# (headings, lists, **bold**, tables); generation happens in the tasks
# service so libraries survive OWUI upgrades. Download is a data: link
# (Excel Creator pattern). Drive save reuses the per-user mcp-gdrive OAuth.

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default="http://tasks:8210")
        gdrive_url: str = Field(default="http://mcp-gdrive:8000")
        internal_secret: str = Field(default="")
        timeout_seconds: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def create_document(
        self,
        title: str,
        markdown: str,
        format: str = "docx",
        save_to_drive: bool = False,
        __user__: dict = {},
    ) -> str:
        """
        Create a Word (.docx) or PDF file from markdown content and give the
        user a download button. Use whenever the user asks for a document,
        report, letter, proposal, or to export this conversation as a file.
        Write the full document content yourself in the markdown argument
        (# headings, lists, **bold**, | tables |).

        :param title: Document title, used as the filename and heading.
        :param markdown: The complete document content as markdown.
        :param format: "docx" for Word or "pdf".
        :param save_to_drive: True when the user asks to save it to Google Drive.
        :return: HTML with a download button (and Drive link), or a plain error sentence.
        """
        fmt = "pdf" if str(format).lower().strip() == "pdf" else "docx"
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                r = await c.post(
                    f"{self.valves.tasks_url}/files/generate",
                    json={"title": title or "", "markdown": markdown, "format": fmt},
                    headers={"X-Internal-Secret": self.valves.internal_secret},
                )
        except Exception as e:
            return f"Sorry, the document service is unreachable: {e}"
        if r.status_code != 200:
            try:
                detail = r.json().get("detail", "")
            except Exception:
                detail = r.text[:120]
            return f"Sorry, the {fmt} could not be created. {detail}"
        d = r.json()
        label = "Word document" if fmt == "docx" else "PDF"
        kb = max(1, d["size"] // 1024)
        html = (
            '<div style="padding:18px;background:linear-gradient(135deg,#1e3a5f,#2d5a87);'
            'border-radius:12px;color:white;margin:10px 0;">'
            f'<h3 style="margin:0 0 8px 0;">{label} ready: {d["filename"]}</h3>'
            f'<p style="margin:0 0 12px 0;opacity:0.9;">{kb} KB</p>'
            f'<a href="data:{d["mime"]};base64,{d["b64"]}" download="{d["filename"]}" '
            'style="display:inline-block;padding:12px 24px;background:#4CAF50;color:white;'
            'text-decoration:none;border-radius:6px;font-weight:bold;">'
            f'Download {d["filename"]}</a>'
        )
        if save_to_drive:
            email = (__user__ or {}).get("email", "default@local")
            try:
                async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                    g = await c.post(
                        f"{self.valves.gdrive_url}/gdrive_create_file",
                        json={"name": d["filename"], "content_b64": d["b64"],
                              "mime_type": d["mime"]},
                        headers={"X-User-Email": email},
                    )
                gd = g.json()
            except Exception as e:
                gd = {"error": f"Google Drive is unreachable: {e}"}
            if gd.get("success"):
                html += (
                    f'<p style="margin:12px 0 0 0;">Saved to your Google Drive: '
                    f'<a href="{gd.get("link", "#")}" target="_blank" '
                    'style="color:#9ecbff;">open in Drive</a></p>'
                )
            else:
                # Not-connected message contains the connect URL; the frontend
                # turns it into the inline Connect button. Pass it through.
                html += ('<p style="margin:12px 0 0 0;">Drive save failed: '
                         f'{gd.get("error", "unknown error")}</p>')
        return html + "</div>"
