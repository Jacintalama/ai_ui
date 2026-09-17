"""Run a schedule as one of the user's AI agents.

An agent is an Open WebUI model row, so running one means calling Open WebUI's
chat API with that model id. Two things make it more than that.

It has to act as the schedule's OWNER. A schedule belongs to one person, reads
their mail and their files, and fires whether or not they are online, so the
request is made with a token minted for them.

And it has to ASK for the agent's tools. Open WebUI attaches a model's own
tools only when the request comes from its own UI, which it recognises by the
session id; its middleware says API callers must request tools via tool_ids.
Without that field the agent arrives with its instructions and nothing it can
do, and answers that it cannot reach your mail.

Returns the same (status, result, extras) triple as the video path, so
_finalize_run stores and delivers it without knowing which kind of run it was.
"""
import logging
import os
import time

import httpx

import agent_access
import agent_activity
import agent_escalation
import agent_memory
from agent_tools import (arguments_of, execute_tool_call,
                         is_write_call, is_write_tool)
from owui_token import mint_owui_token

logger = logging.getLogger(__name__)

#: Enough of the last run to avoid repeating it, not so much that it crowds
#: out the actual task. last_result is capped at 8000 characters upstream.
MEMORY_EXCERPT_CHARS = 1200

#: A single tool result gets cut to this many characters before it is folded
#: back into the conversation. Each further iteration re-posts the whole
#: conversation, so an uncapped result is re-sent up to MAX_TOOL_ITERATIONS - 1
#: more times and can be large enough to get the request itself rejected.
#: Sized generously above an ordinary mail or calendar listing.
TOOL_RESULT_EXCERPT_CHARS = 6000

HTTP_TIMEOUT_SECONDS = 240

#: Said when the loop hits its cap. A sentinel rather than a sentence matched
#: twice: run_agent has to tell "stopped early with nothing to show" apart
#: from "answered, and also mentioned something", and comparing prose in two
#: files is how that kind of check rots.
RAN_OUT_OF_ROUNDS = "Stopped after %d rounds of tool use, so this answer may be incomplete."

#: Asked once, with no tools attached, after the last round is spent. The
#: reads the model did are real and already in the conversation; only the
#: writing is missing. Measured 2026-09-14: Kai spent seven rounds reading
#: five files of the shoe app, had what he needed to say why the new page was
#: not showing, and returned nothing but the note that he had stopped.
FINAL_ROUND_PROMPT = (
    "You have used every tool call you get for this reply. Answer now from "
    "what you have already read. Say plainly what you found, and name "
    "anything you did not get to check.")

#: How many times the model may ask for tools before we stop. Each iteration
#: is a full completion, so this bounds the run's wall clock as well as its
#: appetite.
#:
#: Eight, not five. Measured on the first real weekly review, 2026-09-11: one
#: run spent find_skills, use_skill, list_my_apps and list_my_schedules, four
#: of the five, and wrote a proper report; the run before it used all five and
#: returned nothing but the note saying so. Same schedule, same prompt, a
#: minute apart. So five was not a limit this work fits inside, it was a coin
#: toss with one round of margin, resolved weekly, unattended.
#:
#: Nothing forces a run to use them. The cost of the extra headroom is only
#: paid by a run that needs it, and this surface has no one waiting: the
#: comment on CHANNEL_MAX_TOOL_ITERATIONS below explains why a chat window
#: cannot be given the same slack.
MAX_TOOL_ITERATIONS = 8

#: A channel is somebody waiting at a keyboard, not a cron entry. The
#: schedule path's five rounds at 240 seconds each is a 20 minute worst
#: case, which is fine at 3am and absurd in a Discord window. The 60 second
#: timeout is what keeps this bounded.
#:
#: Five rounds, not three. Three was right until agents could look a skill
#: up: find_skills and use_skill cost two rounds between them, which left
#: one for the actual work. Seen live on 2026-09-10, gpt-5-mini found the
#: right skill, loaded it, read the mailbox, and was out of rounds before it
#: could answer, so the person got an empty bubble. Five at 60 seconds is a
#: five minute worst case, still comfortably inside the ten minute window
#: after which the card calls a chat run dead, which a test asserts.
#: Seven, not five. Measured 2026-09-14 on the first research turn that could
#: actually reach the web: a question needing a search and two pages costs
#: three rounds on a good run and hit the cap on a bad one, so five was the
#: same one-round margin the schedule path had, resolved per question instead
#: of per week. Unlike that one it fails visibly, saying it stopped early, so
#: it annoys rather than deceives.
#:
#: Seven is what the abandon window allowed when it was set, not a round
#: number: at 60 seconds each the rounds are seven minutes. The window is
#: not a count of rounds alone, though. A free agent can spend its fallback
#: ids inside the same turn, and since 2026-09-17 it can move to the paid
#: model, which adds paid rounds and a paid write-up. worst_turn_seconds
#: counts all of it, STALE_AFTER_CHANNEL is sized from that, and a test
#: asserts it, so raising this means raising the window with it.
CHANNEL_MAX_TOOL_ITERATIONS = 7
CHANNEL_HTTP_TIMEOUT_SECONDS = 60

#: The write-up after the tool cap carries every file and result the rounds
#: gathered, so it is the slowest completion of the run. Measured 2026-09-14:
#: gpt-5-mini took 22s for a plain turn with the brief, and Kai's write-up
#: after seven rounds of app files hit the 60s timeout and he said nothing.
#: Seven rounds at 60 plus this is nine minutes. A write-up can cost more
#: than one of these: a free agent can spend its fallback ids in it, and
#: since 2026-09-17 a paid write-up can time out before them, each at this
#: timeout. worst_turn_seconds counts that, and STALE_AFTER_CHANNEL follows.
FINAL_ROUND_MIN_TIMEOUT_SECONDS = 120


