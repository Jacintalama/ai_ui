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
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise TasksAPIError(0, f"tasks service unreachable: {e}") from e
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise TasksAPIError(resp.status_code, str(detail))
        return resp

    async def _internal_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """For system endpoints (/discord-links/*) authed with X-Internal-Secret."""
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method, url, headers={"X-Internal-Secret": self._internal_secret}, **kwargs
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
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

    # --- Video generation (user-scoped, X-User-Email) ---
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
