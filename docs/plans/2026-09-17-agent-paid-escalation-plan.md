# Agents move to the paid model on their own, implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** An agent on a free model moves to GPT-5.5 by itself for app builds, code, pasted errors, long conversations, and when the free models fail, stays there while the job continues, goes back for plain questions, and every run records which model answered and what it cost, under a daily cap of 40 paid turns per person.

**Architecture:** A new pure module `mcp-servers/tasks/agent_escalation.py` holds the rules, the prices, the sticky window, the caller's intent and the once a day cap note. `agent_runner._chat` gains `intent` and `usage` parameters and an `_Escalation` helper that switches the posted model to `gpt-5.5` at most once a turn, without re-running tools. `agent_activity` records the model, reason, tokens and cost on `tasks.agent_run` (migration 050) and counts today's paid turns. Every chat surface, the schedule runner and the room pass an intent; the room summariser passes none and never moves.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async with `text()` SQL, httpx, pytest (`asyncio_mode = auto`), Docker Compose on the Hetzner box, Open WebUI 0.11.3 `/api/chat/completions`.

Design: `docs/plans/2026-09-17-agent-paid-escalation-design.md`.

---

## How this plan was checked

Every code block below was copied by a script from draft files that were run
before this plan was written (2026-09-17, local Python 3.13.5, sse-starlette
3.0.3, on a copy of branch `feat/agent-paid-escalation` at 3d66d0609):

1. The three `agent_escalation` test files: 61 passed, and each module slice
   was checked red before its task and green after it (cost 10, rules 39,
   decide 12).
2. `tests/test_agent_run_cost.py` 6 passed; with `tests/test_agent_activity.py` 30.
3. `tests/test_agent_escalation_loop.py` 21 passed.
4. `tests/test_agent_escalation_surfaces.py` 8 passed.
5. `tests/test_agent_paid_env.py` 6 passed; `tests/test_migrations_runner.py` 7 passed.
6. The existing loop suites (`test_agent_free_fallback`, `test_agent_tool_loop`,
   `test_agent_runner`, `test_agent_stale_model`) 116 passed with the new
   `_chat` in place, before any new test was added.
7. Every `tests/test_agent*.py` file with all of Tasks 1 to 9 applied: 1287
   passed. The 37 failures and 21 errors were all outside this change: files
   that read `open-webui-functions/` or `mcp-servers/gdrive/`, which the
   scratch copy did not include, and 4 DB-tier setup errors.
8. The whole plan was replayed on a fresh copy of the branch by a script,
   task by task, running each task's test command before and after its
   implementation step. Red then green every time, with the counts written
   in each task, and the five modules and the compose file it produced were
   byte-identical to the drafts. Tasks 2 and 3 were replayed separately
   (their module slices: cost 10 passed, rules 39 failed then passed,
   decide 12 errors then passed).

Not checked before writing, and checked in Task 11: anything against Postgres
(the migration, the UPDATE and the count SQL), anything against Open WebUI or
OpenAI (reasoning_effort `low`, `usage` passthrough, latency, tool calls on a
posted `gpt-5.5`), and Python 3.11.

## Ground rules for whoever executes this

1. Work in the worktree `C:\Users\alama\.config\superpowers\worktrees\IO\agent-paid-escalation`, branch `feat/agent-paid-escalation`. Tasks service code is `mcp-servers/tasks/`. Run tests from there: `cd mcp-servers/tasks && python -m pytest tests/test_x.py -q -p no:cacheprovider`.
2. Tests that need Postgres error at setup locally (`ERROR at setup`). Pre-existing, not yours.
3. Never touch `.env`. Never deploy `mcp-servers/tasks/templates.py`. Never `scp -r`. Commit before deploying. Push only to the `fork` remote, after `gh auth switch -u Jacintalama`, `git fetch fork` and a rebase. Never force-push.
4. No emoji, no long dashes, in code, comments and commit messages.
5. The repo checks out CRLF. Keep each edited file's line endings. Commit with `git -c core.safecrlf=false commit`. Every commit ends with the trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
6. Match the surrounding style: comments say why, with the measurement or date that made the choice.
7. Tasks 7 and 8 replace large regions of `agent_runner.py`. Replace exactly the regions named; the rest of the file (for example `_messages_for` and `run_agent`) stays as it is except where Task 8 says.

---
### Task 1: Migration 050, model and cost on agent_run

**Files:**
- Create: `mcp-servers/tasks/migrations/050_agent_run_model_and_cost.sql`
- Create: `mcp-servers/tasks/migrations/rollbacks/050_agent_run_model_and_cost.down.sql`
- Test: `mcp-servers/tasks/tests/test_migrations_runner.py`

**Step 1: Write the failing test.** Append to `tests/test_migrations_runner.py`:

```python
def test_the_agent_run_cost_migration_is_picked_up_and_its_rollback_is_not():
    names = [f.name for f in _would_run()]
    assert "050_agent_run_model_and_cost.sql" in names
    sql = (MIGRATIONS / "050_agent_run_model_and_cost.sql").read_text(encoding="utf-8")
    for column in ("model TEXT", "escalation TEXT", "prompt_tokens INTEGER",
                   "completion_tokens INTEGER", "cost_usd DOUBLE PRECISION"):
        assert "ADD COLUMN IF NOT EXISTS " + column in sql
    assert "DROP" not in sql.upper()
    assert (MIGRATIONS / "rollbacks" / "050_agent_run_model_and_cost.down.sql").exists()
```

**Step 2: Run it, expect failure.**

Run: `python -m pytest tests/test_migrations_runner.py -q -p no:cacheprovider`
Expected: 1 failed, `assert '050_agent_run_model_and_cost.sql' in names`.

**Step 3: Create the migration** `migrations/050_agent_run_model_and_cost.sql`:

```sql
-- 050: which model answered an agent run, why it moved to the paid model,
-- and what it cost.
--
-- Nothing recorded any of this. Agent turns reach Open WebUI through its API,
-- which writes no chat rows, Langfuse holds 0 traces, and agent_run (044)
-- kept only who ran and when. From 2026-09-17 a free agent can move to the
-- paid model on its own, so the daily cap needs something to count and the
-- owner needs something to read.
--
-- escalation is the reason a run moved (build, code, error, sticky,
-- heavy_tool, empty_answer, pool_spent, rounds_cap, long_message,
-- long_conversation) and NULL for a run that stayed where it started. It is
-- written the moment the run moves, not when it finishes, because the cap
-- counts these rows while a room of agents is still answering.
--
-- cost_usd is NULL when it is not known (a model with no price, or a paid
-- reply that carried no usage), never 0, so a row cannot claim a paid run
-- was free.
--
-- Idempotent: db.py re-runs every migration on every startup. ADD COLUMN IF
-- NOT EXISTS only; the rollback lives in rollbacks/ and is applied by hand.
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS model TEXT;
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS escalation TEXT;
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER;
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS completion_tokens INTEGER;
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION;

-- The cap's question: this person's runs that moved, since midnight UTC.
CREATE INDEX IF NOT EXISTS agent_run_paid_today_idx
    ON tasks.agent_run (lower(user_email), started_at)
    WHERE escalation IS NOT NULL;
```

**Step 4: Create the rollback** `migrations/rollbacks/050_agent_run_model_and_cost.down.sql`:

```sql
-- Undo 050 by hand. Never placed in migrations/ itself: the startup runner
-- would run it on every boot (see tests/test_migrations_runner.py).
DROP INDEX IF EXISTS tasks.agent_run_paid_today_idx;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS cost_usd;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS completion_tokens;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS prompt_tokens;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS escalation;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS model;
```

**Step 5: Run the file again.** Expected: 7 passed. `test_no_migration_adds_a_column_it_also_drops` still passes because the rollback is outside the startup set.

**Step 6: Commit.**

```bash
git add mcp-servers/tasks/migrations/050_agent_run_model_and_cost.sql mcp-servers/tasks/migrations/rollbacks/050_agent_run_model_and_cost.down.sql mcp-servers/tasks/tests/test_migrations_runner.py
git -c core.safecrlf=false commit -m "agent_run records which model answered, why it moved, and what it cost

Nothing recorded the model or the cost of an agent turn, and the daily cap on paid turns needs rows to count. Columns only, idempotent, rollback kept by hand.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: agent_escalation, settings and cost

**Files:**
- Create: `mcp-servers/tasks/agent_escalation.py`
- Test: `mcp-servers/tasks/tests/test_agent_escalation_cost.py`

**Step 1: Write the failing tests.** Create `tests/test_agent_escalation_cost.py`:

```python
"""What a turn on the paid model costs, and the settings that switch the move
to the paid model on and off. No model, no database."""
import pytest

import agent_escalation as esc


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(esc, "PAID_MODEL", "gpt-5.5")
    monkeypatch.setattr(esc, "DAILY_CAP", 40)
    monkeypatch.setattr(esc, "PRICES", {"gpt-5.5": (5.0, 30.0)})


def test_prices_parse_and_a_malformed_entry_is_skipped():
    assert esc.parse_prices("gpt-5.5=5:30, gpt-5-mini=0.25:2,broken=x:1,=1:2,nocolon=5") == {
        "gpt-5.5": (5.0, 30.0), "gpt-5-mini": (0.25, 2.0)}


def test_the_shipped_default_prices_gpt_5_5_at_5_and_30():
    assert esc.parse_prices("gpt-5.5=5:30") == {"gpt-5.5": (5.0, 30.0)}


def test_a_free_model_costs_nothing_and_an_unpriced_one_is_unknown():
    assert esc.cost_of("nvidia/nemotron-3-super-120b-a12b:free", 9000, 900) == 0.0
    assert esc.cost_of("gpt-4o-mini", 1000, 100) is None
    assert esc.cost_of("gpt-5.5", 1_000_000, 0) == pytest.approx(5.0)
    assert esc.cost_of("gpt-5.5", 0, 1_000_000) == pytest.approx(30.0)


def test_usage_sums_every_completion_and_prices_it():
    u = esc.TurnUsage(run_id="r1")
    u.add("gpt-5.5", {"prompt_tokens": 1000, "completion_tokens": 100})
    u.add("gpt-5.5", {"prompt_tokens": 1000, "completion_tokens": 100})
    assert (u.prompt_tokens, u.completion_tokens) == (2000, 200)
    assert u.cost_usd == pytest.approx((2000 * 5 + 200 * 30) / 1_000_000)
    assert u.model == "gpt-5.5"


def test_a_paid_reply_without_usage_makes_the_cost_unknown_not_zero():
    u = esc.TurnUsage()
    u.add("gpt-5.5", None)
    assert u.cost_usd is None


def test_a_free_reply_without_usage_still_costs_nothing():
    u = esc.TurnUsage()
    u.add("nex-agi/nex-n2.5-pro:free", None)
    assert u.cost_usd == 0.0


def test_junk_token_counts_count_as_zero():
    u = esc.TurnUsage()
    u.add("gpt-5.5", {"prompt_tokens": "lots", "completion_tokens": True})
    assert (u.prompt_tokens, u.completion_tokens, u.cost_usd) == (0, 0, 0.0)


def test_blank_model_or_zero_cap_switches_it_off(monkeypatch):
    assert esc.enabled()
    monkeypatch.setattr(esc, "DAILY_CAP", 0)
    assert not esc.enabled()
    monkeypatch.setattr(esc, "DAILY_CAP", 40)
    monkeypatch.setattr(esc, "PAID_MODEL", "")
    assert not esc.enabled()


def test_a_paid_completion_gets_at_least_the_paid_timeout(monkeypatch):
    monkeypatch.setattr(esc, "PAID_TIMEOUT_SECONDS", 90)
    assert esc.paid_timeout(60) == 90
    assert esc.paid_timeout(240) == 240


