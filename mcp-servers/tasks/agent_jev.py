"""Small Jev checks beside the team decider.

agent_decider asks Jev who handles a team message. This module asks it the
smaller questions the agents used to answer with word lists: is this a plain
question, is this turn worth remembering, which version did the person mean,
did that reply answer the message, is the person done with the agent.

Each check is one Jev call holding one question, and returns a decision or
None. None always means "do what the code did before": no key, a timeout, an
HTTP error, an unreadable answer, the daily cap, or an answer below its
cut-off. Nothing here raises into the caller.

One row per call in tasks.jev_check for the Debug page and for checking the
cut-offs against real use. No message text, for the reason migration 057
gives. Design: docs/plans/2026-10-23-jev-checks.md.
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import httpx
from sqlalchemy import text as sql_text

import agent_decider
from db import session

logger = logging.getLogger(__name__)

#: Calls per process per UTC day, after which every check returns None until
#: the date changes. 2000 calls at the measured 300 to 450 input tokens is
#: about $0.04 a day. 0 switches the checks off.
DAILY_CALLS_DEFAULT = 2000

PURPOSE_PLAIN = "plain_question"
PURPOSE_REFLECT = "worth_remembering"
PURPOSE_ROLLBACK = "rollback_version"
PURPOSE_REPLY = "reply_answers"
PURPOSE_RELEASE = "release"
PURPOSE_TOOLS = "tool_pick"

#: Where each check acts. A Choice (plain question, rollback version) and the
#: release yes act at or above their cut; the reflection and reply checks act
#: on a no, at or below theirs. Measured 2026-10-23 on jev-1.13.0 with
#: scripts/jev_checks_calibrate.py, two runs of 56 labelled cases, by the
#: rule fixed before the runs (docs/plans/2026-10-23-jev-checks.md): no case
#: was acted on wrongly at any cut in either run, so each is one step in from
#: the edge of the measured range. JEV_CUT_<PURPOSE> overrides one; a cut out
#: of reach (above 1, below 0) switches it off.
CUTS = {PURPOSE_PLAIN: 0.6, PURPOSE_ROLLBACK: 0.6, PURPOSE_RELEASE: 0.6,
        PURPOSE_REFLECT: 0.3, PURPOSE_REPLY: 0.3,
        # Measured 2026-10-27, 14 labelled messages x 2 runs: no needed tool
        # missed at 0.8 or below; one step of margin. A missed tool breaks
        # the answer, an extra one costs a few tokens (9 extras at 0.75).
        PURPOSE_TOOLS: 0.75}


def cut(purpose: str) -> float:
    try:
        return float(os.environ.get(f"JEV_CUT_{purpose.upper()}", "").strip()
                     or CUTS[purpose])
    except ValueError:
        return CUTS[purpose]


@dataclass
class Answer:
    """Jev's answer to one question. `choice` is the picked option for a
    Choice and None for a Noul; `value` is the Choice's confidence or the
    Noul's probability of yes."""
    choice: str | None
    value: float
    model: str | None = None
    input_tokens: int | None = None
    ms: int = 0


def _daily_cap() -> int:
    try:
        return int(os.environ.get("JEV_DAILY_CALLS", "").strip()
                   or DAILY_CALLS_DEFAULT)
    except ValueError:
        return DAILY_CALLS_DEFAULT


_calls = {"day": "", "n": 0}


def _take_call() -> bool:
    """Count one call against today's cap, or False when it is spent."""
    day = datetime.now(timezone.utc).date().isoformat()
    if _calls["day"] != day:
        _calls["day"], _calls["n"] = day, 0
    if _calls["n"] >= _daily_cap():
        return False
    _calls["n"] += 1
    return True


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def read(data, qid: str = "q") -> Answer | None:
    """The answer under `qid`, or None when it is not one Jev would send."""
    try:
        a = data["answers"][qid]
        if a.get("type") == "noul":
            choice, value = None, a["noul"]
        else:
            choice, value = a["choice"], a["confidence"]
            if not isinstance(choice, str):
                return None
        if not _number(value) or not 0 <= value <= 1:
            return None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) \
            else {}
        tokens = usage.get("input_tokens")
        model = data.get("model")
        return Answer(choice=choice, value=float(value),
                      model=model if isinstance(model, str) else None,
                      input_tokens=tokens if isinstance(tokens, int)
                      else None)
    except Exception:                                       # noqa: BLE001
        return None


async def _post(body: dict, key: str) -> dict:
    return await agent_decider._post(body, key)


