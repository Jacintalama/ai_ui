"""Approvals from anywhere (2026-10-28).

An agent on Ask stops before anything that sends, creates or changes, and
asks. Until now the question lived only where it was asked: the main
chat's held call, the office thread's bubble, a bot's buttons. An
automation has no chat, so its agent could only read. Now:

- A held question is a row (tasks.approval) with an id. It can be answered
  from the Agents page, from the main chat with a bare yes or no, or over a
  route; it expires on its own; and whoever answers, the turn picks up
  exactly where it stopped (routes_agent_turn._resume_turn).
- A person can set standing rules (tasks.approval_rule): allow or deny a
  tool, always or when its arguments contain some text. A matching rule
  answers at once, in the tool loop, and nobody is asked.

The pure parts are at the top; the database calls at the bottom are seams
that tests replace.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("agent_approvals")

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REFUSED = "refused"
STATUS_EXPIRED = "expired"

ORIGIN_AUTOMATION = "automation"
ORIGIN_CHAT = "chat"
ORIGIN_API = "api"

ALLOW = "allow"
DENY = "deny"
DECISIONS = frozenset({ALLOW, DENY})

VIA_PAGE = "page"
VIA_CHAT = "chat"
VIA_RULE = "rule"
VIA_API = "api"

#: How long a question waits for an answer before it expires. A day: an
#: automation fires when nobody is watching, and a question answered a
#: week later would act on something nobody remembers.
TTL_SECONDS = 24 * 60 * 60
MAX_RULES = 30
MAX_RULE_TEXT = 120
#: What a run is told when its question ran out of time.
EXPIRED_SENTENCE = "Nobody approved this in time, so it was not done."


# --- standing rules -------------------------------------------------------------

def clean_tool(tool) -> str:
    return " ".join(str(tool or "").split())[:MAX_RULE_TEXT].lower()


def rule_problem(tool: str, decision: str, when_contains: str = "") -> str:
    """What is wrong with a rule, or "". Sentences for the page."""
    if not clean_tool(tool):
        # A proxy example on purpose: `my-clickup_*` is the shape that
        # covers one connected service, and nothing else here says it is
        # allowed, so it was unguessable.
        return ("Name the tool the rule is about, such as send_email, or "
                "my-clickup_* for everything in ClickUp.")
    if decision not in DECISIONS:
        return "A rule either allows or denies."
    if len(str(when_contains or "")) > MAX_RULE_TEXT:
        return f"The text to match is at most {MAX_RULE_TEXT} characters."
    return ""


def _args_text(args) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False, default=str) if not isinstance(args, str) else args
    except (TypeError, ValueError):
        text = str(args)
    return text.lower()


def rule_decision(rules: list[dict], tool: str, args) -> dict | None:
    """The first rule that answers this call, or None. Deny wins over
    allow when both match: a person who wrote "never delete" meant it even
    if another rule allows everything."""
    # Imported here rather than at the top because this module is low level
    # and is imported early by the routes; agent_tools is not. One decision
    # in one place: that function is also what is_write_call and every
    # failure sentence use to find the real name.
    from agent_tools import called_tool_name

    # Both the name the loop sees and the tool it actually runs. Every one
    # of the proxy's ~200 tools arrives as `call_tool` with the real name
    # inside its arguments, so matching only the outer name meant a rule
    # naming the tool never fired for anything, and the only rule that did
    # fire covered web search, Trello, GitHub and deleting a ClickUp space
    # together. Measured 2026-11-09: 46 approvals asked, 0 rules written.
    #
    # The outer name still matches, on purpose. A rule written `call_tool`
    # is a blanket over the proxy today, and somebody who wrote it with
    # deny meant to stop proxy writes: narrowing that to nothing would be a
    # safety regression in the one direction that matters.
    names = []
    inner = called_tool_name(tool, args if isinstance(args, dict) else None)
    for candidate in (tool, inner):
        cleaned = clean_tool(candidate)
        if cleaned and cleaned not in names:
            names.append(cleaned)
    if not names:
        return None
    text = None
    hits = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        pattern = clean_tool(rule.get("tool"))
        if not pattern or not any(fnmatch.fnmatchcase(n, pattern)
                                  for n in names):
            continue
        needle = str(rule.get("when_contains") or "").strip().lower()
        if needle:
            if text is None:
                text = _args_text(args)
            if needle not in text:
                continue
        if rule.get("decision") in DECISIONS:
            hits.append(rule)
    if not hits:
        return None
    return next((r for r in hits if r["decision"] == DENY), hits[0])


# --- the rows --------------------------------------------------------------------

def _iso(dt) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else None


def row_of(a) -> dict:
    """An approval as the page and the routes see it: never the held
    conversation, which may hold the person's own mail."""
    return {"id": str(a.id), "agent_id": a.agent_id, "agent_name": a.agent_name or a.agent_id,
            "origin": a.origin, "origin_ref": a.origin_ref or "", "question": a.question or "",
            "status": a.status, "created_at": _iso(a.created_at), "expires_at": _iso(a.expires_at),
            "decided_at": _iso(a.decided_at), "decided_via": a.decided_via, "result": a.result or ""}


