"""Jev decides who handles a message to the whole team.

Jev is TypeSafe's decision model: it picks from fixed options and says how
sure it is, and writes no text. Before the lead triages a team message
(agent_job_triage), it is asked two questions in one call: is this one
answer or a job, and which agent should take it. Sure of both, and the
answer is one answer, only that agent replies. Sure it is a job, the lead
writes the plan as before. Anything else is today's path.
See docs/plans/2026-10-19-jev-decider-and-glm-design.md.

decide() never raises. No key means no call and no row, and every message
takes today's path, so this ships switched off until TYPESAFE_API_KEY is
passed to the container. A slow, failing or unreadable Jev is a recorded
fallback: the worst it costs is the time limit.

Request shape checked against docs.typesafe.ai and a real call on
2026-10-20 (HTTP 200, 0.28 s, 436 input tokens).
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import text as sql_text

from db import session

logger = logging.getLogger(__name__)

URL = os.environ.get("TYPESAFE_URL", "https://api.typesafe.ai/v1/systemone")

#: The person waits on this before anybody answers. TypeSafe states 70 to
#: 500 ms and the real call took 0.28 s; past this it is not worth waiting.
TIMEOUT_SECONDS = 2.0

#: The most the round waits for a decision to be written.
RECORD_TIMEOUT_SECONDS = 1.0

#: A fixed version, not the jev-latest alias: TypeSafe moves the alias to
#: each new release, and the cut-offs here were measured on 1.13. JEV_MODEL
#: overrides it for a deliberate move, after a calibration run on the new one.
MODEL_DEFAULT = "jev-1.13.0"


def model() -> str:
    return os.environ.get("JEV_MODEL", "").strip() or MODEL_DEFAULT


#: Dollars per million input tokens; output is free (TypeSafe, 2026-10).
PRICE_PER_M_INPUT = 0.042

#: How much of the conversation Jev reads besides the message itself.
HISTORY_LINES = 6
LINE_CHARS = 300
ROLE_CHARS = 120

PROVIDER = "jev"
PATH_ONE_AGENT = "one_agent"
PATH_PLAN = "plan"
PATH_FALLBACK = "fallback"

KIND_INSTRUCTIONS = (
    "Can one team member answer the new message in one reply, or does it "
    "need several pieces of work by different team members?")
KIND_CRITERIA = {
    "answer": "one team member can handle it in a single reply",
    "job": "it needs several pieces of work by different team members",
}
WHO_INSTRUCTIONS = ("Which one team member is best placed to handle the new "
                    "message?")


@dataclass
class Decision:
    path: str
    kind: str | None = None
    kind_confidence: float | None = None
    agent_id: str | None = None
    agent_confidence: float | None = None
    reason: str = ""
    ms: int = 0
    model: str | None = None
    input_tokens: int | None = None


def _min_confidence() -> float:
    """JEV_MIN_CONFIDENCE, 0.8 by default. TypeSafe's own thresholds are
    examples, not defaults, so ours is a setting to check against the
    recorded decisions."""
    try:
        return float(os.environ.get("JEV_MIN_CONFIDENCE", "0.8"))
    except ValueError:
        return 0.8


def _key() -> str:
    return os.environ.get("TYPESAFE_API_KEY", "").strip()


def enabled() -> bool:
    """Whether decide() would call Jev at all."""
    return bool(_key())


def _role(agent: dict) -> str:
    meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
    for field in ("role", "description"):
        value = meta.get(field)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:ROLE_CHARS]
    return "team member"


def _named(agents: list[dict]) -> list[dict]:
    return [a for a in agents if isinstance(a, dict)
            and isinstance(a.get("name"), str) and a["name"].strip()]


def build_request(message: str, history: list[dict],
                  agents: list[dict]) -> dict | None:
    """The body for one Jev call, or None when the team cannot be offered
    as choices: fewer than two named agents, or two sharing a name."""
    named = _named(agents)
    names = [a["name"].strip() for a in named]
    if len(names) < 2 or len(set(names)) != len(names):
        return None
    message = (message or "").strip()
    earlier = [m for m in history or [] if isinstance(m, dict)]
    # The round's history ends with the message itself; it is the last line
    # of the state, not repeated above it.
    if (earlier and earlier[-1].get("role") == "user"
            and str(earlier[-1].get("content") or "").strip() == message):
        earlier = earlier[:-1]
    lines = []
    for m in earlier[-HISTORY_LINES:]:
        who = "person" if m.get("role") == "user" else "agent"
        text = " ".join(str(m.get("content") or "").split())[:LINE_CHARS]
        if text:
            lines.append(f"{who}: {text}")
    team = "\n".join(f"- {a['name'].strip()} ({_role(a)})" for a in named)
    state = "Team:\n" + team
    if lines:
        state += "\n\nRecent conversation:\n" + "\n".join(lines)
    state += "\n\nNew message to the whole team:\n" + message
    return {
        "state": state,
        "model": model(),
        "questions": {
            "kind": {"type": "choice", "instructions": KIND_INSTRUCTIONS,
                     "criteria": dict(KIND_CRITERIA)},
            "who": {"type": "choice", "instructions": WHO_INSTRUCTIONS,
                    "criteria": {a["name"].strip(): _role(a) for a in named}},
        },
    }


def _choice(answers: dict, qid: str) -> tuple[str, float]:
    a = answers[qid]
    choice, conf = a["choice"], a["confidence"]
    if not isinstance(choice, str) or isinstance(conf, bool) \
            or not isinstance(conf, (int, float)):
        raise ValueError(qid)
    return choice, float(conf)


def read_answer(data, agents: list[dict]) -> Decision:
    """What Jev's reply means for the round. Never raises."""
    try:
        answers = data["answers"]
        kind, kc = _choice(answers, "kind")
        if kind not in KIND_CRITERIA:
            raise ValueError(kind)
        who, wc = _choice(answers, "who")
        by_name = {a["name"].strip(): a for a in _named(agents)}
        if who not in by_name:
            raise ValueError(who)
        agent_id = str(by_name[who].get("id") or "")
        model = data.get("model") if isinstance(data.get("model"), str) \
            else None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) \
            else {}
        tokens = usage.get("input_tokens")
        tokens = tokens if isinstance(tokens, int) else None
    except Exception:                                       # noqa: BLE001
        return Decision(path=PATH_FALLBACK, reason="unreadable answer")
    least = _min_confidence()
    if kind == "answer" and kc >= least and wc >= least:
        path, reason = PATH_ONE_AGENT, ""
    elif kind == "job" and kc >= least:
        path, reason = PATH_PLAN, ""
    else:
        path, reason = PATH_FALLBACK, "low confidence"
    return Decision(path=path, kind=kind, kind_confidence=kc,
                    agent_id=agent_id, agent_confidence=wc, reason=reason,
                    model=model, input_tokens=tokens)