def _base_url() -> str:
    return os.environ.get("OPENWEBUI_URL", "http://open-webui:8080").rstrip("/")


async def _owui_user_id_for(email: str) -> str | None:
    """The Open WebUI user id behind an email.

    Imported lazily from routes_gateway so this module can be tested without
    pulling in the router and its dependencies.
    """
    from routes_gateway import _owui_user_id_for as resolve
    return await resolve(email)


async def _list_agents(token: str) -> tuple[list[dict], bool]:
    """The derived models this token's user can see, and whether the listing
    might be missing some.

    /api/v1/models/list rather than /api/models: the latter nests the row under
    `info` and deletes params server side. It pages at 30 on a one indexed
    `page`. The second element is True when the loop stopped before it could
    tell whether every row had been fetched -- the page guard tripped, a page
    came back with no usable `total`, or an empty batch arrived before `total`
    was reached. The caller must not read "not in what we got" as "does not
    exist" when this is True: the agent may simply be on a page this call
    never reached.
    """
    out: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(5):
            r = await client.get(
                f"{_base_url()}/api/v1/models/list?page={page}",
                headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
            batch = data.get("items") or []
            out.extend(batch)
            total = data.get("total")
            if not isinstance(total, int):
                return out, bool(batch)
            if not batch or len(out) >= total:
                return out, len(out) < total
            page += 1
    # The guard tripped: 5 pages fetched and still short of `total`.
    return out, True


#: What Open WebUI says when its in-memory model list is behind the database.
#: It says it two different ways, and only one of them was handled here.
#:
#: "Function not found" is the DERIVED model case: an agent whose base model
#: changed is still routed as whatever its base was when the cache was built,
#: so it looks for a pipe function by the new base's name. Seen live
#: 2026-09-08 as "Function not found: gpt-4o-mini" after two agents were
#: moved between models.
#:
#: "Model not found" is the NEW model case, and it is the more common one: a
#: model row created since the cache was built is not in it at all. Seen live
#: 2026-09-14, the first time an agent was created through the API rather than
#: the browser: five new agents, every turn 400ing, while the retry that
#: exists for exactly this sat there matching the other string.
#:
#: Both heal the same way, by calling /api/models, which is why one list.
_STALE_MODEL_DETAILS = ("Function not found", "Model not found")


def _is_stale_model_cache(response) -> bool:
    """True when this 400 means the model list needs rebuilding.

    Deliberately narrow. The repair below costs a whole extra completion, so
    it fires on this one signature at this one status and nothing near it: a
    500 carrying the same words is the server being broken, not a cache being
    behind, and retrying would only bill for the same failure twice.
    """
    if response.status_code != 400:
        return False
    try:
        detail = (response.json() or {}).get("detail")
    except Exception:                                       # noqa: BLE001
        # Not everything that answers this URL is Open WebUI. A proxy or a
        # gateway failing returns HTML, and .json() raises on it.
        return False
    return isinstance(detail, str) and any(d in detail for d in _STALE_MODEL_DETAILS)


async def _post_once(client, payload: dict, token: str):
    """The request itself. A seam, so the retry above it is testable."""
    return await client.post(
        f"{_base_url()}/api/chat/completions",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json=payload)


async def _refresh_models(client, token: str) -> None:
    """Make Open WebUI rebuild the model list it answers chats from.

    GET /api/models is what the browser calls on every page load, and it is
    what silently fixed this for weeks. Nothing else does: this service reads
    models through /api/v1/models/list, which comes off the database and
    leaves the cache exactly as stale as it found it.
    """
    r = await client.get(f"{_base_url()}/api/models",
                         headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()


async def _post_chat(payload: dict, token: str,
                     timeout: float = HTTP_TIMEOUT_SECONDS) -> dict:
    """One completion. Split out so the loop above it can be tested without
    a model, and so there is one place that knows the wire format.

    Retries exactly once, and only for a stale model cache. A model that
    genuinely does not exist answers the same way every time, and this sits
    inside a loop that runs up to MAX_TOOL_ITERATIONS times, so anything
    keener than once would multiply the cost of a failing run.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await _post_once(client, payload, token)
        if _is_stale_model_cache(r):
            logger.warning(
                "the model list looked stale, rebuilding it and trying again")
            try:
                await _refresh_models(client, token)
                r = await _post_once(client, payload, token)
            except Exception:                               # noqa: BLE001
                # The repair is not the job. If it fails, fall through and
                # let the completion's own failure be the one raised, rather
                # than replacing it with an error from the thing that was
                # trying to help.
                logger.warning("could not rebuild the model list",
                               exc_info=True)
        if r.status_code >= 400:
            # The body, before raise_for_status throws it away. It is Open
            # WebUI's own sentence and is the only thing that says WHY;
            # without it the log holds a stack trace and a status code, which
            # is what made this take four probes against production to find.
            # The token is in a header, never in the URL or the body, so
            # nothing here can leak it.
            logger.error("chat completion failed: %s %s",
                         r.status_code, (r.text or "")[:300])
        r.raise_for_status()
        return r.json()


#: The free-model router reports exhaustion by answering HTTP 200 with its
#: complaint as the assistant's content, so nothing downstream can tell it
#: from a real answer. Both halves are required: its own prefix appears on
#: successful routes too, where it names the model it picked and is useful.
_ROUTER_PREFIX = "[auto-router]"
_ROUTER_GAVE_UP = "rate-limited or failed"

#: What to say instead. The raw text names a model the person never chose and
#: an HTTP status code, neither of which tells them the one thing that would
#: fix it: their agent is on Auto (Free), which shares a pool that runs out.
ROUTER_EXHAUSTED = (
    "The free models are all busy right now, so this agent could not answer. "
    "It is set to Auto (Free), which shares a pool of free models that runs "
    "out. Choosing a specific model on the agent's card fixes this.")


def _router_gave_up(content) -> bool:
    """True when the free router answered with its own failure."""
    if not isinstance(content, str):
        return False
    return _ROUTER_PREFIX in content and _ROUTER_GAVE_UP in content


# --- free models ------------------------------------------------------------
#
# An agent's base model may be a free OpenRouter id. Free means no money and
# a shared quota, and free providers fall over, so two things follow. The
# payload asks for no reasoning, because measured 2026-09-15 a truncated
# reply from nemotron with reasoning on leaked its thinking into the answer,
# and with it off the same model answered in 1.1s with 0 reasoning tokens.
# And when a completion fails the way a provider fails, the same request is
# tried on the next id in the pool, posting the base model directly.

#: The pool, in order. The first entry is what new agents start on. Every
#: id was measured to answer a tool call on 2026-09-15: 1.3s, 3.0s, 7.2s.
FREE_MODELS = [m.strip() for m in os.environ.get(
    "AGENT_FREE_MODELS",
    "nvidia/nemotron-3-super-120b-a12b:free,"
    "nex-agi/nex-n2.5-pro:free,"
    "nex-agi/nex-n2.5-mini:free").split(",") if m.strip()]

#: Sent as reasoning_effort on every free completion. Open WebUI passes it
#: through untouched for a base model, and for a derived model whose own
#: params leave it unset.
FREE_REASONING = os.environ.get("AGENT_FREE_REASONING", "none")

#: What the person sees when every free model in the pool failed.
FREE_POOL_EXHAUSTED = (
    "The free models are all busy right now, so this agent could not "
    "answer. Try again in a few minutes.")

#: Open WebUI's one sentence for any upstream failure, 429 included.
_PROVIDER_ERROR_DETAIL = "Provider returned error"

_MODELS_URL = "https://openrouter.ai/api/v1/models"
_AVAILABLE_TTL_SECONDS = 900
_available_ids: set | None = None
_available_at = 0.0


def _is_free(model_id) -> bool:
    return isinstance(model_id, str) and model_id.endswith(":free")


def _provider_failed(exc_or_body) -> bool:
    """True when this looks like the provider, not the request, failing.

    Three shapes, all measured on production: an HTTPStatusError whose body
    is Open WebUI's "Provider returned error" or whose status is 402, 408,
    429 or 5xx; a 200 whose body carries an `error` object instead of
    choices; a 200 with no choices at all. The last two are one test below,
    because what makes both a failure is the missing choices and not the
    error key. A 401 or 403 is this service's own problem and is not retried
    anywhere.
    """
    if isinstance(exc_or_body, httpx.TimeoutException):
        return True
    if isinstance(exc_or_body, httpx.HTTPStatusError):
        status = exc_or_body.response.status_code
        if status in (401, 403):
            return False
        if status in (402, 408, 429) or status >= 500:
            return True
        try:
            detail = (exc_or_body.response.json() or {}).get("detail")
        except Exception:                                   # noqa: BLE001
            detail = exc_or_body.response.text
        return isinstance(detail, str) and _PROVIDER_ERROR_DETAIL in detail
    if isinstance(exc_or_body, dict):
        # Choices decide it, and an `error` key on its own does not. A body
        # that carries a completion AND a note about an upstream that was
        # retried is an answer, and reading it as a failure would throw the
        # answer away and spend a pool id to ask the question again.
        return not exc_or_body.get("choices")
    if isinstance(exc_or_body, BaseException):
        # Raised, but not by a provider: a bug in this file, or httpx
        # refusing to build the request. Falling back would run the same
        # broken thing three times and then blame the free models for it.
        return False
    # A 2xx carrying anything but an object: unreachable in theory, and in
    # practice it is what a proxy in the middle returns. Calling it a failure
    # moves the turn to the next id; calling it an answer reaches data.get
    # and takes the whole run down with an AttributeError.
    return True


async def _available_free_ids() -> set | None:
    """Free ids OpenRouter serves right now, cached a quarter hour, or None
    when the catalogue could not be read. None means "do not filter": a
    router that refuses every id because it could not read a list is worse
    than one that tries an id that turns out to be gone. A failed read is
    cached for that same quarter hour, so an unreachable catalogue costs one
    probe rather than one per turn. Same reasoning and the same endpoint as
    the Auto (Free) pipe. No key needed."""
    global _available_ids, _available_at
    now = time.time()
    # The stamp, not the contents, decides whether to probe. A failed read
    # leaves the contents empty, so keying on them would probe again on the
    # very next turn, which is exactly the case this cache exists for.
    if _available_at and now - _available_at < _AVAILABLE_TTL_SECONDS:
        return _available_ids
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_MODELS_URL)
            r.raise_for_status()
            ids = {m.get("id") for m in (r.json().get("data") or []) if m.get("id")}
    except Exception:                                       # noqa: BLE001
        # Stamped on the way out, so an unreachable catalogue is probed once
        # a quarter hour rather than once a turn. This sits in front of the
        # person's first token and the client waits up to 10 seconds, so the
        # unstamped version charged every turn 10 seconds for a list that is
        # only used to skip withdrawn ids. Logged, because a silent return
        # of None looks identical to a catalogue that lists everything.
        logger.warning("could not read the OpenRouter free catalogue",
                       exc_info=True)
        _available_at = now
        return _available_ids
    if ids:
        _available_ids = ids
    # Stamped whether or not anything usable came back. A catalogue that
    # answers 200 with no ids in it has still answered, and _fallback_pool
    # skips an empty set anyway, so probing it again on the next free turn
    # would buy nothing and cost the same 10 seconds. An empty read also
    # leaves the last good list in place rather than clearing it.
    _available_at = now
    return _available_ids


async def _fallback_pool(agent: dict | None) -> list[str]:
    """The free ids to try after the agent's own base, in order, or [] for
    an agent that is not on a free model (or no agent at all)."""
    base = (agent or {}).get("base_model_id")
    if not _is_free(base):
        return []
    available = await _available_free_ids()
    pool = [m for m in FREE_MODELS if m != base]
    if available:
        pool = [m for m in pool if m in available]
    return pool


def _agent_system(agent: dict | None) -> str:
    """The agent's own instructions, for a post that goes to the base model.

    params first, then meta.agent_instructions, because Open WebUI returns
    params on /api/v1/models/list only to a caller with WRITE access to the
    row, and blanks it for everybody else. A platform agent is read only to
    every user who is not its owner, so the agents this hits are the shared
    ones. The Agents page already reads the same pair for the same reason
    (instructionsOf in static/agents.html), and the copy in meta is written
    beside params precisely because it is not blanked.

    It matters most on a schedule. A chat turn carries the persona again in
    its identity line, so a fallback there loses a duplicate; a schedule has
    no identity line, so a fallback for a shared agent would post the raw
    base model with no instructions at all: the same agent, answering as
    nobody, once a week, to somebody who is not watching.

    Blank counts as absent, not as an answer: Open WebUI blanks the field
    rather than dropping the key, so reading the key alone would stop here
    with an empty string.
    """
    params = (agent or {}).get("params")
    params = params if isinstance(params, dict) else {}
    system = params.get("system")
    system = system.strip() if isinstance(system, str) else ""
    if system:
        return system
    meta = (agent or {}).get("meta")
    meta = meta if isinstance(meta, dict) else {}
    fallback = meta.get("agent_instructions")
    return fallback.strip() if isinstance(fallback, str) else ""


def worst_turn_seconds(max_iterations: int, timeout: float) -> float:
    """Every completion one turn can make, each at its full timeout, now
    that a free agent can move to the paid model partway through.

    Two shapes, and the worse one counts. Moving at the start: the one free
    answer that decided it, then every round on the paid model. Moving at
    the round cap: every round on the free model, then the paid model's
    extra rounds.

    Both end in the same slowest write-up. The paid write-up times out, the
    turn goes back to the free model it left, and that write-up spends every
    free id, each at the write-up timeout. That is where both failures cost
    most: a write-up is never given less time than a round, and a paid
    failure there comes after every paid round instead of replacing one.
    Spending the fallback ids in the rounds costs less for the same reason.

    Found by review on 2026-09-17, and checked the same day on a copy with
    the plan's Task 7 loop, by searching the runs of timeouts and tool calls
    through it with each post at its full timeout: 1170 seconds for a chat
    turn and 3600 for a schedule, which is what this returns. The first
    version stopped at a paid write-up that answered and said 930 and 3360.

    Assumes the agent's own base model is one of FREE_MODELS. An agent on a
    free id outside the pool has one more fallback id to spend.
    """
    extra_free = max(len(FREE_MODELS) - 1, 0)
    paid = agent_escalation.paid_timeout(timeout)
    free_write_up = max(timeout, FINAL_ROUND_MIN_TIMEOUT_SECONDS)
    paid_write_up = agent_escalation.paid_timeout(free_write_up)
    write_up = paid_write_up + (1 + extra_free) * free_write_up
    up_front = timeout + max_iterations * paid + write_up
    at_cap = (max_iterations * timeout
              + agent_escalation.PAID_EXTRA_ROUNDS * paid + write_up)
    return max(up_front, at_cap)


#: The chat token has to outlive the WHOLE loop, not one completion: the loop
#: can make up to MAX_TOOL_ITERATIONS sequential calls of up to
#: HTTP_TIMEOUT_SECONDS each, plus tool time in between. A token sized for a
#: single call expires partway through a run that needs two or more slow
#: iterations, which surfaces as the agent refusing rather than as the auth
#: failure it actually is.
#:
#: The free pool is counted, and since 2026-09-17 so is the move to the paid
#: model, which is why this is worst_turn_seconds and not a product of two
#: caps. An expired token is a 401, a 401 is deliberately not a provider
#: failure, and so it ends the run instead of moving it anywhere.
#:
#: On a schedule that is 8 free rounds and 3 paid rounds at 240 seconds, a
#: paid write-up that times out at 240, and a free write-up that spends all
#: three free ids at 240: 3600 seconds, and this is that plus a minute.
CHAT_TOKEN_TTL_SECONDS = int(
    worst_turn_seconds(MAX_TOOL_ITERATIONS, HTTP_TIMEOUT_SECONDS)) + 60


def _paid_failed(exc: BaseException) -> bool:
    """True when the paid model failed in a way worth going back to the free
    model for. Wider than _provider_failed on purpose: a paid id this box
    cannot route, or a parameter it rejects, is a 400 that says nothing about
    the provider, and the person should still get the free answer. A 401 or
    403 is this service's own token and ends the turn as it always did.

    A ValueError is a 200 whose body is not JSON: _post_chat's r.json()
    raises JSONDecodeError, or UnicodeDecodeError for bytes that are not
    text (checked against httpx 0.28.1 locally, 2026-09-17). That is the HTTP
    exchange failing too, and without this it ended the turn instead."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError,
                        ValueError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code not in (401, 403)
    return False


class _Escalation:
    """One turn's move to the paid model. At most once a turn: asked once,
    whatever the answer, so a capped or uncountable day costs one query and a
    paid model that failed is not tried again."""

    def __init__(self, *, enabled: bool, user_email: str, agent_id: str,
                 usage: "agent_escalation.TurnUsage") -> None:
        self.enabled = enabled
        self.user_email = user_email
        self.agent_id = agent_id
        self.usage = usage
        self.tried = False
        self.on_paid = False
        self.capped = False
        self.left_from: str | None = None

    @property
    def can_try(self) -> bool:
        return self.enabled and not self.tried

    async def switch(self, reason: str, active: str) -> bool:
        if not self.can_try:
            return False
        self.tried = True
        count = await agent_activity.paid_turns_today(self.user_email)
        if count is None:
            logger.warning("could not count paid turns today, %s stays on "
                           "the free model (%s)", self.agent_id, reason)
            return False
        if count >= agent_escalation.DAILY_CAP:
            self.capped = True
            logger.info("paid turn cap reached, %s stays on the free model "
                        "(%s)", self.agent_id, reason)
            return False
        self.on_paid = True
        # A spent pool has nothing to go back to; anything else goes back to
        # the free model it was on.
        self.left_from = None if reason == agent_escalation.REASON_POOL_SPENT else active
        self.usage.escalation = reason
        # No sticky window here. complete() opens it when a paid completion
        # answers. Opened at the move, a paid model that only fails would
        # move every later message again, each waiting out the paid timeout
        # and using a slot of the daily cap (review, 2026-09-17).
        await agent_activity.mark_escalated(self.usage.run_id, reason)
        logger.warning("agent %s moved to the paid model %s (%s)",
                       self.agent_id, agent_escalation.PAID_MODEL, reason)
        return True

    def fall_back(self) -> str | None:
        self.on_paid = False
        return self.left_from

    def with_note(self, content: str) -> str:
        """The answer, with the cap note once a day when the turn wanted the
        paid model and could not have it. In the answer, not in notes: the
        room draws the answer and drops the notes."""
        if (not self.capped or not content
                or agent_escalation.looks_like_pass(content)):
            return content
        note = agent_escalation.take_cap_note(self.user_email)
        return (content + "\n\n" + note) if note else content


async def _chat(token: str, model: str, messages: list[dict],
                tool_ids: list[str] | None, user_email: str,
                tool_mode: str | None,
                refusal_reason: str = "this schedule is set to read only",
                max_iterations: int = MAX_TOOL_ITERATIONS,
                timeout: float = HTTP_TIMEOUT_SECONDS,
                agent: dict | None = None,
                intent: "agent_escalation.Intent | None" = None,
                usage: "agent_escalation.TurnUsage | None" = None
                ) -> tuple[str, list[str]]:
    """Talk to the agent, running any tools it asks for, until it answers.

    Open WebUI injects the tool specs and returns the model's tool_calls, but
    it never runs them for an API caller: its execution loop lives on the
    socket path used by its own UI. So the execution and the feeding back
    happen here. Verified on production that handing a tool result back
    returns finish_reason "stop" and a real answer.

    Returns the answer and any notes about what was refused, which the caller
    shows the owner. A refusal is not an error: the run completes and says
    what it would not do.

    Raises ApprovalRequired when tool_mode is "ask" and the model asked for a
    write. Reads in the same batch have already run by then and their results
    are in the carried conversation, so resuming does not redo them.

    refusal_reason is the caller's words for why a write was blocked. It is
    a parameter rather than a constant because this loop serves both a
    schedule and a chat window, and "this schedule is set to read only" is
    false in a Discord DM.

    `agent` is the agent's own row (base_model_id, params.system). With it,
    an agent on a free model sends reasoning_effort and falls back through
    FREE_MODELS when the provider fails; without it the loop behaves exactly
    as it did before this parameter existed.

    `intent` (agent_escalation.Intent) is who is asking and how. With it, an
    agent on a free model may move to the paid model for the rest of the
    turn: at the start when the request is the kind free models do badly,
    or partway when the free model reaches for an app change tool, answers
    with nothing, spends its pool or its rounds. Without it the turn never
    leaves the free models, which is what the room summariser relies on.
    `usage` collects which model answered, why it moved and what it cost,
    for the caller to write with the run.
    """
    convo = list(messages)
    notes: list[str] = []
    mode = tool_mode or agent_access.MODE_READ_ONLY
    write_allowed = mode == agent_access.MODE_FULL
    # Set before the loop so a tuned-down max_iterations of 0 still has
    # something defined to return, instead of an UnboundLocalError.
    content = ""

    base = (agent or {}).get("base_model_id")
    free = _is_free(base)
    pool = await _fallback_pool(agent) if free else []
    active = model            # the model id posted; the agent id until a fallback
    instructions = _agent_system(agent)
    usage = usage if usage is not None else agent_escalation.TurnUsage()
    # Only a free agent moves, and only when its caller said who is asking.
    # An agent somebody put on a paid model stays exactly where they put it.
    esc = _Escalation(
        enabled=bool(free and intent is not None and agent_escalation.enabled()),
        user_email=user_email, agent_id=model, usage=usage)

    def billed(active_id: str) -> str:
        # Posting the agent id reaches its base model; that is what answered.
        if active_id == model and isinstance(base, str) and base:
            return base
        return active_id

    async def complete(convo_now: list[dict], with_tools: bool,
                       timeout_now: float) -> dict:
        """One completion on the active model, moving down the pool on a
        provider failure, onto the paid model when the pool is spent and the
        turn may move, and back off the paid model when it fails. Raises the
        last failure for a paid agent, and returns a body with no choices
        only when there is nothing left to try."""
        nonlocal active
        while True:
            msgs = convo_now
            if active != model and instructions:
                # Posting the base model directly, so Open WebUI will not
                # apply the agent's own instructions. They go first, where
                # the derived model would have put them.
                msgs = [{"role": "system", "content": instructions}] + convo_now
            payload: dict = {"model": active, "messages": msgs, "stream": False}
            if with_tools and tool_ids:
                payload["tool_ids"] = tool_ids
            # Decided per post, not once: the same turn can post a free id
            # and then the paid one, and "none" is a free model's setting.
            if esc.on_paid:
                if agent_escalation.PAID_REASONING:
                    payload["reasoning_effort"] = agent_escalation.PAID_REASONING
                this_timeout = agent_escalation.paid_timeout(timeout_now)
            else:
                if free and FREE_REASONING:
                    payload["reasoning_effort"] = FREE_REASONING
                this_timeout = timeout_now
            try:
                data = await _post_chat(payload, token, this_timeout)
            except Exception as exc:                            # noqa: BLE001
                # A paid agent keeps exactly the behaviour it had before
                # there was a pool: the failure is the caller's to see. For
                # a free agent a provider falling over is not news, so it
                # becomes the next id, and once there is no next id it
                # becomes the busy sentence below rather than a stack trace.
                # Anything that is not the provider failing, a 401 say, is
                # raised on either kind of agent.
                if not (free and (_provider_failed(exc)
                                  or (esc.on_paid and _paid_failed(exc)))):
                    raise
                data = None
            if data is not None and not _provider_failed(data):
                usage.add(billed(active), data.get("usage"))
                if esc.on_paid:
                    agent_escalation.mark_paid(user_email, model)
                    tokens = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                    logger.info("paid completion for %s on %s: %s prompt "
                                "tokens, %s completion tokens", model, active,
                                tokens.get("prompt_tokens"),
                                tokens.get("completion_tokens"))
                return data
            if esc.on_paid:
                back = esc.fall_back()
                logger.warning("the paid model %s failed for %s, back to %s",
                               active, model, back or "no free model")
                if back is None:
                    return data if isinstance(data, dict) else {}
                active = back
                continue
            if not pool:
                if esc.can_try and await esc.switch(
                        agent_escalation.REASON_POOL_SPENT, active):
                    active = agent_escalation.PAID_MODEL
                    continue
                # Nothing left to try. The caller reads a body with no
                # choices as the busy sentence for a free agent, and raises
                # its own "no answer" for a paid one, as it always did.
                if free:
                    # The only trace this turn leaves. The busy sentence
                    # reads like an answer, and _post_chat logs nothing at
                    # all when the failure was a timeout rather than a
                    # status, so without this line a turn that reached
                    # nobody is invisible in the log.
                    logger.warning("free pool spent for %s, last model %s",
                                   model, active)
                # Only a dict survives: the caller reads choices off this,
                # and a failed body that is not one would raise there.
                return data if isinstance(data, dict) else {}
            nxt = pool.pop(0)
            logger.warning("free model %s failed for %s, trying %s",
                           active, model, nxt)
            active = nxt

    # Before the first completion: the person's own words, and whether this
    # agent is already mid job for them. An agent in the room that was not
    # named is let decide on the free model first, so a room of seven that
    # hears "build me an app" does not pay seven times to hear six PASSes.
    probe_reason = None
    if esc.enabled:
        reason = agent_escalation.decide(
            intent, agent_escalation.in_window(user_email, model))
        if reason and intent.may_pass:
            probe_reason = reason
        elif reason and await esc.switch(reason, active):
            active = agent_escalation.PAID_MODEL

    rounds = 0
    limit = max_iterations
    while True:
        while rounds < limit:
            deciding = bool(intent is not None and intent.may_pass and rounds == 0)
            if (not deciding and esc.can_try and agent_escalation.too_long(convo)
                    and await esc.switch(
                        agent_escalation.REASON_LONG_CONVERSATION, active)):
                active = agent_escalation.PAID_MODEL
            data = await complete(convo, True, timeout)

            choices = data.get("choices") or []
            if not choices:
                if free:
                    return FREE_POOL_EXHAUSTED, notes
                raise RuntimeError("the model returned no answer")
            message = choices[0].get("message") or {}
            calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()

            reason = None
            if probe_reason and not (not calls
                                     and agent_escalation.looks_like_pass(content)):
                reason = probe_reason
            elif not calls and not content:
                reason = agent_escalation.REASON_EMPTY
            elif calls and agent_escalation.names_heavy_tool(calls):
                reason = agent_escalation.REASON_HEAVY_TOOL
            probe_reason = None
            if reason and esc.can_try and await esc.switch(reason, active):
                # Nothing in this reply has run, so asking again on the paid
                # model repeats no tool and does not use up a round.
                active = agent_escalation.PAID_MODEL
                continue

            if not calls:
                if _router_gave_up(content):
                    # A 200 carrying a failure. Said in words the owner can act
                    # on, rather than passing through a model name they never
                    # chose and an HTTP status code.
                    return ROUTER_EXHAUSTED, notes
                return esc.with_note(content), notes

            rounds += 1
            convo.append({"role": "assistant", "content": content,
                          "tool_calls": calls})
            pending: list[dict] = []
            for call in calls:
                # A tool call comes straight from a model, so its shape cannot be
                # trusted: `call` itself, its "function" object, or "name" inside
                # that can each be something other than what they should be. The
                # same nine shapes are already guarded one layer down in
                # execute_tool_call; guard them here too, before .strip() or
                # .get() can raise and take the whole run down with it. A call
                # that cannot be named degrades to a refused/unnamed call rather
                # than a fatal error.
                call = call if isinstance(call, dict) else {}
                fn = call.get("function")
                fn = fn if isinstance(fn, dict) else {}
                raw_name = fn.get("name")
                name = raw_name.strip() if isinstance(raw_name, str) else ""
                label = name or "an unnamed tool call"
                # Arguments included, because call_tool's own name says nothing
                # about what it runs: searching the web and creating a ClickUp
                # task arrive here under the same name.
                probe = arguments_of(call)
                if is_write_call(name, probe) and not write_allowed:
                    if mode == agent_access.MODE_ASK:
                        # Held back, not refused. The turn ends below and picks
                        # up again once the owner answers.
                        pending.append(call)
                        continue
                    notes.append(
                        "Declined to run " + label + ", because "
                        + refusal_reason + ".")
                    result = ("Refused: " + refusal_reason + ", so "
                              + label + " was not run.")
                else:
                    # tool_ids scopes which native tools this agent is even
                    # allowed to run, not only which ones the model was told
                    # about -- see execute_tool_call.
                    #
                    # `model` IS the agent id on every caller of this function
                    # (a schedule passes sched.agent_id, the chat panel and the
                    # turn endpoint pass agent_id), so it is what a tool acting
                    # as the agent has to be handed. Without it __model__ is
                    # always empty and a schedule an agent makes cannot run as
                    # that agent.
                    result = await execute_tool_call(call, user_email, tool_ids,
                                                     model)
                if isinstance(result, str) and len(result) > TOOL_RESULT_EXCERPT_CHARS:
                    result = (
                        result[:TOOL_RESULT_EXCERPT_CHARS]
                        + "\n\n[This tool result was shortened. It was longer "
                        "than " + str(TOOL_RESULT_EXCERPT_CHARS) + " characters.]")
                convo.append({"role": "tool", "tool_call_id": call.get("id"),
                              "name": name, "content": result})

            if pending:
                # Raised after the whole batch so the reads above are already
                # done and carried. Every held call still needs a tool message
                # before the next completion, which is what the resume writes.
                raise agent_access.ApprovalRequired(convo, pending)

        # The rounds are spent on the free models and the work is not done.
        # The paid model picks up the carried conversation, every tool result
        # included, with a few rounds of its own before the write-up.
        if limit > 0 and esc.can_try and await esc.switch(
                agent_escalation.REASON_ROUNDS_CAP, active):
            active = agent_escalation.PAID_MODEL
            limit += agent_escalation.PAID_EXTRA_ROUNDS
            continue
        break

    # The rounds are spent but the reading is not wasted. One more completion
    # with no tools attached makes the model write up what it gathered,
    # instead of the owner getting only a note that it stopped. No tool_ids
    # means Open WebUI attaches none; any tool_calls that come back anyway are
    # ignored rather than run, because running them is the round the cap
    # exists to refuse.
    #
    # Skipped when the cap is zero. That asks for no completions at all, and
    # answering it with one would be the loop overriding its own caller.
    final = ""
    if max_iterations > 0:
        convo.append({"role": "user", "content": FINAL_ROUND_PROMPT})
        try:
            data = await complete(convo, False,
                                  max(timeout, FINAL_ROUND_MIN_TIMEOUT_SECONDS))
            choices = data.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            final = (message.get("content") or "").strip()
        except Exception:                                   # noqa: BLE001
            logger.warning("the final answer round after the tool cap failed",
                           exc_info=True)
            final = ""
        if final and _router_gave_up(final):
            return ROUTER_EXHAUSTED, notes
    notes.append(RAN_OUT_OF_ROUNDS % limit)
    return esc.with_note(final or content), notes


def _messages_for(sched) -> list[dict]:
    """The task, preceded by a trimmed reminder of the last run when there is
    one. The CLI path this replaces kept a memory between runs, and dropping
    that would make every daily digest say the same thing every day.

    Only carried forward when the previous run actually completed.
    _finalize_run stores last_result for every status, including the
    runner's own synthetic failure sentences ("The agent could not finish
    this run...", "This agent tried to use one of its tools..."), and models
    routinely echo what they are handed. Without this check, one failed run
    poisons every run after it: the agent is handed its own failure message
    as "what you produced last time" and repeats it back."""
    last = (getattr(sched, "last_result", None) or "").strip()
    if getattr(sched, "last_run_status", None) != "completed":
        last = ""
    msgs: list[dict] = []
    if last:
        msgs.append({
            "role": "user",
            "content": ("For context, this is what you produced on the previous "
                        "run of this schedule. Do not repeat it; say what has "
                        "changed.\n\n" + last[:MEMORY_EXCERPT_CHARS]),
        })
    msgs.append({"role": "user", "content": sched.prompt})
    return msgs


async def run_agent(sched) -> tuple[str, str, dict]:
    """Run one schedule as its agent. Returns (status, result, extras).

    Never raises. _finalize_run dispatches this detached, so an escaping
    exception would vanish into a discarded task and leave the schedule stuck
    reporting that it is still running.
    """
    # Recorded so the Agents page can say whether this is awake and how long
    # it took. Fire and forget: a run must never fail because its bookkeeping
    # did, which is why start_run may return None and finish_run takes it.
    run_id = await agent_activity.start_run(
        getattr(sched, "agent_id", None), getattr(sched, "user_email", None),
        agent_activity.SOURCE_SCHEDULE)
    outcome = "failed"
    try:
        owner = await _owui_user_id_for(sched.user_email)
        if not owner:
            outcome = "failed"
            return ("failed",
                    "This schedule could not run: its owner has no account on "
                    "this platform any more.", {})

        # Mint a token for the listing phase. Same lifetime as the chat mint
        # below, not the 60s this used to carry: the listing loop itself can
        # make up to 5 sequential 30s-timeout requests, a worst case longer
        # than 60s, and a token expiring mid-loop would surface as a wrong
        # "agent no longer exists" rather than the auth failure it actually is.
        list_token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS)
        agents, truncated = await _list_agents(list_token)
        agent = next((a for a in agents
                      if isinstance(a, dict) and a.get("id") == sched.agent_id), None)
        if agent is None:
            if truncated:
                # Not in what we fetched is not the same as not existing: the
                # listing was cut short before it could see every agent, so
                # this may simply be further down a page we never reached.
                outcome = "failed"
                return ("failed",
                        "This schedule's agent could not be checked this "
                        "time. It will try again at the next scheduled "
                        "time.", {})
            outcome = "failed"
            return ("failed",
                    "This schedule is set to run as an agent that no longer "
                    "exists. Delete this schedule and create it again with "
                    "a different agent.", {})

        meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
        # The same resolution the chat path uses, not meta["toolIds"] read
        # raw. Measured 2026-09-10: reading it raw gave this agent one tool on
        # a schedule against twelve in chat, and the one was the connected
        # apps umbrella with nothing behind it, so a scheduled run could read
        # nothing at all while its card still promised every tool the owner
        # had. Imported here rather than at module scope because
        # routes_agent_turn imports this module, which is the same deferred
        # import scheduler.py uses to reach run_agent.
        from routes_agent_turn import tools_for_agent
        tools = await tools_for_agent(sched.user_email, meta)

        # Mint a long-lived token immediately before the chat call. The token
        # must outlive the WHOLE tool loop, not one call: up to
        # MAX_TOOL_ITERATIONS sequential completions of up to
        # HTTP_TIMEOUT_SECONDS each, plus tool time in between, or it expires
        # mid run, surfacing as the agent refusing rather than as an auth
        # error.
        chat_token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS)

        # The agent's own level is a ceiling over the schedule's tool_mode.
        # A schedule may narrow what its agent may do and may never widen it;
        # see agent_access. An agent with no level set falls through to
        # exactly the behaviour this had before the setting existed.
        level = agent_access.level_of(meta)
        mode = agent_access.effective_mode(
            level, getattr(sched, "tool_mode", None),
            agent_access.SURFACE_SCHEDULE)

        # What this agent remembers rides in front of the task, the same
        # block the chat surfaces carry. Empty when nothing is stored.
        messages = _messages_for(sched)
        try:
            memory = await agent_memory.recall_block(sched.user_email,
                                                     sched.agent_id)
        except Exception:                                   # noqa: BLE001
            # Optional by definition, and the same arm both chat sites give
            # it. recall_block already fails open, so this only catches a bug
            # in it, and a bug there must cost the memory rather than the run.
            # Without the arm it lands in run_agent's own catch-all, which
            # delivers "could not finish this run" and waits a week: the one
            # surface where nobody is there to try again.
            logger.warning("could not read agent memory for %s",
                           getattr(sched, "agent_id", None), exc_info=True)
            memory = ""
        if memory:
            messages = [{"role": "system", "content": memory}] + messages

        # Keyword arguments on purpose: the tests assert on them by name, and
        # a positional call here would silently drift from those assertions.
        answer, notes = await _chat(
            token=chat_token, model=sched.agent_id,
            agent=agent,
            messages=messages, tool_ids=tools or None,
            user_email=sched.user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, getattr(sched, "tool_mode", None),
                agent_access.SURFACE_SCHEDULE))
        if not answer and not notes:
            outcome = "failed"
            return ("failed", "The agent returned an empty answer.", {})
        # A run that spent every round and produced no answer is a failed run,
        # whatever the loop called it. It used to come back "completed"
        # carrying only the note about stopping early, which on a schedule
        # means the delivered report IS that sentence: 69 characters, once a
        # week, with a green card. Measured on the first real weekly review.
        if not answer and any(n.startswith("Stopped after") for n in notes):
            outcome = "failed"
            return ("failed",
                    "The agent ran out of tool rounds before it could answer. "
                    "Nothing was delivered for this run.", {})
        # The busy sentence is not a report. Delivered as "completed" it goes
        # out as the week's output, and _messages_for only carries
        # last_result forward from a completed run, so it also comes back as
        # "this is what you produced on the previous run" and the agent
        # repeats it. That is the poisoning _messages_for's docstring
        # describes. Same reasoning as the out-of-rounds check above. This
        # also changes ROUTER_EXHAUSTED, which shipped as completed before.
        if answer in (FREE_POOL_EXHAUSTED, ROUTER_EXHAUSTED):
            outcome = "failed"
            return ("failed", answer, {})
        if notes:
            # Say what was refused or stopped early, even when the model's
            # own final content is empty. A run that quietly skipped part of
            # its job, or stopped at the iteration cap, and reported nothing
            # at all would be worse than one that said so.
            note_text = "\n".join(notes)
            answer = (answer + "\n\n" + note_text) if answer else note_text
        outcome = "completed"
        # Guaranteed rather than requested. The brief asks for no long dashes
        # and the model used one in 25 of 36 replies anyway, so a report that
        # lands in the owner's Discord is cleaned on the way out.
        from agent_routing import scrub_long_dashes
        return ("completed", scrub_long_dashes(answer), {})
    except agent_access.ApprovalRequired:
        # Unreachable today: effective_mode never gives a schedule "ask".
        # Kept so that if it ever becomes reachable the owner is told the
        # cause instead of the generic "could not finish this run", which
        # would send somebody hunting for an outage that is not there.
        logger.warning("an agent asked for approval on a schedule, "
                       "which has nobody to ask")
        outcome = "failed"
        return ("failed",
                "This agent is set to ask before it changes anything, and a "
                "scheduled run has nobody to ask. Set it to All access, or "
                "run it from a chat.", {})
    except Exception:                                   # noqa: BLE001
        # Never include the exception's own text blindly: an httpx error can
        # carry the request URL, and this project has already leaked a token
        # that way.
        logger.error("agent schedule run failed", exc_info=True)
        outcome = "failed"
        return ("failed",
                "The agent could not finish this run. It will try again at the "
                "next scheduled time.", {})
    finally:
        await agent_activity.finish_run(run_id, outcome)
