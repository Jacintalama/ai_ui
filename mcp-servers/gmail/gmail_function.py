"""
title: Gmail Assistant
author: AIUI Team
version: 0.1.0
description: Automatically detects email-related requests and executes Gmail actions (create drafts, send emails, list inbox). Works with attached emails from the Gmail picker.
required_open_webui_version: 0.8.0
"""

import re
import json
import httpx
from pydantic import BaseModel, Field
from typing import Optional


class Filter:
    class Valves(BaseModel):
        gmail_api_url: str = Field(
            default="http://mcp-gmail:8000",
            description="Gmail MCP Server URL",
        )
        ai_model: str = Field(
            default="gpt-4o-mini",
            description="Model for generating email replies",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: dict = {}) -> dict:
        """Process incoming messages - detect Gmail commands."""
        # Don't modify, just pass through - we handle in outlet
        return body

    async def outlet(self, body: dict, __user__: dict = {}) -> dict:
        """After AI responds, check if we should execute Gmail actions."""
        messages = body.get("messages", [])
        if len(messages) < 2:
            return body

        # Get the last user message
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                if isinstance(msg.get("content"), str):
                    user_msg = msg["content"].lower()
                elif isinstance(msg.get("content"), list):
                    for part in msg["content"]:
                        if isinstance(part, dict) and part.get("type") == "text":
                            user_msg = part.get("text", "").lower()
                break

        if not user_msg:
            return body

        # Check for Gmail command intent
        # Try the user's email first, fall back to default@local
        user_email = __user__.get("email", "default@local")
        gmail_url = self.valves.gmail_api_url

        # Check which email is connected and use that
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as check_client:
                for try_email in [user_email, "default@local"]:
                    r = await check_client.get(f"{gmail_url}/auth/google/status", params={"user_email": try_email})
                    if r.json().get("connected"):
                        user_email = try_email
                        break
        except Exception:
            pass

        # Extract Gmail Message ID from conversation context AND file contents
        message_id = None

        # Check message content first
        for msg in messages:
            content = ""
            if isinstance(msg.get("content"), str):
                content = msg["content"]
            elif isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if isinstance(part, dict) and part.get("type") == "text":
                        content += part.get("text", "")

            match = re.search(r'\[Gmail Message ID:\s*([^\]]+)\]', content)
            if match:
                message_id = match.group(1).strip()
                break

            # Also check for message IDs mentioned by the AI
            match2 = re.search(r'message_id["\s:=]+["\']?([a-f0-9]{16,})["\']?', content)
            if match2:
                message_id = match2.group(1).strip()

        # If not found in messages, check the AI's response for any Gmail ID reference
        if not message_id:
            last_assistant = ""
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    if isinstance(msg.get("content"), str):
                        last_assistant = msg["content"]
                    break
            match3 = re.search(r'["\(]([a-f0-9]{16,})["\)]', last_assistant)
            if match3:
                message_id = match3.group(1).strip()

        # Detect draft intent
        draft_keywords = ["create a draft", "draft reply", "draft a reply", "make a draft",
                         "write a draft", "save as draft", "create draft", "draft for this"]
        is_draft = any(kw in user_msg for kw in draft_keywords)

        # Detect send intent
        send_keywords = ["send email to", "send a message to", "email to", "send to"]
        is_send = any(kw in user_msg for kw in send_keywords)

        # Detect list/read intent
        list_keywords = ["list my emails", "show my inbox", "check my email", "show emails",
                        "what emails", "any new emails", "unread emails"]
        is_list = any(kw in user_msg for kw in list_keywords)

        if is_draft:
            if not message_id:
                # Try harder to find the ID - check all text for hex strings that look like Gmail IDs
                all_text = " ".join([str(m.get("content", "")) for m in messages])
                id_matches = re.findall(r'[a-f0-9]{16,}', all_text)
                if id_matches:
                    message_id = id_matches[0]

            if message_id:
                result = await self._create_draft(gmail_url, user_email, message_id, user_msg, messages)
                if result:
                    last_msg = messages[-1]
                    if last_msg.get("role") == "assistant":
                        if isinstance(last_msg.get("content"), str):
                            last_msg["content"] += "\n\n---\n" + result
                        body["messages"] = messages
                return body
            else:
                # No message ID found - append error
                last_msg = messages[-1]
                if last_msg.get("role") == "assistant":
                    if isinstance(last_msg.get("content"), str):
                        last_msg["content"] += "\n\n---\n**Could not find email ID.** Please attach an email first using Add from Gmail."
                    body["messages"] = messages
                return body

        # Send is handled by client-side JS with confirmation UI
        # if is_send: pass

        if is_list:
            result = await self._list_emails(gmail_url, user_email)
            if result:
                last_msg = messages[-1]
                if last_msg.get("role") == "assistant":
                    if isinstance(last_msg.get("content"), str):
                        last_msg["content"] += "\n\n---\n" + result
                    body["messages"] = messages
            return body

        return body

    async def _create_draft(self, gmail_url: str, user_email: str, message_id: str, user_msg: str, messages: list) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Read original email
                read_resp = await client.post(
                    f"{gmail_url}/gmail_read_email",
                    json={"message_id": message_id},
                    headers={"X-User-Email": user_email},
                )
                email_data = read_resp.json()
                if "error" in email_data:
                    return f"**Gmail Error:** {email_data['error']}"

                email_body = email_data.get("body", "")[:3000]
                subject = email_data.get("subject", "")
                sender = email_data.get("from", "")

                # Generate reply with AI
                # Get the AI's last response as the reply body
                ai_reply = ""
                for msg in reversed(messages):
                    if msg.get("role") == "assistant":
                        if isinstance(msg.get("content"), str):
                            ai_reply = msg["content"]
                        break

                # If AI already wrote a good reply, use it. Otherwise generate one.
                # Clean the AI reply - remove meta text, tool mentions, etc.
                if ai_reply:
                    ai_reply = re.sub(r'\[Gmail Message ID:.*?\]', '', ai_reply)
                    ai_reply = re.sub(r'---.*?---', '', ai_reply, flags=re.DOTALL)
                    ai_reply = re.sub(r'`gmail_create_draft_reply`', '', ai_reply)
                    ai_reply = re.sub(r'message_id.*?provided.*?\)', '', ai_reply)
                    ai_reply = re.sub(r'Sure,.*?tool[^.]*\.', '', ai_reply)
                    ai_reply = re.sub(r'You can create.*?tool[^.]*\.', '', ai_reply)
                    ai_reply = re.sub(r'To create this draft.*', '', ai_reply)
                    ai_reply = ai_reply.strip()

                if not ai_reply or len(ai_reply) < 20:
                    # Generate a proper reply using AI
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as ai_client:
                            ai_resp = await ai_client.post(
                                "https://api.openai.com/v1/chat/completions",
                                headers={"Authorization": f"Bearer {__import__('os').getenv('OPENAI_API_KEY', '')}"},
                                json={
                                    "model": "gpt-4o-mini",
                                    "messages": [
                                        {"role": "system", "content": "Write a professional email reply in proper email format. Include a greeting (Dear/Hi [Name]), the reply body, and a professional closing (Best regards/Kind regards) with sender name. No Subject line or headers."},
                                        {"role": "user", "content": f"Reply to: From: {sender}, Subject: {subject}\n\n{email_body[:2000]}"}
                                    ],
                                    "max_tokens": 300
                                }
                            )
                            ai_data = ai_resp.json()
                            if ai_data.get("choices"):
                                ai_reply = ai_data["choices"][0]["message"]["content"]
                    except Exception:
                        ai_reply = f"Thank you for your email regarding '{subject}'. I will review and respond shortly."

                # Create the draft
                draft_resp = await client.post(
                    f"{gmail_url}/gmail_create_draft_reply",
                    json={"message_id": message_id, "body": ai_reply},
                    headers={"X-User-Email": user_email},
                )
                draft_data = draft_resp.json()

                if draft_data.get("success"):
                    return (
                        f"**Draft Created in Gmail!**\n"
                        f"- Subject: {draft_data.get('subject', '')}\n"
                        f"- To: {draft_data.get('reply_to', '')}\n"
                        f"- Open Gmail → Drafts to review and send"
                    )
                else:
                    return f"**Failed to create draft:** {draft_data.get('error', draft_data.get('detail', 'Unknown error'))}"

        except Exception as e:
            return f"**Gmail Error:** {str(e)}"

    async def _send_email(self, gmail_url: str, user_email: str, user_msg: str, messages: list) -> Optional[str]:
        try:
            # Extract email address from user message AND all conversation text
            to_email = None
            all_text = user_msg
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, str):
                    all_text += " " + content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            all_text += " " + part.get("text", "")

            # Find all email addresses, pick the one that's NOT the user's
            all_emails = re.findall(r'[\w.-]+@[\w.-]+\.\w+', all_text)
            for e in all_emails:
                if e != user_email and e != "default@local" and "example" not in e:
                    to_email = e
                    break

            if not to_email:
                return "**Error:** No email address found in your message. Please include the recipient's email."

            # Extract the message content after the email address
            email_body = ""
            # Try to get text after "saying", "message:", "body:" etc.
            body_patterns = [
                r'(?:saying|say|message|body|with)\s+["\']?(.+?)(?:["\']?\s*$)',
                r'@[\w.-]+\.\w+\s+(.+?)$',
            ]
            for pattern in body_patterns:
                match = re.search(pattern, user_msg, re.IGNORECASE)
                if match:
                    email_body = match.group(1).strip()
                    break

            if not email_body:
                # Use the text after the email address
                parts = user_msg.split(to_email)
                if len(parts) > 1 and parts[1].strip():
                    email_body = parts[1].strip()

            if not email_body:
                email_body = "Hi, this is a message sent from AIUI."

            # Extract subject if mentioned
            subject = "Message from AIUI"
            subj_match = re.search(r'subject[:\s]+["\']?([^"\']+)["\']?', user_msg, re.IGNORECASE)
            if subj_match:
                subject = subj_match.group(1).strip()

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{gmail_url}/gmail_send_email",
                    json={"to": to_email, "subject": subject, "body": email_body},
                    headers={"X-User-Email": user_email},
                )
                data = resp.json()
                if data.get("success"):
                    return f"**Email Sent!**\n- To: {to_email}\n- Subject: {subject}"
                else:
                    return f"**Failed to send:** {data.get('error', 'Unknown error')}"

        except Exception as e:
            return f"**Gmail Error:** {str(e)}"

    async def _list_emails(self, gmail_url: str, user_email: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{gmail_url}/gmail_list_emails",
                    json={"label": "INBOX", "max_results": 10},
                    headers={"X-User-Email": user_email},
                )
                data = resp.json()
                if "error" in data:
                    return f"**Gmail Error:** {data['error']}"

                emails = data.get("emails", [])
                if not emails:
                    return "**No emails found in inbox.**"

                result = "**Your Recent Emails:**\n\n"
                for i, e in enumerate(emails):
                    unread = " 🔵" if e.get("unread") else ""
                    sender = (e.get("from", "Unknown").split("<")[0].strip())[:30]
                    result += f"{i+1}. **{e.get('subject', '(no subject)')}**{unread}\n"
                    result += f"   From: {sender} — {e.get('date', '')[:20]}\n\n"
                return result

        except Exception as e:
            return f"**Gmail Error:** {str(e)}"
