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

SCOPE RULES — READ CAREFULLY BEFORE BUILDING:
  1. Build ONLY what the task literally describes. Do not infer extra scope.
  2. Prefer the SIMPLEST possible solution that satisfies the task:
     - If the task says "web app" with add/delete/list features, build a
       single-file HTML + CSS + JavaScript page with localStorage. Do NOT
       add a backend, Docker container, or external API integration unless
       the task explicitly says so.
     - If the task says "simple" or "keep it simple" or does not mention a
       backend/server/API, assume client-side only.
     - Do NOT integrate with external services (Todoist.com, Trello, etc.)
       unless the task explicitly names that integration.
     - Do NOT add authentication, Docker, FastAPI, or deployment files
       unless the task explicitly requires them.
  3. If the task is ambiguous about scope, respond with NEEDS_INPUT asking
     for clarification — do NOT guess and over-build.
  4. Place simple standalone apps under `apps/<slug>/` (e.g.
     `apps/todo-list/index.html`). Do NOT put them under `mcp-servers/`
     unless they are actually MCP servers.

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
(include the short commit hash if you made one: "COMPLETED: ... (commit abc1234)")

{supabase_block}"""


SUPABASE_BLOCK_TEMPLATE = """## Supabase integration available

A Supabase project is attached to this app. Use it for any data persistence,
auth, or file storage needs. Do NOT roll your own backend.

- Read URL/key from `window.SUPABASE_URL` and `window.SUPABASE_ANON_KEY`.
  These are injected by the host on every request — never hardcode them.
- Import the SDK in your HTML:
  `<script type="module">import {{ createClient }} from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm"; window.supabase = createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);</script>`
- Auth: `supabase.auth.signUp` / `signInWithPassword` / `signOut` / `onAuthStateChange`.
- Tables: enable Row Level Security (RLS) on every table; document the schema
  the app expects in `schema.sql` at the app root so the user can apply it.

URL: {url}
"""


SUPABASE_SQL_TOOL_TEMPLATE = """

## You can manage the Supabase schema yourself

This project has a Postgres connection URI configured. You have a tool —
DO NOT ask the user to run SQL in the Supabase dashboard. Run it yourself:

```bash
curl -sS -X POST 'http://api-gateway:8080/api/projects/{slug}/db/sql' \\
     -H 'X-User-Email: {user_email}' \\
     -H 'X-User-Admin: true' \\
     -H 'Content-Type: application/json' \\
     -d '{{"sql": "CREATE TABLE …"}}'
```

The endpoint returns JSON: `{{"rows": [...], "rowcount": N, "executed_ms": M}}`
on success, or `{{"detail": "SQL error: ..."}}` with HTTP 400 on failure.
On 502 the Postgres host is unreachable — give up and tell the user, do
not retry.

Use this tool to:
- CREATE TABLE … (start by checking `\\d` via `SELECT table_name FROM
  information_schema.tables WHERE table_schema = 'public'`)
- ALTER TABLE … (add columns, change types)
- Enable RLS: `ALTER TABLE foo ENABLE ROW LEVEL SECURITY`
- CREATE POLICY … (RLS policies — typically `auth.uid() = user_id`)
- CREATE INDEX … (for query performance)

ALWAYS verify with a follow-up `SELECT` that the change took effect before
moving on. Quote identifiers properly. Run statements one at a time — the
endpoint executes a single statement per call.
"""


def _supabase_block(supabase_url: str | None,
                    has_db_uri: bool = False,
                    slug: str = "",
                    user_email: str = "") -> str:
    """Return the Supabase prompt block, or '' if no config."""
    if not supabase_url:
        return ""
    block = SUPABASE_BLOCK_TEMPLATE.format(url=supabase_url)
    if has_db_uri:
        block += SUPABASE_SQL_TOOL_TEMPLATE.format(
            slug=slug or "<slug>",
            user_email=user_email or "<your-email>",
        )
    return block


def build_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    meeting_title: str,
    meeting_date: str,
    supabase_url: str | None = None,
    has_db_uri: bool = False,
    slug: str = "",
    user_email: str = "",
) -> str:
    return PROMPT_TEMPLATE.format(
        description=description,
        action_type=action_type,
        priority=priority,
        meeting_title=meeting_title,
        meeting_date=meeting_date,
        supabase_block=_supabase_block(
            supabase_url, has_db_uri=has_db_uri, slug=slug, user_email=user_email
        ),
    )


# ---------------------------------------------------------------------------
# Superpowers-style prompt templates (clarify → plan → TDD execute → verify)
# ---------------------------------------------------------------------------

CLARIFY_PROMPT_TEMPLATE = """You are the AIUI meeting decision engine preparing to build something.