def cost_usd(input_tokens: int | None) -> float | None:
    if input_tokens is None:
        return None
    return input_tokens * PRICE_PER_M_INPUT / 1_000_000


async def _post(body: dict, key: str) -> dict:
    """One call to Jev. Raises on a timeout or any non-2xx answer."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await asyncio.wait_for(
            client.post(URL, json=body,
                        headers={"Authorization": f"Bearer {key}"}),
            TIMEOUT_SECONDS + 0.5)
        r.raise_for_status()
        return r.json()


async def record(email: str, chat_id: str | None, decision: Decision) -> None:
    """Store one decision. Bookkeeping: logs and returns on any failure."""
    try:
        async with session() as s:
            await s.execute(sql_text(
                "INSERT INTO tasks.agent_decision (user_email, chat_id, "
                "provider, model, kind, kind_confidence, agent_id, "
                "agent_confidence, path, reason, ms, input_tokens, cost_usd) "
                "VALUES (:email, :chat, :provider, :model, :kind, :kc, "
                ":agent, :ac, :path, :reason, :ms, :tokens, :cost)"),
                {"email": email, "chat": chat_id, "provider": PROVIDER,
                 "model": decision.model, "kind": decision.kind,
                 "kc": decision.kind_confidence, "agent": decision.agent_id,
                 "ac": decision.agent_confidence, "path": decision.path,
                 "reason": decision.reason or None, "ms": decision.ms,
                 "tokens": decision.input_tokens,
                 "cost": cost_usd(decision.input_tokens)})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("agent decider: could not record a decision",
                       exc_info=True)


async def recent(email: str, limit: int = 50) -> list[dict]:
    """This person's latest decisions, newest first. Raises on failure."""
    async with session() as s:
        rows = await s.execute(sql_text(
            "SELECT created_at, provider, model, kind, kind_confidence, "
            "agent_id, agent_confidence, path, reason, ms, input_tokens, "
            "cost_usd FROM tasks.agent_decision "
            "WHERE lower(user_email) = lower(:email) "
            "ORDER BY created_at DESC, id DESC LIMIT :limit"),
            {"email": email, "limit": limit})
        return [dict(r._mapping) for r in rows]


async def decide(email: str, chat_id: str | None, message: str,
                 history: list[dict], agents: list[dict]) -> Decision | None:
    """Jev's decision about one team message, or None with no key.
    Never raises."""
    key = _key()
    if not key:
        return None
    started = time.monotonic()
    body = build_request(message, history, agents)
    if body is None:
        reason = ("too few named agents" if len(_named(agents)) < 2
                  else "names not unique")
        decision = Decision(path=PATH_FALLBACK, reason=reason)
    else:
        try:
            data = await _post(body, key)
            decision = read_answer(data, agents)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            decision = Decision(path=PATH_FALLBACK, reason="timeout")
        except Exception as e:                              # noqa: BLE001
            # The class name only: an HTTP error's text can carry the request.
            logger.warning("agent decider: Jev call failed (%s)",
                           type(e).__name__)
            decision = Decision(path=PATH_FALLBACK,
                                reason=f"error: {type(e).__name__}")
    decision.ms = int((time.monotonic() - started) * 1000)
    # Bounded: the person is waiting, and a busy connection pool would
    # otherwise hold the round for its 30 s pool timeout over bookkeeping.
    try:
        await asyncio.wait_for(record(email, chat_id, decision),
                               RECORD_TIMEOUT_SECONDS)
    except Exception:                                       # noqa: BLE001
        logger.warning("agent decider: recording failed or was slow",
                       exc_info=True)
    return decision
