"""Build prompts, spawn the claude CLI subprocess, and parse its outcomes."""
import asyncio
import os
import re
from dataclasses import dataclass
from typing import AsyncIterator, Literal

CLAUDE_WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
EXECUTION_TIMEOUT_SECONDS = int(os.environ.get("TASKS_AI_TIMEOUT_SECONDS", "600"))

# Sanity bounds on AI execution to limit blast radius
MAX_PROMPT_CHARS = 8000
MAX_LOG_BYTES = 1_000_000  # 1 MB cap on stdout we'll buffer per execution

# When set, run claude inside this writable copy of the workspace instead of
# the live mount. Set CLAUDE_SANDBOX_DIR=/sandbox to enable; the route layer
# is responsible for snapshotting the repo into that path before each run.
CLAUDE_SANDBOX_DIR = os.environ.get("CLAUDE_SANDBOX_DIR", "")

PROMPT_TEMPLATE = """You are executing a task from the AIUI meeting decision engine.

TASK: {description}
TYPE: {action_type}
PRIORITY: {priority}
SOURCE: {meeting_title} on {meeting_date}

Repository: /workspace/ai_ui (you have full read/write access; it is a git
working tree tracking `feat/gdrive-gmail-connectors` on GitHub).

If your work modifies files, you MUST:
  1. Stage just the files you changed: `git add <path1> <path2> ...`
     (do NOT `git add -A` or `git add .` — only stage what you intentionally
     edited, and never commit files like .env, *.db, or anything under
     openwebui-overrides/ unless the task explicitly calls for it).
  2. Create one commit per task using your summary as the message:
     `git commit -m "<short summary of the change>"`.
     If git says nothing is staged, skip the commit step — you didn't edit
     any code.
  3. Do NOT push; the admin pulls on the VPS manually.

Complete the task autonomously. If you cannot proceed because of:
  - Missing credentials -> respond ending with: NEEDS_INPUT: <what you need>
  - Unclear requirement -> respond ending with: NEEDS_INPUT: <clarifying question>
  - Hard blocker -> respond ending with: NEEDS_STEPS: <numbered manual steps>

When done successfully, respond ending with: COMPLETED: <summary of what you did>
(include the short commit hash if you made one: "COMPLETED: ... (commit abc1234)")"""


def build_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    meeting_title: str,
    meeting_date: str,
) -> str:
    return PROMPT_TEMPLATE.format(
        description=description,
        action_type=action_type,
        priority=priority,
        meeting_title=meeting_title,
        meeting_date=meeting_date,
    )


@dataclass(frozen=True)
class Outcome:
    kind: Literal["completed", "needs_input", "needs_steps", "failed"]
    payload: str


_SENTINEL_RE = re.compile(
    r"(?P<kind>COMPLETED|NEEDS_INPUT|NEEDS_STEPS):\s*(?P<rest>[^\n]*)",
    re.DOTALL,
)


def _extract_assistant_text(stream_text: str) -> str:
    """Collect all assistant text chunks from a stream-json log."""
    import json as _json
    out: list[str] = []
    for line in stream_text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = _json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "result" and isinstance(obj.get("result"), str):
            out.append(obj["result"])
        elif obj.get("type") == "assistant":
            for item in (obj.get("message", {}) or {}).get("content", []) or []:
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    out.append(item["text"])
    return "\n".join(out)


def parse_outcome(claude_response: str) -> Outcome:
    """Find the LAST sentinel in Claude's text output. Supports both raw
    text and stream-json (newline-delimited JSON) formats."""
    text = _extract_assistant_text(claude_response) or claude_response
    matches = list(_SENTINEL_RE.finditer(text))
    if not matches:
        return Outcome(kind="failed", payload=text.strip()[:500] or claude_response.strip()[:500])
    last = matches[-1]
    kind_map = {
        "COMPLETED": "completed",
        "NEEDS_INPUT": "needs_input",
        "NEEDS_STEPS": "needs_steps",
    }
    return Outcome(kind=kind_map[last.group("kind")], payload=last.group("rest").strip())


async def run_claude_subprocess(prompt: str, proc_holder: dict | None = None) -> AsyncIterator[str]:
    """Spawn the claude CLI and stream its stdout.

    proc_holder (optional): dict where this function stores the spawned
    subprocess under key "proc" so the cancel endpoint can .kill() it
    from outside.

    Safety:
      - Prompt is capped at MAX_PROMPT_CHARS to limit injection of huge payloads.
      - Hard timeout of EXECUTION_TIMEOUT_SECONDS; process is killed on timeout.
      - Stdout is capped at MAX_LOG_BYTES; subsequent output is dropped.
      - cwd is CLAUDE_SANDBOX_DIR if set (snapshot copy), else CLAUDE_WORKSPACE.
    """
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n[truncated by tasks service]"

    cwd = CLAUDE_SANDBOX_DIR or CLAUDE_WORKSPACE

    # IS_SANDBOX=1 lets claude accept --dangerously-skip-permissions under root
    # (the container runs as root and there's no rootless option for us here).
    env = {**os.environ, "IS_SANDBOX": "1"}
    # Use stream-json + verbose so each tool call / partial text chunk is
    # emitted immediately on its own line. The panel parses those lines to
    # render "Reading foo.py", "Running: docker restart …", etc.
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",
        prompt,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    if proc_holder is not None:
        proc_holder["proc"] = proc
    assert proc.stdout is not None
    bytes_yielded = 0
    try:
        async with asyncio.timeout(EXECUTION_TIMEOUT_SECONDS):
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                if bytes_yielded >= MAX_LOG_BYTES:
                    proc.kill()
                    yield "\n[OUTPUT CAP exceeded — process killed]\n"
                    break
                bytes_yielded += len(chunk)
                yield chunk.decode("utf-8", errors="replace")
            await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        yield f"\n[TIMEOUT after {EXECUTION_TIMEOUT_SECONDS}s — process killed]\n"
    except asyncio.CancelledError:
        try:
            proc.kill()
        except Exception:
            pass
        raise
    finally:
        if proc_holder is not None:
            proc_holder["proc"] = None