def rule_of(r) -> dict:
    return {"id": str(r.id), "tool": r.tool, "decision": r.decision,
            "when_contains": r.when_contains or "", "label": r.label or "",
            "created_at": _iso(r.created_at)}


class TooMany(Exception):
    pass


async def _create_row(email: str, fields: dict) -> dict:
    from db import session
    from models import Approval
    now = datetime.now(timezone.utc)
    row = Approval(id=uuid.uuid4(), user_email=email, status=STATUS_PENDING,
                   created_at=now, expires_at=now + timedelta(seconds=TTL_SECONDS), **fields)
    async with session() as s:
        s.add(row)
        await s.commit()
        return row_of(row)


async def _get_row(email: str, approval_id: str, with_held: bool = False) -> dict | None:
    from sqlalchemy import select
    from db import session
    from models import Approval
    try:
        aid = uuid.UUID(str(approval_id))
    except ValueError:
        return None
    async with session() as s:
        row = (await s.execute(
            select(Approval).where(Approval.id == aid, Approval.user_email == email)
        )).scalar_one_or_none()
        if row is None:
            return None
        out = row_of(row)
        if with_held:
            out["calls"] = row.calls
            out["conversation"] = row.conversation
        return out


async def _pending_rows(email: str) -> list[dict]:
    """Every pending question, oldest first; ones past their time are
    marked expired on the way and left out."""
    from sqlalchemy import select
    from db import session
    from models import Approval
    now = datetime.now(timezone.utc)
    out = []
    async with session() as s:
        rows = (await s.execute(
            select(Approval).where(Approval.user_email == email,
                                   Approval.status == STATUS_PENDING)
            .order_by(Approval.created_at))).scalars().all()
        for row in rows:
            if row.expires_at is not None and row.expires_at < now:
                row.status = STATUS_EXPIRED
                row.decided_at = now
                row.result = EXPIRED_SENTENCE
                continue
            out.append(row_of(row))
        await s.commit()
    return out


async def _settle_row(email: str, approval_id: str, status: str, via: str, result: str) -> bool:
    """Mark a pending row decided. False when it was not pending any more,
    so two answers cannot both run the call."""
    from sqlalchemy import select
    from db import session
    from models import Approval
    try:
        aid = uuid.UUID(str(approval_id))
    except ValueError:
        return False
    async with session() as s:
        row = (await s.execute(
            select(Approval).where(Approval.id == aid, Approval.user_email == email)
            .with_for_update())).scalar_one_or_none()
        if row is None or row.status != STATUS_PENDING:
            return False
        row.status = status
        row.decided_at = datetime.now(timezone.utc)
        row.decided_via = via
        row.result = (result or "")[:8000]
        await s.commit()
    return True


async def _rules_rows(email: str) -> list[dict]:
    from sqlalchemy import select
    from db import session
    from models import ApprovalRule
    async with session() as s:
        rows = (await s.execute(
            select(ApprovalRule).where(ApprovalRule.user_email == email)
            .order_by(ApprovalRule.created_at))).scalars().all()
    return [rule_of(r) for r in rows]


async def _add_rule_row(email: str, fields: dict) -> dict:
    from sqlalchemy import select, func
    from db import session
    from models import ApprovalRule
    async with session() as s:
        count = (await s.execute(
            select(func.count()).select_from(ApprovalRule)
            .where(ApprovalRule.user_email == email))).scalar_one()
        if count >= MAX_RULES:
            raise TooMany()
        row = ApprovalRule(id=uuid.uuid4(), user_email=email,
                           created_at=datetime.now(timezone.utc), **fields)
        s.add(row)
        await s.commit()
        return rule_of(row)


async def _delete_rule_row(email: str, rule_id: str) -> bool:
    from sqlalchemy import select
    from db import session
    from models import ApprovalRule
    try:
        rid = uuid.UUID(str(rule_id))
    except ValueError:
        return False
    async with session() as s:
        row = (await s.execute(
            select(ApprovalRule).where(ApprovalRule.id == rid,
                                       ApprovalRule.user_email == email))).scalar_one_or_none()
        if row is None:
            return False
        await s.delete(row)
        await s.commit()
    return True


#: Seams. Tests replace these rather than opening a database.
_create = _create_row
_get = _get_row
_pending = _pending_rows
_settle = _settle_row
_rules = _rules_rows
_add_rule = _add_rule_row
_delete_rule = _delete_rule_row


# --- what the callers use ------------------------------------------------------------