def test_a_bad_number_in_the_environment_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("AGENT_PAID_DAILY_CAP", "forty")
    assert esc._int_env("AGENT_PAID_DAILY_CAP", 40) == 40
    monkeypatch.setenv("AGENT_PAID_DAILY_CAP", "")
    assert esc._int_env("AGENT_PAID_DAILY_CAP", 40) == 40
    monkeypatch.setenv("AGENT_PAID_DAILY_CAP", "7")
    assert esc._int_env("AGENT_PAID_DAILY_CAP", 40) == 7
```

**Step 2: Run, expect failure.**

Run: `python -m pytest tests/test_agent_escalation_cost.py -q -p no:cacheprovider`
Expected: collection error, `ModuleNotFoundError: No module named 'agent_escalation'`.

**Step 3: Create `agent_escalation.py`** with exactly this (the imports for Tasks 3 and 4 are already here):

```python
"""When an agent on a free model moves to the paid model, and what it cost.

Free models answer ordinary questions well. What they do badly is long, many
round work: building an app, changing code, chasing an error. The owner asked
on 2026-09-17 for that switch to happen on its own, so nobody has to open an
agent's card and change its model for one job and then change it back.

Pure on purpose: no database and no HTTP. agent_runner asks the questions
here and does the switching, agent_activity counts and records. Everything a
test needs to pin a decision is a plain function of its arguments, and the
two pieces of state that are not (the sticky window and the once a day note)
take an explicit clock.

Design: docs/plans/2026-09-17-agent-paid-escalation-design.md.
"""
import contextlib
import contextvars
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone


def _int_env(name: str, default: int) -> int:
    """An integer setting, or the default when it is unset or not a number.

    A typo in compose must not take the tasks service down at import, which
    is what a bare int() would do.
    """
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


#: The model a free agent moves to. Blank switches the feature off.
PAID_MODEL = os.environ.get("AGENT_PAID_MODEL", "gpt-5.5").strip()

#: Sent as reasoning_effort on paid completions. Blank sends nothing.
PAID_REASONING = os.environ.get("AGENT_PAID_REASONING", "low").strip()

#: The least a paid completion is allowed. A caller's own timeout wins when
#: it is longer (a schedule's 240 seconds).
PAID_TIMEOUT_SECONDS = _int_env("AGENT_PAID_TIMEOUT_SECONDS", 90)

#: Paid turns per person per UTC day. 0 switches the feature off.
DAILY_CAP = _int_env("AGENT_PAID_DAILY_CAP", 40)

#: How long an agent stays on the paid model for this person after a paid
#: completion, refreshed by every paid completion.
STICKY_SECONDS = _int_env("AGENT_PAID_STICKY_SECONDS", 900)

#: Extra tool rounds the paid model gets when a free turn ran out of rounds.
PAID_EXTRA_ROUNDS = _int_env("AGENT_PAID_EXTRA_ROUNDS", 3)

#: A carried conversation longer than this, in characters, moves to paid.
CONVERSATION_CHARS = _int_env("AGENT_PAID_CONVERSATION_CHARS", 60000)

#: A single message from the person longer than this moves to paid.
MESSAGE_CHARS = _int_env("AGENT_PAID_MESSAGE_CHARS", 2000)

REASON_BUILD = "build"
REASON_CODE = "code"
REASON_ERROR = "error"
REASON_LONG_MESSAGE = "long_message"
REASON_LONG_CONVERSATION = "long_conversation"
REASON_STICKY = "sticky"
REASON_HEAVY_TOOL = "heavy_tool"
REASON_EMPTY = "empty_answer"
REASON_POOL_SPENT = "pool_spent"
REASON_ROUNDS_CAP = "rounds_cap"

#: Tools that mean the agent is changing an app. No agent tool builds a new
#: app today (open-webui-functions/*_tool.py, 2026-09-17); add its name here
#: if one appears.
HEAVY_TOOLS = frozenset({"propose_app_change", "apply_app_change"})

#: Said once a day, per person, when a turn would have moved and could not.
CAP_NOTE = ("Today's limit of %d turns on the stronger model is used up, so "
            "this answer comes from the free model.")


def enabled() -> bool:
    return bool(PAID_MODEL) and DAILY_CAP > 0


def paid_timeout(timeout: float) -> float:
    return max(float(timeout), float(PAID_TIMEOUT_SECONDS))


# --- cost -------------------------------------------------------------------

def parse_prices(raw: str) -> dict:
    """"gpt-5.5=5:30,gpt-5-mini=0.25:2" as {id: (input, output)}, in US
    dollars per million tokens. A malformed entry is skipped rather than
    guessed at, so a typo costs that model its price, not the service."""
    out = {}
    for part in (raw or "").split(","):
        name, sep, value = part.strip().partition("=")
        if not sep or not name.strip():
            continue
        given_in, _sep, given_out = value.partition(":")
        try:
            out[name.strip()] = (float(given_in), float(given_out))
        except ValueError:
            continue
    return out


#: Read 2026-09-17 from developers.openai.com/api/docs/pricing: gpt-5.5 is
#: $5.00 input and $30.00 output per million tokens.
PRICES = parse_prices(os.environ.get("AGENT_PAID_PRICES", "gpt-5.5=5:30"))


def cost_of(model: str, prompt_tokens: int, completion_tokens: int):
    """What one completion cost in dollars, or None when nothing says.

    Free ids cost nothing. A model with no price is None rather than 0, so a
    row never claims a paid run was free.
    """
    if isinstance(model, str) and model.endswith(":free"):
        return 0.0
    price = PRICES.get(model)
    if price is None:
        return None
    return (prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(int(value), 0)


@dataclass
class TurnUsage:
    """What one turn spent, summed over every completion that answered.

    Filled in by agent_runner._chat as it goes and written with the run by
    agent_activity.finish_run, so a turn that stops to ask still records
    what it spent before it stopped.
    """
    run_id: str | None = None
    model: str | None = None
    escalation: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = 0.0

    def add(self, model: str, usage) -> None:
        self.model = model
        free = isinstance(model, str) and model.endswith(":free")
        if not isinstance(usage, dict):
            # No usage on a paid reply means the cost is unknown, not zero.
            if not free:
                self.cost_usd = None
            return
        prompt = _count(usage.get("prompt_tokens"))
        completion = _count(usage.get("completion_tokens"))
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        cost = cost_of(model, prompt, completion)
        if cost is None or self.cost_usd is None:
            self.cost_usd = None
        else:
            self.cost_usd += cost
```

**Step 4: Run again.** Expected: 10 passed.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/agent_escalation.py mcp-servers/tasks/tests/test_agent_escalation_cost.py
git -c core.safecrlf=false commit -m "The paid model's settings and price live in one pure module

gpt-5.5 at 5 and 30 dollars per million tokens, read 2026-09-17 from developers.openai.com/api/docs/pricing. Unknown cost is None, never 0, so a row cannot claim a paid run was free.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The rules on what the person typed

**Files:**
- Modify: `mcp-servers/tasks/agent_escalation.py` (append)
- Test: `mcp-servers/tasks/tests/test_agent_escalation_rules.py`

**Step 1: Write the failing tests.** Create `tests/test_agent_escalation_rules.py`:

```python
"""Which requests a free agent does badly enough to move to the paid model.
Keyword rules on what the person typed, pinned case by case."""
import pytest

import agent_escalation as esc


@pytest.fixture(autouse=True)
def _limits(monkeypatch):
    monkeypatch.setattr(esc, "MESSAGE_CHARS", 2000)
    monkeypatch.setattr(esc, "CONVERSATION_CHARS", 60000)


@pytest.mark.parametrize("text,reason", [
    ("build me a todo app with a login page", esc.REASON_BUILD),
    ("Can you create a landing page for my shoe store?", esc.REASON_BUILD),
    ("make a dashboard of my sales", esc.REASON_BUILD),
    ("refactor the checkout code", esc.REASON_CODE),
    ("please debug the signup flow", esc.REASON_CODE),
    ("write a script that renames my files", esc.REASON_CODE),
    ("fix the bug on the pricing page", esc.REASON_CODE),
    ("add a feature to export as CSV", esc.REASON_CODE),
    ("open it in App Builder", esc.REASON_CODE),
    ("here:\n```js\nconst x = 1\n```", esc.REASON_CODE),
    ("I get TypeError: Cannot read properties of undefined", esc.REASON_ERROR),
    ("Traceback (most recent call last):\n  File \"a.py\"", esc.REASON_ERROR),
    ("it crashed\n    at Object.<anonymous> (/app/x.js:10:5)", esc.REASON_ERROR),
])
def test_work_the_free_model_does_badly_moves_to_paid(text, reason):
    assert esc.rule_reason(text) == reason


@pytest.mark.parametrize("text", [
    "what is my schedule meeting on calendar tomorrow?",
    "hi team",
    "make sure the site is up",
    "set up a meeting with Ralph on Friday",
    "create a schedule that emails me every morning",
    "make it blue",
    "yes, go ahead",
    "",
    None,
])
def test_ordinary_requests_stay_free(text):
    assert esc.rule_reason(text) is None


def test_a_very_long_message_moves_to_paid():
    assert esc.rule_reason("a" * 2001) == esc.REASON_LONG_MESSAGE
    assert esc.rule_reason("a" * 2000) is None


@pytest.mark.parametrize("text,plain", [
    ("what is on my calendar tomorrow?", True),
    ("Who emailed me today", True),
    ("why did the build fail?", False),
    ("is the page live yet?", False),
    ("can you make it blue?", False),
    ("make it blue", False),
    ("yes go ahead", False),
    ("", False),
])
def test_a_plain_question_is_one_about_something_else(text, plain):
    assert esc.is_plain_question(text) is plain


@pytest.mark.parametrize("content,passed", [
    ("PASS", True), (" pass. ", True), ('"PASS"', True),
    ("PASS\n\nI checked the files", False), ("", False), (None, False),
])
def test_pass_shapes(content, passed):
    assert esc.looks_like_pass(content) is passed


def test_heavy_tools_are_the_app_change_tools_and_junk_is_not():
    call = lambda n: {"function": {"name": n}}  # noqa: E731
    assert esc.names_heavy_tool([call("read_app_file"), call("propose_app_change")])
    assert esc.names_heavy_tool([call(" apply_app_change ")])
    assert not esc.names_heavy_tool([call("list_my_apps")])
    assert not esc.names_heavy_tool([None, {"function": "x"}, {"function": {"name": 3}}])
    assert not esc.names_heavy_tool("nope")


def test_conversation_size_counts_text_parts_and_ignores_junk(monkeypatch):
    monkeypatch.setattr(esc, "CONVERSATION_CHARS", 10)
    msgs = [{"role": "user", "content": "12345"},
            {"role": "user", "content": [{"type": "text", "text": "123456"}]},
            {"role": "tool", "content": None}, "junk"]
    assert esc.conversation_chars(msgs) == 11
    assert esc.too_long(msgs)
```

**Step 2: Run, expect failure.**

Run: `python -m pytest tests/test_agent_escalation_rules.py -q -p no:cacheprovider`
Expected: 39 failed, `AttributeError: module 'agent_escalation' has no attribute ...`.

**Step 3: Append to `agent_escalation.py`** (after `TurnUsage`, one blank line pair between):

```python
# --- the rules --------------------------------------------------------------

_BUILD = re.compile(
    r"\b(?:build|create|make(?!\s+sure)|generate|scaffold|develop|code up|"
    r"spin up|set up)\b[^.?!\n]{0,40}?\b(?:apps?|application|web ?sites?|"
    r"sites?|web ?pages?|landing pages?|pages?|dashboards?|games?|api|"
    r"backend|frontend|extension|bot|plugin|portal|store|shop)\b")

_CODE = re.compile(
    r"\b(?:refactor|debug|debugging|implement)\b"
    r"|\bwrite\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|some\s+)?(?:code|script|"
    r"function|class|query|regex|tests?|component|endpoint|migration|"
    r"program)\b"
    r"|\bfix\b[^.?!\n]{0,30}?\b(?:bugs?|errors?|code|build|tests?|"
    r"crash(?:es)?|issues?|page|app|site|feature)\b"
    r"|\badd\b[^.?!\n]{0,30}?\b(?:feature|endpoint|component|function)\b"
    r"|\bapp builder\b")

_ERROR = re.compile(
    r"traceback \(most recent call last\)"
    r"|\bstack ?trace\b"
    r"|\b[a-z]*(?:error|exception):\s"
    r"|^\s*at \S+ \(\S+:\d+:\d+\)",
    re.MULTILINE)


def rule_reason(text) -> str | None:
    """Why this message needs the paid model, or None. Read from what the
    person typed, never from an instruction this service added."""
    raw = text if isinstance(text, str) else ""
    if not raw.strip():
        return None
    low = raw.lower()
    if "```" in raw:
        return REASON_CODE
    if _ERROR.search(low):
        return REASON_ERROR
    if _BUILD.search(low):
        return REASON_BUILD
    if _CODE.search(low):
        return REASON_CODE
    if len(raw) > MESSAGE_CHARS:
        return REASON_LONG_MESSAGE
    return None


_QUESTION_START = re.compile(
    r"^\s*(?:what|what's|whats|when|where|who|whom|whose|which|why|how)\b")
_REQUEST_START = re.compile(
    r"^\s*(?:please|can you|could you|would you|will you|can we|could we|"
    r"let's|lets)\b")
_TASK_WORDS = re.compile(
    r"\b(?:apps?|site|website|pages?|build|builds|code|files?|bugs?|errors?|"
    r"fail(?:s|ed|ing)?|broken|deploy(?:ed)?|change|changes|fix|feature|"
    r"buttons?|style|colou?rs?|layout|design|preview|tests?|component|"
    r"header|footer|logo|font|images?|database|login|form)\b")


def is_plain_question(text) -> bool:
    """A question about something other than the work in hand.

    "What is on my calendar tomorrow?" goes back to the free model even while
    an agent is mid build. "Can you make it blue?" is a request in a question's
    clothes, and "why did the build fail?" is about the work, so neither is.
    """
    low = (text if isinstance(text, str) else "").strip().lower()
    if not low or _REQUEST_START.search(low):
        return False
    if not (low.endswith("?") or _QUESTION_START.search(low)):
        return False
    return not _TASK_WORDS.search(low)


def looks_like_pass(content) -> bool:
    """The room's PASS, in the shapes models send it."""
    text = content if isinstance(content, str) else ""
    return text.strip().strip('."\'').upper() == "PASS"


def names_heavy_tool(calls) -> bool:
    for call in calls if isinstance(calls, list) else []:
        fn = call.get("function") if isinstance(call, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str) and name.strip() in HEAVY_TOOLS:
            return True
    return False


def conversation_chars(messages) -> int:
    total = 0
    for m in messages if isinstance(messages, list) else []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(p.get("text") or "") for p in content
                         if isinstance(p, dict)
                         and isinstance(p.get("text"), str))
    return total


