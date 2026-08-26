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

import httpx

from agent_tools import execute_tool_call, is_write_tool
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

#: How many times the model may ask for tools before we stop. Each iteration
#: is a full completion, so this bounds the run's wall clock as well as its
#: appetite.
MAX_TOOL_ITERATIONS = 5

#: The chat token has to outlive the WHOLE loop, not one completion: the loop
#: can make up to MAX_TOOL_ITERATIONS sequential calls of up to
#: HTTP_TIMEOUT_SECONDS each, plus tool time in between. A token sized for a
#: single call expires partway through a run that needs two or more slow
#: iterations, which surfaces as the agent refusing rather than as the auth
#: failure it actually is.
CHAT_TOKEN_TTL_SECONDS = MAX_TOOL_ITERATIONS * HTTP_TIMEOUT_SECONDS + 60


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


async def _post_chat(payload: dict, token: str) -> dict:
    """One completion. Split out so the loop above it can be tested without
    a model, and so there is one place that knows the wire format."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        r = await client.post(
            f"{_base_url()}/api/chat/completions",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=payload)
        r.raise_for_status()
        return r.json()


async def _chat(token: str, model: str, messages: list[dict],
                tool_ids: list[str] | None, user_email: str,
                tool_mode: str | None) -> tuple[str, list[str]]:
    """Talk to the agent, running any tools it asks for, until it answers.

    Open WebUI injects the tool specs and returns the model's tool_calls, but
    it never runs them for an API caller: its execution loop lives on the
    socket path used by its own UI. So the execution and the feeding back
    happen here. Verified on production that handing a tool result back
    returns finish_reason "stop" and a real answer.

    Returns the answer and any notes about what was refused, which the caller
    shows the owner. A refusal is not an error: the run completes and says
    what it would not do.
    """
    convo = list(messages)
    notes: list[str] = []
    write_allowed = (tool_mode or "read_only") == "full"
    # Set before the loop so a tuned-down MAX_TOOL_ITERATIONS of 0 still has
    # something defined to return, instead of an UnboundLocalError.
    content = ""

    for _ in range(MAX_TOOL_ITERATIONS):
        payload: dict = {"model": model, "messages": convo, "stream": False}
        if tool_ids:
            payload["tool_ids"] = tool_ids
        data = await _post_chat(payload, token)

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("the model returned no answer")
        message = choices[0].get("message") or {}
        calls = message.get("tool_calls") or []
        content = (message.get("content") or "").strip()

        if not calls:
            return content, notes

        convo.append({"role": "assistant", "content": content,
                      "tool_calls": calls})
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
            if is_write_tool(name) and not write_allowed:
                notes.append(
                    "Declined to run " + label + ", because this schedule is "
                    "set to read only.")
                result = ("Refused: this scheduled run is read only, so "
                          + label + " was not run.")
            else:
                # tool_ids scopes which native tools this agent is even
                # allowed to run, not only which ones the model was told
                # about -- see execute_tool_call.
                result = await execute_tool_call(call, user_email, tool_ids)
            if isinstance(result, str) and len(result) > TOOL_RESULT_EXCERPT_CHARS:
                result = (
                    result[:TOOL_RESULT_EXCERPT_CHARS]
                    + "\n\n[This tool result was shortened. It was longer "
                    "than " + str(TOOL_RESULT_EXCERPT_CHARS) + " characters.]")
            convo.append({"role": "tool", "tool_call_id": call.get("id"),
                          "name": name, "content": result})

    notes.append("Stopped after " + str(MAX_TOOL_ITERATIONS)
                 + " rounds of tool use, so this answer may be incomplete.")
    return content, notes


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
    try:
        owner = await _owui_user_id_for(sched.user_email)
        if not owner:
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
                return ("failed",
                        "This schedule's agent could not be checked this "
                        "time. It will try again at the next scheduled "
                        "time.", {})
            return ("failed",
                    "This schedule is set to run as an agent that no longer "
                    "exists. Delete this schedule and create it again with "
                    "a different agent.", {})

        meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
        tools = meta.get("toolIds")
        tools = [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else []

        # Mint a long-lived token immediately before the chat call. The token
        # must outlive the WHOLE tool loop, not one call: up to
        # MAX_TOOL_ITERATIONS sequential completions of up to
        # HTTP_TIMEOUT_SECONDS each, plus tool time in between, or it expires
        # mid run, surfacing as the agent refusing rather than as an auth
        # error.
        chat_token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS)

        # Keyword arguments on purpose: the tests assert on them by name, and
        # a positional call here would silently drift from those assertions.
        answer, notes = await _chat(
            token=chat_token, model=sched.agent_id,
            messages=_messages_for(sched), tool_ids=tools or None,
            user_email=sched.user_email,
            tool_mode=getattr(sched, "tool_mode", None))
        if not answer and not notes:
            return ("failed", "The agent returned an empty answer.", {})
        if notes:
            # Say what was refused or stopped early, even when the model's
            # own final content is empty. A run that quietly skipped part of
            # its job, or stopped at the iteration cap, and reported nothing
            # at all would be worse than one that said so.
            note_text = "\n".join(notes)
            answer = (answer + "\n\n" + note_text) if answer else note_text
        return ("completed", answer, {})
    except Exception:                                   # noqa: BLE001
        # Never include the exception's own text blindly: an httpx error can
        # carry the request URL, and this project has already leaked a token
        # that way.
        logger.error("agent schedule run failed", exc_info=True)
        return ("failed",
                "The agent could not finish this run. It will try again at the "
                "next scheduled time.", {})
