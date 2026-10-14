"""The lead agent decides whether a team message is one answer or a job.

One extra completion per message to the whole team, made by the lead before
the round runs. It has the summariser's settings (routes_agent_chat
._summarise) for the summariser's reason: this is a reading job, so tools
are off, there is one iteration, and no intent is passed, which keeps the
call on the free models. Deciding how to split work is never worth the paid
model; the paid model stays reachable inside a step, under its daily cap.

Never raises, and anything short of a valid plan is None: an error, a slow
or busy model, or an answer agent_job_plan will not accept. None means the
round runs exactly as it did before jobs existed, so the worst a broken
triage can do is cost one free call and a short wait.
"""
import asyncio
import logging

import agent_access
import agent_job_plan
# Imported as names on this module, not used as attributes of their own
# modules, so a test patches them here, as routes_agent_chat's tests patch
# the summariser's.
from agent_runner import FREE_POOL_EXHAUSTED, ROUTER_EXHAUSTED, _chat
from routes_agent_turn import _resolve_agent

logger = logging.getLogger(__name__)

#: The word the fake model (dev/fake-llm) looks for to play a triage, and a
#: way to find these calls in a log.
TRIAGE_MARKER = "TEAM_TRIAGE"

#: The person is waiting on this before anybody answers, so it is far shorter
#: than a chat turn's 60 seconds. A triage that takes longer is abandoned and
#: the round goes ahead as normal.
TRIAGE_TIMEOUT_SECONDS = 25

#: The outer bound over the whole call. TRIAGE_TIMEOUT_SECONDS bounds one
#: HTTP completion; the runner can still spend time around it (the token, a
#: fallback id), and the person must not wait on that either.
TRIAGE_GRACE_SECONDS = 5

TRIAGE_INSTRUCTION = (
    "TEAM_TRIAGE. You lead this team: {names}. Decide how to handle the "
    "person's last message. If one answer in the chat is enough, reply "
    'exactly {{"kind": "answer"}}. If it needs several pieces of work by '
    "different team members, reply with a plan as JSON: "
    '{{"kind": "job", "steps": [{{"agent": "<a name from the team>", '
    '"do": "<what that member should do, one sentence>"}}]}} with 2 to 6 '
    "steps in the order they should happen. Reply with the JSON only.")


def _team_names(roster: list[dict]) -> str:
    return ", ".join(a["name"].strip() for a in roster
                     if isinstance(a, dict) and isinstance(a.get("name"), str)
                     and a["name"].strip())


async def _ask(email: str, lead: dict, roster: list[dict],
               history: list[dict]) -> str:
    token, _tools, _level = await _resolve_agent(email, lead["id"])
    instruction = TRIAGE_INSTRUCTION.format(names=_team_names(roster))
    answer, _notes = await _chat(
        token=token, model=lead["id"], agent=lead,
        messages=list(history) + [{"role": "user", "content": instruction}],
        tool_ids=None, user_email=email,
        tool_mode=agent_access.MODE_READ_ONLY,
        refusal_reason="triage does not run tools",
        max_iterations=1, timeout=TRIAGE_TIMEOUT_SECONDS,
        intent=None)
    return answer or ""


async def triage(email: str, lead: dict, roster: list[dict],
                 history: list[dict]) -> list[dict] | None:
    """Steps for a job, or None to run the round as today. Never raises."""
    if not lead or not roster:
        return None
    try:
        answer = await asyncio.wait_for(
            _ask(email, lead, roster, history),
            TRIAGE_TIMEOUT_SECONDS + TRIAGE_GRACE_SECONDS)
    except Exception:                                       # noqa: BLE001
        # TimeoutError included: a triage that could not decide in time
        # decides nothing.
        logger.warning("agent jobs: triage failed, the round runs as normal",
                       exc_info=True)
        return None
    answer = answer.strip()
    # The busy sentences are answers, not exceptions: the free pool and the
    # router report giving up by saying so. Neither is a plan.
    if answer in (FREE_POOL_EXHAUSTED, ROUTER_EXHAUSTED):
        logger.warning("agent jobs: triage could not reach a model")
        return None
    return agent_job_plan.parse_triage(answer, roster)