def too_long(messages) -> bool:
    return conversation_chars(messages) > CONVERSATION_CHARS
```

**Step 4: Run again.** Expected: 39 passed. Also run `tests/test_agent_escalation_cost.py`: 10 passed.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/agent_escalation.py mcp-servers/tasks/tests/test_agent_escalation_rules.py
git -c core.safecrlf=false commit -m "A free agent knows which requests it does badly: builds, code, errors, very long messages

Keyword rules on the person's own words, each pinned by a case. make sure is not make, and a plain question about something else is not about the work.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Who is asking, the sticky window, the decision, the cap note

**Files:**
- Modify: `mcp-servers/tasks/agent_escalation.py` (append)
- Test: `mcp-servers/tasks/tests/test_agent_escalation_decide.py`

**Step 1: Write the failing tests.** Create `tests/test_agent_escalation_decide.py`:

```python
"""Who is asking, whether this agent is mid job for them, and the once a day
cap note. The clock is handed in, never read."""
import pytest

import agent_escalation as esc


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    monkeypatch.setattr(esc, "_windows", {})
    monkeypatch.setattr(esc, "_noted", set())
    monkeypatch.setattr(esc, "STICKY_SECONDS", 900)
    monkeypatch.setattr(esc, "DAILY_CAP", 40)
    monkeypatch.setattr(esc, "MESSAGE_CHARS", 2000)


def test_an_intent_is_carried_and_then_gone():
    assert esc.current_intent() is None
    with esc.asking(esc.Intent(person_text="build an app", may_pass=True)):
        assert esc.current_intent().person_text == "build an app"
    assert esc.current_intent() is None


def test_the_window_opens_per_person_per_agent_and_closes_after_15_minutes():
    esc.mark_paid("Ada@Example.com", "agent-1", now=1000.0)
    assert esc.in_window("ada@example.com", "agent-1", now=1000.0 + 899)
    assert not esc.in_window("ada@example.com", "agent-2", now=1001.0)
    assert not esc.in_window("bob@example.com", "agent-1", now=1001.0)
    assert not esc.in_window("ada@example.com", "agent-1", now=1000.0 + 900)


@pytest.mark.parametrize("text,window,follow_up,expected", [
    ("build me an app", False, False, esc.REASON_BUILD),
    ("what is on my calendar tomorrow?", False, False, None),
    ("make it blue", False, False, None),
    ("make it blue", True, False, esc.REASON_STICKY),
    ("yes", True, False, esc.REASON_STICKY),
    ("what is on my calendar tomorrow?", True, False, None),
    ("why did the build fail?", True, False, esc.REASON_STICKY),
    ("", True, True, esc.REASON_STICKY),
    ("", False, True, None),
])
def test_decide(text, window, follow_up, expected):
    intent = esc.Intent(person_text=text, follow_up=follow_up)
    assert esc.decide(intent, window) == expected


def test_the_cap_note_is_said_once_a_day_per_person():
    first = esc.take_cap_note("a@example.com", today="2026-09-17")
    assert first == ("Today's limit of 40 turns on the stronger model is used "
                     "up, so this answer comes from the free model.")
    assert esc.take_cap_note("A@example.com", today="2026-09-17") == ""
    assert esc.take_cap_note("b@example.com", today="2026-09-17") != ""
    assert esc.take_cap_note("a@example.com", today="2026-09-18") != ""
```

**Step 2: Run, expect failure.**

Run: `python -m pytest tests/test_agent_escalation_decide.py -q -p no:cacheprovider`
Expected: 12 errors at setup, `AttributeError: <module 'agent_escalation'> has no attribute '_windows'`.

**Step 3: Append to `agent_escalation.py`:**

```python
# --- who is asking ----------------------------------------------------------

@dataclass(frozen=True)
class Intent:
    """What a turn's caller knows about the person asking.

    person_text is what they typed. may_pass is true in the room when this
    agent was not named and may answer PASS. follow_up is true when the turn
    continues one that stopped to ask.
    """
    person_text: str = ""
    may_pass: bool = False
    follow_up: bool = False


_current = contextvars.ContextVar("agent_escalation_intent", default=None)


def current_intent() -> Intent | None:
    return _current.get()


@contextlib.contextmanager
def asking(intent: Intent):
    """Carry an intent to the turn beneath this call without changing the
    signature of everything in between. Reset on the way out, so it never
    leaks to the next agent in the room."""
    token = _current.set(intent)
    try:
        yield intent
    finally:
        _current.reset(token)


# --- sticky window ----------------------------------------------------------

_windows: dict = {}


def _key(user_email, agent_id) -> tuple:
    return ((user_email or "").strip().lower(), agent_id or "")


def mark_paid(user_email, agent_id, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if len(_windows) > 500:
        for k in [k for k, until in _windows.items() if until <= now]:
            _windows.pop(k, None)
    _windows[_key(user_email, agent_id)] = now + STICKY_SECONDS


def in_window(user_email, agent_id, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    key = _key(user_email, agent_id)
    until = _windows.get(key)
    if until is None:
        return False
    if until <= now:
        _windows.pop(key, None)
        return False
    return True


def decide(intent: Intent, window_open: bool) -> str | None:
    """Why this turn starts on the paid model, or None."""
    reason = rule_reason(intent.person_text)
    if reason:
        return reason
    if not window_open:
        return None
    if intent.follow_up:
        return REASON_STICKY
    if is_plain_question(intent.person_text):
        return None
    return REASON_STICKY


# --- the once a day note ----------------------------------------------------

_noted: set = set()


def take_cap_note(user_email, today: str | None = None) -> str:
    """The cap note the first time today, "" after that."""
    day = today or datetime.now(timezone.utc).date().isoformat()
    key = ((user_email or "").strip().lower(), day)
    if key in _noted:
        return ""
    if len(_noted) > 1000:
        for old in [k for k in _noted if k[1] != day]:
            _noted.discard(old)
    _noted.add(key)
    return CAP_NOTE % DAILY_CAP
```

**Step 4: Run all three escalation test files.** Expected: 61 passed.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/agent_escalation.py mcp-servers/tasks/tests/test_agent_escalation_decide.py
git -c core.safecrlf=false commit -m "An agent stays on the paid model while the job goes on, and plain questions go back to free

Fifteen minutes per person per agent, refreshed by every paid completion. The room will carry the person's words through a context variable, because about fifteen test doubles of _turn_for have fixed signatures.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Recording the cost and counting today's paid turns

**Files:**
- Modify: `mcp-servers/tasks/agent_activity.py` (the `finish_run` function)
- Test: `mcp-servers/tasks/tests/test_agent_run_cost.py`

**Step 1: Write the failing tests.** Create `tests/test_agent_run_cost.py`:

```python
"""What a run cost, which model answered, and how many paid turns a person
has had today. The SQL is captured, not run: the DB tier is exercised on the
server (see the plan's live verification task)."""
import pytest

import agent_activity
import agent_escalation


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Session:
    def __init__(self, log, value=None, boom=False):
        self.log, self.value, self.boom = log, value, boom

    async def __aenter__(self):
        if self.boom:
            raise RuntimeError("db down")
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, statement, params=None):
        self.log.append((str(statement), dict(params or {})))
        return _Result(self.value)

    async def commit(self):
        self.log.append(("COMMIT", {}))


@pytest.fixture
def db(monkeypatch):
    log = []
    state = {"value": None, "boom": False}
    monkeypatch.setattr(agent_activity, "session",
                        lambda: _Session(log, state["value"], state["boom"]))
    return log, state


async def test_finishing_without_usage_writes_exactly_what_it_did_before(db):
    log, _ = db
    await agent_activity.finish_run("run-1", "completed")
    sql, params = log[0]
    assert "model" not in sql and "cost_usd" not in sql
    assert params == {"id": "run-1", "status": "completed"}


async def test_finishing_with_usage_writes_the_model_the_reason_and_the_cost(db):
    log, _ = db
    usage = agent_escalation.TurnUsage(run_id="run-1", model="gpt-5.5",
                                       escalation="build", prompt_tokens=2000,
                                       completion_tokens=200, cost_usd=0.016)
    await agent_activity.finish_run("run-1", "completed", usage=usage)
    sql, params = log[0]
    assert "COALESCE(:escalation, escalation)" in sql
    assert params == {"id": "run-1", "status": "completed", "model": "gpt-5.5",
                      "escalation": "build", "prompt_tokens": 2000,
                      "completion_tokens": 200, "cost_usd": 0.016}
    assert log[-1][0] == "COMMIT"


async def test_a_move_is_recorded_the_moment_it_happens(db):
    log, _ = db
    await agent_activity.mark_escalated("run-1", "heavy_tool")
    assert log[0][1] == {"id": "run-1", "reason": "heavy_tool"}
    await agent_activity.mark_escalated(None, "heavy_tool")
    await agent_activity.mark_escalated("run-1", None)
    assert len([e for e in log if e[0] != "COMMIT"]) == 1


async def test_todays_paid_turns_are_counted_per_person_from_utc_midnight(db):
    log, state = db
    state["value"] = 3
    assert await agent_activity.paid_turns_today("Ada@Example.com") == 3
    sql, params = log[0]
    assert "lower(user_email) = lower(:email)" in sql
    assert "escalation IS NOT NULL" in sql
    assert "date_trunc('day', now() AT TIME ZONE 'UTC')" in sql
    assert params == {"email": "Ada@Example.com"}


async def test_a_count_that_fails_is_none_not_zero(db):
    _, state = db
    state["boom"] = True
    assert await agent_activity.paid_turns_today("a@example.com") is None
    assert await agent_activity.paid_turns_today("") is None


async def test_recording_cost_never_raises_when_the_database_is_down(db):
    _, state = db
    state["boom"] = True
    await agent_activity.finish_run("run-1", "completed",
                                    usage=agent_escalation.TurnUsage())
    await agent_activity.mark_escalated("run-1", "build")
```

**Step 2: Run, expect failure.**

Run: `python -m pytest tests/test_agent_run_cost.py -q -p no:cacheprovider`
Expected: 5 failed (`finish_run() got an unexpected keyword argument 'usage'`, `no attribute 'mark_escalated'`, `no attribute 'paid_turns_today'`); `test_finishing_without_usage_writes_exactly_what_it_did_before` passes already, it guards the old statement.

**Step 3: Replace `finish_run` in `agent_activity.py`.** Replace this whole function:

```python
async def finish_run(run_id: str | None, status: str) -> None:
    """Close a run out. Safe to call with None, which is what start_run
    returns when it could not write."""
    if not run_id:
        return
    try:
        async with session() as s:
            await s.execute(
                sql_text(
                    "UPDATE tasks.agent_run "
                    "SET finished_at = now(), status = :status "
                    "WHERE id = :id"),
                {"id": run_id, "status": status})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record the end of an agent run",
                       exc_info=True)
