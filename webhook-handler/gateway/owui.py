"""Open WebUI calls made AS a specific user.

clients/openwebui.py already talks to Open WebUI, but with the shared admin API
key. Using that here would resolve every caller as the admin, so the Brain
filter would inject the ADMIN's memory into every user's answer. An admin
testing it would see a perfectly correct-looking result. That silent failure is
the reason this second client exists.

The token comes from the tasks service, is scoped to one user, and lives 60
seconds. Never persist it and never log it.
"""
import json
import logging
import mimetypes
import os
import time

import httpx

log = logging.getLogger(__name__)


class OWUIError(Exception):
    """status = 0 means a network-level failure (timeout, connection refused)."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"open-webui error {status}: {message}")


class OWUIUserClient:
    def __init__(self, base_url: str, token: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method, url, headers=self._headers(), **kwargs)
        except httpx.TransportError as e:
            # TransportError, not just ConnectError and TimeoutException: a reset
            # partway through an upload raises ReadError or RemoteProtocolError,
            # and those would otherwise escape untyped. The caller branches on
            # .status, so an exception without one leaves it unable to tell a
            # network failure from a model failure.
            raise OWUIError(0, f"open-webui unreachable: {e}") from e
        if resp.status_code >= 400:
            # resp.text, not the JSON detail: a 502 from the proxy is HTML.
            raise OWUIError(resp.status_code, resp.text[:400])
        return resp

    @staticmethod
    def _json(resp: httpx.Response) -> dict:
        """Parse a 200 body, or raise a typed error.

        A 200 carrying something that is not JSON is what a proxy returning an
        HTML error page with the wrong status looks like. Letting the decode
        error escape would hand the caller an exception with no status to
        branch on.
        """
        try:
            return resp.json()
        except ValueError as e:
            raise OWUIError(
                502, f"open-webui returned a non-JSON body: {resp.text[:200]}"
            ) from e

    async def chat_completion(
        self, messages: list[dict], model: str, chat_id: str | None = None,
    ) -> str:
        payload: dict = {"model": model, "messages": messages, "stream": False}
        if chat_id:
            # Lets Open WebUI's own filters associate the turn with the chat.
            payload["chat_id"] = chat_id
        resp = await self._request("POST", "/api/chat/completions", json=payload)
        data = self._json(resp)
        choices = data.get("choices") or []
        if not choices:
            raise OWUIError(502, f"no choices in response: {json.dumps(data)[:300]}")
        content = (choices[0].get("message") or {}).get("content") or ""
        if not content.strip():
            raise OWUIError(502, "the model returned an empty answer")
        return content

    async def create_chat(self, title: str, model: str) -> str:
        """Create a real Open WebUI chat and return its id.

        Real, not synthetic, on purpose: it puts the conversation in the user's
        sidebar, makes it searchable, and feeds the Brain, with no sync
        mechanism of our own to keep correct.
        """
        chat = {
            "id": "",
            "title": title[:120] or "New chat",
            "models": [model],
            "params": {},
            "messages": [],
            "history": {"messages": {}, "currentId": None},
            "tags": [],
            "timestamp": int(time.time() * 1000),
            "files": [],
        }
        resp = await self._request("POST", "/api/v1/chats/new", json={"chat": chat})
        chat_id = self._json(resp).get("id")
        if not chat_id:
            raise OWUIError(502, "chat creation returned no id")
        return chat_id

    async def get_chat(self, chat_id: str) -> dict:
        """The inner chat object, which is what update_chat expects back."""
        resp = await self._request("GET", f"/api/v1/chats/{chat_id}")
        chat = self._json(resp).get("chat")
        if not chat:
            # Every other accessor here raises on a malformed 200, and this one
            # must too. Returning an empty object would let a caller round-trip
            # it into update_chat and overwrite a real chat with nothing.
            raise OWUIError(502, f"chat {chat_id} came back with no chat object")
        return chat

    async def update_chat(self, chat_id: str, chat: dict) -> None:
        await self._request("POST", f"/api/v1/chats/{chat_id}", json={"chat": chat})

    async def transcribe(self, path: str) -> str:
        """Speech to text through Open WebUI's own endpoint.

        Deliberately not a direct faster-whisper call: going through Open WebUI
        means the model, the cache and the engine setting stay in one place, and
        the container already has faster-whisper-base warm.

        The filename matters. Open WebUI checks the extension against
        AUDIO_STT_ALLOWED_EXTENSIONS, whose default list contains "ogg" and not
        Telegram's native "oga", so callers must hand us a .ogg path.
        """
        mime = mimetypes.guess_type(path)[0] or "audio/ogg"
        with open(path, "rb") as fh:
            files = {"file": (os.path.basename(path), fh.read(), mime)}
        resp = await self._request(
            "POST", "/api/v1/audio/transcriptions", files=files)
        text = (self._json(resp) or {}).get("text")
        if not text:
            raise OWUIError(502, "transcription returned no text")
        return text