async def record(row: dict) -> None:
    """Store one check. Bookkeeping: logs and returns on any failure."""
    try:
        async with session() as s:
            await s.execute(sql_text(
                "INSERT INTO tasks.jev_check (user_email, purpose, model, "
                "choice, value, outcome, reason, ms, input_tokens, cost_usd) "
                "VALUES (:user_email, :purpose, :model, :choice, :value, "
                ":outcome, :reason, :ms, :input_tokens, :cost_usd)"),
                {k: row.get(k) for k in (
                    "user_email", "purpose", "model", "choice", "value",
                    "outcome", "reason", "ms", "input_tokens", "cost_usd")})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("jev check: could not record a check", exc_info=True)


async def _call(state, questions: dict) -> tuple[dict | None, str, str]:
    """One request to Jev: (reply, reason it failed, key). Never raises."""
    key = agent_decider._key()
    if not key:
        return None, "no key", ""
    if not _take_call():
        return None, "daily cap", key
    body = {"model": agent_decider.model(), "state": state,
            "questions": questions}
    try:
        return await _post(body, key), "", key
    except (httpx.TimeoutException, asyncio.TimeoutError):
        return None, "timeout", key
    except Exception as e:                                  # noqa: BLE001
        # The class name only: an HTTP error's text can carry the request.
        logger.warning("jev check: call failed (%s)", type(e).__name__)
        return None, f"error: {type(e).__name__}", key


async def _note(email: str, purpose: str, ms: int, reason: str,
                got: Answer | None = None, outcome: str = "fallback",
                choice: str | None = None, value: float | None = None,
                model: str | None = None,
                input_tokens: int | None = None) -> None:
    """Record one call. Bounded, as the decider's record is: somebody may be
    waiting."""
    row = {"user_email": email, "purpose": purpose,
           "model": got.model if got else model,
           "choice": got.choice if got else choice,
           "value": got.value if got else value,
           "outcome": outcome, "reason": reason or None, "ms": ms,
           "input_tokens": got.input_tokens if got else input_tokens,
           "cost_usd": agent_decider.cost_usd(
               got.input_tokens if got else input_tokens)}
    try:
        await asyncio.wait_for(record(row),
                               agent_decider.RECORD_TIMEOUT_SECONDS)
    except Exception:                                       # noqa: BLE001
        logger.warning("jev check: recording failed or was slow",
                       exc_info=True)


async def ask(email: str, purpose: str, state, question: dict,
              outcome: Callable[[Answer], str] | None = None
              ) -> Answer | None:
    """Put one question to Jev about `state`. Never raises.

    `outcome` names what the caller will do with the answer, for the row.
    """
    if not agent_decider._key():
        return None
    started = time.monotonic()
    data, reason, _ = await _call(state, {"q": question})
    answer = read(data) if data is not None else None
    if answer is None and not reason:
        reason = "unreadable answer"
    ms = int((time.monotonic() - started) * 1000)
    done = "fallback"
    if answer is not None:
        answer.ms = ms
        if outcome is not None:
            try:
                done = outcome(answer)
            except Exception:                               # noqa: BLE001
                done = "fallback"
    await _note(email, purpose, ms, reason, answer, done)
    return answer


async def ask_many(email: str, purpose: str, state, questions: dict,
                   outcome: Callable[[dict], tuple[str, float | None]]
                   | None = None) -> dict | None:
    """Several questions about one state in one call, as Jev's fan-out
    pattern intends: {question id: Answer}, or None unless every one of them
    came back readable. One row: `outcome` turns the answers into what the
    caller did and the number worth keeping. Never raises."""
    if not agent_decider._key():
        return None
    started = time.monotonic()
    data, reason, _ = await _call(state, questions)
    answers = None
    got = {qid: read(data, qid) for qid in questions}
    if all(a is not None for a in got.values()):
        answers = got
    elif not reason:
        reason = "unreadable answer"
    ms = int((time.monotonic() - started) * 1000)
    done, value, model, tokens = "fallback", None, None, None
    if answers:
        first = next(iter(answers.values()))
        model, tokens = first.model, first.input_tokens
        if outcome is not None:
            try:
                done, value = outcome(answers)
            except Exception:                               # noqa: BLE001
                done, value = "fallback", None
    await _note(email, purpose, ms, reason, None, done, None, value, model,
                tokens)
    return answers


def _sure_choice(answer: Answer | None, purpose: str,
                 options) -> str | None:
    """The picked option when Jev was sure of it and it is one of ours."""
    if answer is None or answer.choice not in options:
        return None
    return answer.choice if answer.value >= cut(purpose) else None


