"""
title: Fuse
author: Ralph Benitez
version: 1.0.0
description: Cross-check the answers your models just gave and produce one verified answer. Pick the model that does the fusing in this action's settings.
"""

import os
from typing import Any, Callable, Literal, Optional

import httpx
from pydantic import BaseModel, Field

# The judge lives in the tasks service. This runs inside Open WebUI's process,
# so it cannot reach fusion_engine directly and calls the internal API instead.
TASKS_URL = os.environ.get("TASKS_URL", "http://tasks:8210")
INTERNAL_SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")

# Kept in step with fusion_engine.PROVIDER_REGISTRY. Open WebUI renders a
# Literal as a dropdown, which is the only native way to get one, so this has to
# be a literal rather than a list fetched at runtime.
JudgeId = Literal[
    "claude-opus-4-8",
    "claude-opus-4-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-haiku-4-5-20251001",
    "gpt-5.5",
    "gpt-5",
    "o3",
    "gpt-4o",
    "gpt-4.1",
]


class Action:
    class Valves(BaseModel):
        tasks_url: str = Field(
            default=TASKS_URL,
            description="Base URL of the tasks service on the docker network.",
        )
        timeout_seconds: int = Field(
            default=300, description="How long to wait for the fusion."
        )

    class UserValves(BaseModel):
        fuse_with: JudgeId = Field(
            default="claude-opus-4-8",
            description="The model that reads every answer, cross-checks them and writes the verified one.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _collect_answers(self, body: dict, message_id: str) -> tuple[str, list[dict]]:
        """The question, and every model's answer to it.

        Open WebUI keeps a multi-model turn as sibling assistant messages that
        share one parentId, so the answers are siblings of the message the button
        was clicked on, not entries in a linear history.
        """
        history = (body.get("messages") or [])
        by_id = {m.get("id"): m for m in history if m.get("id")}
        clicked = by_id.get(message_id)

        answers: list[dict] = []
        question = ""

        if clicked and clicked.get("parentId") is not None:
            parent_id = clicked.get("parentId")
            for m in history:
                if (m.get("role") == "assistant"
                        and m.get("parentId") == parent_id
                        and (m.get("content") or "").strip()):
                    answers.append({
                        "model": m.get("model") or m.get("modelName") or "a model",
                        "content": m.get("content"),
                    })
            parent = by_id.get(parent_id)
            if parent and parent.get("role") == "user":
                question = parent.get("content") or ""

        if not answers:
            # Flat history (no sibling ids): take the trailing assistant run and
            # the user turn that prompted it.
            trailing: list[dict] = []
            for m in reversed(history):
                if m.get("role") == "assistant" and (m.get("content") or "").strip():
                    trailing.append({
                        "model": m.get("model") or m.get("modelName") or "a model",
                        "content": m.get("content"),
                    })
                elif m.get("role") == "user":
                    question = question or (m.get("content") or "")
                    break
            answers = list(reversed(trailing))

        return question.strip(), answers

    async def action(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
        __event_call__: Optional[Callable[[dict], Any]] = None,
    ) -> Optional[dict]:
        async def say(description: str, done: bool = False) -> None:
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": description, "done": done},
                })

        async def post(markdown: str) -> None:
            if __event_emitter__:
                await __event_emitter__({
                    "type": "message",
                    "data": {"content": markdown},
                })

        uv = (__user__ or {}).get("valves") or self.UserValves()

        message_id = body.get("id") or ""
        question, answers = self._collect_answers(body, message_id)

        if len(answers) < 2:
            await say("Nothing to cross-check", done=True)
            await post(
                "\n\n---\n**Fusion:** only one model answered, so there is nothing "
                "to cross-check. Add a second model to this chat with the **+** "
                "next to the model name, ask again, then press Fuse.\n"
            )
            return None
        if not question:
            await say("Could not find the question", done=True)
            await post("\n\n---\n**Fusion:** could not work out which question "
                       "these answers belong to.\n")
            return None
        if not INTERNAL_SECRET:
            await say("Fusion is not configured", done=True)
            await post("\n\n---\n**Fusion:** INTERNAL_CALLBACK_SECRET is missing "
                       "from Open WebUI's environment, so the fusion service "
                       "cannot be reached.\n")
            return None

        await say(f"Cross-checking {len(answers)} answers with {uv.fuse_with}...")

        url = self.valves.tasks_url.rstrip("/") + "/api/fusion/synthesize"
        payload = {"question": question, "answers": answers, "judge": uv.fuse_with}
        chunks: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                async with client.stream(
                    "POST", url, json=payload,
                    headers={"X-Internal-Secret": INTERNAL_SECRET},
                ) as r:
                    if r.status_code != 200:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        await say("Fusion failed", done=True)
                        await post(f"\n\n---\n**Fusion failed** ({r.status_code}): "
                                   f"{detail}\n")
                        return None
                    async for piece in r.aiter_text():
                        if piece:
                            chunks.append(piece)
        except Exception as e:
            await say("Fusion failed", done=True)
            await post(f"\n\n---\n**Fusion could not run:** {e}\n")
            return None

        verified = "".join(chunks).strip()
        if not verified:
            await say("Fusion returned nothing", done=True)
            await post("\n\n---\n**Fusion:** the judge returned nothing. Try again.\n")
            return None

        models = ", ".join(a["model"] for a in answers)
        await say(f"Cross-checked {len(answers)} answers", done=True)
        await post(f"\n\n---\n## Fusion\n\n{verified}\n\n"
                   f"*Cross-checked {models}; fused by {uv.fuse_with}.*\n")
        return None