TASK FROM TRANSCRIPT: {description}
TYPE: {action_type}
PRIORITY: {priority}

Before writing ANY code, you MUST understand what to build.

RULES:
1. Ask ONE clarifying question at a time.
2. Prefer MULTIPLE CHOICE questions when possible, e.g.:
   "Which platform? (a) Web only (b) Mobile (c) Both"
   "What framework? (a) Vanilla HTML/CSS/JS (b) React (c) Vue (d) No preference"
3. Ask about: purpose, target users, key features, platform, tech preferences,
   success criteria, scope boundaries.
4. Minimum 2 questions before you can proceed.
5. Do NOT write any code. Do NOT plan yet. Only ask questions.

For each question, end your response with:
  NEEDS_INPUT: <your question>

When you have gathered enough information to write a detailed plan, end with:
  CLARIFY_DONE: <one-paragraph summary of gathered requirements>

{conversation_history_block}"""

PLAN_PROMPT_TEMPLATE = """You are creating an implementation plan for the AIUI decision engine.

TASK: {description}
TYPE: {action_type}
PRIORITY: {priority}

GATHERED REQUIREMENTS:
{requirements}

Create a DETAILED implementation plan with these EXACT sections:

## 1. BUSINESS REQUIREMENTS
- What the user needs and why
- Success criteria (how do we know it's done?)
- Scope boundaries (what is explicitly OUT of scope)

## 2. TECHNICAL BREAKDOWN
- Architecture: files to create, components, data flow
- Exact file paths under apps/<slug>/ (e.g. apps/todo-organizer/index.html)
- Dependencies (if any — prefer zero-dep vanilla JS for simple apps)

## 3. TEST SPECIFICATIONS
- List each test to write BEFORE implementation
- What each test verifies (expected behavior, not implementation details)
- Edge cases to cover (empty state, error handling, boundary values)
- For HTML/JS apps: what to check (renders, interactions work, state persists)

## 4. IMPLEMENTATION STEPS
- Bite-sized tasks (one action each, 2-5 minutes)
- Each step: which file, what to write, which test it satisfies
- Order matters: tests FIRST, then implementation for each feature

Do NOT write any code. Plan only.
End your response with:
  PLAN: <your complete plan>"""

TDD_EXECUTE_PROMPT_TEMPLATE = """You are executing a BUILD task from the AIUI decision engine.

TASK: {description}
TYPE: {action_type}
PRIORITY: {priority}
SOURCE: {meeting_title} on {meeting_date}

Repository: /workspace/ai_ui (git working tree).

APPROVED PLAN:
{plan}

{conversation_history_block}

{error_context_block}

YOU MUST FOLLOW TEST-DRIVEN DEVELOPMENT. This is not optional.

For EACH feature in the plan, follow Red-Green-Refactor:

  RED — Write a failing test first. The test defines the expected behavior.
        For HTML/JS apps, write a test file (e.g. apps/<slug>/tests/test.html
        or apps/<slug>/test.js) that checks the feature works.
        Run it. Confirm it fails because the feature is missing.

  GREEN — Write the MINIMAL code to make the test pass. Nothing extra.
          Do NOT add features beyond what the test requires.
          Run the test. Confirm it passes.

  REFACTOR — Clean up if needed. Keep tests passing.

SCOPE RULES:
  1. Build ONLY what the plan describes. Do not infer extra scope.
  2. Prefer the SIMPLEST solution (vanilla HTML/CSS/JS with localStorage
     unless the plan explicitly calls for a framework/backend).
  3. Place apps under apps/<slug>/ (e.g. apps/todo-list/index.html).
  4. Do NOT add auth, Docker, FastAPI, or deployment unless the plan says so.

GIT RULES:
  1. Stage just the files you changed: git add <path1> <path2> ...
     (do NOT git add -A or git add . — only stage what you intentionally edited)
  2. Commit after each Red-Green cycle: git commit -m "<what this step adds>"
  3. Do NOT push.

When ALL tests pass and the app is complete:
  COMPLETED: <summary of what you built + list of commit hashes>

If you cannot proceed:
  NEEDS_INPUT: <what you need from the admin>
  FAILED: <what went wrong>

{supabase_block}"""

VERIFY_PROMPT_TEMPLATE = """You are verifying a completed build task.

The app was built at: apps/{slug}/
Task description: {description}

Run a thorough verification:
1. Check all expected files exist (per the plan)
2. Open/parse HTML files — valid structure, no broken references
3. Check JavaScript — no syntax errors, logic matches requirements
4. Run any test files that exist (apps/{slug}/tests/ or apps/{slug}/test.*)
5. Verify the app matches what was requested in the task description

If everything works correctly:
  TESTS_PASSED: <one-line summary of what was verified>

If something is broken:
  TESTS_FAILED: <specific list of what's wrong and how to fix each issue>"""

ENHANCE_PROMPT_TEMPLATE = """You are enhancing an EXISTING app from the AIUI decision engine.

APP LOCATION: /workspace/ai_ui/apps/{slug}/

USER REQUEST: {user_request}

RULES — READ CAREFULLY:
  1. You are MODIFYING existing code, not creating a new app from scratch.
  2. READ the existing files first (index.html, server.py, etc.) before
     changing anything. Understand the current structure before you touch it.
  3. Make the SMALLEST change that satisfies the request. Do not refactor.
  4. PRESERVE THE EXISTING TECH STACK. If the app is Python/Flask/sqlite3,
     stay there — do not switch to Node/Prisma or vice versa.
  5. Preserve existing features. The user is ADDING to the app, not replacing
     it.
  6. Do NOT delete the existing database file (apps/{slug}/data/*.db).
     If you change the schema, write a migration that ALTERs the existing
     table instead.
  7. Keep tests passing. If there's a tests/ folder or test file, update it
     if your change breaks existing tests.

You MUST follow Red-Green-Refactor for the change itself:
  RED:   Write a test (or update an existing one) that proves the new
         behavior. Run it. Confirm it fails.
  GREEN: Make the minimal change. Run the test. Confirm it passes.
  COMMIT: Stage only the files you changed. One commit with clear message.

{error_context_block}

When done successfully, end your response with a `COMPLETED:` block formatted
EXACTLY like this (friendly, plain language — written for the admin user who
will read it in the chat panel, not a developer reading a commit log):

  COMPLETED:
  <2-3 sentence summary in plain language. Lead with WHAT the user will now
  see or be able to do. Mention where in the UI it shows up. Avoid jargon.>

  **Next ideas:**
  - <one short, concrete follow-up the user might want next>
  - <one more short follow-up — different angle (polish, validation, related feature)>

  (commit <sha>)

Example of a good COMPLETED block:

  COMPLETED:
  Added a **Name** field to the "New Meeting" form. When you add a meeting
  the name is saved alongside the title and date, and it shows up in the
  meeting list and API responses.

  **Next ideas:**
  - Make the Name field required so meetings can't be saved blank
  - Add an email field next to Name so you can link meetings to attendees

  (commit 64bcf50)

If you cannot proceed:
  NEEDS_INPUT: <what you need>
  FAILED: <what went wrong>

{supabase_block}
"""


def build_enhance_prompt(
    *,
    slug: str,
    user_request: str,
    attempt_count: int = 0,
    max_attempts: int = 3,
    error_context: str = "",
    supabase_url: str | None = None,
    has_db_uri: bool = False,
    user_email: str = "",
) -> str:
    if error_context:
        err_block = (
            f"PREVIOUS ATTEMPT ({attempt_count}/{max_attempts}) FAILED:\n"
            f"{error_context}\n"
            "Fix the issues above. Do NOT repeat the same mistake."
        )
    else:
        err_block = ""
    return ENHANCE_PROMPT_TEMPLATE.format(
        slug=slug,
        user_request=user_request,
        error_context_block=err_block,
        supabase_block=_supabase_block(
            supabase_url, has_db_uri=has_db_uri, slug=slug, user_email=user_email
        ),
    )


# ---------------------------------------------------------------------------
# Builder functions for the Superpowers-style prompts
# ---------------------------------------------------------------------------

def _format_conversation_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for entry in history:
        role = "AI asked" if entry["role"] == "ai" else "Admin answered"
        lines.append(f"  {role}: {entry['content']}")
    return "CONVERSATION HISTORY:\n" + "\n".join(lines)


def build_clarify_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    conversation_history: list[dict],
) -> str:
    history_block = _format_conversation_history(conversation_history)
    return CLARIFY_PROMPT_TEMPLATE.format(
        description=description,
        action_type=action_type,
        priority=priority,
        conversation_history_block=history_block,
    )