```

with these three functions:

```python
async def finish_run(run_id: str | None, status: str, usage=None) -> None:
    """Close a run out. Safe to call with None, which is what start_run
    returns when it could not write.

    `usage` is the turn's agent_escalation.TurnUsage when the caller has one:
    which model answered, why the turn moved to the paid model, and the
    tokens and dollars it spent. Written in the same statement as the finish,
    so a row that says it finished also says what it cost."""
    if not run_id:
        return
    try:
        async with session() as s:
            if usage is None:
                await s.execute(
                    sql_text(
                        "UPDATE tasks.agent_run "
                        "SET finished_at = now(), status = :status "
                        "WHERE id = :id"),
                    {"id": run_id, "status": status})
            else:
                await s.execute(
                    sql_text(
                        "UPDATE tasks.agent_run "
                        "SET finished_at = now(), status = :status, "
                        "model = :model, "
                        "escalation = COALESCE(:escalation, escalation), "
                        "prompt_tokens = :prompt_tokens, "
                        "completion_tokens = :completion_tokens, "
                        "cost_usd = :cost_usd "
                        "WHERE id = :id"),
                    {"id": run_id, "status": status,
                     "model": usage.model,
                     "escalation": usage.escalation,
                     "prompt_tokens": usage.prompt_tokens,
                     "completion_tokens": usage.completion_tokens,
                     "cost_usd": usage.cost_usd})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record the end of an agent run",
                       exc_info=True)


async def mark_escalated(run_id: str | None, reason: str | None) -> None:
    """Say a run moved to the paid model, the moment it moves.

    Not left to finish_run: the daily cap counts these rows, and a room round
    of several agents would otherwise count none of the moves still in flight.
    Never raises, like everything here."""
    if not run_id or not reason:
        return
    try:
        async with session() as s:
            await s.execute(
                sql_text("UPDATE tasks.agent_run SET escalation = :reason "
                         "WHERE id = :id"),
                {"id": run_id, "reason": reason})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record a move to the paid model",
                       exc_info=True)


async def paid_turns_today(user_email: str) -> int | None:
    """How many of this person's runs moved to the paid model since midnight
    UTC, or None when it could not be counted.

    None, not 0: the caller treats an uncounted day as a day at its cap and
    stays on the free model. Spending money because the count broke is the
    wrong way round."""
    if not user_email:
        return None
    try:
        async with session() as s:
            n = (await s.execute(
                sql_text(
                    "SELECT count(*) FROM tasks.agent_run "
                    "WHERE lower(user_email) = lower(:email) "
                    "AND escalation IS NOT NULL "
                    "AND started_at >= (date_trunc('day', now() AT TIME ZONE 'UTC') "
                    "AT TIME ZONE 'UTC')"),
                {"email": user_email})).scalar()
        return int(n or 0)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not count today's paid agent turns",
                       exc_info=True)
        return None
```

**Step 4: Run again, plus the old activity tests.**

Run: `python -m pytest tests/test_agent_run_cost.py tests/test_agent_activity.py -q -p no:cacheprovider`
Expected: 30 passed.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/agent_activity.py mcp-servers/tasks/tests/test_agent_run_cost.py
git -c core.safecrlf=false commit -m "A run records its model, its reason for moving and its cost, and today's paid turns can be counted

The move is written the moment it happens, so the cap sees moves still in flight in a room. An uncountable day returns None and the caller stays free: spending money because the count broke is the wrong way round.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The worst turn, the token lifetime and the stale windows

A paid continuation must not outlive the minted token or be called dead by
the Agents page while it is still working.

**Files:**
- Modify: `mcp-servers/tasks/agent_runner.py` (import; the `CHAT_TOKEN_TTL_SECONDS` block; two comments)
- Modify: `mcp-servers/tasks/agent_activity.py` (`STALE_AFTER_CHANNEL`, `STALE_AFTER_SCHEDULE`)
- Test: `mcp-servers/tasks/tests/test_agent_activity.py`, `mcp-servers/tasks/tests/test_agent_runner.py`

**Step 1: Write the failing tests.**

1. In `tests/test_agent_activity.py`, replace the whole function `test_each_cut_off_clears_the_worst_case_of_its_own_path` with:

```python
def test_each_cut_off_clears_the_worst_case_of_its_own_path():
    """One number cannot be honest about both paths: a scheduled run may take
    twenty minutes of model time before a tool has run, while a chat turn is
    bounded at about three."""
    import agent_escalation
    from agent_runner import (CHANNEL_HTTP_TIMEOUT_SECONDS,
                              CHANNEL_MAX_TOOL_ITERATIONS, FREE_MODELS,
                              FINAL_ROUND_MIN_TIMEOUT_SECONDS,
                              HTTP_TIMEOUT_SECONDS, MAX_TOOL_ITERATIONS)
    # An agent on a free model can spend the whole pool in one turn, and
    # each spent id costs one more failed completion of up to the full
    # timeout. The pool is consumed across the turn, not per round, so this
    # is an addition and not a multiplication.
    extra = len(FREE_MODELS) - 1

    def worst(rounds, timeout):
        # Written out here rather than read from worst_turn_seconds, so this
        # test cannot agree with a wrong formula by calling it. The two
        # shapes are moving to the paid model at the start (the free
        # attempts that decided it, then every round on paid) and moving at
        # the round cap (every free round and fallback id, then the paid
        # model's extra rounds). Both end in the write-up.
        paid = max(timeout, agent_escalation.PAID_TIMEOUT_SECONDS)
        write_up = max(paid, FINAL_ROUND_MIN_TIMEOUT_SECONDS)
        up_front = (1 + extra) * timeout + rounds * paid + write_up
        at_cap = ((rounds + extra) * timeout
                  + agent_escalation.PAID_EXTRA_ROUNDS * paid + write_up)
        return timedelta(seconds=max(up_front, at_cap)), timedelta(seconds=paid)

    worst_schedule, schedule_round = worst(MAX_TOOL_ITERATIONS,
                                           HTTP_TIMEOUT_SECONDS)
    worst_channel, channel_round = worst(CHANNEL_MAX_TOOL_ITERATIONS,
                                         CHANNEL_HTTP_TIMEOUT_SECONDS)
    # One round of headroom, not one second. Neither worst case counts tool
    # time between completions, so a window that clears the model time by
    # less than a round is not clearing anything. This is what the move from
    # forty five minutes to fifty bought: forty five cleared 2640 seconds by
    # sixty, which is a quarter of one round.
    assert STALE_AFTER_SCHEDULE > worst_schedule + schedule_round, (
        "a healthy long schedule would be reported as failed")
    # The channel clears its worst case by exactly one round and not a
    # second more: 660 plus 60 is 720, which is the twelve minute window. So
    # this one is >= where the schedule's is >, and that is deliberate.
    # Somebody is sitting at a keyboard here, and the only way to buy more
    # headroom is to make them wait longer for a turn that has already gone
    # wrong. Raising CHANNEL_MAX_TOOL_ITERATIONS or the pool means raising
    # the window with it; this assertion is what says so.
    assert STALE_AFTER_CHANNEL >= worst_channel + channel_round, (
        "a healthy long chat turn would be reported as failed")
```

2. In `tests/test_agent_runner.py`, replace the whole function `test_the_token_outlives_the_whole_loop` with this (it adds a second assertion and a new test after it):

```python
def test_the_token_outlives_the_whole_loop():
    """Derived, not hardcoded. Raising the cap without raising the token gives
    an agent that dies partway through and reports it as a refusal.

    The free pool counts too. An agent on a free model can spend every id in
    one turn, and each spent id is one more completion of up to the full
    timeout, so the rounds alone stopped describing the worst case the day
    the fallback was added. The token expiring mid-loop is the worst kind of
    failure here: a 401 is deliberately not a provider failure, so it ends
    the run rather than moving to the next model.

    The write-up after the tool cap is in the count as well, the `+ 1`. It
    is the round that carries everything the run read, so it is the one most
    worth not losing, and it is the last thing the person hears from a run
    that spent every round. Leaving it out left the token three minutes
    short of the loop it is supposed to outlive."""
    assert agent_runner.CHAT_TOKEN_TTL_SECONDS >= (
        (agent_runner.MAX_TOOL_ITERATIONS + 1
         + len(agent_runner.FREE_MODELS) - 1)
        * agent_runner.HTTP_TIMEOUT_SECONDS)
    # And the move to the paid model, which can add rounds after the free
    # ones are spent (2026-09-17).
    assert agent_runner.CHAT_TOKEN_TTL_SECONDS >= agent_runner.worst_turn_seconds(
        agent_runner.MAX_TOOL_ITERATIONS, agent_runner.HTTP_TIMEOUT_SECONDS)