def _no(answer: Answer | None, purpose: str) -> bool | None:
    """For a check that acts on a no: False when Jev is sure of the no, True
    when it is as sure of the yes, None otherwise."""
    if answer is None:
        return None
    if answer.value <= cut(purpose):
        return False
    return True if answer.value >= 1 - cut(purpose) else None


#: How much of each side of an exchange a check reads.
EXCHANGE_CHARS = 1200


def _clip(text) -> str:
    return " ".join(str(text or "").split())[:EXCHANGE_CHARS]


# Each check has a request builder, used here and by
# scripts/jev_checks_calibrate.py, so the cut-offs are measured on exactly
# the question production asks.

# --- the paid move (agent_escalation.decide) --------------------------------

PLAIN_INSTRUCTIONS = (
    "The agent is in the middle of work for this person. Is the new message "
    "a plain question about something else, or is it about that work?")
PLAIN_CRITERIA = {
    "plain": "a question about something other than the work, such as a "
             "calendar, a fact, an opinion or another topic",
    "work": "about the work in hand: the app, site, code, build, files or "
            "task, including a request to change it or a question about why "
            "it failed",
}


def plain_request(text: str) -> tuple[str, dict]:
    return ("New message:\n" + _clip(text),
            {"type": "choice", "instructions": PLAIN_INSTRUCTIONS,
             "criteria": dict(PLAIN_CRITERIA)})


async def plain_question(email: str, text: str) -> bool | None:
    """True when Jev is sure the message is a plain question (the turn goes
    back to the free model), False when it is sure it is about the work
    (it stays paid), None to leave it to is_plain_question."""
    state, question = plain_request(text)
    answer = await ask(
        email, PURPOSE_PLAIN, state, question,
        outcome=lambda a: (_sure_choice(a, PURPOSE_PLAIN, PLAIN_CRITERIA)
                           or "fallback"))
    choice = _sure_choice(answer, PURPOSE_PLAIN, PLAIN_CRITERIA)
    return None if choice is None else choice == "plain"


# --- the reflection (agent_memory._reflect_now) -----------------------------

REFLECT_INSTRUCTIONS = (
    "Does this exchange tell us something about the person, their work, their "
    "projects or their preferences that is worth remembering for later "
    "conversations?")
REFLECT_CRITERIA = {
    "true": "it states a lasting fact, preference, decision, name, plan or "
            "piece of context about the person or their work",
    "false": "it is small talk, a one-off lookup or a question whose answer "
             "will not matter later",
}


def reflect_request(user_text: str, answer: str) -> tuple[str, dict]:
    return ("The person wrote:\n" + _clip(user_text)
            + "\n\nThe agent answered:\n" + _clip(answer),
            {"type": "noul", "instructions": REFLECT_INSTRUCTIONS,
             "criteria": dict(REFLECT_CRITERIA)})


async def worth_remembering(email: str, user_text: str,
                            answer: str) -> bool | None:
    """False when Jev is sure the turn holds nothing to remember (the
    reflection is skipped), True when it is sure it does, None otherwise.
    Only False changes anything."""
    state, question = reflect_request(user_text, answer)
    got = await ask(
        email, PURPOSE_REFLECT, state, question,
        outcome=lambda a: ("skip" if _no(a, PURPOSE_REFLECT) is False
                           else "reflect"))
    return _no(got, PURPOSE_REFLECT)


# --- the rollback (routes_aiuibuilder.resolve_rollback_target) --------------

#: The newest versions offered. More options spread the probability thinner,
#: and "before the thing we just added" is about recent work.
ROLLBACK_VERSIONS = 12
ROLLBACK_INSTRUCTIONS = (
    "The person wants to go back to before something they name. Which "
    "version's change added or started that thing?")


def rollback_request(phrase: str, versions: list[dict]
                     ) -> tuple[str, dict, dict] | None:
    """State, question and {short sha: version}, or None with fewer than two
    versions to choose from."""
    offered = [v for v in versions[:ROLLBACK_VERSIONS]
               if isinstance(v, dict) and v.get("short_sha")]
    by_sha = {v["short_sha"]: v for v in offered}
    if len(by_sha) < 2:
        return None
    criteria = {sha: " ".join(str(v.get("message") or "").split())[:200]
                for sha, v in by_sha.items()}
    return ("The person said:\n" + _clip(phrase),
            {"type": "choice", "instructions": ROLLBACK_INSTRUCTIONS,
             "criteria": criteria}, by_sha)