def build_plan_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    requirements: str = "",
) -> str:
    return PLAN_PROMPT_TEMPLATE.format(
        description=description,
        action_type=action_type,
        priority=priority,
        requirements=requirements or "(no clarification — task was clear enough)",
    )


def build_tdd_execute_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    meeting_title: str,
    meeting_date: str,
    plan: str,
    conversation_history: list[dict],
    attempt_count: int = 0,
    max_attempts: int = 1,
    error_context: str = "",
    supabase_url: str | None = None,
    has_db_uri: bool = False,
    slug: str = "",
    user_email: str = "",
) -> str:
    history_block = _format_conversation_history(conversation_history)
    if error_context:
        error_block = (
            f"PREVIOUS ATTEMPT ({attempt_count}/{max_attempts}) FAILED:\n"
            f"{error_context}\n"
            "Fix the issues above. Do NOT repeat the same mistake."
        )
    else:
        error_block = ""
    return TDD_EXECUTE_PROMPT_TEMPLATE.format(
        description=description,
        action_type=action_type,
        priority=priority,
        meeting_title=meeting_title,
        meeting_date=meeting_date,
        plan=plan,
        conversation_history_block=history_block,
        error_context_block=error_block,
        supabase_block=_supabase_block(
            supabase_url, has_db_uri=has_db_uri, slug=slug, user_email=user_email
        ),
    )


