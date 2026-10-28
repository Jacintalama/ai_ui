"""What one firing of an automation does (2026-10-27).

The agent runs the same turn it runs from Discord and from an automation
key (routes_agent_turn._run_turn on the automation surface: only an agent
set to All acts, nobody is there to ask), on one message made of the rule's
instructions and what was posted. Then the answer goes where the rule
says: into the agent's private conversation in the office, into the
person's Discord thread, or nowhere but the caller's reply. The run is
written down either way, so the page can show the last few.

Never raises. A workflow that posted a form, or a person reading the page,
gets a status and a sentence, not a stack trace. Every outward call is a
seam that tests replace.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import agent_access
import agent_approvals
import agent_events
import automations
from routes_agent_turn import _run_turn
from routes_automation import _slots

logger = logging.getLogger("automation_runner")

STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
#: The agent stopped to ask; the answer comes when somebody says yes.
STATUS_WAITING = "waiting"

TURN_FAILED = "The agent could not finish this run."
NO_DISCORD = ("not delivered: no Discord thread is linked to this account; "
              "link Discord and the next run will be posted there")
NOT_DELIVERED = "not delivered: the chat could not be written"


# --- delivery -------------------------------------------------------------------

async def _to_chat(email: str, agent_id: str, agent_name: str,
                   rule_name: str, answer: str) -> str:
    """Append the answer to the person's private conversation with this
    agent, as a bubble under a note saying which automation ran. The
    office dock and the Agents page both read that conversation."""
    import agent_chat_store as store
    from routes_agent_chat import _hydrate
    s = store.get_session(email, agent_id)
    await _hydrate(email, s, agent_id)
    now = datetime.now(timezone.utc).isoformat()
    s.messages.append({"role": "note", "content": f"Automation ran: {rule_name}"})
    s.messages.append({"role": "assistant", "at": now, "agent_id": agent_id,
                       "agent_name": agent_name, "content": answer,
                       "replying_to": None, "automation": rule_name})
    if s.chat_id is None:
        s.chat_id = await store.create_chat(email, rule_name, s, agent_id)
    else:
        await store.save_chat(email, s)
    agent_events.publish("speaking_started", agent_id=agent_id, user_email=email,
                         chars=len(answer), source="automation")
    return "chat"


async def _discord_thread_for(email: str) -> str | None:
    from sqlalchemy import select
    from db import session
    from models import DiscordLink
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.email == email,
                                      DiscordLink.status == "approved")
        )).scalars().first()
    return link.schedules_thread_id if link else None


async def _to_discord(email: str, rule_name: str, status: str, answer: str) -> str:
    thread = await _discord_thread_seam(email)
    if not thread:
        return NO_DISCORD
    from scheduler import _deliver_result
    await _deliver_result(thread, "discord", rule_name,
                          "completed" if status == STATUS_DONE else status, answer)
    return "discord"


#: Seams.
_run_turn_seam = _run_turn
_to_chat_seam = _to_chat
_to_discord_seam = _to_discord
_discord_thread_seam = _discord_thread_for


async def deliver(automation: dict, agent_name: str, status: str, answer: str) -> str:
    """Where the answer went, as a word, or a sentence saying why not."""
    where = automation.get("deliver_to")
    try:
        if where == automations.DELIVER_CHAT:
            return await _to_chat_seam(automation["user_email"], automation["agent_id"],
                                       agent_name, automation["name"], answer)
        if where == automations.DELIVER_DISCORD:
            return await _to_discord_seam(automation["user_email"], automation["name"],
                                          status, answer)
    except Exception:                                       # noqa: BLE001
        logger.warning("automation %s: delivery to %s failed", automation.get("id"),
                       where, exc_info=True)
        return NOT_DELIVERED
    return "none"


async def fire(automation: dict, payload, agent_name: str = "") -> dict:
    """Run the automation on what was posted. Returns
    {"status", "answer", "notes", "delivered"}. Never raises."""
    email = automation["user_email"]
    message = automations.message_for(automation["instructions"], payload)
    summary = automations.trigger_summary(payload)
    try:
        async with _slots:
            out = await _run_turn_seam(
                email, automation["agent_id"], [{"role": "user", "content": message}],
                brief=True, surface=agent_access.SURFACE_AUTOMATION)
        answer = str(out.get("answer") or "")
        notes = [n for n in (out.get("notes") or []) if isinstance(n, str)]
        status = STATUS_DONE
        held = out.get("pending") if isinstance(out.get("pending"), dict) else None
        if held and held.get("calls"):
            # The agent stopped to ask. Written down with an id so it can
            # be answered from the Agents page or the main chat
            # (agent_approvals, 2026-10-28); what is delivered now is the
            # question, and the answer follows when somebody says yes.
            import routes_approvals
            row = await routes_approvals.hold_and_tell(
                email, automation["agent_id"], agent_name or automation["agent_id"],
                held, agent_approvals.ORIGIN_AUTOMATION, str(automation["id"]))
            status = STATUS_WAITING
            answer = (routes_approvals.question_for(agent_name or automation["agent_id"],
                                                    held["calls"])
                      + "\n\n" + routes_approvals.HOW_TO_ANSWER)
            if row is None:
                notes.append("The question could not be written down, so it "
                             "cannot be answered later.")
    except Exception as exc:                                # noqa: BLE001
        detail = getattr(exc, "detail", None)
        logger.warning("automation %s: the turn failed", automation.get("id"),
                       exc_info=detail is None)
        answer, notes, status = "", [str(detail) if detail else TURN_FAILED], STATUS_FAILED
    shown = answer or "\n".join(notes)
    delivered = await deliver(automation, agent_name or automation["agent_id"],
                              status, shown) if shown else "none"
    await automations.record_run(email, automation["id"], status, summary,
                                 shown, delivered)
    return {"status": status, "answer": answer, "notes": notes, "delivered": delivered}