async def rollback_version(email: str, phrase: str,
                           versions: list[dict]) -> dict | None:
    """The version Jev is sure added what the phrase names, or None.

    The caller goes one version older (rollback_pick.before_version). The
    pick is always an element of `versions`: it is matched back by short sha.
    """
    built = rollback_request(phrase, versions)
    if built is None:
        return None
    state, question, by_sha = built
    answer = await ask(
        email, PURPOSE_ROLLBACK, state, question,
        outcome=lambda a: ("picked" if _sure_choice(a, PURPOSE_ROLLBACK,
                                                    by_sha) else "fallback"))
    sha = _sure_choice(answer, PURPOSE_ROLLBACK, by_sha)
    return by_sha[sha] if sha else None


# --- the reply check (routes_agent_chat._run_round) -------------------------

REPLY_INSTRUCTIONS = "Does the reply answer the person's message?"
REPLY_CRITERIA = {
    "true": "the reply answers or does what the message asked, or says "
            "clearly why it cannot",
    "false": "the reply misses the point, answers a different question or "
             "only says it will look into it",
}


def reply_request(message: str, reply: str) -> tuple[str, dict]:
    return ("The person's message:\n" + _clip(message)
            + "\n\nThe reply:\n" + _clip(reply),
            {"type": "noul", "instructions": REPLY_INSTRUCTIONS,
             "criteria": dict(REPLY_CRITERIA)})


async def reply_answers(email: str, message: str, reply: str) -> bool | None:
    """False when Jev is sure the reply did not answer the message (the rest
    of the room gets a turn), True when sure it did, None otherwise."""
    state, question = reply_request(message, reply)
    got = await ask(
        email, PURPOSE_REPLY, state, question,
        outcome=lambda a: ("not answered" if _no(a, PURPOSE_REPLY) is False
                           else "answered"))
    return _no(got, PURPOSE_REPLY)


# --- release (routes_agent_turn.chat) ---------------------------------------

RELEASE_INSTRUCTIONS = (
    "Is the person saying they are finished with this agent for now and "
    "want to stop talking to it?")
RELEASE_CRITERIA = {
    "true": "they are ending the conversation with the agent or dismissing "
            "it, for example done for now, that is all, you can go",
    "false": "they are answering it, agreeing, thanking it while still "
             "working, or asking for something more",
}


def release_request(text: str) -> tuple[str, dict]:
    return ("The person wrote:\n" + _clip(text),
            {"type": "noul", "instructions": RELEASE_INSTRUCTIONS,
             "criteria": dict(RELEASE_CRITERIA)})


async def wants_release(email: str, text: str) -> bool | None:
    """True when Jev is sure the person is done with the agent, False when
    it is not sure of that, None when it could not be asked."""
    state, question = release_request(text)
    got = await ask(
        email, PURPOSE_RELEASE, state, question,
        outcome=lambda a: ("released" if a.value >= cut(PURPOSE_RELEASE)
                           else "kept"))
    return None if got is None else got.value >= cut(PURPOSE_RELEASE)


# --- the main chat's tools (main_assistant, routes_agent_turn.chat) --------

#: What each tool is for, in the words a person would use. A tool not listed
#: here is described by its id, which is better than leaving it out.
TOOL_NOTES = {
    "gmail": "reading, searching, drafting or sending the person's email",
    "calendar": "the person's calendar: events, meetings, appointments, free "
                "time, scheduling",
    "gdrive": "finding or reading files, documents and spreadsheets in the "
              "person's Google Drive",
    "documents": "documents the person uploaded here or wants made: "
                 "reading, writing, or listing the ones they have",
    "excel_creator": "making a spreadsheet or Excel file",
    "executive_dashboard": "a summary dashboard of the person's business "
                           "numbers",
    "code": "the person's built apps and their code: reading, changing or "
            "building an app",
    "account": "the person's own account: their apps, connected services, "
               "usage and settings",
    "schedules": "the person's own cron jobs and recurring tasks that "
                 "the platform runs for them: making, listing, changing "
                 "or deleting something that runs on a timer. Not "
                 "meetings or appointments, which are the calendar",
    "remember": "saving or recalling a fact the person asked to remember",
    "skills": "the person's skills: looking one up, or listing the "
              "skills and procedures they have set up",
    "video": "the person's videos: making one, or listing the videos "
             "they have already made",
    "colleague": "asking one of the person's agents for help",
    "agents": "asking the person's agents a question",
    "agent_builder": "making new AI agents or a team of agents for the "
                     "person, or listing their agents",
    "automations": "rules that run one of the person's agents when something "
                   "happens or arrives (a lead, a form, a webhook, an event), "
                   "not on a timer: making, listing, pausing or deleting them",
    # Measured against the live router on 2026-10-30, not reasoned about.
    # Four ways of asking about a connected Trello picked this tool 3 times
    # out of 12 while the note read "GitHub, Notion, ClickUp, n8n
    # workflows". Naming the apps and what is inside them took it to 12 out
    # of 12 with the controls unmoved. "can you see my trello?" went 0/3 to
    # 3/3, and 0/3 is the chat answering "I don't have any tools available
    # here" about an app the person had just connected.
    #
    # The rule this leaves behind, pinned in
    # tests/test_connected_apps_are_reachable.py: an app the platform can
    # act in has to be NAMED here, or it is unreachable from the main chat
    # however well the rest of it works.
    "server:mcp-proxy": "the apps the person connected and the web: their "
                        "Trello boards, lists and cards, ClickUp tasks, "
                        "GitHub repositories and issues, Notion pages, "
                        "Airtable bases, HubSpot contacts, n8n workflows "
                        "and Zapier zaps, plus web search, flights and the "
                        "knowledge graph of past chats and meetings. Seeing "
                        "what is in one of them, listing it, or adding to "
                        "it",
}