def test_the_worst_turn_counts_the_move_to_the_paid_model(monkeypatch):
    """Pinned with numbers, so a formula that quietly drops a term fails."""
    import agent_escalation
    monkeypatch.setattr(agent_runner, "FREE_MODELS", ["a:free", "b:free", "c:free"])
    monkeypatch.setattr(agent_escalation, "PAID_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(agent_escalation, "PAID_EXTRA_ROUNDS", 3)
    # Chat: 3 free attempts at 60 + 7 paid rounds at 90 + 120 write-up = 930,
    # and 9 free completions at 60 + 3 paid at 90 + 120 = 930.
    assert agent_runner.worst_turn_seconds(7, 60) == 930
    # Schedule: 10 free at 240 + 3 paid at 240 + 240 write-up = 3360.
    assert agent_runner.worst_turn_seconds(8, 240) == 3360
```

**Step 2: Run, expect failure.**

Run: `python -m pytest tests/test_agent_activity.py tests/test_agent_runner.py -q -p no:cacheprovider -k "cut_off or token_outlives or worst_turn"`
Expected: 3 failed: the cut-off test (`a healthy long schedule would be reported as failed`) and two `AttributeError: module 'agent_runner' has no attribute 'worst_turn_seconds'`.

**Step 3: Implement.**

1. In `agent_runner.py`, add `import agent_escalation` directly after `import agent_activity`.
2. In `agent_runner.py`, replace the block that starts at the comment line `#: The chat token has to outlive the WHOLE loop` and ends with the closing parenthesis of `CHAT_TOKEN_TTL_SECONDS = (...)` (just above `async def _chat`) with:

```python
def worst_turn_seconds(max_iterations: int, timeout: float) -> float:
    """Every completion one turn can make, each at its full timeout, now
    that a free agent can move to the paid model partway through.

    Two shapes, and the worse one counts. Moving at the start: the free
    attempts that decided it (the agent's own model and every fallback id),
    then every round on the paid model, then the write-up. Moving at the
    round cap: every round on the free models, every fallback id, then the
    paid model's extra rounds and the write-up. A paid model that fails
    sends the turn back to the free one it left, which costs less than
    either shape, because the paid timeout is never shorter than the free.
    """
    extra_free = max(len(FREE_MODELS) - 1, 0)
    paid = agent_escalation.paid_timeout(timeout)
    write_up = max(paid, FINAL_ROUND_MIN_TIMEOUT_SECONDS)
    up_front = (1 + extra_free) * timeout + max_iterations * paid + write_up
    at_cap = ((max_iterations + extra_free) * timeout
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
#: On a schedule that is 8 free rounds and 2 fallback ids at 240 seconds,
#: 3 paid rounds at 240 and a 240 second write-up: 3360 seconds, and this is
#: that plus a minute.
CHAT_TOKEN_TTL_SECONDS = int(
    worst_turn_seconds(MAX_TOOL_ITERATIONS, HTTP_TIMEOUT_SECONDS)) + 60
```

3. In `agent_runner.py`, keep the comments honest. In the comment above `CHANNEL_MAX_TOOL_ITERATIONS`, after the sentence ending `against a 720 second window.`, add the line `#: Since 2026-09-17 the move to the paid model adds rounds too; see worst_turn_seconds, which the seventeen minute window follows.` In the comment above `FINAL_ROUND_MIN_TIMEOUT_SECONDS`, replace `inside STALE_AFTER_CHANNEL at twelve.` with `inside STALE_AFTER_CHANNEL (seventeen since the paid model can take over a turn).`
4. In `agent_activity.py`, replace:

```python
#: failed, and it is the last turn of a bad day that gets called dead, not a
#: healthy one. A test derives both numbers from the runner's constants.
STALE_AFTER_CHANNEL = timedelta(minutes=12)
```

   with:

```python
#: failed, and it is the last turn of a bad day that gets called dead, not a
#: healthy one. A test derives both numbers from the runner's constants.
#:
#: Seventeen, not twelve, since a free agent can move to the paid model
#: partway through a turn (2026-09-17). The worst turn is now 930 seconds
#: (agent_runner.worst_turn_seconds with 7 rounds at 60): three free attempts,
#: seven paid rounds at 90 and the 120 second write-up, or seven free rounds,
#: two fallback ids, three paid rounds and the write-up, which comes to the
#: same. Seventeen minutes is that plus one paid round.
STALE_AFTER_CHANNEL = timedelta(minutes=17)
```

5. In `agent_activity.py`, replace:

```python
#: four minutes. Forty five cleared that by sixty seconds, which is not
#: margin when tool time is not counted in it at all.
STALE_AFTER_SCHEDULE = timedelta(minutes=50)
```

   with:

```python
#: four minutes. Forty five cleared that by sixty seconds, which is not
#: margin when tool time is not counted in it at all.
#:
#: Sixty five, not fifty, for the move to the paid model: eight free rounds,
#: two fallback ids, three paid rounds and the write-up, all at 240 seconds,
#: is 3360 seconds, fifty six minutes, and a round of headroom is sixty.
STALE_AFTER_SCHEDULE = timedelta(minutes=65)
```

**Step 4: Run again.** Same command. Expected: 8 passed (the red run was 3 failed, 5 passed). Then the full two files: `python -m pytest tests/test_agent_activity.py tests/test_agent_runner.py -q -p no:cacheprovider`, all pass.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/agent_activity.py mcp-servers/tasks/tests/test_agent_activity.py mcp-servers/tasks/tests/test_agent_runner.py
git -c core.safecrlf=false commit -m "The token and the stale windows cover a turn that moves to the paid model

Worst chat turn 930 seconds, so STALE_AFTER_CHANNEL 12 to 17 minutes; worst schedule 3360 seconds, so STALE_AFTER_SCHEDULE 50 to 65 and the token 2700 to 3420 seconds. Derived by worst_turn_seconds and pinned with numbers.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The move inside the tool loop

**Files:**
- Modify: `mcp-servers/tasks/agent_runner.py` (replace `_chat`)
- Test: `mcp-servers/tasks/tests/test_agent_escalation_loop.py`

**Step 1: Write the failing tests.** Create `tests/test_agent_escalation_loop.py`:

```python
"""A free agent moving to the paid model inside one turn.

Every test drives agent_runner._chat with a fake _post_chat, the pattern in
test_agent_free_fallback.py. Nothing reaches a model, a database or a clock:
the daily count and the record of a move are AsyncMocks, and the sticky
window is cleared per test.
"""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import agent_activity
import agent_escalation
import agent_runner

FREE = "nvidia/nemotron-3-super-120b-a12b:free"
POOL = [FREE, "nex-agi/nex-n2.5-pro:free", "nex-agi/nex-n2.5-mini:free"]


def _reply(content="ok", calls=None, usage=None):
    msg = {"content": content, "tool_calls": calls or None}
    body = {"choices": [{"message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}]}
    if usage is not None:
        body["usage"] = usage
    return body


def _call(name, cid="c1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": "{}"}}


def _http(status, detail="boom"):
    req = httpx.Request("POST", "http://open-webui:8080/api/chat/completions")
    resp = httpx.Response(status, json={"detail": detail}, request=req)
    return httpx.HTTPStatusError(str(status), request=req, response=resp)


def _agent(base=FREE):
    return {"id": "agent-1", "name": "Ada", "base_model_id": base,
            "params": {"system": "Be Ada."}}


class _AsyncNone:
    async def __call__(self):
        return None


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    monkeypatch.setattr(agent_runner, "FREE_MODELS", list(POOL))
    monkeypatch.setattr(agent_runner, "FREE_REASONING", "none")
    monkeypatch.setattr(agent_runner, "_available_free_ids", _AsyncNone())
    monkeypatch.setattr(agent_escalation, "PAID_MODEL", "gpt-5.5")
    monkeypatch.setattr(agent_escalation, "PAID_REASONING", "low")
    monkeypatch.setattr(agent_escalation, "PAID_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(agent_escalation, "DAILY_CAP", 40)
    monkeypatch.setattr(agent_escalation, "PAID_EXTRA_ROUNDS", 3)
    monkeypatch.setattr(agent_escalation, "CONVERSATION_CHARS", 60000)
    monkeypatch.setattr(agent_escalation, "PRICES", {"gpt-5.5": (5.0, 30.0)})
    monkeypatch.setattr(agent_escalation, "_windows", {})
    monkeypatch.setattr(agent_escalation, "_noted", set())
    count = AsyncMock(return_value=0)
    marked = AsyncMock()
    monkeypatch.setattr(agent_activity, "paid_turns_today", count)
    monkeypatch.setattr(agent_activity, "mark_escalated", marked)
    return {"count": count, "marked": marked}


async def _run(fake_post, text="hi", *, agent=None, may_pass=False,
               follow_up=False, intent=True, tool=None, usage=None,
               max_iterations=7, timeout=60, messages=None, tool_mode="read_only"):
    intent_obj = (agent_escalation.Intent(person_text=text, may_pass=may_pass,
                                          follow_up=follow_up)
                  if intent else None)
    usage = usage if usage is not None else agent_escalation.TurnUsage(run_id="run-1")

    async def no_tool(*a, **k):
        return "tool ran"

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=tool or no_tool):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=messages or [{"role": "system", "content": "identity"},
                                  {"role": "user", "content": text}],
            tool_ids=["code"], user_email="ada@example.com",
            tool_mode=tool_mode, agent=agent or _agent(), intent=intent_obj,
            usage=usage, max_iterations=max_iterations, timeout=timeout)
    return answer, notes, usage


# --- up front ---------------------------------------------------------------

async def test_a_build_request_goes_to_the_paid_model_from_the_first_post(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append((payload, timeout))
        return _reply("built", usage={"prompt_tokens": 1000, "completion_tokens": 100})

    answer, _, usage = await _run(fake_post, "build me a todo app")

    assert answer == "built"
    payload, used_timeout = posts[0]
    assert payload["model"] == "gpt-5.5"
    assert payload["messages"][0] == {"role": "system", "content": "Be Ada."}
    assert payload["tool_ids"] == ["code"]
    assert payload["reasoning_effort"] == "low"
    assert used_timeout == 90
    assert usage.escalation == "build"
    assert usage.model == "gpt-5.5"
    assert usage.cost_usd == pytest.approx((1000 * 5 + 100 * 30) / 1_000_000)
    wired["marked"].assert_awaited_once_with("run-1", "build")


async def test_an_ordinary_question_stays_on_the_free_model(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("Standup at 9:30", usage={"prompt_tokens": 900, "completion_tokens": 20})

    answer, _, usage = await _run(fake_post, "what is on my calendar tomorrow?")

    assert answer == "Standup at 9:30"
    assert [p["model"] for p in posts] == ["agent-1"]
    assert posts[0]["reasoning_effort"] == "none"
    assert usage.escalation is None
    assert usage.model == FREE
    assert usage.cost_usd == 0.0
    wired["count"].assert_not_awaited()


async def test_no_intent_never_moves_which_is_what_the_summariser_relies_on(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("notes")

    await _run(fake_post, "build me a todo app", intent=False)
    assert [p["model"] for p in posts] == ["agent-1"]
    wired["count"].assert_not_awaited()


async def test_an_agent_on_a_paid_model_is_left_where_its_owner_put_it(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("done")

    await _run(fake_post, "build me a todo app", agent=_agent(base="gpt-4o-mini"))
    assert [p["model"] for p in posts] == ["agent-1"]
    wired["count"].assert_not_awaited()


async def test_blank_reasoning_sends_no_reasoning_on_the_paid_model(wired, monkeypatch):
    monkeypatch.setattr(agent_escalation, "PAID_REASONING", "")
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("built")

    await _run(fake_post, "build me a todo app")
    assert posts[0]["model"] == "gpt-5.5"
    assert "reasoning_effort" not in posts[0]


# --- the cap ----------------------------------------------------------------

async def test_at_the_cap_the_turn_stays_free_and_says_so_once_a_day(wired):
    wired["count"].return_value = 40
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("here is a start")

    first, _, usage = await _run(fake_post, "build me a todo app")
    second, _, _ = await _run(fake_post, "build me a todo app")

    assert [p["model"] for p in posts] == ["agent-1", "agent-1"]
    assert first == ("here is a start\n\nToday's limit of 40 turns on the "
                     "stronger model is used up, so this answer comes from "
                     "the free model.")
    assert second == "here is a start"
    assert usage.escalation is None
    wired["marked"].assert_not_awaited()


async def test_a_count_that_failed_stays_free_and_says_nothing(wired):
    wired["count"].return_value = None
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("here is a start")

    answer, _, _ = await _run(fake_post, "build me a todo app")
    assert answer == "here is a start"
    assert [p["model"] for p in posts] == ["agent-1"]


# --- the room: decide on free first -----------------------------------------

async def test_an_unnamed_agent_that_passes_costs_nothing_paid(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("PASS")

    answer, _, usage = await _run(fake_post, "build me a todo app", may_pass=True)
    assert answer == "PASS"
    assert [p["model"] for p in posts] == ["agent-1"]
    assert usage.escalation is None
    wired["count"].assert_not_awaited()


async def test_an_unnamed_agent_that_takes_the_job_moves_before_any_tool_runs(wired):
    posts = []
    ran = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("", calls=[_call("list_my_apps")])
        return _reply("built it")

    async def tool(call, *a, **k):
        ran.append(call["function"]["name"])
        return "[]"

    answer, _, usage = await _run(fake_post, "build me a todo app",
                                  may_pass=True, tool=tool)
    assert answer == "built it"
    assert [p["model"] for p in posts] == ["agent-1", "gpt-5.5"]
    assert ran == []
    assert usage.escalation == "build"


# --- partway through --------------------------------------------------------

async def test_an_app_change_tool_moves_the_turn_and_no_tool_runs_twice(wired):
    posts = []
    ran = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("", calls=[_call("read_app_file", "r1")])
        if len(posts) == 2:
            return _reply("", calls=[_call("propose_app_change", "p1")])
        if len(posts) == 3:
            return _reply("", calls=[_call("propose_app_change", "p2")])
        return _reply("proposed")

    async def tool(call, *a, **k):
        ran.append(call["id"])
        return "result of " + call["id"]

    answer, _, usage = await _run(fake_post, "the header looks off",
                                  tool=tool)
    assert answer == "proposed"
    assert [p["model"] for p in posts] == ["agent-1", "agent-1", "gpt-5.5", "gpt-5.5"]
    # The read ran once on the free model; the free model's change was never
    # run; the paid model's change ran once.
    assert ran == ["r1", "p2"]
    carried = [m for m in posts[2]["messages"] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in carried] == ["r1"]
    assert usage.escalation == "heavy_tool"


async def test_an_empty_answer_is_asked_again_on_the_paid_model(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("")
        return _reply("a real answer")

    answer, _, usage = await _run(fake_post, "summarise my week")
    assert answer == "a real answer"
    assert [p["model"] for p in posts] == ["agent-1", "gpt-5.5"]
    assert usage.escalation == "empty_answer"


async def test_a_long_conversation_moves_before_the_post(wired, monkeypatch):
    monkeypatch.setattr(agent_escalation, "CONVERSATION_CHARS", 50)
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("ok")

    await _run(fake_post, "summarise " + "x" * 60)
    assert posts[0]["model"] == "gpt-5.5"


async def test_a_spent_pool_moves_to_paid_with_the_carried_conversation(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("", calls=[_call("list_my_apps", "l1")])
        if payload["model"] != "gpt-5.5":
            raise _http(400, "Provider returned error")
        return _reply("answered on paid")

    answer, _, usage = await _run(fake_post, "which of my apps is newest?")
    assert answer == "answered on paid"
    assert [p["model"] for p in posts] == [
        "agent-1", "agent-1", "nex-agi/nex-n2.5-pro:free",
        "nex-agi/nex-n2.5-mini:free", "gpt-5.5"]
    assert any(m.get("tool_call_id") == "l1" for m in posts[-1]["messages"])
    assert usage.escalation == "pool_spent"


async def test_a_paid_model_that_also_fails_after_a_spent_pool_is_the_busy_sentence(wired):
    async def fake_post(payload, token, timeout=None):
        raise _http(400, "Provider returned error")

    answer, _, _ = await _run(fake_post, "which of my apps is newest?")
    assert answer == agent_runner.FREE_POOL_EXHAUSTED


async def test_out_of_rounds_on_free_the_paid_model_gets_three_more(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if payload["model"] == "gpt-5.5" and len(posts) >= 4:
            return _reply("finished on paid")
        return _reply("", calls=[_call("list_my_apps", "c%d" % len(posts))])

    answer, notes, usage = await _run(fake_post, "check my apps", max_iterations=2)
    assert answer == "finished on paid"
    assert [p["model"] for p in posts] == ["agent-1", "agent-1", "gpt-5.5", "gpt-5.5"]
    assert usage.escalation == "rounds_cap"
    assert notes == []


async def test_out_of_rounds_on_paid_too_says_how_many_rounds_in_total(wired):
    async def fake_post(payload, token, timeout=None):
        if payload.get("tool_ids") is None:
            return _reply("wrote it up")
        return _reply("", calls=[_call("list_my_apps")])

    answer, notes, _ = await _run(fake_post, "check my apps", max_iterations=2)
    assert answer == "wrote it up"
    assert notes == [agent_runner.RAN_OUT_OF_ROUNDS % 5]


async def test_a_failing_paid_model_goes_back_to_the_free_model_it_left(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if payload["model"] == "gpt-5.5":
            raise _http(400, "Unsupported value: 'reasoning_effort'")
        return _reply("free answer")

    answer, _, usage = await _run(fake_post, "build me a todo app")
    assert answer == "free answer"
    assert [p["model"] for p in posts] == ["gpt-5.5", "agent-1"]
    assert posts[1]["reasoning_effort"] == "none"
    assert usage.escalation == "build"


async def test_a_401_on_the_paid_model_is_raised_not_hidden(wired):
    async def fake_post(payload, token, timeout=None):
        raise _http(401, "Not authenticated")

    with pytest.raises(httpx.HTTPStatusError):
        await _run(fake_post, "build me a todo app")


async def test_it_moves_at_most_once_a_turn(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if payload["model"] == "gpt-5.5":
            raise _http(500)
        if len(posts) == 2:
            return _reply("", calls=[_call("propose_app_change")])
        return _reply("free again")

    await _run(fake_post, "build me a todo app", max_iterations=3)
    assert wired["count"].await_count == 1
    assert [p["model"] for p in posts].count("gpt-5.5") == 1


# --- staying on it ----------------------------------------------------------

async def test_a_follow_up_stays_paid_and_a_plain_question_goes_back(wired):
    models = []

    async def fake_post(payload, token, timeout=None):
        models.append(payload["model"])
        return _reply("ok")

    await _run(fake_post, "build me a todo app")
    await _run(fake_post, "make it blue")
    await _run(fake_post, "what is on my calendar tomorrow?")
    await _run(fake_post, "", follow_up=True)
    assert models == ["gpt-5.5", "gpt-5.5", "agent-1", "gpt-5.5"]


async def test_usage_is_summed_over_every_completion_in_the_turn(wired):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply("", calls=[_call("list_my_apps")],
                          usage={"prompt_tokens": 1000, "completion_tokens": 100})
        return _reply("done", usage={"prompt_tokens": 1500, "completion_tokens": 200})

    _, _, usage = await _run(fake_post, "build me a todo app")
    assert (usage.prompt_tokens, usage.completion_tokens) == (2500, 300)
    assert usage.cost_usd == pytest.approx((2500 * 5 + 300 * 30) / 1_000_000)
```

**Step 2: Run, expect failure.**

Run: `python -m pytest tests/test_agent_escalation_loop.py -q -p no:cacheprovider`
Expected: 21 failed, `TypeError: _chat() got an unexpected keyword argument 'intent'`.

**Step 3: Implement.** In `agent_runner.py`, replace everything from the line `async def _chat(token: str, model: str, messages: list[dict],` down to, but not including, the line `def _messages_for(sched) -> list[dict]:` with the following. It adds `_paid_failed` and `_Escalation` above a new `_chat`; every comment of the old `_chat` that still applies is kept.

```python
def _paid_failed(exc) -> bool:
    """True when the paid model failed in a way worth going back to the free
    model for. Wider than _provider_failed on purpose: a paid id this box
    cannot route, or a parameter it rejects, is a 400 that says nothing about
    the provider, and the person should still get the free answer. A 401 or
    403 is this service's own token and ends the turn as it always did."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code not in (401, 403)
    return False


class _Escalation:
    """One turn's move to the paid model. At most once a turn: asked once,
    whatever the answer, so a capped or uncountable day costs one query and a
    paid model that failed is not tried again."""

    def __init__(self, *, enabled: bool, user_email: str, agent_id: str,
                 usage: "agent_escalation.TurnUsage"):
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
        agent_escalation.mark_paid(self.user_email, self.agent_id)
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
```

**Step 4: Run the new tests and every existing loop suite.**

Run: `python -m pytest tests/test_agent_escalation_loop.py tests/test_agent_free_fallback.py tests/test_agent_tool_loop.py tests/test_agent_runner.py tests/test_agent_stale_model.py -q -p no:cacheprovider`
Expected: all pass (21 new; the existing 116 unchanged, which is the proof that a caller passing no intent gets exactly the old loop). These suites are slow locally, about four minutes, because agent_activity tries a database that is not there.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/tests/test_agent_escalation_loop.py
git -c core.safecrlf=false commit -m "A free agent moves to the paid model inside its turn, at most once, without running a tool twice

Up front from the person's words or the sticky window; partway on an app change tool, an empty answer or a long conversation; on a spent pool or the round cap. An unnamed agent in the room decides on free first so six PASSes cost nothing paid. A paid failure goes back to the free model it left. reasoning_effort is decided per post. Usage is summed from every completion.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Every surface says who is asking and records the cost

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_turn.py` (`_run_turn`, `_resume_turn`, import)
- Modify: `mcp-servers/tasks/agent_runner.py` (`run_agent`)
- Modify: `mcp-servers/tasks/routes_agent_chat.py` (`_run_round`, `_summarise`, import)
- Test: `mcp-servers/tasks/tests/test_agent_escalation_surfaces.py`

Surfaces covered: the Agents page room (`_run_round` sets the intent, `_turn_for` and `_run_turn` read it), the main chat pipe and `/agents/speak` (`_turn_for` to `_run_turn`, intent from the last user message), Discord, Slack and Telegram (`/agents/turn` to `_run_turn`, same), approvals from any of them (`_resume_turn`, follow-up), schedules (`run_agent`, the schedule prompt). The room summariser passes `intent=None`. The memory reflection never calls `_chat` and is pinned by a test.

**Step 1: Write the failing tests.** Create `tests/test_agent_escalation_surfaces.py`:

```python
"""Every surface that runs an agent says who is asking, and records what the
turn cost. The loop itself is tested in test_agent_escalation_loop.py; this
file only checks what each caller hands it and what it writes back."""
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_escalation
import agent_memory
import agent_runner
import routes_agent_turn as rt

EMAIL = "owner@example.com"


def _agent():
    return {"id": "agent-1", "name": "Ada",
            "base_model_id": "nvidia/nemotron-3-super-120b-a12b:free",
            "meta": {"toolIds": ["gmail"], "access": "ask"}}


def _wire_turn(monkeypatch, seen):
    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=["gmail"]))
    monkeypatch.setattr(rt.agent_activity, "start_run",
                        AsyncMock(return_value="run-7"))
    finish = AsyncMock()
    monkeypatch.setattr(rt.agent_activity, "finish_run", finish)
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(agent_memory, "schedule_reflection", lambda *a, **k: None)
    return finish


