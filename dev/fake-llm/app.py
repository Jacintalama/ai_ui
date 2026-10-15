"""A scripted, OpenAI-compatible fake model for the local dev stack.

Open WebUI uses this as its only OpenAI connection, so every agent turn in the
local stack lands here. Answers are fixed and timed, and a keyword in the last
user message picks a scene:

    (none)      "<Name> here. You said: <text>" after FAKE_DELAY_MS
    scene:slow  the same answer, after 5000 ms
    scene:tool  calls the first offered tool, then answers "<Name> used a tool."
    scene:fail  HTTP 500 with an OpenAI error body
    scene:pass  answers "PASS" (the room protocol)
    scene:job   the team lead's triage (TEAM_TRIAGE) answers a fixed 3-step plan
                (Mia, Ada, Dev); any other triage answers {"kind": "answer"}
                at once, so plain local chats stay fast
"""
import asyncio
import json
import os
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODEL_ID = "fake-agent"
SLOW_DELAY_MS = 5000
#: agent_job_triage.TRIAGE_MARKER, repeated here: the fake model is its own
#: image and does not import the tasks service.
TRIAGE_MARKER = "TEAM_TRIAGE"
#: agent_job_brief's markers for a step and for the lead's closing turn.
STEP_MARK = "<- this is your step"
CLOSING_MARK = "Write the person a short final answer"
JOB_PLAN = {"kind": "job", "steps": [
    {"agent": "Mia", "do": "Find the three latest reports."},
    {"agent": "Ada", "do": "Compare them."},
    {"agent": "Dev", "do": "Draft a one page summary."}]}

app = FastAPI(title="fake-llm")


def _text(content) -> str:
    """Message content as plain text (string, or a list of OpenAI parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def _agent_name(messages) -> str:
    """First capitalised word after "You are" in the first system message."""
    system = next((m for m in messages if m.get("role") == "system"), None)
    if not system:
        return "Agent"
    text = _text(system.get("content"))
    m = re.search(r"You are\s+([^.\n]*)", text)
    if not m:
        return "Agent"
    for word in re.findall(r"[A-Za-z][\w'-]*", m.group(1)):
        if word[0].isupper():
            return word
    return "Agent"


def _last_user_text(messages) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return _text(m.get("content"))
    return ""


def _default_delay_ms() -> int:
    try:
        return max(0, int(os.environ.get("FAKE_DELAY_MS", "1500")))
    except ValueError:
        return 1500


def _completion(message: dict, finish_reason: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _sse(message: dict, finish_reason: str):
    """The same answer as OpenAI stream chunks, ending with [DONE]."""
    cid = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    def chunk(delta: dict, finish=None) -> str:
        body = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(body)}\n\n"

    async def gen():
        yield chunk({"role": "assistant", "content": ""})
        if message.get("tool_calls"):
            calls = [dict(c, index=i) for i, c in enumerate(message["tool_calls"])]
            yield chunk({"tool_calls": calls})
        elif message.get("content"):
            yield chunk({"content": message["content"]})
        yield chunk({}, finish_reason)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/v1/models")
async def models():
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "local"}],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    messages = body.get("messages") or []
    name = _agent_name(messages)
    said = _last_user_text(messages)
    lowered = said.lower()

    # The team lead's triage (mcp-servers/tasks/agent_job_triage.py) ends with
    # its own instruction, so the person's words are earlier in the history.
    # Answered before the delay: it is housekeeping, and every team message
    # in the local stack goes through it.
    if TRIAGE_MARKER in said:
        asked_for_job = any(
            "scene:job" in _text(m.get("content")).lower()
            for m in messages if m.get("role") == "user")
        plan = JOB_PLAN if asked_for_job else {"kind": "answer"}
        message = {"role": "assistant", "content": json.dumps(plan)}
        if body.get("stream"):
            return _sse(message, "stop")
        return JSONResponse(_completion(message, "stop"))

    delay_ms = SLOW_DELAY_MS if "scene:slow" in lowered else _default_delay_ms()
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)

    if "scene:fail" in lowered:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "fake-llm: scripted failure (scene:fail)",
                               "type": "server_error", "code": "scene_fail"}},
        )

    finish = "stop"
    if "scene:pass" in lowered:
        message = {"role": "assistant", "content": "PASS"}
    elif "scene:tool" in lowered:
        tools = body.get("tools") or []
        if any(m.get("role") == "tool" for m in messages):
            message = {"role": "assistant", "content": f"{name} used a tool."}
        elif tools:
            fn = (tools[0].get("function") or {}).get("name", "tool")
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {"name": fn, "arguments": "{}"},
                }],
            }
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": f"{name} here. No tool was offered."}
    elif STEP_MARK in said:
        # A team job step (agent_job_brief.step_messages): answer the step,
        # not the whole brief, so a local job reads as three short results.
        mine = next((ln for ln in said.splitlines() if STEP_MARK in ln), "")
        task = mine.replace(STEP_MARK, "").split(":", 1)[-1].strip()
        message = {"role": "assistant", "content": f"{name} did: {task}"}
    elif CLOSING_MARK in said:
        message = {"role": "assistant",
                   "content": f"{name}: all steps are done. Summary of the team's results."}
    else:
        message = {"role": "assistant", "content": f"{name} here. You said: {said}"}

    if body.get("stream"):
        return _sse(message, finish)
    return JSONResponse(_completion(message, finish))
