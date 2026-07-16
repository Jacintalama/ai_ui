"""
title: Fusion
author: Ralph Benitez
version: 1.0.0
description: Ask a panel of models one question and get a single combined answer. Pick the panel and the model that fuses them in this tool's settings.
"""

import json
import os
from typing import Any, Callable, Literal, Optional

import httpx
from pydantic import BaseModel, Field

# The fan-out and the judge live in the tasks service. This tool runs inside
# Open WebUI's process, so it cannot reach fusion_engine directly and calls the
# internal API over the docker network instead.
TASKS_URL = os.environ.get("TASKS_URL", "http://tasks:8210")
INTERNAL_SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")

# Kept in step with fusion_engine.PROVIDER_REGISTRY. Open WebUI renders a
# Literal as a dropdown, which is the only native way a tool gets one, so these
# have to be literals rather than a list fetched at runtime.
ModelId = Literal[
    "gpt-5.5",
    "gpt-5",
    "o3",
    "gpt-4o",
    "gpt-4.1",
    "claude-opus-4-8",
    "claude-opus-4-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-haiku-4-5-20251001",
]
OptionalModelId = Literal[
    "none",
    "gpt-5.5",
    "gpt-5",
    "o3",
    "gpt-4o",
    "gpt-4.1",
    "claude-opus-4-8",
    "claude-opus-4-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-haiku-4-5-20251001",
]


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(
            default=TASKS_URL,
            description="Base URL of the tasks service on the docker network.",
        )
        timeout_seconds: int = Field(
            default=300,
            description="How long to wait for the whole fan-out plus judge.",
        )

    class UserValves(BaseModel):
        panel_model_1: ModelId = Field(
            default="gpt-5.5", description="First model on the panel."
        )
        panel_model_2: OptionalModelId = Field(
            default="claude-opus-4-8",
            description="Second model on the panel. 'none' to leave it out.",
        )
        panel_model_3: OptionalModelId = Field(
            default="none",
            description="Third model on the panel. 'none' to leave it out.",
        )
        panel_model_4: OptionalModelId = Field(
            default="none",
            description="Fourth model on the panel. 'none' to leave it out.",
        )
        fuse_with: ModelId = Field(
            default="claude-opus-4-8",
            description="The model that reads every panel answer and writes the single combined one.",
        )
        web_search: bool = Field(
            default=False,
            description="Search the web first and give every panel model the same live results.",
        )
        show_panel: bool = Field(
            default=True,
            description="Show which models answered underneath the reply.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    async def fuse(
        self,
        question: str,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
    ) -> str:
        """
        Ask several AI models the same question and return one combined answer.

        Use this whenever the user wants a second opinion, a consensus, a
        cross-check, or explicitly asks for Fusion. Pass the user's question
        through as-is.

        :param question: The question to put to the panel, in full.
        :return: One answer, combined from every panel model.
        """
        uv = (__user__ or {}).get("valves")
        if uv is None:
            uv = self.UserValves()

        async def say(description: str, done: bool = False) -> None:
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": description, "done": done},
                })

        # "none" is how a user empties a panel slot, and duplicates would just
        # buy the same answer twice.
        panel: list[str] = []
        for m in (uv.panel_model_1, uv.panel_model_2, uv.panel_model_3, uv.panel_model_4):
            if m and m != "none" and m not in panel:
                panel.append(m)
        if not panel:
            return ("No panel models are selected. Open this tool's settings and "
                    "pick at least one.")

        if not INTERNAL_SECRET:
            return ("Fusion is not configured: INTERNAL_CALLBACK_SECRET is missing "
                    "from Open WebUI's environment, so it cannot reach the fusion "
                    "service.")

        await say(f"Asking {len(panel)} models, then combining...")

        payload = {
            "messages": [{"role": "user", "content": question}],
            "panel": panel,
            "judge": uv.fuse_with,
            "web_search": bool(uv.web_search),
        }
        url = self.valves.tasks_url.rstrip("/") + "/api/fusion/complete"
        chunks: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                async with client.stream(
                    "POST", url, json=payload,
                    headers={"X-Internal-Secret": INTERNAL_SECRET},
                ) as r:
                    if r.status_code != 200:
                        body = (await r.aread()).decode("utf-8", "replace")[:300]
                        await say("Fusion failed", done=True)
                        return f"Fusion failed ({r.status_code}): {body}"
                    async for piece in r.aiter_text():
                        if piece:
                            chunks.append(piece)
        except Exception as e:
            await say("Fusion failed", done=True)
            return f"Fusion could not run: {e}"

        answer = "".join(chunks).strip()
        if not answer:
            await say("Fusion returned nothing", done=True)
            return "The panel returned nothing. Try again, or pick different models."

        await say(f"Combined {len(panel)} answers", done=True)

        if uv.show_panel:
            searched = "Searched the web, then asked " if uv.web_search else "Asked "
            answer += (f"\n\n---\n*{searched}{', '.join(panel)}; combined by "
                       f"{uv.fuse_with}.*")
        return answer