async def test_a_chat_turn_says_what_the_person_typed_and_records_the_cost(monkeypatch):
    seen = {}
    finish = _wire_turn(monkeypatch, seen)

    await rt._run_turn(EMAIL, "agent-1",
                       [{"role": "system", "content": "identity"},
                        {"role": "user", "content": "build me a todo app"}])

    assert seen["intent"] == agent_escalation.Intent(person_text="build me a todo app")
    assert seen["usage"].run_id == "run-7"
    finish.assert_awaited_once()
    assert finish.await_args.kwargs["usage"] is seen["usage"]


async def test_a_turn_inside_the_room_uses_the_rooms_intent(monkeypatch):
    seen = {}
    _wire_turn(monkeypatch, seen)
    room = agent_escalation.Intent(person_text="build me a todo app", may_pass=True)

    with agent_escalation.asking(room):
        await rt._run_turn(EMAIL, "agent-1",
                           [{"role": "user", "content": "build me a todo app"},
                            {"role": "user", "content": "reply with exactly PASS"}])

    assert seen["intent"] is room


async def test_a_resumed_turn_is_a_follow_up(monkeypatch):
    seen = {}
    finish = _wire_turn(monkeypatch, seen)
    monkeypatch.setattr(rt, "execute_tool_call", AsyncMock(return_value="sent"))

    await rt._resume_turn(EMAIL, "agent-1",
                          [{"role": "user", "content": "send it"},
                           {"role": "assistant", "content": "",
                            "tool_calls": [{"id": "c1", "function": {
                                "name": "send_email", "arguments": "{}"}}]}],
                          [{"id": "c1", "type": "function",
                            "function": {"name": "send_email", "arguments": "{}"}}],
                          True)

    assert seen["intent"] == agent_escalation.Intent(follow_up=True)
    assert finish.await_args.kwargs["usage"] is seen["usage"]


