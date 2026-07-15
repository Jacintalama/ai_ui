"""Fusion endpoints. Internal-only (called by the OWUI fusion pipe over the
docker network with X-Internal-Secret); never routed publicly. Delegates all
logic to fusion_engine."""
import os

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import fusion_engine

router = APIRouter(prefix="/api/fusion")


def _require_internal(x_internal_secret: str) -> None:
    expected = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="invalid internal secret")


class FusionRequest(BaseModel):
    preset: str = Field(min_length=1, max_length=32)
    messages: list[dict]


@router.post("/complete")
async def fusion_complete(body: FusionRequest,
                          x_internal_secret: str = Header(default="")):
    _require_internal(x_internal_secret)
    if body.preset not in fusion_engine.PRESETS:
        raise HTTPException(status_code=400, detail=f"unknown preset: {body.preset}")
    return StreamingResponse(
        fusion_engine.fuse(body.messages, body.preset),
        media_type="text/plain",
    )


@router.get("/models")
async def fusion_models(x_internal_secret: str = Header(default="")):
    _require_internal(x_internal_secret)
    return {"presets": {name: {"panel": list(p["panel"]), "judge": p["judge"]}
                        for name, p in fusion_engine.PRESETS.items()}}