#: How much of the conversation Jev is shown behind the latest message.
#: Enough for a follow-up to inherit its subject, not so much that an old
#: topic outweighs the current one.
CONTEXT_CHARS = 900


def tools_request(text: str, tools: list[str],
                  context: str = "") -> tuple[str, dict]:
    """One Noul per tool, ids t0, t1, ... in the order given.

    `context` is what was said just before, and it exists because without it
    this check read one orphan sentence. Measured on the live box
    2026-10-29, a person asking for a daily quote agent:

        13:56:42  agent_builder,schedules  0.89   describing it
        13:57:38  agent_builder            0.84   still describing it
        13:57:48  none                     0.34   "create it please"

    "create it please" has no subject in it, so Jev picked nothing, the
    assistant never ran, and the plain free model answered "I can't
    actually create agents or scheduled cron jobs inside your platform" --
    which is false, and is the platform denying its own feature at the
    moment somebody asked for it. The capability vanished exactly when it
    was wanted, because agreement is always the shortest message.

    Empty context gives the question the old wording verbatim, so the
    calibration cases (scripts/jev_checks_calibrate.py) still measure what
    they measured before.
    """
    questions = {}
    for i, tool in enumerate(tools):
        note = TOOL_NOTES.get(tool) or f"the tool called {tool}"
        questions[f"t{i}"] = {
            "type": "noul",
            "instructions": f"To answer or do what the message asks, is a "
                            f"tool for {note} needed?",
            "criteria": {
                "true": "the message asks for something this tool reads, "
                        "finds or does",
                "false": "the message can be answered without it, or is "
                         "about something else",
            }}
    if not str(context or "").strip():
        return "The person wrote:\n" + _clip(text), questions
    # The latest message last and labelled, so it is plainly the one being
    # judged and the rest is there only to give it a subject.
    return ("Earlier in this conversation:\n"
            + " ".join(str(context).split())[:CONTEXT_CHARS]
            + "\n\nThe person has now written:\n" + _clip(text)), questions


async def pick_tools(email: str, text: str, tools: list[str],
                     context: str = "") -> list[str] | None:
    """The tools Jev is sure this message needs, in the order given: [] when
    it needs none, None when Jev could not be asked or answered unreadably
    (the caller then offers every tool, as before). Never raises.

    `context` is what was said just before. A follow-up carries no subject of
    its own ("create it please", "yes do it", "go ahead"), and agreement is
    always the shortest message, so without it the tools go missing at
    exactly the moment somebody says go.
    """
    tools = [t for t in tools or [] if isinstance(t, str) and t]
    if not tools:
        return []
    state, questions = tools_request(text, tools, context)
    least = cut(PURPOSE_TOOLS)

    def picked(answers: dict) -> list[str]:
        return [tools[int(q[1:])] for q, a in answers.items()
                if a.value >= least]

    def outcome(answers: dict) -> tuple[str, float | None]:
        chosen = picked(answers)
        top = max((a.value for a in answers.values()), default=None)
        return (",".join(chosen) or "none"), top

    answers = await ask_many(email, PURPOSE_TOOLS, state, questions,
                             outcome=outcome)
    return None if answers is None else picked(answers)
