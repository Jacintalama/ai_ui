"""Events out: the hooks a person sets (events_out.py).

    GET    /api/tasks/events/hooks             this person's hooks
    POST   /api/tasks/events/hooks             {"url", "events", "label"}; the secret, once
    PATCH  /api/tasks/events/hooks/{id}        {"enabled", "events", "label"}
    DELETE /api/tasks/events/hooks/{id}
    POST   /api/tasks/events/hooks/{id}/test   send a test event now and report

The URL has to be public, the same check the automation key's callback
uses: nothing on this box or a private network, so a hook cannot aim the
platform at its own routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import events_out
from auth import CurrentUser, current_user
from routes_automation import callback_problem

router = APIRouter(prefix="/events")


class HookIn(BaseModel):
    url: str = Field(min_length=1, max_length=events_out.MAX_URL)
    events: list[str] | None = None
    label: str = Field(default="", max_length=200)


class HookPatch(BaseModel):
    enabled: bool | None = None
    events: list[str] | None = None
    label: str | None = Field(default=None, max_length=200)


@router.get("/hooks")
async def list_hooks(user: CurrentUser = Depends(current_user)) -> dict:
    return {"hooks": await events_out.hooks_for(user.email), "events": list(events_out.EVENTS)}


@router.post("/hooks")
async def make_hook(body: HookIn, user: CurrentUser = Depends(current_user)) -> dict:
    problem = await callback_problem(body.url)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    try:
        return await events_out.create(user.email, body.url, body.events, body.label)
    except events_out.TooMany:
        raise HTTPException(
            status_code=409,
            detail=f"You have {events_out.MAX_HOOKS} hooks, which is the limit. "
                   "Delete one to make another.")


@router.patch("/hooks/{hook_id}")
async def change_hook(hook_id: str, body: HookPatch,
                      user: CurrentUser = Depends(current_user)) -> dict:
    changes: dict = {}
    if body.enabled is not None:
        changes["enabled"] = bool(body.enabled)
    if body.events is not None:
        changes["events"] = events_out.clean_events(body.events)
    if body.label is not None:
        changes["label"] = " ".join(body.label.split())[:events_out.MAX_LABEL]
    row = await events_out.update(user.email, hook_id, changes)
    if row is None:
        raise HTTPException(status_code=404, detail="No such hook.")
    return row


@router.delete("/hooks/{hook_id}")
async def drop_hook(hook_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    return {"deleted": await events_out.delete(user.email, hook_id)}


@router.post("/hooks/{hook_id}/test")
async def test_hook(hook_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    ok = await events_out.test_hook(user.email, hook_id)
    return {"ok": ok, "note": "The URL answered." if ok else "The URL did not answer with success. Check it and try again."}
