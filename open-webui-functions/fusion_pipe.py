"""Model Fusion Pipe Function for Open WebUI.

Exposes 'Fusion (Quality)' and 'Fusion (Budget)' as selectable models. When
used, it streams the prompt to the tasks-service /api/fusion/complete endpoint,
which fans out to a panel of real models and streams back a judge-synthesized
answer. All fusion logic lives in the tasks-service; this pipe is a thin,
authenticated, streaming proxy.

Install: python scripts/install_fusion_pipe.py  (upserts into OWUI function table)
Configure Valves: TASKS_URL (http://tasks:8210), INTERNAL_SECRET.
"""
from typing import AsyncIterator

import httpx
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        TASKS_URL: str = Field(default="http://tasks:8210",
                               description="tasks-service base URL (docker network)")
        INTERNAL_SECRET: str = Field(default="",
                                     description="INTERNAL_CALLBACK_SECRET for /api/fusion auth")
        TIMEOUT_SECONDS: int = Field(default=150, description="overall stream timeout")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list:
        return [
            {"id": "fusion-quality", "name": "Fusion (Quality)"},
            {"id": "fusion-budget", "name": "Fusion (Budget)"},
        ]

    async def pipe(self, body: dict, __user__: dict = None,
                   __event_emitter__=None) -> AsyncIterator[str]:
        model = (body.get("model") or "")
        preset = "budget" if "budget" in model else "quality"
        messages = body.get("messages", [])
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {
                "description": f"Consulting the {preset} model panel...", "done": False}})
        url = self.valves.TASKS_URL.rstrip("/") + "/api/fusion/complete"
        payload = {"preset": preset, "messages": messages}
        headers = {"X-Internal-Secret": self.valves.INTERNAL_SECRET}
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        detail = (await resp.aread()).decode(errors="replace")[:200]
                        yield f"[Fusion error {resp.status_code}] {detail}"
                        return
                    async for chunk in resp.aiter_text():
                        if chunk:
                            yield chunk
        except Exception as e:  # noqa: BLE001
            yield f"[Fusion unavailable: {e}]"
        finally:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {
                    "description": "", "done": True}})
