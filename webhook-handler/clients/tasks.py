"""HTTP client for the tasks service (mcp-servers/tasks).

CRITICAL SECURITY: This client MUST send ONLY X-User-Email — never the
X-Cron-Secret header. The tasks routes_schedules._resolve_caller flips
to operator mode when the cron secret is present, after which list_schedules
returns all users' schedules. By withholding the secret we stay on the
end-user code path and per-row ownership is enforced server-side.
"""
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: An agent turn runs up to CHANNEL_MAX_TOOL_ITERATIONS completions with tool
#: calls in between, so it cannot use the 15 second default that suits
#: reading a row. Sized above the tasks service's own worst case for a
#: channel turn (3 rounds at 60 seconds) with room for the tool calls
#: themselves. A timeout here reads to the user as the bot ignoring them.
AGENT_TURN_TIMEOUT_SECONDS = 240.0


class TasksAPIError(Exception):
    """Raised when the tasks service returns a non-2xx or is unreachable.

    status = 0 means network-level failure (ConnectError, timeout).
    """
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"tasks API error {status}: {message}")


class TasksClient:
    def __init__(self, base_url: str, timeout: float = 15.0, internal_secret: str = ""):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # For system (non-user-scoped) endpoints like /discord-links/*. Sent as
        # X-Internal-Secret — NOT the cron secret, and never on /schedules.
        self._internal_secret = internal_secret

    def _headers(self, user_email: str) -> dict[str, str]:
        # ONLY X-User-Email. Never X-Cron-Secret here.
        #
        # And never X-User-Admin, even for a user who IS an admin. This is
        # deliberate, not an oversight: it means an admin scheduling from
        # Discord or Slack is capped like anyone else (MAX_SCHEDULES_PER_USER,
        # the interval floor) while the same person is exempt on the web.
        #
        # The tasks service trusts X-User-Admin only because the API gateway
        # strips it from the client request and re-sets it after validating
        # the JWT, so the client can never assert it. The webhook-handler is
        # not the gateway: it takes the email from a Discord/Slack identity it
        # has already resolved, but it holds no JWT and validates nothing about
        # admin-ness. If it started sending the header, the header would become
        # forgeable-by-proxy and would stop being trustworthy ANYWHERE — every
        # route in the tasks service that reads it would be weakened, to buy an
        # admin a cap they can already bypass through the web UI or the
        # operator secret (X-Cron-Secret).
        #
        # So: an admin who needs more than the cap uses the web UI. Do not
        # "fix" this by adding the header here.
        return {"X-User-Email": user_email}

    async def _request(
        self, method: str, path: str, user_email: str, **kwargs
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method, url, headers=self._headers(user_email), **kwargs
                )
        except httpx.TransportError as e:
            # TransportError, not just ConnectError and TimeoutException: a reset
            # partway through a request raises ReadError or RemoteProtocolError,
            # and those would otherwise escape as raw httpx errors that callers
            # catching TasksAPIError never see.
            raise TasksAPIError(0, f"tasks service unreachable: {e}") from e
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise TasksAPIError(resp.status_code, str(detail))
        return resp

    async def _internal_request(self, method: str, path: str,
                                timeout: float | None = None,
                                **kwargs) -> httpx.Response:
        """For system endpoints (/discord-links/*) authed with X-Internal-Secret."""
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                resp = await client.request(
                    method, url, headers={"X-Internal-Secret": self._internal_secret}, **kwargs
                )
        except httpx.TransportError as e:
            # TransportError, not just ConnectError and TimeoutException: a reset
            # partway through a request raises ReadError or RemoteProtocolError,
            # and those would otherwise escape as raw httpx errors that callers
            # catching TasksAPIError never see.
            raise TasksAPIError(0, f"tasks service unreachable: {e}") from e
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise TasksAPIError(resp.status_code, str(detail))
        return resp

    async def list_schedules(
        self, user_email: str, platform: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if platform is not None:
            kwargs["params"] = {"platform": platform}
        resp = await self._request("GET", "/schedules", user_email, **kwargs)
        return resp.json()

    async def create_schedule(
        self, user_email: str, name: str, cron: str, prompt: str,
        tz: str = "Asia/Manila", delivery_channel_id: str | None = None,
        delivery_platform: str = "discord", run_once: bool = False,
        kind: str = "agent", video_config: dict | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name, "cron_expr": cron, "prompt": prompt, "tz": tz,
        }
        # Only include the delivery target when set — keeps the payload (and the
        # existing create test) stable for callers that don't deliver to Discord.
        if delivery_channel_id is not None:
            body["delivery_channel_id"] = delivery_channel_id
        # Only include run_once when True so existing (repeating) create payloads
        # stay byte-identical for callers that never set it.
        if run_once:
            body["run_once"] = True
        if delivery_platform:
            body["delivery_platform"] = delivery_platform
        # Only include non-default kinds so existing create payloads stay
        # byte-identical for agent schedules.
        if kind and kind != "agent":
            body["kind"] = kind
        if video_config is not None:
            body["video_config"] = video_config
        resp = await self._request("POST", "/schedules", user_email, json=body)
        return resp.json()

    async def delete_schedule(self, user_email: str, schedule_id: str) -> bool:
        await self._request("DELETE", f"/schedules/{schedule_id}", user_email)
        return True

    async def pause_schedule(self, user_email: str, schedule_id: str) -> bool:
        await self._request("POST", f"/schedules/{schedule_id}/disable", user_email)
        return True

    async def resume_schedule(self, user_email: str, schedule_id: str) -> bool:
        await self._request("POST", f"/schedules/{schedule_id}/enable", user_email)
        return True

    async def run_schedule_now(self, user_email: str, schedule_id: str) -> bool:
        await self._request("POST", f"/schedules/{schedule_id}/run-now", user_email)
        return True

    async def enable_schedule(self, user_email: str, schedule_id: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/schedules/{schedule_id}/enable", user_email,
        )
        return resp.json()

    async def disable_schedule(self, user_email: str, schedule_id: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/schedules/{schedule_id}/disable", user_email,
        )
        return resp.json()

    async def run_now_schedule(self, user_email: str, schedule_id: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/schedules/{schedule_id}/run-now", user_email,
        )
        return resp.json()

    async def update_schedule(
        self, user_email: str, schedule_id: str, *,
        name: str | None = None, cron: str | None = None, prompt: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if cron is not None:
            body["cron_expr"] = cron
        if prompt is not None:
            body["prompt"] = prompt
        resp = await self._request("PATCH", f"/schedules/{schedule_id}", user_email, json=body)
        return resp.json()

    # --- Discord-link management (system calls, X-Internal-Secret) ---
    async def request_link(self, discord_id: str, discord_username: str, email: str) -> dict[str, Any]:
        resp = await self._internal_request(
            "POST", "/discord-links/request",
            json={"discord_id": discord_id, "discord_username": discord_username, "email": email},
        )
        return resp.json()

    async def approve_link(self, discord_id: str, decided_by: str = "") -> dict[str, Any]:
        resp = await self._internal_request(
            "POST", f"/discord-links/{discord_id}/approve", json={"decided_by": decided_by},
        )
        return resp.json()

    async def reject_link(self, discord_id: str, decided_by: str = "") -> bool:
        await self._internal_request(
            "POST", f"/discord-links/{discord_id}/reject", json={"decided_by": decided_by},
        )
        return True

    async def resolve_link(self, discord_id: str) -> str | None:
        resp = await self._internal_request("GET", f"/discord-links/resolve/{discord_id}")
        return resp.json().get("email")

    async def get_user_thread(self, discord_id: str) -> str | None:
        resp = await self._internal_request("GET", f"/discord-links/{discord_id}/thread")
        return resp.json().get("thread_id")

    async def set_user_thread(self, discord_id: str, thread_id: str) -> bool:
        await self._internal_request(
            "POST", f"/discord-links/{discord_id}/thread", json={"thread_id": thread_id})
        return True

    async def get_user_builder_thread(self, discord_id: str) -> str | None:
        resp = await self._internal_request(
            "GET", f"/discord-links/{discord_id}/builder-thread")
        return resp.json().get("thread_id")

    async def set_user_builder_thread(self, discord_id: str, thread_id: str) -> bool:
        await self._internal_request(
            "POST", f"/discord-links/{discord_id}/builder-thread",
            json={"thread_id": thread_id})
        return True

    async def get_user_video_thread(self, discord_id: str) -> str | None:
        resp = await self._internal_request("GET", f"/discord-links/{discord_id}/video-thread")
        return resp.json().get("thread_id")

    async def set_user_video_thread(self, discord_id: str, thread_id: str) -> bool:
        await self._internal_request("POST", f"/discord-links/{discord_id}/video-thread",
                                     json={"thread_id": thread_id})
        return True

    # --- Generic bot state KV (system calls, X-Internal-Secret) ---
    async def get_state(self, key: str) -> Any:
        resp = await self._internal_request("GET", f"/state/{key}")
        return resp.json().get("value")

    async def set_state(self, key: str, value: Any, ttl_seconds: int | None = None) -> bool:
        body: dict[str, Any] = {"value": value}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        await self._internal_request("PUT", f"/state/{key}", json=body)
        return True

    async def delete_state(self, key: str) -> bool:
        await self._internal_request("DELETE", f"/state/{key}")
        return True

    # --- Agent turns (system calls, X-Internal-Secret) ---
    async def agent_turn(self, user_email: str, agent_id: str,
                         messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Run one turn as this user's agent, tools and all.

        Deliberately does NOT send tool_ids. The tasks service resolves the
        agent's own tools, because that field is the gate on which native
        tools may execute and naming it from here would move the decision out
        of the service that enforces it.
        """
        resp = await self._internal_request(
            "POST", "/agents/turn",
            json={"user_email": user_email, "agent_id": agent_id,
                  "messages": messages},
            timeout=AGENT_TURN_TIMEOUT_SECONDS)
        return resp.json()

    async def agent_turn_resume(self, user_email: str, agent_id: str,
                                conversation: list[dict[str, Any]],
                                calls: list[dict[str, Any]],
                                approved: bool) -> dict[str, Any]:
        """Continue a turn the agent stopped to ask about."""
        resp = await self._internal_request(
            "POST", "/agents/turn/resume",
            json={"user_email": user_email, "agent_id": agent_id,
                  "conversation": conversation, "calls": calls,
                  "approved": approved},
            timeout=AGENT_TURN_TIMEOUT_SECONDS)
        return resp.json()

    async def list_projects(self, user_email: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/api/projects", user_email)
        return resp.json()

    async def get_project_status(
        self, user_email: str, slug: str,
    ) -> dict[str, Any]:
        resp = await self._request("GET", f"/api/projects/{slug}/status", user_email)
        return resp.json()

    async def start_build(
        self, user_email: str, description: str, name: str | None = None,
        template_key: str | None = None,
        attachment_text: str | None = None, attachment_name: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "description": description, "name": name, "template_key": template_key,
        }
        if attachment_text is not None:  # omit when absent → unchanged for plain builds
            body["attachment_text"] = attachment_text
            body["attachment_name"] = attachment_name
        resp = await self._request(
            "POST", "/api/aiuibuilder/build", user_email, json=body,
        )
        return resp.json()

    async def resolve_rollback(
        self, user_email: str, slug: str, phrase: str,
    ) -> dict[str, Any]:
        """Which version does this sentence mean? READ-ONLY — changes nothing.
        Kept separate from rollback_app so the user can be shown the target and
        the reason before agreeing to anything."""
        resp = await self._request(
            "GET", f"/api/aiuibuilder/{slug}/rollback/resolve", user_email,
            params={"phrase": phrase},
        )
        return resp.json()

    async def rollback_app(
        self, user_email: str, slug: str, sha: str,
    ) -> dict[str, Any]:
        """Restore the app to `sha`. Owner-only; the service commits on top of
        HEAD rather than rewriting history, so this stays undoable."""
        resp = await self._request(
            "POST", f"/api/aiuibuilder/{slug}/rollback", user_email,
            json={"sha": sha},
        )
        return resp.json()

    async def list_templates(self, user_email: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/api/aiuibuilder/templates", user_email)
        return resp.json()

    async def get_build_status(
        self, user_email: str, task_id: str,
    ) -> dict[str, Any]:
        resp = await self._request(
            "GET", f"/api/aiuibuilder/build/{task_id}", user_email,
        )
        return resp.json()

    async def answer_build(
        self, user_email: str, task_id: str, answer: str | None = None,
        answers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Answer a paused (needs_input) build and resume it. Returns the new
        build status ({status, slug, preview_url, error, user_prompt,
        question, questions}).

        Two shapes: free-text `answer` (the Jul-13 mid-build flow, unchanged)
        and `answers`, one string per stored pre-build question in order,
        or [] to skip (the Task-4 structured pre-build questions flow).
        `answers`, when given, is included in the request body; `answer` is
        included whenever it's not None (back-compat with existing callers
        that only ever pass `answer`).
        """
        body: dict[str, Any] = {}
        if answer is not None:
            body["answer"] = answer
        if answers is not None:
            body["answers"] = answers
        resp = await self._request(
            "POST", f"/api/aiuibuilder/build/{task_id}/answer", user_email,
            json=body,
        )
        return resp.json()

    # --- Video generation (user-scoped, X-User-Email) ---
    async def get_video_templates(self) -> dict[str, Any]:
        """Template preset catalog (static registry - not user-scoped)."""
        resp = await self._request("GET", "/api/video-jobs/templates", "system@aiui.local")
        return resp.json()

    async def get_video_voices(self) -> dict[str, Any]:
        # /voices is unauthenticated server-side; reuse _request (the header is harmless).
        resp = await self._request("GET", "/api/video-jobs/voices", "system@aiui.local")
        return resp.json()

    async def create_video_draft(self, user_email: str, title: str, prompt: str,
                                 style: str, voice: str, *,
                                 render_mode: str = "remotion",
                                 animation_preset: str = "cursor_click") -> dict[str, Any]:
        resp = await self._request("POST", "/api/video-jobs/draft", user_email,
                                   json={"title": title, "prompt": prompt,
                                         "style": style, "voice": voice,
                                         "render_mode": render_mode,
                                         "animation_preset": animation_preset})
        return resp.json()

    async def get_current_video_draft(self, user_email: str) -> dict[str, Any] | None:
        try:
            resp = await self._request("GET", "/api/video-jobs/current-draft", user_email)
        except TasksAPIError as e:
            if e.status == 404:
                return None
            raise
        return resp.json()

    async def set_video_draft_fields(self, user_email: str, job_id: str, *,
                                     style: str | None = None, voice: str | None = None,
                                     title: str | None = None, prompt: str | None = None,
                                     render_mode: str | None = None,
                                     animation_preset: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if style is not None:
            body["style"] = style
        if voice is not None:
            body["voice"] = voice
        if title is not None:
            body["title"] = title
        if prompt is not None:
            body["prompt"] = prompt
        if render_mode is not None:
            body["render_mode"] = render_mode
        if animation_preset is not None:
            body["animation_preset"] = animation_preset
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/draft-set", user_email, json=body)
        return resp.json()

    async def add_video_screenshots_urls(self, user_email: str, job_id: str,
                                         urls: list[str]) -> dict[str, Any]:
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/screenshots-by-url",
                                   user_email, json={"urls": urls})
        return resp.json()

    async def capture_video_screenshots(self, user_email: str, job_id: str, url: str,
                                        *, max_frames: int | None = None) -> dict[str, Any]:
        """Drive server-side headless-browser capture of `url` onto the job. Uses
        a longer timeout than the default because a capture takes seconds."""
        body: dict[str, Any] = {"url": url}
        if max_frames is not None:
            body["max_frames"] = max_frames
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/capture-from-url",
                                   user_email, json=body, timeout=45.0)
        return resp.json()

    async def queue_video(self, user_email: str, job_id: str) -> dict[str, Any]:
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/queue", user_email)
        return resp.json()

    async def get_video(self, user_email: str, job_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/api/video-jobs/{job_id}", user_email)
        return resp.json()

    async def list_videos(self, user_email: str) -> dict[str, Any]:
        resp = await self._request("GET", "/api/video-jobs", user_email)
        return resp.json()

    async def refine_video(self, user_email: str, job_id: str, message: str) -> dict[str, Any]:
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/refine", user_email,
                                   json={"message": message})
        return resp.json()

    async def apply_video(self, user_email: str, job_id: str) -> dict[str, Any]:
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/apply", user_email)
        return resp.json()

    async def video_versions(self, user_email: str, job_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/api/video-jobs/{job_id}/versions", user_email)
        return resp.json()

    async def revert_video(self, user_email: str, job_id: str, version_no: int) -> dict[str, Any]:
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/revert", user_email,
                                   json={"version_no": version_no})
        return resp.json()

    async def delete_video(self, user_email: str, job_id: str) -> dict[str, Any]:
        """Delete one of the user's video jobs (409 while it is rendering)."""
        resp = await self._request("DELETE", f"/api/video-jobs/{job_id}", user_email)
        return resp.json()

    async def retry_video(self, user_email: str, job_id: str) -> dict[str, Any]:
        """Re-queue a failed render (409 unless the job status is failed)."""
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/retry", user_email)
        return resp.json()

    async def download_video_bytes(self, user_email: str, job_id: str) -> bytes:
        """Fetch the rendered MP4 (member-auth via X-User-Email). Returns raw bytes."""
        resp = await self._request("GET", f"/api/video-jobs/{job_id}/download", user_email)
        return resp.content

    async def fetch_bytes(self, path: str) -> bytes:
        """GET a public/static path on the tasks service (e.g. a voice sample), no auth.
        Used to attach the voice preview MP3s."""
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            raise TasksAPIError(0, f"fetch failed: {e}") from e
        return resp.content

    async def start_outreach(
        self, user_email: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        # Always include a direction so the backend can label the run; callers
        # override via payload["direction"] ("hire" | "reverse").
        body = {"direction": "hire", **payload}
        resp = await self._request("POST", "/outreach", user_email, json=body)
        return resp.json()

    async def get_outreach_status(
        self, user_email: str, task_id: str,
    ) -> dict[str, Any]:
        resp = await self._request("GET", f"/outreach/{task_id}", user_email)
        return resp.json()

    async def get_outreach_candidates(self, user_email: str, task_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/outreach/{task_id}/candidates", user_email)
        return resp.json()

    async def patch_outreach_candidate(
        self, user_email: str, task_id: str, cid: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        resp = await self._request(
            "PATCH", f"/outreach/{task_id}/candidates/{cid}", user_email, json=payload,
        )
        return resp.json()

    async def send_outreach(self, user_email: str, task_id: str) -> dict[str, Any]:
        resp = await self._request("POST", f"/outreach/{task_id}/send", user_email, json={})
        return resp.json()

    async def publish_app(self, user_email: str, slug: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/aiuibuilder/{slug}/publish", user_email,
        )
        return resp.json()

    async def unpublish_app(self, user_email: str, slug: str) -> bool:
        await self._request("DELETE", f"/api/aiuibuilder/{slug}/publish", user_email)
        return True

    async def delete_app(self, user_email: str, slug: str) -> bool:
        await self._request("DELETE", f"/api/aiuibuilder/{slug}/app", user_email)
        return True

    async def enhance_app(
        self, user_email: str, slug: str, prompt: str,
        attachment_text: str | None = None, attachment_name: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt}
        if attachment_text is not None:
            body["attachment_text"] = attachment_text
            body["attachment_name"] = attachment_name
        resp = await self._request(
            "POST", f"/api/aiuibuilder/{slug}/enhance", user_email, json=body,
        )
        return resp.json()

    async def list_app_versions(self, user_email: str, slug: str) -> list[dict[str, Any]]:
        resp = await self._request(
            "GET", f"/api/aiuibuilder/{slug}/versions", user_email,
        )
        return resp.json()

    async def rollback_app(self, user_email: str, slug: str, sha: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/aiuibuilder/{slug}/rollback", user_email, json={"sha": sha},
        )
        return resp.json()

    # --- Multi-platform gateway ---------------------------------------------
    # These use _internal_request (X-Internal-Secret), never _request: there is
    # no user email yet at resolve time, and resolving IS how we learn it.

    async def gateway_resolve(
        self, platform: str, platform_user_id: str, platform_user_name: str = "",
    ) -> dict:
        """Who is this platform user?

        Linked -> {"linked": True, "email", "owui_user_id", "owui_token"}
        Unlinked -> {"linked": False, "code", "expires_at"}

        The token is scoped to one user for 60 seconds. Do not store it, do not
        log it, and do not reuse it across requests.
        """
        resp = await self._internal_request("POST", "/gateway/resolve", json={
            "platform": platform,
            "platform_user_id": platform_user_id,
            "platform_user_name": platform_user_name,
        })
        return resp.json()

    async def gateway_get_session(self, platform: str, chat_id: str) -> dict[str, Any]:
        """The stored mapping for this conversation.

        {"owui_chat_id": None} when there is no session yet, otherwise
        {"owui_chat_id": ..., "owui_user_id": ...}. Callers need BOTH fields:
        owui_user_id is what lets get_or_create_chat notice a session that
        points at a different user's chat (a re-paired account) instead of
        trusting Open WebUI's ownership check alone.
        """
        resp = await self._internal_request(
            "GET", "/gateway/session",
            params={"platform": platform, "chat_id": chat_id})
        return resp.json()

    async def gateway_put_session(
        self, platform: str, chat_id: str, owui_chat_id: str, owui_user_id: str,
    ) -> None:
        await self._internal_request("PUT", "/gateway/session", json={
            "platform": platform,
            "chat_id": chat_id,
            "owui_chat_id": owui_chat_id,
            "owui_user_id": owui_user_id,
        })

    async def gateway_recent_sessions(
        self, owui_user_id: str, limit: int = 10,
    ) -> list[dict]:
        """Backs /resume. Newest first."""
        resp = await self._internal_request(
            "GET", "/gateway/sessions/recent",
            params={"owui_user_id": owui_user_id, "limit": limit})
        return resp.json().get("sessions", [])

    async def gateway_bot_config(self, bot_key: str) -> dict | None:
        """Everything needed to serve one inbound update on a user's own bot.

        Returns None when the key is unknown, which is normal: a removed bot
        can still have a webhook pointing here for a while. Any other failure
        raises, because the caller must be able to tell "no such bot" from "I
        could not ask", and only the second one may return a 503.

        The `token` in the response is plaintext. Do not log this dict.
        """
        try:
            resp = await self._internal_request("GET", f"/gateway/bots/{bot_key}")
        except TasksAPIError as exc:
            if exc.status == 404:
                return None
            raise
        return resp.json()

    async def gateway_bots_for_platform(self, platform: str) -> list[dict]:
        """Every enabled connection on one platform, with credentials.

        Only for platforms IO connects OUT to. A webhook platform names its own
        bot on the way in, so it never needs the whole list; a relay we hold
        open has no inbound call to name anything, so this is how the manager
        learns what should be connected.

        The `token` in each entry is plaintext. Do not log these.
        """
        resp = await self._internal_request(
            "GET", "/gateway/bots", params={"platform": platform})
        return resp.json().get("bots") or []

    async def gateway_bot_state(self, bot_key: str, connected: bool,
                                error: str = "") -> None:
        """Report whether a held-open connection is actually up.

        Best effort on purpose: this is status reporting, and failing to report
        must never take down the connection it is reporting on.
        """
        try:
            await self._internal_request(
                "POST", f"/gateway/bots/{bot_key}/state",
                json={"connected": connected, "error": error[:300]})
        except Exception:                                       # noqa: BLE001
            logger.warning("gateway: could not report state for %s", bot_key)

    async def gateway_bot_claim(self, bot_key: str, platform_user_id: str) -> bool:
        """First contact decides who an unclaimed bot serves."""
        resp = await self._internal_request(
            "POST", f"/gateway/bots/{bot_key}/claim",
            json={"platform_user_id": platform_user_id})
        return bool(resp.json().get("claimed"))