async def hold(email: str, agent_id: str, agent_name: str, pending: dict,
               origin: str, origin_ref: str, question: str) -> dict | None:
    """Write a held question down. None when it could not be: the caller
    then falls back to whatever it did before rows existed."""
    try:
        return await _create(email, {
            "agent_id": agent_id, "agent_name": agent_name or agent_id,
            "origin": origin, "origin_ref": origin_ref or "",
            "calls": list(pending.get("calls") or []),
            "conversation": list(pending.get("conversation") or []),
            "question": (question or "")[:4000]})
    except Exception:                                       # noqa: BLE001
        logger.warning("approval could not be written down", exc_info=True)
        return None


def is_answerable(row) -> bool:
    """True unless this question is about a call that cannot run.

    2026-11-06. Ralph said yes to creating a ClickUp space and was told
    "More than one question is waiting, so I did not guess which you
    meant", with four rows listed. Two were `refresh_cache`, which does
    not exist and 404s, so they could never be answered usefully and sat
    in the queue making every later yes ambiguous.

    `never_ask_about` stops new ones being created. This is about the ones
    already in the table, and about any future method that stops existing.

    The TTL is not the answer here. It is 24 hours on purpose, because an
    automation fires when nobody is watching. These were hours old and
    correctly unexpired; they were never answerable, which is a different
    thing.

    A row with no held calls is ANSWERABLE. Older rows and rows from other
    surfaces carry none, and they are somebody's real question: a check
    that cannot see inside a row must not throw it away.
    """
    import agent_tools

    if not isinstance(row, dict):
        return False

    held = row.get("held")
    calls = held.get("calls") if isinstance(held, dict) else None
    if isinstance(calls, list) and calls:
        for call in calls:
            fn = call.get("function") if isinstance(call, dict) else None
            name = fn.get("name") if isinstance(fn, dict) else None
            if not agent_tools.never_ask_about(name):
                return True
        return False

    # No held calls to read. `row_of` deliberately leaves them out,
    # because the held conversation can carry the person's own mail, and
    # `row_of` is what every route and the page see. So the names come
    # from the QUESTION, which approval_question built out of those same
    # names: a header line, then each tool indented under it.
    #
    # Reading the question is not a shortcut around the held calls. It is
    # the only thing a pending row carries, and the first version of this
    # check looked at `held` alone, found nothing, and let every one of
    # them through. It passed its tests because the tests built rows that
    # production never produces.
    names = _tools_named_in(row.get("question"))
    if not names:
        return True
    return any(not agent_tools.never_ask_about(n) for n in names)


def _tools_named_in(question) -> list[str]:
    """The tool names an approval question lists.

    approval_question writes a header, then "  <tool name>" per call, then
    arguments indented further under each. So a line with exactly two
    leading spaces and no colon is a tool name.
    """
    out = []
    for line in str(question or "").splitlines():
        if not line.startswith("  ") or line.startswith("     "):
            continue
        text = line.strip()
        if not text or ":" in text:
            continue
        out.append(text)
    return out


async def pending_for(email: str) -> list[dict]:
    """What is really waiting for this person.

    Questions about calls that cannot run are left out rather than
    deleted: the row is still the record of what an agent tried, and the
    Agents page can still show it. It simply stops being counted as
    something somebody has to answer.
    """
    try:
        return [r for r in await _pending(email) if is_answerable(r)]
    except Exception:                                       # noqa: BLE001
        logger.warning("approvals could not be read", exc_info=True)
        return []


async def get(email: str, approval_id: str, with_held: bool = False) -> dict | None:
    try:
        return await _get(email, approval_id, with_held)
    except Exception:                                       # noqa: BLE001
        logger.warning("approval could not be read", exc_info=True)
        return None


async def settle(email: str, approval_id: str, approved: bool, via: str,
                 result: str = "") -> bool:
    try:
        return await _settle(email, approval_id,
                             STATUS_APPROVED if approved else STATUS_REFUSED, via, result)
    except Exception:                                       # noqa: BLE001
        logger.warning("approval could not be settled", exc_info=True)
        return False


async def rules_for(email: str) -> list[dict]:
    """This person's standing rules. Never raises: with no rules, every
    question is asked, which is what happened before rules existed."""
    try:
        return await _rules(email)
    except Exception:                                       # noqa: BLE001
        logger.warning("approval rules could not be read", exc_info=True)
        return []


async def add_rule(email: str, tool: str, decision: str, when_contains: str = "",
                   label: str = "") -> dict:
    return await _add_rule(email, {"tool": clean_tool(tool), "decision": decision,
                                   "when_contains": str(when_contains or "").strip()[:MAX_RULE_TEXT],
                                   "label": " ".join(str(label or "").split())[:MAX_RULE_TEXT]})


async def delete_rule(email: str, rule_id: str) -> bool:
    return await _delete_rule(email, rule_id)
