"""Internal Fusion API, called by the Open WebUI Fusion tool over the docker
network with X-Internal-Secret. Never routed publicly.

This exists because the tool runs inside Open WebUI's process, not this one, so
unlike the Fusion page it cannot reach fusion_engine in-process and needs an
HTTP hop. All the logic still lives in fusion_engine.
"""
import logging
import os
import secrets

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import fusion_engine
import fusion_search

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fusion")

MAX_PANEL = 4


def _require_internal(x_internal_secret: str) -> None:
    expected = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    # compare_digest, not ==: a plain compare on a secret leaks its prefix
    # through timing. Missing config denies rather than opens.
    if not expected or not secrets.compare_digest(x_internal_secret or "", expected):
        raise HTTPException(status_code=403, detail="invalid internal secret")


class FusionRequest(BaseModel):
    messages: list[dict]
    panel: list[str] = Field(min_length=1, max_length=MAX_PANEL)
    judge: str = Field(min_length=1, max_length=64)
    web_search: bool = False


@router.post("/complete")
async def fusion_complete(body: FusionRequest,
                          x_internal_secret: str = Header(default="")):
    _require_internal(x_internal_secret)
    unknown = [m for m in list(body.panel) + [body.judge]
               if m not in fusion_engine.PROVIDER_REGISTRY]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"unknown model(s): {', '.join(sorted(set(unknown)))}")
    # Drop empty turns: empty content is rejected by the Anthropic API and would
    # silently take every Claude panelist out of the fan-out.
    messages = [m for m in body.messages if (m.get("content") or "").strip()]
    if not messages:
        raise HTTPException(status_code=400, detail="no message to answer")

    async def gen():
        msgs = messages
        if body.web_search:
            msgs = await fusion_search.ground_in_search(msgs)
        async for chunk in fusion_engine.fuse(msgs, list(body.panel), body.judge):
            if chunk:
                yield chunk

    return StreamingResponse(gen(), media_type="text/plain")


class PanelAnswerIn(BaseModel):
    model: str = Field(default="a model", max_length=120)
    content: str


class SynthesizeRequest(BaseModel):
    question: str = Field(min_length=1)
    answers: list[PanelAnswerIn] = Field(min_length=1, max_length=8)
    judge: str = Field(min_length=1, max_length=64)


@router.post("/synthesize")
async def fusion_synthesize(body: SynthesizeRequest,
                            x_internal_secret: str = Header(default="")):
    """Judge answers that already exist, for the Open WebUI Fuse action.

    Unlike /complete this runs no fan-out: the models the user picked in the
    chat have already answered and been paid for, so fusion only judges.
    """
    _require_internal(x_internal_secret)
    if body.judge not in fusion_engine.PROVIDER_REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown judge: {body.judge}")
    answers = [{"model": a.model, "content": a.content} for a in body.answers]

    async def gen():
        async for chunk in fusion_engine.synthesize(body.question, answers, body.judge):
            if chunk:
                yield chunk

    return StreamingResponse(gen(), media_type="text/plain")


@router.get("/models")
async def fusion_models(x_internal_secret: str = Header(default="")):
    """The registry, so the tool's dropdowns never drift from what exists."""
    _require_internal(x_internal_secret)
    return {"models": fusion_engine.available_models(),
            "presets": {name: {"panel": list(p["panel"]), "judge": p["judge"]}
                        for name, p in fusion_engine.PRESETS.items()}}
