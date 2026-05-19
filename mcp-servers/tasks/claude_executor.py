"""Build prompts, spawn the claude CLI subprocess, and parse its outcomes."""
import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Per-app .gitignore management
# ---------------------------------------------------------------------------
# The agent commits app changes after each successful build/enhance. Without
# a per-app .gitignore, attachment blobs uploaded via /api/tasks/enhance land
# in apps/<slug>/.attachments/ and end up in the build's commit history.
# This helper makes sure `.attachments/` is excluded — idempotently, so it's
# safe to call on every fresh-app creation AND on existing apps before each
# build.
_GITIGNORE_ATTACHMENTS_LINE = ".attachments/"


def _ensure_gitignore_attachments(app_dir: Path) -> None:
    """Make sure `apps/<slug>/.gitignore` excludes `.attachments/`.

    Idempotent: running twice does not duplicate the line. Adds a trailing
    newline if the existing file is missing one.
    """
    app_dir = Path(app_dir)
    if not app_dir.exists():
        return
    gitignore_path = app_dir / ".gitignore"
    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    # Match the bare line, ignoring surrounding whitespace.
    lines = [ln.strip() for ln in existing.splitlines()]
    if _GITIGNORE_ATTACHMENTS_LINE in lines:
        return
    with gitignore_path.open("a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write(_GITIGNORE_ATTACHMENTS_LINE + "\n")

PROMPT_TEMPLATE = """You are executing a task from the AIUI meeting decision engine.

TASK: {description}
TYPE: {action_type}
PRIORITY: {priority}
SOURCE: {meeting_title} on {meeting_date}

Repository: /workspace/ai_ui (you have full read/write access; it is a git
working tree tracking `feat/gdrive-gmail-connectors` on GitHub).

STYLE — TERSE, CODE-FIRST:
  - Don't narrate your plan, don't explain what you're about to do, don't
    preface with "I'll start by…", and don't recap the task back to the user.
    Just do the work, then end with the COMPLETED block.
  - The admin sees your raw output in a chat panel — anything before
    COMPLETED is friction, not value. Short progress lines while running
    tools are fine; long essays are not.

SCOPE RULES — READ CAREFULLY BEFORE BUILDING:
  1. Build ONLY what the task literally describes. Do not infer extra scope.
  2. Prefer the SIMPLEST possible solution that satisfies the task:
     - Build a static HTML + CSS + vanilla JavaScript app with localStorage
       (or Supabase if attached). Do NOT add a backend, Docker container,
       or external API integration unless the task explicitly says so.
     - If the task says "simple" or "keep it simple" or does not mention a
       backend/server/API, assume client-side only.
     - Do NOT integrate with external services (Todoist.com, Trello, etc.)
       unless the task explicitly names that integration.
     - Do NOT add authentication, Docker, FastAPI, or deployment files
       unless the task explicitly requires them.
  3. If the task is ambiguous about scope, respond with NEEDS_INPUT asking
     for clarification — do NOT guess and over-build.
  4. Place apps under `apps/<slug>/` (e.g. `apps/todo-list/`). Do NOT put
     them under `mcp-servers/` unless they are actually MCP servers.

CONTENT FILL — NON-NEGOTIABLE (overrides "TERSE / SIMPLEST" for any
content the *visitor* of the built app will see):
  • Every visible section MUST contain substantive body content. A heading
    alone is NOT a section. Empty <section> bodies, or sections with only an
    <h2> and no paragraph/list/grid/cards beneath it, are treated as a BUILD
    FAILURE even if the file structure and styling are correct.
  • Forbidden in shipped output: 'Lorem ipsum', 'TODO', 'Coming soon',
    'Add content here', 'Your bio goes here', or any other placeholder
    text. Comments like <!-- TODO --> are also forbidden in shipped HTML.
  • If the user described the section topic but did NOT hand you the exact
    text (bios, project descriptions, skill lists, taglines, hero copy,
    About paragraphs), you MUST GENERATE realistic, polished, finished
    copy yourself in a voice appropriate to the role. Don't ask — generate.
  • Concrete fill targets per section type: About = 2-3 real paragraphs.
    Skills = a populated grid of at least 8-12 items grouped sensibly.
    Projects = at least 3-4 fully-described cards (title + 1-2 sentence
    description + tech tags + link). Hero = name + tagline + CTA. Contact
    = realistic-looking email + relevant social links.
  • Self-check before COMPLETED: mentally scroll the rendered page top to
    bottom — would a first-time visitor see real text, lists, or cards in
    EVERY section? If any section would render as empty whitespace below
    its heading, you are NOT done — go fill it before emitting COMPLETED.

FILE LAYOUT (MANDATORY — create the project folder first, then subfolders, then files):

  apps/<slug>/                    ← project root, always created first
    index.html                    # ~30 lines: <head>, mount target, CDN scripts, link to styles + main.js
    README.md                     # 1-paragraph description + how to run
    styles/
      main.css                    # project-specific overrides (Tailwind handles 95%)
    src/
      main.js                     # bootstraps Alpine + initializes things
      components/                 # one file per Alpine x-data factory (e.g. LoginForm.js, DashboardTable.js)
      lib/
        supabase.js               # createClient(...) — only for storage="supabase"
        api.js                    # thin fetch wrappers for REST/RPC — only for storage="supabase"
    schema.sql                    # Supabase tables + RLS — only for storage="supabase"
    public/                       # static assets (favicon, images); keep tiny — empty is fine

INDEX.HTML CDN BLOCK (in <head>, in this EXACT order — order matters,
do not rearrange):
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="styles/main.css">
    <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>  <!-- icons; optional -->
    <script type="module" src="src/main.js"></script>
    <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  For Supabase apps also load BEFORE main.js (so the Supabase global is
  ready when main.js imports run):
    <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"></script>

  WHY main.js MUST come BEFORE alpinejs: Alpine fires its `alpine:init`
  event during its own boot. main.js's job is to register Alpine.data()
  components — if main.js runs AFTER alpinejs, Alpine has already
  initialized and its event has already fired, so x-data="myComponent"
  bindings never resolve and every <template x-for> renders nothing
  (sections look empty in the browser even though the HTML and the
  Alpine factory data are both correct). Putting main.js first registers
  the listener; the deferred alpinejs script then runs and fires the
  event into the live listener.

ALPINE.JS USAGE (your reactivity layer — use this instead of addEventListener spaghetti):
  • Components live in src/components/<Name>.js as ES modules exporting an Alpine factory:
        export function loginForm() {{ return {{ email: '', password: '', async submit() {{ /* ... */ }} }}; }}
  • Register in src/main.js:
        import {{ loginForm }} from './components/LoginForm.js';
        document.addEventListener('alpine:init', () => {{ Alpine.data('loginForm', loginForm); }});
  • In HTML: <form x-data="loginForm" @submit.prevent="submit"> … </form>
  • Prefer x-data, x-show, x-if, x-on, x-bind, x-model for reactivity.

  • index.html MUST be a thin entry — markup skeleton only. NO inline <style>
    blocks beyond a tiny one for an initial loading screen if needed. NO
    inline app logic. The single-file index.html pattern is FORBIDDEN.
  • src/main.js uses native ES modules: `import {{ Foo }} from './components/Foo.js';`
    The browser resolves these directly — no bundler, no build step, no npm install.
  • Every component file in src/components/ must be a valid ES module
    (top-level `export` statements).
  • Static-only templates (landing/portfolio/docs/blog/form-builder) DO NOT
    include src/lib/supabase.js, src/lib/api.js, or schema.sql. Everything
    else stays.
  • Caddy serves nested paths under /tasks/preview-app/<slug>/... so the
    browser will fetch src/main.js, styles/main.css, src/components/*.js,
    etc., directly. No additional config needed.

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

Tool usage rule: BEFORE calling Edit or Write on any path that already
exists, FIRST call Read on that path. Skipping the Read step makes the
Edit/Write call fail with a "File has not been read yet" tool error and
forces a retry. New files (paths that do not exist yet) can be Written
without a prior Read.

When done successfully, respond ending with the literal sentinel on its own
line: `COMPLETED: <summary of what you did>` (include the short commit hash
if you made one: `COMPLETED: ... (commit abc1234)`). Use exactly this form —
the colon is required. Do NOT prefix it with `---` or other markdown.

{supabase_block}"""


SUPABASE_BLOCK_TEMPLATE = """## Supabase integration available

A Supabase project is attached to this app. Use it for any data persistence,
auth, or file storage. Do NOT roll your own backend.

### MANDATORY pattern — copy this exactly into <head>:

```html
<head>
  <!-- Loads window.SUPABASE_URL / SUPABASE_ANON_KEY from the host. ALWAYS first. -->
  <script src="aiui-config.js"></script>
  <!-- Imports the SDK once, attaches to window. -->
  <script type="module">
    import {{ createClient }} from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";
    if (!window.supabase) {{
      window.supabase = createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);
    }}
  </script>
</head>
```

### Rules

- NEVER write `const supabase = ...` at top-level. The dev server hot-reloads
  the same file — a top-level `const` redeclares and throws.
  Always use `window.supabase = createClient(...)` guarded by `if (!window.supabase)`.
- ALL code that touches Supabase reads `window.supabase` (or destructures from it).
- Auth: `window.supabase.auth.signUp` / `signInWithPassword` / `signOut` / `onAuthStateChange`.
- Tables: enable Row Level Security (RLS) on every table; document the schema
  in `schema.sql` at the app root.

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

### RLS is MANDATORY on every table you create

Never leave a table with RLS off. Without RLS, anon-key access exposes the
entire table to anyone with the project URL — Supabase will warn the user,
and you will have shipped a security hole. Every `CREATE TABLE` MUST be
followed (in separate calls) by:

  1. `CREATE TABLE <name> (…);`
  2. `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY;`
  3. At least one policy:
     - For apps that DO NOT use Supabase Auth (no sign-in flow yet):
       `CREATE POLICY "allow_all_anon" ON <name> FOR ALL TO anon USING (true) WITH CHECK (true);`
     - For apps that DO use Supabase Auth and have a `user_id` column:
       `CREATE POLICY "user_owns_row" ON <name> FOR ALL TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);`

Pick the policy that matches the app's auth model. Apply all three steps for
every new table — no exceptions.
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
  3. Place apps under apps/<slug>/ (e.g. apps/todo-list/).
  4. Do NOT add auth, Docker, FastAPI, or deployment unless the plan says so.

FILE LAYOUT (MANDATORY — create these folders BEFORE writing any files):

  apps/<slug>/
    index.html             # thin entry: markup skeleton only; loads main.js + main.css
    README.md              # 1-paragraph description + how to run
    styles/
      main.css             # all styling
    src/
      main.js              # bootstraps the app
      components/          # one file per logical UI unit (ES modules)
      lib/
        supabase.js        # Supabase client init — only for storage="supabase"
        api.js             # REST/RPC wrappers — only for storage="supabase"
    schema.sql             # Supabase tables + RLS — only for storage="supabase"
    public/                # static assets; tiny / empty is fine

  • index.html MUST be a thin entry — markup skeleton + exactly two
    project asset references:
        <link rel="stylesheet" href="styles/main.css">
        <script type="module" src="src/main.js"></script>
    The single-file index.html pattern is REPLACED by this layout — do
    not fall back to dumping everything into index.html.
  • src/main.js uses native ES module imports
    (`import {{ Foo }} from './components/Foo.js';`). No bundler.
  • Static-only templates omit src/lib/supabase.js, src/lib/api.js, and
    schema.sql; everything else stays.

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

STYLE — FAST AND SURGICAL:
  - The admin watches a chat panel for the result. They want the change
    made FAST. Don't narrate your plan, don't explain, don't preface with
    "I'll start by…", don't recap. Just edit and exit.
  - Aim for 1-3 file reads and 1-3 file edits. If you find yourself reading
    a 5th file or planning a refactor, you're over-thinking — pull back.

RULES (in priority order):
  1. SCOPE: Make the SMALLEST possible change. Edit the minimum number of
     files, the minimum number of lines. Do not refactor. Do not "improve"
     unrelated code you happen to see.
  2. THOROUGH: When the user replaces a value (a name, a label, a brand,
     a copy string), grep the WHOLE project for the OLD value first, then
     update EVERY occurrence in one pass — HTML, JS, CSS, README, schema,
     comments, page titles, meta tags, alt text, footers. NEVER claim "it
     was already set" without verifying — read the file before saying so.
  3. CHECK BEFORE CLAIMING: If your COMPLETED message says "X was already
     set" or "no change needed in Y", you must have actually read Y first.
     Hallucinated assertions are a quality bug.
  4. NO TESTS: Skip writing tests for this change. The user wants the edit
     to land — quality gates run elsewhere. Use the Edit tool, commit, exit.
  5. PRESERVE: Keep the existing tech stack and existing features intact.
     Do not delete data files (apps/{slug}/data/*.db). If schema changes,
     write an ALTER migration; never drop and recreate.
  6. COMMIT: Stage only the files you changed. One commit, clear message.
  7. CONTENT FILL: If the request adds a new visible section (e.g. "add
     a testimonials section", "add a pricing section"), the new section
     MUST contain substantive body content — at least 3 realistic items
     for a list/grid, 2-3 paragraphs for narrative copy. No empty bodies,
     no placeholder strings, no <!-- TODO -->. Generate the content
     yourself in a voice that matches the rest of the app.

WORKFLOW:
  1. If the request replaces a placeholder value (name, brand, copy):
     run `grep -rln "OLD_VALUE" apps/{slug}/` first, then Edit every
     match in one sweep. Don't stop after the first file.
  2. Otherwise: read 1-2 key files to locate the exact lines, then Edit.
  3. Use the Edit tool with exact-match strings. Avoid Write unless
     creating a brand-new file.
  4. Commit. Stop. Emit the COMPLETED block.

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
    attachments: list[str] | None = None,
    selection_block: str = "",
) -> str:
    if error_context:
        err_block = (
            f"PREVIOUS ATTEMPT ({attempt_count}/{max_attempts}) FAILED:\n"
            f"{error_context}\n"
            "Fix the issues above. Do NOT repeat the same mistake."
        )
    else:
        err_block = ""
    body = ENHANCE_PROMPT_TEMPLATE.format(
        slug=slug,
        user_request=user_request,
        error_context_block=err_block,
        supabase_block=_supabase_block(
            supabase_url, has_db_uri=has_db_uri, slug=slug, user_email=user_email
        ),
    )
    if selection_block:
        # Element-picker context lands at the very top so the agent's first
        # tool call (a Read or grep) is scoped to the selected element.
        body = selection_block + "\n" + body
    if attachments:
        body += (
            "\n\n## Attached images\n"
            "The user attached these images. Read them with your Read tool "
            "before responding — the user is referencing them in the request. "
            "If a file can't be read, tell the user which one:\n"
        )
        for rel in attachments:
            body += f"- {rel}\n"
    return body


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
    # Match a sentinel keyword at start-of-line, optionally preceded by a
    # markdown `---` separator. The keyword may be followed by a colon,
    # whitespace, period — OR nothing at all (end of text). Claude has been
    # seen writing all of these:
    #   COMPLETED: <summary>       (strict form)
    #   --- COMPLETED Built apps/  (markdown header form)
    #   COMPLETED. Customized…     (period form, mid-sentence)
    #   …done.\n\nCOMPLETED        (bare keyword, last token — no terminator)
    # The terminator `[:\s.]` is therefore OPTIONAL — `\b` already pins the
    # keyword as a whole word (so "PRECOMPLETED" won't match). Treating any
    # of these as the sentinel keeps tasks from sitting at "QUEUED" forever
    # just because of punctuation drift.
    # `rest` captures everything up to the NEXT sentinel (or end-of-string).
    # Non-greedy + lookahead so a multiline COMPLETED block — including a
    # "Next ideas:" suggestions section — is preserved intact.
    r"(?:^|\n)\s*(?:-{3,}\s*)?\b(?P<kind>COMPLETED|FAILED|NEEDS_INPUT|NEEDS_STEPS)\b[:\s.]?\s*"
    r"(?P<rest>.*?)(?=\n\s*(?:-{3,}\s*)?\b(?:COMPLETED|FAILED|NEEDS_INPUT|NEEDS_STEPS)\b[:\s.]?|\Z)",
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
        "FAILED": "failed",
        "NEEDS_INPUT": "needs_input",
        "NEEDS_STEPS": "needs_steps",
    }
    return Outcome(kind=kind_map[last.group("kind")], payload=last.group("rest").strip())


def line_outcome(claude_response_line: str) -> Outcome | None:
    """Interpret a single stream-json line from `claude --print --verbose`.

    Returns the parsed Outcome iff the line is claude's terminal `result`
    event; otherwise None. RemoteExecutor uses this to detect when a run is
    over and (on `completed`) when to rsync the agent workspace back.

    Why decode the JSON instead of regex-matching the raw line: an escaped
    `\\n` immediately before a sentinel keyword, or the JSON-closing `"`
    right after it, breaks regex word boundaries on the raw line. The
    `result` event is emitted exactly once, last, and its `result` field is
    the agent's final text — decoding it is reliable where raw matching is
    not.
    """
    import json as _json
    line = claude_response_line.strip()
    if not line.startswith("{"):
        return None
    try:
        obj = _json.loads(line)
    except Exception:
        return None
    if obj.get("type") != "result":
        return None
    result_text = obj.get("result")
    if not isinstance(result_text, str):
        return None
    return parse_outcome(result_text)


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


async def run_claude_subprocess(
    prompt: str,
    proc_holder: dict | None = None,
) -> AsyncIterator[str]:
    """LEGACY shim — preserved so existing callers in routes_execution.py
    keep working until Task 3 migrates them to the executor interface.

    proc_holder: if provided, this dict gets a "proc" key pointing at the
    spawned subprocess so the caller can .kill() it externally. New code
    should use agent_executor.get_executor() + executor.stop() instead.
    """
    from local_executor import LocalExecutor  # local import avoids cycle
    ex = LocalExecutor()
    try:
        async for chunk in ex.run(prompt, slug=None, execution_id="legacy"):
            # Surface self._proc to the legacy proc_holder convention so the
            # existing routes_execution.py cancel path keeps working.
            if proc_holder is not None and ex._proc is not None and proc_holder.get("proc") is None:
                proc_holder["proc"] = ex._proc
            yield chunk
    finally:
        if proc_holder is not None:
            proc_holder["proc"] = None
