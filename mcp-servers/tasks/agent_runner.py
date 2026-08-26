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

from owui_token import mint_owui_token

logger = logging.getLogger(__name__)

#: Enough of the last run to avoid repeating it, not so much that it crowds
#: out the actual task. last_result is capped at 8000 characters upstream.
MEMORY_EXCERPT_CHARS = 1200

HTTP_TIMEOUT_SECONDS = 240


def _base_url() -> str:
    return os.environ.get("OPENWEBUI_URL", "http://open-webui:8080").rstrip("/")


async def _owui_user_id_for(email: str) -> str | None:
    """The Open WebUI user id behind an email.

    Imported lazily from routes_gateway so this module can be tested without
    pulling in the router and its dependencies.
    """
    from routes_gateway import _owui_user_id_for as resolve
    return await resolve(email)


async def _list_agents(token: str) -> list[dict]:
    """The derived models this token's user can see.

    /api/v1/models/list rather than /api/models: the latter nests the row under
    `info` and deletes params server side. It pages at 30 on a one indexed
    `page`, and a user is capped at 25 agents, so one page is enough here; the
    guard stops a wrong total looping.
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
            if not batch or not isinstance(total, int) or len(out) >= total:
                break
            page += 1
    return out


async def _chat(token: str, model: str, messages: list[dict],
                tool_ids: list[str] | None) -> str:
    """One non streaming completion, as the token's user."""
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if tool_ids:
        payload["tool_ids"] = tool_ids
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        r = await client.post(
            f"{_base_url()}/api/chat/completions",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=payload)
        r.raise_for_status()
        data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("the model returned no answer")
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def _messages_for(sched) -> list[dict]:
    """The task, preceded by a trimmed reminder of the last run when there is
    one. The CLI path this replaces kept a memory between runs, and dropping
    that would make every daily digest say the same thing every day."""
    last = (getattr(sched, "last_result", None) or "").strip()
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

        # Mint a short-lived token for the listing phase only.
        list_token = mint_owui_token(owner, ttl_seconds=60)
        agents = await _list_agents(list_token)
        agent = next((a for a in agents
                      if isinstance(a, dict) and a.get("id") == sched.agent_id), None)
        if agent is None:
            return ("failed",
                    "This schedule is set to run as an agent that no longer "
                    "exists. Open the Cron page and pick another one.", {})

        meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
        tools = meta.get("toolIds")
        tools = [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else []

        # Mint a long-lived token immediately before the chat call. The token
        # must outlive the slowest single call (up to HTTP_TIMEOUT_SECONDS) or
        # it expires mid run, surfacing as the agent refusing rather than as an
        # auth error.
        chat_token = mint_owui_token(owner, ttl_seconds=HTTP_TIMEOUT_SECONDS + 60)

        # Keyword arguments on purpose: the tests assert on them by name, and
        # a positional call here would silently drift from those assertions.
        answer = await _chat(token=chat_token, model=sched.agent_id,
                             messages=_messages_for(sched),
                             tool_ids=tools or None)
        if not answer:
            return ("failed", "The agent returned an empty answer.", {})
        return ("completed", answer, {})
    except Exception:                                   # noqa: BLE001
        # Never include the exception's own text blindly: an httpx error can
        # carry the request URL, and this project has already leaked a token
        # that way.
        logger.error("agent schedule run failed", exc_info=True)
        return ("failed",
                "The agent could not finish this run. It will try again at the "
                "next scheduled time.", {})
