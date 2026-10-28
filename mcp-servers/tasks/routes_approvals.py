"""Approvals from anywhere: the routes, and the one place an answer lands.

    GET    /api/tasks/approvals                 what is waiting for this person
    POST   /api/tasks/approvals/{id}/decide     {"approved": true|false}
    GET    /api/tasks/approvals/rules           standing rules
    POST   /api/tasks/approvals/rules           {"tool", "decision", "when_contains", "label"}
    DELETE /api/tasks/approvals/rules/{id}

`decide` is also what the main chat calls for a bare yes or no when the
chat itself holds nothing (routes_agent_turn.chat). Wherever the answer
comes from, the same thing happens: the row is settled first, so two
answers cannot both run the call; the turn is resumed; and the result
goes where the question came from: an automation's own delivery, or the
agent's conversation in the office for a question born in the main chat,
since nothing can be pushed into an Open WebUI chat afterwards.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import agent_approvals
import automations
import events_out
from auth import CurrentUser, current_user

logger = logging.getLogger("routes_approvals")
router = APIRouter(prefix="/approvals")

ALREADY = "That question was already answered, or has expired."
HOW_TO_ANSWER = ("Answer on the Agents page under Automation, or say yes or no "
                 "in the main chat.")
STATUS_WAITING = "waiting"


def question_for(agent_name: str, calls) -> str:
    from routes_agent_turn import approval_question
    return approval_question(agent_name, calls)


async def _resume(email: str, agent_id: str, conversation, calls, approved: bool) -> dict:
    from routes_agent_turn import _resume_turn
    return await _resume_turn(user_email=email, agent_id=agent_id,
                              conversation=list(conversation or []),
                              calls=list(calls or []), approved=approved)


async def _clear_chat_hold(state_key: str) -> None:
    from routes_agent_turn import _clear_pending
    await _clear_pending(state_key)


async def _deliver_automation(email: str, automation_id: str, agent_name: str,
                              status: str, text: str) -> str:
    import automation_runner
    rule = await automations.get(email, automation_id)
    if rule is None:
        return "none"
    rule = dict(rule, user_email=email)
    delivered = await automation_runner.deliver(rule, agent_name, status, text)
    await automations.record_run(email, automation_id, status, "approval answered",
                                 text, delivered)
    return delivered


async def _deliver_chat(email: str, agent_id: str, agent_name: str, text: str) -> str:
    import automation_runner
    try:
        return await automation_runner._to_chat(email, agent_id, agent_name,
                                                "Answered from the Agents page", text)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not post the answered question's result", exc_info=True)
        return "not delivered"


#: Seams.
_resume_seam = _resume
_clear_chat_hold_seam = _clear_chat_hold
_deliver_automation_seam = _deliver_automation
_deliver_chat_seam = _deliver_chat


async def hold_and_tell(email: str, agent_id: str, agent_name: str, pending: dict,
                        origin: str, origin_ref: str) -> dict | None:
    """Write a held question down and say how to answer it. Returns the
    row, or None when it could not be written."""
    question = question_for(agent_name, pending.get("calls") or [])
    row = await agent_approvals.hold(email, agent_id, agent_name, pending,
                                     origin, origin_ref, question)
    if row:
        events_out.emit(email, "approval.requested", {
            "approval_id": row["id"], "agent_id": agent_id, "agent_name": agent_name,
            "origin": origin, "origin_ref": origin_ref, "question": question,
            "tools": [str(((c.get("function") or {}).get("name")) or "")
                      for c in pending.get("calls") or [] if isinstance(c, dict)]})
    return row


async def decide(email: str, approval_id: str, approved: bool, via: str) -> dict:
    """Answer one held question. Returns {"status", "answer", "notes",
    "agent", "delivered"}; status is done, waiting (it asked again),
    failed, or already (nothing left to answer). Never raises."""
    row = await agent_approvals.get(email, approval_id, with_held=True)
    if row is None or row.get("status") != agent_approvals.STATUS_PENDING:
        return {"status": "already", "answer": ALREADY, "notes": [], "agent": None,
                "delivered": "none"}
    agent = {"id": row["agent_id"], "name": row.get("agent_name") or row["agent_id"]}
    # Settled before anything runs: whoever settles it runs it, nobody else.
    if not await agent_approvals.settle(email, approval_id, approved, via):
        return {"status": "already", "answer": ALREADY, "notes": [], "agent": agent,
                "delivered": "none"}
    if row.get("origin") == agent_approvals.ORIGIN_CHAT and row.get("origin_ref"):
        await _clear_chat_hold_seam(row["origin_ref"])
    try:
        out = await _resume_seam(email, row["agent_id"], row.get("conversation"),
                                 row.get("calls"), approved)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not resume approval %s", approval_id, exc_info=True)
        out = {"answer": "", "notes": ["The agent could not finish this run."]}
        status = "failed"
    else:
        status = "done"
    pending = out.get("pending") if isinstance(out.get("pending"), dict) else None
    answer = str(out.get("answer") or "")
    notes = [n for n in (out.get("notes") or []) if isinstance(n, str)]
    if pending and pending.get("calls"):
        # It asked again. Same place, new row, and the question is what is
        # delivered rather than an answer.
        again = await hold_and_tell(email, agent["id"], agent["name"], pending,
                                    row.get("origin"), row.get("origin_ref") or "")
        status = STATUS_WAITING
        answer = question_for(agent["name"], pending["calls"]) + "\n\n" + HOW_TO_ANSWER
        if again is None:
            notes.append("The question could not be written down, so it cannot be answered later.")
    shown = answer or "\n".join(notes)
    delivered = "none"
    if shown:
        if row.get("origin") == agent_approvals.ORIGIN_AUTOMATION and row.get("origin_ref"):
            delivered = await _deliver_automation_seam(
                email, row["origin_ref"], agent["name"], status, shown)
        elif row.get("origin") == agent_approvals.ORIGIN_CHAT and via != agent_approvals.VIA_CHAT:
            delivered = await _deliver_chat_seam(email, agent["id"], agent["name"], shown)
    events_out.emit(email, "approval.decided", {
        "approval_id": approval_id, "agent_id": agent["id"], "agent_name": agent["name"],
        "approved": approved, "via": via, "origin": row.get("origin"),
        "status": status, "answer": answer, "notes": notes, "delivered": delivered})
    return {"status": status, "answer": answer, "notes": notes, "agent": agent,
            "delivered": delivered}


# --- the routes -------------------------------------------------------------------

class DecideIn(BaseModel):
    approved: bool


class RuleIn(BaseModel):
    tool: str = Field(min_length=1, max_length=200)
    decision: str
    when_contains: str = Field(default="", max_length=200)
    label: str = Field(default="", max_length=200)


@router.get("")
async def list_pending(user: CurrentUser = Depends(current_user)) -> dict:
    return {"approvals": await agent_approvals.pending_for(user.email)}


@router.post("/{approval_id}/decide")
async def decide_route(approval_id: str, body: DecideIn,
                       user: CurrentUser = Depends(current_user)) -> dict:
    out = await decide(user.email, approval_id, body.approved, agent_approvals.VIA_PAGE)
    if out["status"] == "already":
        raise HTTPException(status_code=409, detail=ALREADY)
    return out


@router.get("/rules")
async def list_rules(user: CurrentUser = Depends(current_user)) -> dict:
    return {"rules": await agent_approvals.rules_for(user.email)}


@router.post("/rules")
async def add_rule(body: RuleIn, user: CurrentUser = Depends(current_user)) -> dict:
    problem = agent_approvals.rule_problem(body.tool, body.decision, body.when_contains)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    try:
        return await agent_approvals.add_rule(user.email, body.tool, body.decision,
                                              body.when_contains, body.label)
    except agent_approvals.TooMany:
        raise HTTPException(
            status_code=409,
            detail=f"You have {agent_approvals.MAX_RULES} rules, which is the limit. "
                   "Delete one to make another.")


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    return {"deleted": await agent_approvals.delete_rule(user.email, rule_id)}