async def test_a_schedule_says_its_own_prompt(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "report", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(agent_runner.agent_activity, "start_run",
                        AsyncMock(return_value="run-9"))
    finish = AsyncMock()
    monkeypatch.setattr(agent_runner.agent_activity, "finish_run", finish)
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=[]))

    sched = SimpleNamespace(id="s1", user_email=EMAIL, agent_id="agent-1",
                            prompt="Refactor the pricing page code.",
                            last_result="last week", last_run_status="completed",
                            tool_mode=None)
    await agent_runner.run_agent(sched)

    assert seen["intent"] == agent_escalation.Intent(
        person_text="Refactor the pricing page code.")
    assert seen["usage"].run_id == "run-9"
    assert finish.await_args.kwargs["usage"] is seen["usage"]


def _room(monkeypatch, answers):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)
    seen = []

    async def turn(email, agent, messages, names=()):
        seen.append(agent_escalation.current_intent())
        return {"answer": answers.pop(0), "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    async def agents_for(email):
        return [{"id": "agent-a", "name": "Ada"}, {"id": "agent-m", "name": "Mia"}]

    async def noop_create(email, title, s):
        return "chat-1"

    async def noop_save(email, s):
        return None

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn)
    monkeypatch.setattr(routes_agent_chat.store, "create_chat", noop_create)
    monkeypatch.setattr(routes_agent_chat.store, "save_chat", noop_save)
    app = FastAPI()
    app.include_router(routes_agent_chat.router)
    return TestClient(app), seen


def test_the_room_hands_every_agent_the_persons_words_not_the_pass_instruction(monkeypatch):
    client, seen = _room(monkeypatch, ["PASS", "PASS", "Mia here"])
    hdr = {"X-User-Email": "panel@example.com"}
    client.post("/tasks/agents/chat/send", data={"message": "build me a todo app"},
                headers=hdr)
    client.get("/tasks/agents/chat/stream", headers=hdr)

    assert [i.person_text for i in seen] == ["build me a todo app"] * 3
    # Both heard it unnamed; the everybody-passed fallback may not pass.
    assert [i.may_pass for i in seen] == [True, True, False]
    assert agent_escalation.current_intent() is None


def test_a_named_agent_in_the_room_may_not_pass(monkeypatch):
    client, seen = _room(monkeypatch, ["on it"])
    hdr = {"X-User-Email": "panel@example.com"}
    client.post("/tasks/agents/chat/send",
                data={"message": "ada, build me a todo app"}, headers=hdr)
    client.get("/tasks/agents/chat/stream", headers=hdr)

    assert [(i.person_text, i.may_pass) for i in seen] == [
        ("ada, build me a todo app", False)]


async def test_the_room_summariser_never_leaves_the_free_models(monkeypatch):
    import routes_agent_chat as mod
    seen = {}

    async def fake_resolve(email, agent_id):
        return "tok", [], "all"

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "notes", []

    monkeypatch.setattr(mod, "_resolve_agent", fake_resolve)
    monkeypatch.setattr(mod, "_chat", fake_chat)
    await mod._summarise("a@example.com", {"id": "agent-a"},
                         [{"role": "user", "content": "build me an app"}])
    assert "intent" in seen and seen["intent"] is None


async def test_the_reflection_never_posts_the_paid_model(monkeypatch):
    posted = []

    async def fake_post(payload, token, timeout=None):
        posted.append(payload["model"])
        return {"choices": [{"message": {"content": "[]"}}]}

    async def no_pool(agent):
        return []

    monkeypatch.setattr(agent_runner, "_post_chat", fake_post)
    monkeypatch.setattr(agent_runner, "_fallback_pool", no_pool)
    await agent_memory._complete(
        {"model": agent_memory.reflect_model() or "nvidia/nemotron-3-super-120b-a12b:free",
         "messages": [{"role": "user", "content": "build me an app"}]},
        "tok", 5)
    assert posted and agent_escalation.PAID_MODEL not in posted
```

**Step 2: Run, expect failure.**

Run: `python -m pytest tests/test_agent_escalation_surfaces.py -q -p no:cacheprovider`
Expected: 7 failed, 1 passed. `KeyError: 'intent'` on the two turn tests, the resume and the schedule test, `'NoneType' object has no attribute 'person_text'` on the two room tests, `assert 'intent' in seen` on the summariser. The reflection test passes already; it guards.

**Step 3: Implement.**

1. In `routes_agent_turn.py`, add `import agent_escalation` directly after `import agent_activity`.
2. In `routes_agent_turn.py`, replace:

```python
    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=messages,
            agent=agent,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
```

   with:

```python
    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    # Who is asking. The room says so through agent_escalation.asking,
    # because only it can tell the person's words from its own PASS
    # instruction; every other chat surface hands this the person's own
    # messages, so the last user message is what they typed.
    intent = (agent_escalation.current_intent()
              or agent_escalation.Intent(person_text=_last_user_text(messages)))
    usage = agent_escalation.TurnUsage(run_id=run_id)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=messages,
            agent=agent,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS,
            intent=intent, usage=usage)
```

3. In `routes_agent_turn.py`, replace:

```python
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome)


@router.post("/turn")
```

   with:

```python
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome, usage=usage)


@router.post("/turn")
```

4. In `routes_agent_turn.py`, replace:

```python
    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=convo,
            agent=agent,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
```

   with:

```python
    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    # An approval is the same job carrying on, so it stays on whichever
    # model this agent was on for this person, for as long as that lasts.
    usage = agent_escalation.TurnUsage(run_id=run_id)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=convo,
            agent=agent,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS,
            intent=agent_escalation.Intent(follow_up=True), usage=usage)
```

5. In `routes_agent_turn.py`, replace:

```python
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome)


@router.post("/turn/resume")
```

   with:

```python
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome, usage=usage)


@router.post("/turn/resume")
```

Items 6 to 8 are in `run_agent`. `agent_runner.py` already imports `agent_escalation` since Task 6.

6. In `agent_runner.py`, replace:

```python
        agent_activity.SOURCE_SCHEDULE)
    outcome = "failed"
```

   with:

```python
        agent_activity.SOURCE_SCHEDULE)
    usage = agent_escalation.TurnUsage(run_id=run_id)
    outcome = "failed"
```

7. In `agent_runner.py`, replace:

```python
            refusal_reason=agent_access.refusal_reason(
                level, getattr(sched, "tool_mode", None),
                agent_access.SURFACE_SCHEDULE))
```

   with:

```python
            refusal_reason=agent_access.refusal_reason(
                level, getattr(sched, "tool_mode", None),
                agent_access.SURFACE_SCHEDULE),
            # The schedule's own prompt is what its owner asked for. The
            # reminder of the last run in front of it is ours, not theirs.
            intent=agent_escalation.Intent(
                person_text=getattr(sched, "prompt", "") or ""),
            usage=usage)
```

8. In `agent_runner.py`, replace:

```python
    finally:
        await agent_activity.finish_run(run_id, outcome)
```

   with:

```python
    finally:
        await agent_activity.finish_run(run_id, outcome, usage=usage)
```

9. In `routes_agent_chat.py`, add `import agent_escalation` directly after `import agent_access`.

10. In `routes_agent_chat.py`, replace:

```python
        out = await _turn_for(email, agent, turn_history, names)
        answer = out.get("answer") or ""
```

   with:

```python
        # The person's own words, not PASS_INSTRUCTION, which is the last
        # user message this agent reads. Carried rather than passed because
        # _turn_for and _run_turn sit in between.
        with agent_escalation.asking(agent_escalation.Intent(
                person_text=asked, may_pass=may_pass)):
            out = await _turn_for(email, agent, turn_history, names)
        answer = out.get("answer") or ""
```

11. In `routes_agent_chat.py`, replace:

```python
        out = await _turn_for(email, fallback, history, names)
```

   with:

```python
        with agent_escalation.asking(agent_escalation.Intent(
                person_text=asked, may_pass=False)):
            out = await _turn_for(email, fallback, history, names)
```

12. In `routes_agent_chat.py`, replace:

```python
            max_iterations=1, timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
```

   with:

```python
            max_iterations=1, timeout=CHANNEL_HTTP_TIMEOUT_SECONDS,
            # Notes for the room are housekeeping and never worth the paid
            # model. No intent means this turn cannot leave the free ones.
            intent=None)
```

**Step 4: Run the new tests and every agent test file.**

Run: `python -m pytest tests/test_agent_escalation_surfaces.py -q -p no:cacheprovider` then, for regressions, every agent file: `python -m pytest tests/test_agent_*.py tests/test_agents_*.py -q -p no:cacheprovider`
Expected: 8 passed; the agent files all pass apart from `ERROR at setup` on DB-tier tests. Existing test doubles accept the new keyword arguments (`**kwargs`, `AsyncMock`, `lambda *a, **k`), which is why no existing test changes.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/agent_runner.py mcp-servers/tasks/routes_agent_chat.py mcp-servers/tasks/tests/test_agent_escalation_surfaces.py
git -c core.safecrlf=false commit -m "Every agent surface says who is asking, and every run writes what it cost

The room hands over the person's words, not PASS_INSTRUCTION, and whether the agent may pass. An approval is a follow-up. A schedule's own prompt is its person text. The summariser passes no intent and cannot move.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The settings reach the container

**Files:**
- Modify: `docker-compose.unified.yml` (tasks service, after `AGENT_REFLECT_MODEL`)
- Test: `mcp-servers/tasks/tests/test_agent_paid_env.py`

**Step 1: Write the failing test.** Create `tests/test_agent_paid_env.py`:

```python
"""The paid model settings reach the tasks container.

Compose only injects what a service declares, and this repo has lost
WEBUI_SECRET_KEY, the Telegram credentials and GATEWAY_MODEL that way. A
setting the code reads but compose never passes silently runs on the code's
default, which here means spending money on a model nobody chose on purpose.
"""
import re