def build_verify_prompt(*, slug: str, description: str) -> str:
    return VERIFY_PROMPT_TEMPLATE.format(slug=slug, description=description)


@dataclass(frozen=True)
class Outcome:
    kind: Literal["completed", "needs_input", "needs_steps", "failed"]
    payload: str


_SENTINEL_RE = re.compile(
    # `rest` captures everything up to the NEXT sentinel (or end-of-string).
    # Non-greedy + lookahead so a multiline COMPLETED block — including a
    # "Next ideas:" suggestions section — is preserved intact. Single-line
    # payloads still work (the lookahead falls through to \Z).
    r"(?P<kind>COMPLETED|NEEDS_INPUT|NEEDS_STEPS):\s*"
    r"(?P<rest>.*?)(?=\n\s*(?:COMPLETED|NEEDS_INPUT|NEEDS_STEPS):|\Z)",
    re.DOTALL,
)

# New sentinels for the Superpowers-style loop phases
_CLARIFY_DONE_RE = re.compile(r"CLARIFY_DONE:\s*(?P<rest>.+)", re.DOTALL)
_PLAN_RE = re.compile(r"PLAN:\s*(?P<rest>.+)", re.DOTALL)
_TEST_RE = re.compile(
    r"(?P<kind>TESTS_PASSED|TESTS_FAILED):\s*(?P<rest>[^\n]*)",
    re.DOTALL,
)
_SLUG_RE = re.compile(r"apps/([a-z0-9_-]+)/")


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


# ---------------------------------------------------------------------------
# Parsers for the Superpowers-style loop sentinels
# ---------------------------------------------------------------------------

def parse_clarify_done(claude_response: str) -> str | None:
    text = _extract_assistant_text(claude_response) or claude_response
    match = _CLARIFY_DONE_RE.search(text)
    return match.group("rest").strip() if match else None


def parse_plan(claude_response: str) -> str | None:
    text = _extract_assistant_text(claude_response) or claude_response
    match = _PLAN_RE.search(text)
    return match.group("rest").strip() if match else None


@dataclass(frozen=True)
class TestOutcome:
    passed: bool
    detail: str


def parse_test_outcome(claude_response: str) -> TestOutcome:
    text = _extract_assistant_text(claude_response) or claude_response
    matches = list(_TEST_RE.finditer(text))
    if not matches:
        return TestOutcome(passed=False, detail="No test sentinel found in output")
    last = matches[-1]
    return TestOutcome(
        passed=last.group("kind") == "TESTS_PASSED",
        detail=last.group("rest").strip(),
    )


def extract_app_slug(claude_response: str) -> str | None:
    text = _extract_assistant_text(claude_response) or claude_response
    match = _SLUG_RE.search(text)
    return match.group(1) if match else None


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
