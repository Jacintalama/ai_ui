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
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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

    async def list_schedules(self, user_email: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/schedules", user_email)
        return resp.json()

    async def create_schedule(
        self, user_email: str, name: str, cron: str, prompt: str,
        tz: str = "Asia/Manila", delivery_channel_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name, "cron_expr": cron, "prompt": prompt, "tz": tz,
        }
        # Only include the delivery target when set — keeps the payload (and the
        # existing create test) stable for callers that don't deliver to Discord.
        if delivery_channel_id is not None:
            body["delivery_channel_id"] = delivery_channel_id
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
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST", "/api/aiuibuilder/build", user_email,
            json={"description": description, "name": name, "template_key": template_key},
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

    async def publish_app(self, user_email: str, slug: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/aiuibuilder/{slug}/publish", user_email,
        )
        return resp.json()

    async def unpublish_app(self, user_email: str, slug: str) -> bool:
        await self._request("DELETE", f"/api/aiuibuilder/{slug}/publish", user_email)
        return True

    async def enhance_app(self, user_email: str, slug: str, prompt: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/api/aiuibuilder/{slug}/enhance", user_email,
            json={"prompt": prompt},
        )
        return resp.json()
