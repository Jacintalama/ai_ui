"""Build prompts, spawn the claude CLI subprocess, and parse its outcomes."""
import asyncio
import os
import re
from dataclasses import dataclass
from typing import AsyncIterator, Literal

CLAUDE_WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
EXECUTION_TIMEOUT_SECONDS = 300

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

Repository: /workspace/ai_ui (you have full read/write access in this container)

Complete the task autonomously. If you cannot proceed because of:
  - Missing credentials -> respond ending with: NEEDS_INPUT: <what you need>
  - Unclear requirement -> respond ending with: NEEDS_INPUT: <clarifying question>
  - Hard blocker -> respond ending with: NEEDS_STEPS: <numbered manual steps>

When done successfully, respond ending with: COMPLETED: <summary of what you did>"""


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
    r"^(?P<kind>COMPLETED|NEEDS_INPUT|NEEDS_STEPS):\s*(?P<rest>.*)",
    re.MULTILINE | re.DOTALL,
)


def parse_outcome(claude_response: str) -> Outcome:
    """Find the LAST sentinel line and treat its payload as the result."""
    matches = list(_SENTINEL_RE.finditer(claude_response))
    if not matches:
        return Outcome(kind="failed", payload=claude_response.strip()[:500])
    last = matches[-1]
    kind_map = {
        "COMPLETED": "completed",
        "NEEDS_INPUT": "needs_input",
        "NEEDS_STEPS": "needs_steps",
    }
    return Outcome(kind=kind_map[last.group("kind")], payload=last.group("rest").strip())


async def run_claude_subprocess(prompt: str) -> AsyncIterator[str]:
    """Spawn the claude CLI with --print and stream its stdout in 4 KB chunks.

    Safety:
      - Prompt is capped at MAX_PROMPT_CHARS to limit injection of huge payloads.
      - Hard timeout of EXECUTION_TIMEOUT_SECONDS; process is killed on timeout.
      - Stdout is capped at MAX_LOG_BYTES; subsequent output is dropped.
      - cwd is CLAUDE_SANDBOX_DIR if set (snapshot copy), else CLAUDE_WORKSPACE.
    """
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n[truncated by tasks service]"

    cwd = CLAUDE_SANDBOX_DIR or CLAUDE_WORKSPACE

    proc = await asyncio.create_subprocess_exec(
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        prompt,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ},
    )
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