import pytest

import agent_escalation
from conftest import repo_root_or_skip

COMPOSE = repo_root_or_skip() / "docker-compose.unified.yml"

pytestmark = pytest.mark.skipif(
    not COMPOSE.exists(), reason="compose file not present in this checkout")

TEXT = COMPOSE.read_text(encoding="utf-8")


def _tasks_block() -> str:
    start = TEXT.index("\n  tasks:")
    rest = TEXT[start + 1:]
    m = re.search(r"\n  [a-z0-9_-]+:\n", rest)
    return rest[: m.start()] if m else rest


def _default(name: str) -> str:
    for line in _tasks_block().splitlines():
        s = line.strip()
        prefix = "- %s=${%s:-" % (name, name)
        if s.startswith(prefix) and s.endswith("}"):
            return s[len(prefix):-1]
    raise AssertionError(name + " is not passed to the tasks service")


@pytest.mark.parametrize("name,expected", [
    ("AGENT_PAID_MODEL", "gpt-5.5"),
    ("AGENT_PAID_REASONING", "low"),
    ("AGENT_PAID_TIMEOUT_SECONDS", "90"),
    ("AGENT_PAID_DAILY_CAP", "40"),
    ("AGENT_PAID_PRICES", "gpt-5.5=5:30"),
])
def test_each_paid_setting_reaches_the_container_with_the_agreed_default(name, expected):
    assert _default(name) == expected


def test_the_compose_prices_parse_to_the_price_read_on_2026_09_17():
    # No braces in the value: compose interpolation ends ${VAR:-...} at the
    # first closing brace, so a JSON default would be cut short.
    assert agent_escalation.parse_prices(_default("AGENT_PAID_PRICES")) == {
        "gpt-5.5": (5.0, 30.0)}
```

**Step 2: Run, expect failure.** Expected: 6 failed, `AGENT_PAID_MODEL is not passed to the tasks service`.

**Step 3: Implement.** In `docker-compose.unified.yml`, replace the line

```yaml
      - AGENT_REFLECT_MODEL=${AGENT_REFLECT_MODEL:-}
```

with:

```yaml
      - AGENT_REFLECT_MODEL=${AGENT_REFLECT_MODEL:-}
      # A free agent moves to the paid model on its own for app builds,
      # code, pasted errors, very long conversations, and when the free
      # models fail or run out of rounds (agent_escalation.py, design in
      # docs/plans/2026-09-17-agent-paid-escalation-design.md). The model
      # needs a public.model row and a read grant in Open WebUI, which
      # gpt-5.5 has. Prices are dollars per million tokens, input:output,
      # read 2026-09-17 from developers.openai.com/api/docs/pricing.
      # AGENT_PAID_DAILY_CAP is paid turns per person per UTC day; 0 turns
      # the whole feature off without a code change.
      - AGENT_PAID_MODEL=${AGENT_PAID_MODEL:-gpt-5.5}
      - AGENT_PAID_REASONING=${AGENT_PAID_REASONING:-low}
      - AGENT_PAID_TIMEOUT_SECONDS=${AGENT_PAID_TIMEOUT_SECONDS:-90}
      - AGENT_PAID_DAILY_CAP=${AGENT_PAID_DAILY_CAP:-40}
      - AGENT_PAID_PRICES=${AGENT_PAID_PRICES:-gpt-5.5=5:30}
```

**Step 4: Run again.** Expected: 6 passed. Also `python -m pytest tests/test_agent_gateway_env.py -q -p no:cacheprovider`: still passes.

**Step 5: Commit.**

```bash
git add docker-compose.unified.yml mcp-servers/tasks/tests/test_agent_paid_env.py
git -c core.safecrlf=false commit -m "The paid model settings reach the tasks container, and the cap can switch the feature off

No braces in the price default: compose ends ${VAR:-...} at the first closing brace.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Whole local suite, then review

**Step 1:** `cd mcp-servers/tasks && python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/browser`. Compare the failures with a run on the branch base (`git stash` is not needed: run the same command in the main checkout at the base commit). Only `ERROR at setup` on DB-tier tests may appear, and the same count on both.

**Step 2:** Browser suites that load agents pages: `python -m pytest tests/browser/test_agents_page.py tests/browser/test_agent_chat_turn_targets.py -q -p no:cacheprovider`. Expected: all pass (no UI changed).

**Step 3:** Request a code review (superpowers:requesting-code-review) of `git diff <base>..HEAD` against the design doc. Things worth a reviewer's eye: the probe path when a free probe returns PASS; `_paid_failed` treating a 400 as a reason to go back to free; the context variable set and reset around `_turn_for` inside an async generator (no `yield` between set and reset); the COALESCE in `finish_run`.

**Step 4:** Fix what the review finds, test first, one commit each.

---

### Task 11: Deploy and prove it live

Costs money: one real GPT-5.5 agent turn with tools. Estimate $0.05 to $0.40 (list price $5 in / $30 out per million tokens; an agent with every tool sends large tool specs, and a turn can make two or three completions). Read the actual cost from the row, do not quote the estimate as the result.

**Step 1: Merge and push.**
1. `git fetch fork`, then `git log --oneline HEAD..fork/main` and read anything new; rebase onto `fork/main` and rerun Tasks 7 and 8 test commands if anything under `mcp-servers/tasks` changed.
2. Merge into `main` (no fast-forward merge commit is fine), `gh auth switch -u Jacintalama`, `git push fork main`. Never push anywhere else.

**Step 2: Sweep the server before overwriting.** For every file this branch changed under `mcp-servers/tasks/` and `docker-compose.unified.yml`: compare the server copy (`ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/<path> | md5sum"`) with the version at the commit in `/root/proxy-server/.deploy-state` (`git show <sha>:<path> | tr -d '\r' | md5sum`). Any mismatch means someone changed it on the box: stop and look before copying. Then `git branch -r --contains <that sha>` to confirm what production runs is in `fork/main`.

**Step 3: Copy and rebuild.** One `scp` per changed file into the same path under `/root/proxy-server/` (new files: `agent_escalation.py`, the migration, the rollback, the seven new test files). Run `sed -i 's/\r$//'` on each copied file on the server. Then `cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks`. The tasks image bakes the code in, so nothing reaches the container without the rebuild. Write `.deploy-state` as JSON (`{"sha": ..., "deployed_at": ..., "deployed_by": ...}`) with the merge commit.

**Step 4: Smoke.** `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`. `docker exec tasks printenv AGENT_PAID_MODEL AGENT_PAID_DAILY_CAP AGENT_PAID_PRICES` shows `gpt-5.5`, `40`, `gpt-5.5=5:30`. `docker exec tasks sh -lc 'cd /app && python -c "import agent_runner, agent_activity; print(agent_runner.CHAT_TOKEN_TTL_SECONDS, agent_activity.STALE_AFTER_CHANNEL)"'` shows `3420 0:17:00`.

**Step 5: The migration ran.** In the postgres container (find the user with `docker exec postgres printenv POSTGRES_USER`, never print the password): `\d tasks.agent_run` lists `model`, `escalation`, `prompt_tokens`, `completion_tokens`, `cost_usd`, and `agent_run_paid_today_idx`. Run the cap's count SQL by hand for `alamajacintg04@gmail.com` and confirm it returns a number, which proves the `date_trunc(...) AT TIME ZONE` expression parses.

**Step 6: Tests in the container, DB tier included where it is safe.** `docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_agent_escalation_cost.py tests/test_agent_escalation_rules.py tests/test_agent_escalation_decide.py tests/test_agent_run_cost.py tests/test_agent_escalation_loop.py tests/test_agent_escalation_surfaces.py tests/test_migrations_runner.py -q -p no:cacheprovider'` (Python 3.11 there). Do not run destructive DB tests; none of these are.

**Step 7: A plain question stays free.** Inside the tasks container, POST `http://localhost:8210/agents/turn` with header `X-Internal-Secret` read from `INTERNAL_CALLBACK_SECRET` in the container's env (never printed), body `{"user_email": "alamajacintg04@gmail.com", "agent_id": "agent-ada-a1bc", "messages": [{"role": "user", "content": "What is on my calendar tomorrow?"}]}`, timeout 420. Record status, seconds, answer length. Then read the newest `tasks.agent_run` row for that agent: `model` is a `:free` id, `escalation` NULL, `cost_usd` 0.

**Step 8: A request that needs the paid model moves, uses a tool, and records its cost.** Same call with the content `I get TypeError: Cannot read properties of undefined (reading 'items') in my calendar sync. First check what is on my calendar tomorrow with your tools, then tell me in two sentences whether the calendar itself looks fine.` Expect: `docker logs tasks --since 5m` shows `agent agent-ada-a1bc moved to the paid model gpt-5.5 (error)` and one `paid completion for agent-ada-a1bc on gpt-5.5: N prompt tokens, M completion tokens` line per paid completion, and no `the paid model gpt-5.5 failed` line. The newest row has `model = gpt-5.5`, `escalation = error`, `prompt_tokens` equal to the sum of N, `completion_tokens` equal to the sum of M, and `cost_usd` equal to (sum N x 5 + sum M x 30) / 1,000,000. The tool call shows in the log (a calendar tool GET or `call_tool`). Record the latency.

If the log shows `the paid model gpt-5.5 failed` with a 400 about `reasoning_effort`, set the compose default of `AGENT_PAID_REASONING` to blank (not `.env`), commit, redeploy, and repeat this step once. If a paid reply carried no usage, `cost_usd` is NULL: record that, it means Open WebUI does not pass usage through and the cost has to come from somewhere else.

**Step 9: The window, then a plain question inside it.** Within 15 minutes of Step 8, repeat Step 7's question. The row must be free again (`escalation` NULL): a plain question inside the window goes back to free.

**Step 10: Report, verified versus inferred.** The two or three rows (model, reason, tokens, cost, seconds), the log lines, the actual dollars spent, and anything that did not behave as this plan says. Note for the owner that Ada's window for alamajacintg04 stays open for 15 minutes after Step 8, so a non-question message to Ada in that time goes to GPT-5.5.

**Step 11: Update memory.** Update `project_agent_subconscious_and_free_models.md` (or add a new project memory) with what shipped, the measured cost and latency, and the knobs (`AGENT_PAID_DAILY_CAP=0` switches it off).

---

## Open questions and assumptions

1. `reasoning_effort: low` on gpt-5.5 through Open WebUI, `usage` passthrough, latency inside 90 seconds, and tool calls on a posted `gpt-5.5` base id are unverified until Task 11. The loop fails open to the free model on a paid failure, so none of these can make a turn worse than today.
2. The Discord, Slack and Telegram gateway waits 420 seconds for a turn; a worst case paid turn is 930. Not changed here.
3. The sticky window and the once a day note are process memory. The tasks service runs one uvicorn worker (Dockerfile CMD has no `--workers`), so they are consistent while it runs and forgotten on restart. The cap is counted from the table and survives.
4. The cap counts runs that moved, including a paid attempt that failed and fell back. It is checked once per turn, so a room round of several agents can pass the cap by at most the number of agents still in that round.
5. Cached input is charged at the full input price, so the recorded cost errs high.
6. The message length threshold (2,000 characters), the paid timeout (90 seconds) and the extra rounds (3) are judgment, not measurement. The conversation threshold (60,000 characters) sits above the largest history nemotron answered in the 2026-09-17 repro (50.9k).
