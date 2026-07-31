"""
title: Documents
author: AIUI Team
version: 0.1.0
description: Create real Word (.docx), PDF, or PowerPoint (.pptx) files from chat and optionally save them to your Google Drive. Ask for any document, report, letter, slide deck, or "export this conversation".
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
        gmail_url: str = Field(default="http://mcp-gmail:8000")
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
        email_to: str = "",
        email_subject: str = "",
        __user__: dict = {},
    ) -> str:
        """
        Create a Word (.docx), PDF, or PowerPoint (.pptx) file from markdown
        content and give the user a download button. Use whenever the user
        asks for a document, report, letter, proposal, slide deck, or to
        export this conversation as a file. Write the full document content
        yourself in the markdown argument (# headings, lists, **bold**,
        | tables |). For PowerPoint, each # or ## heading starts a new slide.

        :param title: Document title, used as the filename and heading.
        :param markdown: The complete document content as markdown.
        :param format: "docx" for Word, "pdf", or "pptx" for PowerPoint.
        :param save_to_drive: True when the user asks to save it to Google Drive.
        :param email_to: Recipient address when the user asks to email the file to someone; a Gmail DRAFT with the file attached is created for the user to review and send (nothing is sent automatically).
        :param email_subject: Subject for that draft (defaults to the title).
        :return: HTML with a download button (and Drive/Gmail links), or a plain error sentence.
        """
        f = str(format).lower().strip()
        fmt = f if f in ("pdf", "pptx") else "docx"
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
        label = {"docx": "Word document", "pdf": "PDF",
                 "pptx": "PowerPoint deck"}[fmt]
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
        if email_to.strip():
            email = (__user__ or {}).get("email", "default@local")
            try:
                async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                    m = await c.post(
                        f"{self.valves.gmail_url}/gmail_create_draft_with_attachment",
                        json={"to": email_to.strip(),
                              "subject": (email_subject or title or d["filename"]).strip(),
                              "body": f"Please find {d['filename']} attached.",
                              "filename": d["filename"], "content_b64": d["b64"],
                              "mime_type": d["mime"]},
                        headers={"X-User-Email": email},
                    )
                md = m.json()
            except Exception as e:
                md = {"error": f"Gmail is unreachable: {e}"}
            if md.get("success"):
                html += (
                    f'<p style="margin:12px 0 0 0;">Gmail draft to '
                    f'<strong>{email_to.strip()}</strong> created with the file '
                    'attached. <a href="https://mail.google.com/mail/#drafts" '
                    'target="_blank" style="color:#9ecbff;">Open Gmail</a> to '
                    'review and send it.</p>'
                )
            else:
                html += ('<p style="margin:12px 0 0 0;">Email draft failed: '
                         f'{md.get("error", md.get("detail", "unknown error"))}</p>')
        return html + "</div>"
