# Agent subconscious and free models, implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Every agent remembers what it learned across conversations and surfaces, and every agent runs on a free OpenRouter model with automatic fallback to other free models.

**Architecture:** A new `agent_memory.py` module in the tasks service owns per-agent notes (`tasks.agent_memory`) and shared facts (`public.memory`), renders a recall block that the existing identity line and schedule runner carry, and runs a detached reflection after chat turns. `agent_runner._chat` learns a free-model pool: when the agent's base model is free it sends `reasoning_effort` and, on a provider failure, retries on the next pool id posting the base model directly. Nothing in Open WebUI changes except two config values and eleven `base_model_id` fields, both set through its admin API.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async (`db.session`), asyncpg for `public.*` tables, httpx, pytest with `asyncio_mode = auto`, vanilla JS in `static/agents.html`, Docker Compose on the Hetzner box.

Design: `docs/plans/2026-09-15-agent-subconscious-and-free-models-design.md`.

---

## Ground rules for whoever executes this

1. Work from `C:\Users\alama\Desktop\Lukas Work\IO`. Tasks service code is in `mcp-servers/tasks/`. Run its tests from that directory: `cd mcp-servers/tasks && python -m pytest tests/test_x.py -q`.
2. Expect about 167 `ERROR at setup` from tests that need Postgres. They are pre-existing. Only the tests named in each task matter.
3. Never touch `.env`. Never deploy `mcp-servers/tasks/templates.py`. Never `scp -r`. Commit before deploying. Push only to the `fork` remote.
4. No emoji, no long dashes, plain text labels, in code comments and in UI text.
5. Commit after every task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Use `git -c core.safecrlf=false commit` because the repo checks out CRLF.

---

### Task 1: Migration 049, the per-agent notes table

**Files:**
- Create: `mcp-servers/tasks/migrations/049_agent_memory.sql`
- Test: `mcp-servers/tasks/tests/test_migrations_runner.py`

**Step 1: Write the failing test**

Append to `tests/test_migrations_runner.py`:

```python
def test_the_agent_memory_migration_is_picked_up():
    names = [f.name for f in _would_run()]
    assert "049_agent_memory.sql" in names
    sql = (MIGRATIONS / "049_agent_memory.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS tasks.agent_memory" in sql
    assert "UNIQUE (agent_id, user_email, key)" in sql
```

**Step 2: Run it, expect failure**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_migrations_runner.py -q`
Expected: 1 failed, `assert '049_agent_memory.sql' in names`.

**Step 3: Write the migration**

Create `migrations/049_agent_memory.sql`:

```sql
-- 049: what an agent remembers between conversations.
--
-- Nothing carried across a chat before this. The panel summarises one
-- conversation (048), a schedule gets its own last result, and the remember
-- tool writes to Open WebUI's public.memory table, which held 0 rows after a
-- year because nothing on the agent path read it back. This table is the
-- agent's own notes: what it did for this person, what is open, how they
-- like its output. Facts about the PERSON stay in public.memory so they show
-- in Settings > Personalization > Memories and the Brain graph.
--
-- `key` is the note normalised (lower case, punctuation stripped, whitespace
-- collapsed, 120 characters) and is what makes the same note said twice one
-- row. A reflection that re-learns a fact touches last_seen_at instead of
-- adding a duplicate.
--
-- No foreign key to public.model: Open WebUI owns that table and an agent
-- can be deleted at any moment, the same reasoning as 044.
--
-- Idempotent: db.py re-runs every migration on every startup.
CREATE TABLE IF NOT EXISTS tasks.agent_memory (
    id           UUID        PRIMARY KEY,
    agent_id     TEXT        NOT NULL,
    user_email   TEXT        NOT NULL,
    content      TEXT        NOT NULL,
    key          TEXT        NOT NULL,
    source       TEXT        NOT NULL DEFAULT 'reflection',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, user_email, key)
);

-- The recall query: this person's notes for this agent, newest first.
CREATE INDEX IF NOT EXISTS agent_memory_recall_idx
    ON tasks.agent_memory (user_email, agent_id, last_seen_at DESC);
```

**Step 4: Run the test, expect pass**

Run: `python -m pytest tests/test_migrations_runner.py -q`
Expected: all passed.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/migrations/049_agent_memory.sql mcp-servers/tasks/tests/test_migrations_runner.py
git -c core.safecrlf=false commit -m "Agents get a table for what they remember between conversations" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: agent_memory.py, the pure parts

**Files:**
- Create: `mcp-servers/tasks/agent_memory.py`
- Test: `mcp-servers/tasks/tests/test_agent_memory.py`

**Step 1: Write the failing tests**

Create `tests/test_agent_memory.py`:

```python
"""What an agent remembers between conversations, the parts with no I/O.

The key, the recall block and the reflection parser are pure, so they are
tested directly. The store is tested against real Postgres in the container
(test_agent_memory_db.py) because a fake session would only prove what the
fake imagined.
"""
import json

import agent_memory as am


def test_the_key_collapses_case_punctuation_and_whitespace():
    a = am.memory_key("Prefers replies in Tagalog.")
    b = am.memory_key("  prefers   replies, in TAGALOG ")
    assert a == b == "prefers replies in tagalog"


def test_the_key_is_capped_so_a_long_note_still_dedups():
    assert len(am.memory_key("x" * 500)) == 120


def test_an_empty_store_renders_nothing():
    """Byte identical turns for agents with no memory: the block must be
    empty, not a heading over nothing."""
    assert am.render_recall([], []) == ""


def test_notes_come_first_then_facts_with_their_headings():
    out = am.render_recall(["Sends the digest at 7am Manila time."],
                           ["Client is called Northwind."])
    assert out.index("Your notes from earlier conversations") < out.index(
        "Known about this person")
    assert "- Sends the digest at 7am Manila time." in out
    assert "- Client is called Northwind." in out


def test_the_block_stays_inside_its_budget_and_keeps_the_newest():
    notes = ["note %d %s" % (i, "n" * 100) for i in range(40)]
    facts = ["fact %d %s" % (i, "f" * 100) for i in range(40)]
    out = am.render_recall(notes, facts)
    assert len(out) <= am.RECALL_BUDGET_CHARS
    # Newest first is the caller's order; the first note must survive.
    assert "note 0 " in out
    assert "fact 0 " in out


def test_the_parser_reads_json_wrapped_in_prose_and_fences():
    text = ('Here you go:\n```json\n{"notes": ["Did the weekly review."], '
            '"facts": ["Lives in Cebu."]}\n```')
    notes, facts = am.parse_reflection(text)
    assert notes == ["Did the weekly review."]
    assert facts == ["Lives in Cebu."]


def test_the_parser_drops_questions_pass_short_and_over_three():
    text = json.dumps({
        "notes": ["What does he want?", "PASS", "short", "Keeps Friday free.",
                  "Second real note here.", "Third real note here.",
                  "Fourth real note here."],
        "facts": [42, "", "Prefers short answers."]})
    notes, facts = am.parse_reflection(text)
    assert notes == ["Keeps Friday free.", "Second real note here.",
                     "Third real note here."]
    assert facts == ["Prefers short answers."]


def test_the_parser_caps_each_item_at_two_hundred_characters():
    notes, _ = am.parse_reflection(json.dumps({"notes": ["y" * 300]}))
    assert len(notes[0]) == 200


def test_garbage_parses_to_nothing():
    assert am.parse_reflection("no json here") == ([], [])
    assert am.parse_reflection("") == ([], [])


def test_should_reflect_needs_a_real_message_and_a_real_answer():
    assert am.should_reflect("Set the digest to 7am Manila time from now on.",
                             "Done, 7am Manila it is.")
    assert not am.should_reflect("hi", "Hello.")
    assert not am.should_reflect("Set the digest to 7am Manila time from now on.", "PASS")
    assert not am.should_reflect("Set the digest to 7am Manila time from now on.", "")
    assert not am.should_reflect(
        "Set the digest to 7am Manila time from now on.",
        "This agent is set to a model that cannot run an agent.")


def test_the_prompt_carries_what_is_already_known():
    prompt = am.reflection_prompt("Ada", ["Already knows this."],
                                  ["Client is Northwind."],
                                  "Move the digest to 7am.", "Done.")
    assert "Ada" in prompt
    assert "Already knows this." in prompt
    assert "Client is Northwind." in prompt
    assert "Move the digest to 7am." in prompt
    assert '{"notes": [], "facts": []}' in prompt
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agent_memory.py -q`
Expected: errors, `ModuleNotFoundError: No module named 'agent_memory'`.

**Step 3: Write the pure half of the module**

Create `agent_memory.py`:

```python
"""What an agent remembers between conversations: its subconscious.

Two stores. The agent's own notes live in tasks.agent_memory, one row per
(agent, person, note). Facts about the person live in Open WebUI's
public.memory, because that is the table Settings > Personalization >
Memories and the Brain graph already read, and a fact every agent shares
belongs where the person can see and delete it.

Two directions. Recall: recall_block() renders both stores as one block of
text that the identity line (chat, panel, bots) and the schedule runner
carry, so every turn on every surface starts from what is known. Capture:
schedule_reflection() runs a detached completion after a chat turn that
writes down what was settled, so the agent does not have to think to
remember. The remember tool still exists for when the person says
"remember this".

Everything here fails open. A turn must never fail because its memory did.
"""
import asyncio
import json
import logging
import re
import time
import uuid

from sqlalchemy import text as sql_text

from db import session

logger = logging.getLogger(__name__)

#: The whole block, notes plus facts. Sized so it costs less than the skill
#: brief and far less than the conversation it rides in front of.
RECALL_BUDGET_CHARS = 2400
NOTES_BUDGET_CHARS = 1400
FACTS_BUDGET_CHARS = 1000

#: Caps on what is kept. Beyond these the oldest by last_seen_at goes.
MAX_NOTES_PER_AGENT = 60
MAX_FACTS_PER_PERSON = 100

#: The reflection's own limits. Three of each per turn is plenty: a turn
#: that settled more than three things is rare, and a model told it may
#: write ten writes ten.
MAX_ITEMS_PER_KIND = 3
MAX_ITEM_CHARS = 200
MIN_ITEM_CHARS = 12

#: A turn worth reflecting on. Shorter than this is a greeting or a yes.
MIN_USER_CHARS = 40

#: One reflection per agent per this many seconds, and this many in flight
#: per process. Free models are free of money, not of quota: 1,000 requests
#: a day on this key, shared with everything else on the platform.
REFLECT_MIN_INTERVAL_SECONDS = 90
REFLECT_MAX_IN_FLIGHT = 2

#: The service's own sentences that must never be reflected on as if the
#: agent had said them. Kept as prefixes because two of them carry a name.
_NOT_AN_ANSWER_PREFIXES = (
    "PASS",
    "This agent is set to a model that cannot run an agent.",
    "The free models are all busy right now",
    "There was nothing to answer.",
    "Stopped after",
)

_KEY_STRIP_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def memory_key(text: str) -> str:
    """The note as a dedup key: lower case, letters digits and spaces only,
    single spaces, 120 characters."""
    out = _KEY_STRIP_RE.sub(" ", (text or "").lower())
    return _WS_RE.sub(" ", out).strip()[:120]


def _fit(items: list[str], budget: int) -> list[str]:
    """The leading items that fit the budget, whole items only."""
    out: list[str] = []
    spent = 0
    for item in items:
        line = "- " + item + "\n"
        if spent + len(line) > budget:
            break
        out.append(item)
        spent += len(line)
    return out


def render_recall(notes: list[str], facts: list[str]) -> str:
    """Both stores as one block, or "" when both are empty.

    Caller passes newest first; the budget keeps the front of each list.
    Rendered as plain lines under two headings, in the second person,
    because it sits inside the identity line that already speaks that way.
    """
    parts = []
    kept_notes = _fit([n for n in notes if n], NOTES_BUDGET_CHARS)
    kept_facts = _fit([f for f in facts if f], FACTS_BUDGET_CHARS)
    if kept_notes:
        parts.append("Your notes from earlier conversations with this person, "
                     "newest first. Use them; do not repeat them back unless "
                     "asked:\n" + "\n".join("- " + n for n in kept_notes))
    if kept_facts:
        parts.append("Known about this person:\n"
                     + "\n".join("- " + f for f in kept_facts))
    return "\n\n".join(parts)[:RECALL_BUDGET_CHARS]


def _clean_items(raw) -> list[str]:
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, str):
            continue
        item = _WS_RE.sub(" ", item).strip()[:MAX_ITEM_CHARS]
        if len(item) < MIN_ITEM_CHARS:
            continue
        if item.endswith("?") or item.upper() == "PASS":
            continue
        out.append(item)
        if len(out) >= MAX_ITEMS_PER_KIND:
            break
    return out


def parse_reflection(text: str) -> tuple[list[str], list[str]]:
    """(notes, facts) from whatever the model wrote. Lenient on purpose:
    the JSON is found between the first "{" and the last "}", so prose and
    code fences around it do not matter. Anything that is not the shape
    asked for parses to nothing rather than raising."""
    text = text or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return [], []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return [], []
    if not isinstance(data, dict):
        return [], []
    return _clean_items(data.get("notes")), _clean_items(data.get("facts"))


def should_reflect(user_text: str, answer: str) -> bool:
    """Whether this turn is worth one free completion."""
    if len((user_text or "").strip()) < MIN_USER_CHARS:
        return False
    answer = (answer or "").strip()
    if not answer:
        return False
    return not any(answer.startswith(p) for p in _NOT_AN_ANSWER_PREFIXES)


def reflection_prompt(agent_name: str, notes: list[str], facts: list[str],
                      user_text: str, answer: str) -> str:
    known = ("Notes it already has:\n" + "\n".join("- " + n for n in notes)
             if notes else "Notes it already has: none.")
    facts_block = ("Facts already known about the person:\n"
                   + "\n".join("- " + f for f in facts)
                   if facts else "Facts already known about the person: none.")
    return (
        "You are the memory of an assistant called %s. Below is what it "
        "already remembers, then one exchange it just had with the person "
        "it works for. Write down only what is worth keeping for a month: "
        "decisions, preferences, names, numbers, commitments, open items.\n\n"
        "%s\n\n%s\n\n"
        "The person said:\n%s\n\nThe assistant answered:\n%s\n\n"
        "Return JSON only, of the shape {\"notes\": [], \"facts\": []}. "
        "notes: things about this assistant's own work with the person, "
        "what it did, what is open, how they want its output. "
        "facts: lasting things about the person that any assistant should "
        "know, preferences, people, places, names. Up to 3 of each, one "
        "sentence each, under 200 characters, in the third person, with no "
        "reference to this conversation, and nothing that is already in the "
        "lists above. Never store a guess, a question, a greeting or a "
        "thank you. If nothing is worth keeping, return exactly "
        "{\"notes\": [], \"facts\": []}."
        % (agent_name or "this assistant", known, facts_block,
           (user_text or "")[:2000], (answer or "")[:2000]))
```

**Step 4: Run, expect pass**

Run: `python -m pytest tests/test_agent_memory.py -q`
Expected: 11 passed.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_memory.py mcp-servers/tasks/tests/test_agent_memory.py
git -c core.safecrlf=false commit -m "The pure half of agent memory: keys, the recall block, the reflection parser" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: agent_memory.py, the store

**Files:**
- Modify: `mcp-servers/tasks/agent_memory.py` (append)
- Test: `mcp-servers/tasks/tests/test_agent_memory_db.py` (DB tier, container only)
- Test: `mcp-servers/tasks/tests/test_agent_memory.py` (fail-open, local)

**Step 1: Write the failing tests**

Append to `tests/test_agent_memory.py`:

```python
from unittest.mock import AsyncMock, patch


async def test_recall_fails_open_when_the_database_is_down():
    with patch.object(am, "list_notes", new=AsyncMock(side_effect=RuntimeError("db"))), \
         patch.object(am, "list_facts", new=AsyncMock(return_value=["a fact"])):
        out = await am.recall_block("o@example.com", "agent-1")
    assert out == ""


async def test_recall_renders_both_stores_newest_first():
    with patch.object(am, "list_notes", new=AsyncMock(return_value=[
            {"id": "n1", "content": "newest note"}, {"id": "n2", "content": "older note"}])), \
         patch.object(am, "list_facts", new=AsyncMock(return_value=["a fact"])):
        out = await am.recall_block("o@example.com", "agent-1")
    assert out.index("newest note") < out.index("older note")
    assert "a fact" in out
```

Create `tests/test_agent_memory_db.py`:

```python
"""The agent memory store against real Postgres.

Container only: `python -m pytest tests/test_agent_memory_db.py -q` inside
the tasks container with AIUI_TEST_DB=1 and a DATABASE_URL containing
"test". Locally every test here errors at setup, which is expected.
"""
import uuid

import pytest

import agent_memory as am

pytestmark = pytest.mark.asyncio


def _who():
    tag = uuid.uuid4().hex[:8]
    return "memtest-%s@example.com" % tag, "agent-memtest-%s" % tag


async def test_add_list_dedup_and_delete(db_session):
    email, agent = _who()
    added = await am.add_notes(email, agent, ["Sends the digest at 7am.",
                                              "sends the digest at 7am"])
    assert added == 1, "the same note in different case is one row"
    rows = await am.list_notes(email, agent)
    assert [r["content"] for r in rows] == ["Sends the digest at 7am."]
    assert await am.delete_note(email, agent, rows[0]["id"]) is True
    assert await am.list_notes(email, agent) == []


async def test_the_cap_prunes_the_oldest(db_session):
    email, agent = _who()
    for i in range(am.MAX_NOTES_PER_AGENT + 5):
        await am.add_notes(email, agent, ["note number %d for pruning" % i])
    rows = await am.list_notes(email, agent, limit=500)
    assert len(rows) == am.MAX_NOTES_PER_AGENT
    assert all("note number 0 " not in r["content"] for r in rows)
    await am.clear_notes(email, agent)


async def test_counts_are_per_agent_for_one_person(db_session):
    email, agent = _who()
    await am.add_notes(email, agent, ["one thing worth keeping"])
    await am.add_notes(email, agent + "-b", ["another thing worth keeping"])
    counts = await am.note_counts(email)
    assert counts[agent] == 1 and counts[agent + "-b"] == 1
    await am.clear_notes(email, agent)
    await am.clear_notes(email, agent + "-b")
```

**Step 2: Run the local test, expect failure**

Run: `python -m pytest tests/test_agent_memory.py -q`
Expected: 2 failed, `AttributeError: ... has no attribute 'list_notes'`.

**Step 3: Append the store to agent_memory.py**

```python
# --- the agent's own notes: tasks.agent_memory ------------------------------

async def add_notes(user_email: str, agent_id: str, notes: list[str],
                    source: str = "reflection") -> int:
    """Store notes, one row each, deduplicated by key. Returns how many were
    new. A repeat touches last_seen_at so pruning keeps what keeps coming
    up. Prunes to the cap afterwards. Never raises."""
    if not user_email or not agent_id:
        return 0
    added = 0
    try:
        async with session() as s:
            for note in notes:
                key = memory_key(note)
                if not key:
                    continue
                r = await s.execute(sql_text(
                    "INSERT INTO tasks.agent_memory "
                    "(id, agent_id, user_email, content, key, source) "
                    "VALUES (:id, :agent, :email, :content, :key, :source) "
                    "ON CONFLICT (agent_id, user_email, key) DO UPDATE "
                    "SET last_seen_at = now() "
                    "RETURNING (xmax = 0) AS inserted"),
                    {"id": str(uuid.uuid4()), "agent": agent_id,
                     "email": user_email, "content": note, "key": key,
                     "source": source})
                row = r.first()
                if row is not None and row[0]:
                    added += 1
            await s.execute(sql_text(
                "DELETE FROM tasks.agent_memory WHERE id IN ("
                " SELECT id FROM tasks.agent_memory "
                " WHERE agent_id = :agent AND user_email = :email "
                " ORDER BY last_seen_at DESC OFFSET :cap)"),
                {"agent": agent_id, "email": user_email,
                 "cap": MAX_NOTES_PER_AGENT})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not store agent notes", exc_info=True)
    return added


async def list_notes(user_email: str, agent_id: str,
                     limit: int = MAX_NOTES_PER_AGENT) -> list[dict]:
    """Newest first. Raises on a database failure; recall_block catches."""
    async with session() as s:
        r = await s.execute(sql_text(
            "SELECT id, content, source, created_at, last_seen_at "
            "FROM tasks.agent_memory "
            "WHERE user_email = :email AND agent_id = :agent "
            "ORDER BY last_seen_at DESC LIMIT :limit"),
            {"email": user_email, "agent": agent_id, "limit": limit})
        return [{"id": str(row.id), "content": row.content,
                 "source": row.source,
                 "created_at": row.created_at.isoformat(),
                 "last_seen_at": row.last_seen_at.isoformat()}
                for row in r]


async def note_counts(user_email: str) -> dict:
    """{agent_id: notes} for one person, for the cards."""
    async with session() as s:
        r = await s.execute(sql_text(
            "SELECT agent_id, count(*) AS n FROM tasks.agent_memory "
            "WHERE user_email = :email GROUP BY agent_id"),
            {"email": user_email})
        return {row.agent_id: int(row.n) for row in r}


async def delete_note(user_email: str, agent_id: str, note_id: str) -> bool:
    async with session() as s:
        r = await s.execute(sql_text(
            "DELETE FROM tasks.agent_memory "
            "WHERE user_email = :email AND agent_id = :agent AND id = CAST(:id AS uuid)"),
            {"email": user_email, "agent": agent_id, "id": note_id})
        await s.commit()
        return r.rowcount > 0


async def clear_notes(user_email: str, agent_id: str) -> int:
    async with session() as s:
        r = await s.execute(sql_text(
            "DELETE FROM tasks.agent_memory "
            "WHERE user_email = :email AND agent_id = :agent"),
            {"email": user_email, "agent": agent_id})
        await s.commit()
        return r.rowcount


# --- facts about the person: public.memory ----------------------------------

async def _owui_user_id(user_email: str) -> str | None:
    async with session() as s:
        r = await s.execute(sql_text(
            'SELECT id FROM public."user" WHERE email = :email LIMIT 1'),
            {"email": user_email})
        row = r.first()
        return str(row[0]) if row else None


async def list_facts(user_email: str,
                     limit: int = MAX_FACTS_PER_PERSON) -> list[str]:
    """Newest first. Raises on failure; recall_block catches."""
    uid = await _owui_user_id(user_email)
    if not uid:
        return []
    async with session() as s:
        r = await s.execute(sql_text(
            'SELECT content FROM public."memory" WHERE user_id = :uid '
            "ORDER BY created_at DESC LIMIT :limit"),
            {"uid": uid, "limit": limit})
        return [row[0] for row in r if row[0]]


async def add_facts(user_email: str, facts: list[str]) -> int:
    """Store facts about the person as Open WebUI memories, deduplicated by
    key against what is already there. Returns how many were new. Never
    raises."""
    if not user_email or not facts:
        return 0
    added = 0
    try:
        uid = await _owui_user_id(user_email)
        if not uid:
            return 0
        existing = {memory_key(f) for f in await list_facts(user_email)}
        async with session() as s:
            for fact in facts:
                key = memory_key(fact)
                if not key or key in existing:
                    continue
                now = int(time.time())
                await s.execute(sql_text(
                    'INSERT INTO public."memory" '
                    "(id, user_id, content, created_at, updated_at) "
                    "VALUES (:id, :uid, :content, :now, :now)"),
                    {"id": str(uuid.uuid4()), "uid": uid,
                     "content": fact, "now": now})
                existing.add(key)
                added += 1
            await s.execute(sql_text(
                'DELETE FROM public."memory" WHERE id IN ('
                ' SELECT id FROM public."memory" WHERE user_id = :uid '
                " ORDER BY created_at DESC OFFSET :cap)"),
                {"uid": uid, "cap": MAX_FACTS_PER_PERSON})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not store facts about the person", exc_info=True)
    return added


# --- recall -----------------------------------------------------------------

#: Reading memory must never hold a turn hostage.
RECALL_TIMEOUT_SECONDS = 3.0


async def recall_block(user_email: str, agent_id: str) -> str:
    """Everything this agent should start the turn knowing, or "".

    Both reads race one timeout. Any failure, including the timeout, is an
    empty block and one log line: a turn without memory is a turn, a turn
    that waits on memory is an outage.
    """
    if not user_email or not agent_id:
        return ""
    try:
        notes, facts = await asyncio.wait_for(
            asyncio.gather(list_notes(user_email, agent_id),
                           list_facts(user_email)),
            timeout=RECALL_TIMEOUT_SECONDS)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read agent memory for %s", agent_id,
                       exc_info=True)
        return ""
    return render_recall([n["content"] for n in notes], facts)
```

**Step 4: Run the local test, expect pass**

Run: `python -m pytest tests/test_agent_memory.py -q`
Expected: 13 passed. `tests/test_agent_memory_db.py` errors at setup locally; that is the DB tier and runs in Task 13.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_memory.py mcp-servers/tasks/tests/test_agent_memory.py mcp-servers/tasks/tests/test_agent_memory_db.py
git -c core.safecrlf=false commit -m "Agent memory store: notes per agent, facts per person, recall that fails open" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Recall rides in the identity line on chat, panel and bots

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_turn.py` (`_identity_line` at line 725, `_turn_for` at line 824)
- Test: `mcp-servers/tasks/tests/test_agent_recall.py`

**Step 1: Write the failing tests**

Create `tests/test_agent_recall.py`:

```python
"""What an agent starts a turn knowing.

The recall block rides at the end of the identity line so every surface that
builds a turn through _turn_for carries it: the main chat pipe, the panel,
Discord, Slack and Telegram.
"""
from unittest.mock import AsyncMock

import pytest

import agent_memory
import routes_agent_turn as rt


def _agent():
    return {"id": "agent-1", "name": "Ada", "meta": {"toolIds": ["gmail"]}}


def test_an_empty_block_leaves_the_identity_line_byte_identical():
    before = rt._identity_line(_agent(), ["Ada"])
    after = rt._identity_line(_agent(), ["Ada"], memory="")
    assert before == after


def test_the_block_is_appended_after_everything_else():
    line = rt._identity_line(_agent(), ["Ada"], memory="Known about this person:\n- x")
    content = line["content"]
    assert content.endswith("Known about this person:\n- x")
    assert "\n\nKnown about this person" in content


async def test_turn_for_reads_memory_and_hands_it_to_the_line(monkeypatch):
    seen = {}

    async def fake_run(user_email, agent_id, messages):
        seen["messages"] = messages
        return {"answer": "ok", "notes": []}

    monkeypatch.setattr(rt, "_run_turn", fake_run)
    monkeypatch.setattr(agent_memory, "recall_block",
                        AsyncMock(return_value="Known about this person:\n- likes tea"))
    await rt._turn_for("o@example.com", _agent(),
                       [{"role": "user", "content": "hello there"}], ["Ada"])
    system = seen["messages"][0]
    assert system["role"] == "system"
    assert "likes tea" in system["content"]
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agent_recall.py -q`
Expected: `TypeError: _identity_line() got an unexpected keyword argument 'memory'` and the async test fails.

**Step 3: Edit routes_agent_turn.py**

Add `import agent_memory` next to `import agent_access` (line 26 area).

Change the signature at line 725:

```python
def _identity_line(agent: dict, names, memory: str = "") -> dict:
```

At the end of `_identity_line`, replace:

```python
    chosen = agent_skills.brief_for(agent.get("meta"))
    if chosen:
        content += "\n\n" + chosen
    return {"role": "system", "content": content}
```

with:

```python
    chosen = agent_skills.brief_for(agent.get("meta"))
    if chosen:
        content += "\n\n" + chosen
    # Last, after the skills. What the agent remembers is the most specific
    # thing in the line and the thing most likely to answer the question
    # being asked, so it sits nearest the conversation. Empty for an agent
    # with nothing stored, which keeps every existing turn byte identical.
    if memory:
        content += "\n\n" + memory
    return {"role": "system", "content": content}
```

In `_turn_for`, replace:

```python
    history = ([_identity_line(agent, names)]
               + agent_routing.clean_history_for_agent(messages, names))
```

with:

```python
    memory = await agent_memory.recall_block(user_email, agent["id"])
    history = ([_identity_line(agent, names, memory=memory)]
               + agent_routing.clean_history_for_agent(messages, names))
```

**Step 4: Run, expect pass; then the neighbours**

Run: `python -m pytest tests/test_agent_recall.py tests/test_agent_label_echo.py tests/test_agent_skills.py tests/test_agent_tool_reach.py tests/test_agents_speak.py tests/test_agent_chat_round.py -q`
Expected: all passed. If a neighbour test fails because `_turn_for` now awaits `recall_block` against a missing database, patch `agent_memory.recall_block` in that test's fixture with `AsyncMock(return_value="")` rather than weakening the assertion. `recall_block` fails open, so most will pass untouched.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/tests/test_agent_recall.py
git -c core.safecrlf=false commit -m "Every chat, panel and bot turn starts from what the agent remembers" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Recall on schedules

**Files:**
- Modify: `mcp-servers/tasks/agent_runner.py` (`run_agent`, the `_chat(` call near line 539)
- Test: `mcp-servers/tasks/tests/test_agent_recall.py` (append)

**Step 1: Write the failing test**

Look at `tests/test_agent_runner.py` for how `run_agent` is driven (it patches `_owui_user_id_for`, `_list_agents`, `mint_owui_token`, `_chat`, and builds a fake `sched` object). Copy its fixture shape. Append to `tests/test_agent_recall.py`:

```python
async def test_a_schedule_run_carries_the_block_as_the_leading_system_message(monkeypatch):
    import agent_runner

    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "report", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([{"id": "agent-1", "name": "Ada",
                                                   "meta": {"toolIds": []}}], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)
    monkeypatch.setattr(agent_runner.agent_activity, "start_run", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runner.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(agent_memory, "recall_block",
                        AsyncMock(return_value="Known about this person:\n- likes tea"))
    import routes_agent_turn
    monkeypatch.setattr(routes_agent_turn, "tools_for_agent", AsyncMock(return_value=[]))

    class Sched:
        id = "s1"; agent_id = "agent-1"; user_email = "o@example.com"
        prompt = "Write the weekly review."; last_result = ""; last_run_status = None
        tool_mode = "read_only"

    status, _result, _extras = await agent_runner.run_agent(Sched())
    assert status == "completed"
    first = seen["messages"][0]
    assert first["role"] == "system" and "likes tea" in first["content"]
    assert seen["messages"][-1]["content"] == "Write the weekly review."
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agent_recall.py -q`
Expected: the new test fails on `first["role"] == "system"` (the first message is the prompt).

**Step 3: Edit agent_runner.py**

Add `import agent_memory` beside `import agent_access` at the top. In `run_agent`, replace:

```python
        answer, notes = await _chat(
            token=chat_token, model=sched.agent_id,
            messages=_messages_for(sched), tool_ids=tools or None,
```

with:

```python
        # What this agent remembers rides in front of the task, the same
        # block the chat surfaces carry. Empty when nothing is stored.
        messages = _messages_for(sched)
        memory = await agent_memory.recall_block(sched.user_email, sched.agent_id)
        if memory:
            messages = [{"role": "system", "content": memory}] + messages
        answer, notes = await _chat(
            token=chat_token, model=sched.agent_id,
            messages=messages, tool_ids=tools or None,
```

**Step 4: Run, expect pass**

Run: `python -m pytest tests/test_agent_recall.py tests/test_agent_runner.py -q`
Expected: all passed.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/tests/test_agent_recall.py
git -c core.safecrlf=false commit -m "A scheduled run starts from what the agent remembers too" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: The free model pool and fallback in the tool loop

**Files:**
- Modify: `mcp-servers/tasks/agent_runner.py` (`_chat` at line 289 and the constants above it)
- Test: `mcp-servers/tasks/tests/test_agent_free_fallback.py`

**Step 1: Write the failing tests**

Create `tests/test_agent_free_fallback.py`:

```python
"""Agents on free models: reasoning off, and the next free model when the
provider fails.

Every test drives agent_runner._chat with a fake _post_chat, the way
test_agent_tool_loop.py does. The failure shapes are the three measured on
production on 2026-09-15: HTTP 400 "Provider returned error", HTTP 200 with
an error object and no choices, and a body with no choices at all.
"""
from unittest.mock import patch

import httpx
import pytest

import agent_runner


def _reply(content="ok", calls=None):
    msg = {"content": content, "tool_calls": calls or None}
    return {"choices": [{"message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}]}


def _http_400():
    req = httpx.Request("POST", "http://open-webui:8080/api/chat/completions")
    resp = httpx.Response(400, json={"detail": "Provider returned error"}, request=req)
    return httpx.HTTPStatusError("400", request=req, response=resp)


def _agent(base="nvidia/nemotron-3-super-120b-a12b:free", system="Be Ada."):
    return {"id": "agent-1", "name": "Ada", "base_model_id": base,
            "params": {"system": system}}


POOL = ["nvidia/nemotron-3-super-120b-a12b:free",
        "nex-agi/nex-n2.5-pro:free", "nex-agi/nex-n2.5-mini:free"]


@pytest.fixture(autouse=True)
def _pool(monkeypatch):
    monkeypatch.setattr(agent_runner, "FREE_MODELS", list(POOL))
    monkeypatch.setattr(agent_runner, "FREE_REASONING", "none")
    monkeypatch.setattr(agent_runner, "_available_free_ids",
                        _AsyncNone())


class _AsyncNone:
    async def __call__(self):
        return None


async def test_a_free_agent_sends_reasoning_off_and_a_paid_one_does_not():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply()

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        await agent_runner._chat(token="t", model="agent-1",
                                 messages=[{"role": "user", "content": "q"}],
                                 tool_ids=None, user_email="o@example.com",
                                 tool_mode="read_only", agent=_agent())
        await agent_runner._chat(token="t", model="agent-2",
                                 messages=[{"role": "user", "content": "q"}],
                                 tool_ids=None, user_email="o@example.com",
                                 tool_mode="read_only", agent=_agent(base="gpt-4o-mini"))
    assert posts[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in posts[1]


async def test_a_provider_failure_moves_the_turn_to_the_next_free_model():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            raise _http_400()
        return _reply("answered on the fallback")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "system", "content": "identity"},
                      {"role": "user", "content": "q"}],
            tool_ids=["schedules"], user_email="o@example.com",
            tool_mode="read_only", agent=_agent())

    assert answer == "answered on the fallback"
    assert posts[0]["model"] == "agent-1"
    assert posts[1]["model"] == "nex-agi/nex-n2.5-pro:free"
    # Posting the base model directly loses the agent's own instructions,
    # which Open WebUI only applies for the derived model, so they go first.
    assert posts[1]["messages"][0] == {"role": "system", "content": "Be Ada."}
    assert posts[1]["messages"][1]["content"] == "identity"
    assert posts[1]["tool_ids"] == ["schedules"]
    assert posts[1]["reasoning_effort"] == "none"


async def test_a_200_with_an_error_object_counts_as_a_provider_failure():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return {"error": {"code": 502, "message": "Upstream error"}}
        return _reply("ok")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, _ = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == "ok"
    assert posts[1]["model"] == "nex-agi/nex-n2.5-pro:free"


async def test_the_turn_stays_on_the_fallback_for_its_later_rounds():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            raise _http_400()
        if len(posts) == 2:
            return _reply("", calls=[{"id": "c1", "type": "function",
                                       "function": {"name": "list_my_schedules",
                                                    "arguments": "{}"}}])
        return _reply("two schedules")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", return_value="[]") as ex:
        ex.side_effect = None
        async def run(*a, **k):
            return "[]"
        ex.side_effect = run
        answer, _ = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["schedules"], user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == "two schedules"
    assert [p["model"] for p in posts] == [
        "agent-1", "nex-agi/nex-n2.5-pro:free", "nex-agi/nex-n2.5-pro:free"]


async def test_a_spent_pool_answers_with_the_busy_sentence_not_an_exception():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise _http_400()

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == agent_runner.FREE_POOL_EXHAUSTED
    assert len(posts) == 3, "each pool id is tried exactly once"


async def test_a_paid_agent_never_falls_back():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise _http_400()

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         pytest.raises(httpx.HTTPStatusError):
        await agent_runner._chat(
            token="t", model="agent-2", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent(base="gpt-4o-mini"))
    assert len(posts) == 1


async def test_no_agent_row_means_the_old_behaviour_exactly():
    """Callers that predate this (tests, the summariser) pass no agent."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise _http_400()

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         pytest.raises(httpx.HTTPStatusError):
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only")
    assert len(posts) == 1 and "reasoning_effort" not in posts[0]


async def test_withdrawn_pool_ids_are_skipped_when_the_catalogue_is_known(monkeypatch):
    async def catalogue():
        return {"nvidia/nemotron-3-super-120b-a12b:free", "nex-agi/nex-n2.5-mini:free"}
    monkeypatch.setattr(agent_runner, "_available_free_ids", catalogue)
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            raise _http_400()
        return _reply("ok")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert posts[1]["model"] == "nex-agi/nex-n2.5-mini:free"
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agent_free_fallback.py -q`
Expected: failures, `AttributeError: module 'agent_runner' has no attribute 'FREE_MODELS'` and `TypeError: _chat() got an unexpected keyword argument 'agent'`.

**Step 3: Implement in agent_runner.py**

Add `import time` to the imports if absent. Below `ROUTER_EXHAUSTED` and `_router_gave_up` (around line 288), add:

```python
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
    429 or 5xx; a 200 whose body carries an `error` object; a 200 with no
    choices at all. A 401 or 403 is this service's own problem and is not
    retried anywhere.
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
        if exc_or_body.get("error"):
            return True
        return not exc_or_body.get("choices")
    return False


async def _available_free_ids() -> set | None:
    """Free ids OpenRouter serves right now, cached a quarter hour, or None
    when the catalogue could not be read. None means "do not filter": a
    router that refuses every id because it could not read a list is worse
    than one that tries an id that turns out to be gone. Same reasoning and
    the same endpoint as the Auto (Free) pipe. No key needed."""
    global _available_ids, _available_at
    now = time.time()
    if _available_ids is not None and now - _available_at < _AVAILABLE_TTL_SECONDS:
        return _available_ids
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_MODELS_URL)
            r.raise_for_status()
            ids = {m.get("id") for m in (r.json().get("data") or []) if m.get("id")}
    except Exception:                                       # noqa: BLE001
        return _available_ids
    if ids:
        _available_ids = ids
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
    params = (agent or {}).get("params")
    params = params if isinstance(params, dict) else {}
    system = params.get("system")
    return system.strip() if isinstance(system, str) else ""
```

Then change `_chat`. New signature:

```python
async def _chat(token: str, model: str, messages: list[dict],
                tool_ids: list[str] | None, user_email: str,
                tool_mode: str | None,
                refusal_reason: str = "this schedule is set to read only",
                max_iterations: int = MAX_TOOL_ITERATIONS,
                timeout: float = HTTP_TIMEOUT_SECONDS,
                agent: dict | None = None) -> tuple[str, list[str]]:
```

Add to its docstring:

```
    `agent` is the agent's own row (base_model_id, params.system). With it,
    an agent on a free model sends reasoning_effort and falls back through
    FREE_MODELS when the provider fails; without it the loop behaves exactly
    as it did before this parameter existed.
```

Inside `_chat`, after `content = ""`, add the state and a helper closure, and route every completion through it:

```python
    free = _is_free((agent or {}).get("base_model_id"))
    pool = await _fallback_pool(agent) if free else []
    active = model            # the model id posted; the agent id until a fallback
    instructions = _agent_system(agent)

    async def complete(convo_now: list[dict], with_tools: bool,
                       timeout_now: float) -> dict:
        """One completion on the active model, moving down the pool on a
        provider failure. Raises the last failure for a paid agent, and
        returns a body with no choices only when the pool is spent."""
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
            if free and FREE_REASONING:
                payload["reasoning_effort"] = FREE_REASONING
            try:
                data = await _post_chat(payload, token, timeout_now)
            except Exception as exc:                            # noqa: BLE001
                if not (free and pool and _provider_failed(exc)):
                    raise
                data = None
            if data is not None and not _provider_failed(data):
                return data
            if not (free and pool):
                return data if data is not None else {}
            nxt = pool.pop(0)
            logger.warning("free model %s failed for %s, trying %s",
                           active, model, nxt)
            active = nxt
```

Replace the loop's first two statements:

```python
        payload: dict = {"model": model, "messages": convo, "stream": False}
        if tool_ids:
            payload["tool_ids"] = tool_ids
        data = await _post_chat(payload, token, timeout)

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("the model returned no answer")
```

with:

```python
        data = await complete(convo, True, timeout)

        choices = data.get("choices") or []
        if not choices:
            if free:
                return FREE_POOL_EXHAUSTED, notes
            raise RuntimeError("the model returned no answer")
```

And the final round after the cap, replace:

```python
            data = await _post_chat(
                {"model": model, "messages": convo, "stream": False},
                token, max(timeout, FINAL_ROUND_MIN_TIMEOUT_SECONDS))
```

with:

```python
            data = await complete(convo, False,
                                  max(timeout, FINAL_ROUND_MIN_TIMEOUT_SECONDS))
```

**Step 4: Run, expect pass; then the whole loop suite**

Run: `python -m pytest tests/test_agent_free_fallback.py tests/test_agent_tool_loop.py tests/test_agent_runner.py tests/test_agent_stale_model.py -q`
Expected: all passed. `_post_chat`'s own stale-cache retry is untouched and sits below `complete`.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/tests/test_agent_free_fallback.py
git -c core.safecrlf=false commit -m "An agent on a free model asks for no reasoning and moves to the next free model when the provider fails" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Hand the agent row to the loop from every caller

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_turn.py` (`_resolve_agent` line 135, `_run_turn` line 242, `_resume_turn` line 301)
- Modify: `mcp-servers/tasks/agent_runner.py` (`run_agent`, the `_chat(` call)
- Modify: `mcp-servers/tasks/routes_agent_chat.py` (`_summarise` line 273)
- Test: `mcp-servers/tasks/tests/test_agent_recall.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_agent_recall.py`:

```python
async def test_run_turn_hands_the_agent_row_to_the_loop(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    row = {"id": "agent-1", "name": "Ada", "base_model_id": "x:free",
           "params": {"system": "Be Ada."}, "meta": {"toolIds": []}}
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([row], False)))
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt.agent_activity, "start_run", AsyncMock(return_value=None))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(agent_memory, "schedule_reflection", lambda *a, **k: None)

    await rt._run_turn("o@example.com", "agent-1", [{"role": "user", "content": "q"}])
    assert seen["agent"]["base_model_id"] == "x:free"
    assert seen["agent"]["params"]["system"] == "Be Ada."


async def test_resolve_agent_still_returns_three_values(monkeypatch):
    """Callers and tests predating the row read a 3-tuple."""
    row = {"id": "agent-1", "name": "Ada", "meta": {"toolIds": []}}
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([row], False)))
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=[]))
    out = await rt._resolve_agent("o@example.com", "agent-1")
    assert len(out) == 3
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agent_recall.py -q`
Expected: the first new test fails with `KeyError: 'agent'` (or `schedule_reflection` missing; if so, temporarily assert only on `seen["agent"]` after Task 8 adds it. Simplest order: do Task 8 before running this test again. Tasks 7 and 8 commit together if needed.)

**Step 3: Implement**

In `routes_agent_turn.py`, rename the body of `_resolve_agent` into a new function and keep a three-value wrapper:

```python
async def _resolve_agent_row(user_email: str, agent_id: str
                             ) -> tuple[str, list[str], str | None, dict]:
    """(token, the agent's own tool ids, its access level, the agent row).

    Raises HTTPException rather than returning a sentinel: every caller here
    would have to re-raise anyway, and a sentinel that got ignored once would
    run a turn with no tools and look like a model problem.
    """
    ... the existing body, unchanged, ending with:
    return (token, await tools_for_agent(user_email, meta),
            agent_access.level_of(meta), agent)


async def _resolve_agent(user_email: str, agent_id: str) -> tuple[str, list[str], str | None]:
    """The three values every older caller reads. See _resolve_agent_row."""
    token, tools, level, _agent = await _resolve_agent_row(user_email, agent_id)
    return token, tools, level
```

In `_run_turn` and `_resume_turn`, replace `token, tools, level = await _resolve_agent(user_email, agent_id)` with `token, tools, level, agent = await _resolve_agent_row(user_email, agent_id)` and add `agent=agent,` to their `_chat(` keyword calls.

In `agent_runner.run_agent`, the row is already in `agent`; add `agent=agent,` to the `_chat(` call.

In `routes_agent_chat._summarise`, the `_chat(` call already has `agent` in scope (its parameter); add `agent=agent,`.

**Step 4: Run, expect pass**

Run: `python -m pytest tests/test_agent_recall.py tests/test_agent_turn_endpoint.py tests/test_agent_turn_resume.py tests/test_agent_tool_scope.py tests/test_agent_tool_reach.py tests/test_agent_runner.py tests/test_agent_chat_round.py -q`
Expected: all passed. Tests that patch `_resolve_agent` keep working because `_run_turn` no longer calls it; if one of them relied on that indirection, patch `_resolve_agent_row` there instead with a 4-tuple.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/agent_runner.py mcp-servers/tasks/routes_agent_chat.py mcp-servers/tasks/tests/test_agent_recall.py
git -c core.safecrlf=false commit -m "Every caller of the tool loop hands it the agent row" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: The reflection, detached after a chat turn

**Files:**
- Modify: `mcp-servers/tasks/agent_memory.py` (append)
- Modify: `mcp-servers/tasks/routes_agent_turn.py` (`_run_turn`)
- Test: `mcp-servers/tasks/tests/test_agent_memory.py` (append)
- Test: `mcp-servers/tasks/tests/test_agent_recall.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_agent_memory.py`:

```python
import asyncio


def _agent():
    return {"id": "agent-1", "name": "Ada",
            "base_model_id": "nvidia/nemotron-3-super-120b-a12b:free"}


def test_schedule_reflection_skips_a_turn_not_worth_it(monkeypatch):
    calls = []
    monkeypatch.setattr(am, "reflect_after_turn",
                        lambda *a, **k: calls.append(a))
    assert am.schedule_reflection("o@example.com", _agent(), "tok", "hi", "Hello.") is None
    assert calls == []


async def test_schedule_reflection_rate_limits_per_agent(monkeypatch):
    ran = []

    async def fake_reflect(*a, **k):
        ran.append(a)

    monkeypatch.setattr(am, "reflect_after_turn", fake_reflect)
    am._last_reflect.clear()
    text = "Set the digest to 7am Manila time from now on, please."
    first = am.schedule_reflection("o@example.com", _agent(), "tok", text, "Done.")
    second = am.schedule_reflection("o@example.com", _agent(), "tok", text, "Done.")
    assert first is not None and second is None
    await first
    assert len(ran) == 1


async def test_reflect_after_turn_stores_what_the_model_returned(monkeypatch):
    seen = {}

    async def fake_post(payload, token, timeout=None):
        seen["payload"] = payload
        return {"choices": [{"message": {"content":
                 '{"notes": ["Sends the digest at 7am Manila time."], '
                 '"facts": ["Client is called Northwind."]}'}}]}

    stored = {}
    monkeypatch.setattr(am, "_complete", fake_post)
    monkeypatch.setattr(am, "list_notes", AsyncMock(return_value=[]))
    monkeypatch.setattr(am, "list_facts", AsyncMock(return_value=[]))

    async def add_notes(email, agent_id, notes, source="reflection"):
        stored["notes"] = (agent_id, notes); return len(notes)

    async def add_facts(email, facts):
        stored["facts"] = facts; return len(facts)

    monkeypatch.setattr(am, "add_notes", add_notes)
    monkeypatch.setattr(am, "add_facts", add_facts)

    await am.reflect_after_turn("o@example.com", _agent(), "tok",
                                "Move the digest to 7am Manila, client is Northwind.",
                                "Done.")
    assert stored["notes"] == ("agent-1", ["Sends the digest at 7am Manila time."])
    assert stored["facts"] == ["Client is called Northwind."]
    assert seen["payload"]["model"] == am.REFLECT_MODEL
    assert "tool_ids" not in seen["payload"]
    assert seen["payload"]["reasoning_effort"] == "none"


async def test_reflect_after_turn_never_raises(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(am, "_complete", boom)
    monkeypatch.setattr(am, "list_notes", AsyncMock(return_value=[]))
    monkeypatch.setattr(am, "list_facts", AsyncMock(return_value=[]))
    await am.reflect_after_turn("o@example.com", _agent(), "tok",
                                "Move the digest to 7am Manila, client is Northwind.",
                                "Done.")
```

Append to `tests/test_agent_recall.py`:

```python
async def test_run_turn_schedules_a_reflection_with_the_last_user_message(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        return "Done, 7am it is.", []

    row = {"id": "agent-1", "name": "Ada", "base_model_id": "x:free",
           "params": {"system": "Be Ada."}, "meta": {"toolIds": []}}
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([row], False)))
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt.agent_activity, "start_run", AsyncMock(return_value=None))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())

    def fake_schedule(user_email, agent, token, user_text, answer):
        seen.update(email=user_email, agent=agent["id"], text=user_text, answer=answer)

    monkeypatch.setattr(agent_memory, "schedule_reflection", fake_schedule)
    await rt._run_turn("o@example.com", "agent-1", [
        {"role": "system", "content": "identity"},
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "earlier answer"},
        {"role": "user", "content": "Set the digest to 7am Manila from now on."}])
    assert seen == {"email": "o@example.com", "agent": "agent-1",
                    "text": "Set the digest to 7am Manila from now on.",
                    "answer": "Done, 7am it is."}
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agent_memory.py tests/test_agent_recall.py -q`
Expected: `AttributeError` for `schedule_reflection`, `reflect_after_turn`, `_complete`, `REFLECT_MODEL`.

**Step 3: Append the reflection to agent_memory.py**

```python
# --- capture: the reflection after a turn ----------------------------------

#: The model the reflection runs on. The first free id in the pool unless
#: told otherwise: it has no tools, no history and a 2,000 character input,
#: so the cheapest thing that follows a JSON instruction is right.
REFLECT_MODEL = os.environ.get("AGENT_REFLECT_MODEL") or (
    [m.strip() for m in os.environ.get(
        "AGENT_FREE_MODELS",
        "nvidia/nemotron-3-super-120b-a12b:free").split(",") if m.strip()]
    or ["nvidia/nemotron-3-super-120b-a12b:free"])[0]
REFLECT_TIMEOUT_SECONDS = 45

_last_reflect: dict[tuple[str, str], float] = {}
_in_flight = asyncio.Semaphore(REFLECT_MAX_IN_FLIGHT)


async def _complete(payload: dict, token: str, timeout: float) -> dict:
    """One completion through Open WebUI, with the free pool fallback the
    tool loop has. A seam, so tests stand in for it without a model."""
    import agent_runner
    row = {"base_model_id": payload.get("model"), "params": {}}
    pool = await agent_runner._fallback_pool(row)
    active = payload.get("model")
    while True:
        body = dict(payload, model=active)
        try:
            data = await agent_runner._post_chat(body, token, timeout)
        except Exception as exc:                                # noqa: BLE001
            if not (pool and agent_runner._provider_failed(exc)):
                raise
            data = None
        if data is not None and not agent_runner._provider_failed(data):
            return data
        if not pool:
            return data if data is not None else {}
        active = pool.pop(0)


async def reflect_after_turn(user_email: str, agent: dict, token: str,
                             user_text: str, answer: str) -> None:
    """Write down what this turn settled. Never raises."""
    agent_id = str((agent or {}).get("id") or "")
    try:
        async with _in_flight:
            notes = [n["content"] for n in await list_notes(user_email, agent_id)]
            facts = await list_facts(user_email)
            prompt = reflection_prompt(str((agent or {}).get("name") or ""),
                                       notes, facts, user_text, answer)
            payload = {"model": REFLECT_MODEL, "stream": False,
                       "messages": [{"role": "user", "content": prompt}]}
            if agent_runner_reasoning():
                payload["reasoning_effort"] = agent_runner_reasoning()
            data = await _complete(payload, token, REFLECT_TIMEOUT_SECONDS)
            choices = data.get("choices") or []
            content = ((choices[0].get("message") or {}).get("content")
                       if choices else "") or ""
            new_notes, new_facts = parse_reflection(content)
            n = await add_notes(user_email, agent_id, new_notes) if new_notes else 0
            f = await add_facts(user_email, new_facts) if new_facts else 0
            logger.info("reflection for %s: %d new notes, %d new facts",
                        agent_id, n, f)
    except Exception:                                       # noqa: BLE001
        logger.warning("reflection failed for %s", agent_id, exc_info=True)


def agent_runner_reasoning() -> str:
    """The same reasoning setting the tool loop sends, read late so a test
    that patches agent_runner.FREE_REASONING is honoured."""
    import agent_runner
    return agent_runner.FREE_REASONING if _is_free_id(REFLECT_MODEL) else ""


def _is_free_id(model_id: str) -> bool:
    return isinstance(model_id, str) and model_id.endswith(":free")


def schedule_reflection(user_email: str, agent: dict, token: str,
                        user_text: str, answer: str):
    """Run the reflection detached, or return None when the turn is not
    worth it or this agent reflected within the last 90 seconds.

    Returns the task so a test can await it. Never raises: a turn that
    could not schedule its reflection is still a finished turn.
    """
    try:
        if not should_reflect(user_text, answer):
            return None
        agent_id = str((agent or {}).get("id") or "")
        key = (user_email, agent_id)
        now = time.time()
        if now - _last_reflect.get(key, 0.0) < REFLECT_MIN_INTERVAL_SECONDS:
            return None
        _last_reflect[key] = now
        return asyncio.get_running_loop().create_task(
            reflect_after_turn(user_email, agent, token, user_text, answer))
    except Exception:                                       # noqa: BLE001
        logger.warning("could not schedule a reflection", exc_info=True)
        return None
```

Add `import os` to the module's imports.

In `routes_agent_turn._run_turn`, after the block that turns notes into an answer and before `return {"answer": answer, "notes": notes}`, add:

```python
        # The subconscious: after a real answer, one detached completion
        # writes down what was settled. Fire and forget, never awaited here.
        agent_memory.schedule_reflection(
            user_email, agent, token, _last_user_text(messages), answer)
```

and add the helper near `_trim_for_storage`:

```python
def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content")
            return content if isinstance(content, str) else ""
    return ""
```

**Step 4: Run, expect pass**

Run: `python -m pytest tests/test_agent_memory.py tests/test_agent_recall.py tests/test_agent_turn_endpoint.py -q`
Expected: all passed.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_memory.py mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/tests/test_agent_memory.py mcp-servers/tasks/tests/test_agent_recall.py
git -c core.safecrlf=false commit -m "After a chat turn the agent writes down what was settled, on a free model, detached" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Memory endpoints, owner only

**Files:**
- Modify: `mcp-servers/tasks/routes_agents.py` (append routes after `/activity`)
- Test: `mcp-servers/tasks/tests/test_agent_memory_routes.py`

**Step 1: Write the failing tests**

```python
"""What a person may read and forget about their own agents' memory."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import routes_agents


class _User:
    email = "o@example.com"
    is_admin = False


def _mine():
    return [{"id": "agent-1", "name": "Ada"}]


async def test_counts_are_for_the_callers_agents():
    with patch.object(routes_agents.agent_memory, "note_counts",
                      new=AsyncMock(return_value={"agent-1": 2})):
        out = await routes_agents.memory_counts(user=_User())
    assert out == {"counts": {"agent-1": 2}}


async def test_listing_someone_elses_agent_is_403():
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         pytest.raises(HTTPException) as err:
        await routes_agents.memory_list("agent-9", user=_User())
    assert err.value.status_code == 403


async def test_listing_and_forgetting_your_own():
    with patch.object(routes_agents, "_agents_for", new=AsyncMock(return_value=_mine())), \
         patch.object(routes_agents.agent_memory, "list_notes",
                      new=AsyncMock(return_value=[{"id": "n1", "content": "x"}])), \
         patch.object(routes_agents.agent_memory, "delete_note",
                      new=AsyncMock(return_value=True)) as forget, \
         patch.object(routes_agents.agent_memory, "clear_notes",
                      new=AsyncMock(return_value=3)) as clear:
        listed = await routes_agents.memory_list("agent-1", user=_User())
        one = await routes_agents.memory_forget("agent-1", "n1", user=_User())
        every = await routes_agents.memory_forget_all("agent-1", user=_User())
    assert listed == {"notes": [{"id": "n1", "content": "x"}]}
    assert one == {"forgotten": True}
    assert every == {"forgotten": 3}
    forget.assert_awaited_once_with("o@example.com", "agent-1", "n1")
    clear.assert_awaited_once_with("o@example.com", "agent-1")
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agent_memory_routes.py -q`
Expected: `AttributeError: module 'routes_agents' has no attribute 'agent_memory'`.

**Step 3: Implement**

In `routes_agents.py` add `import agent_memory` beside `import agent_activity`, and after the `/activity` route add:

```python
async def _own_agent_or_403(user_email: str, agent_id: str) -> None:
    """The same rule /speak uses: not one of yours is not yours to read."""
    agents = await _agents_for(user_email)
    if not any(a.get("id") == agent_id for a in agents):
        raise HTTPException(status_code=403, detail="That is not one of your agents.")


@router.get("/memory")
async def memory_counts(user: CurrentUser = Depends(current_user)) -> dict:
    """How many notes each of the caller's agents holds, for the cards."""
    return {"counts": await agent_memory.note_counts(user.email)}


@router.get("/{agent_id}/memory")
async def memory_list(agent_id: str,
                      user: CurrentUser = Depends(current_user)) -> dict:
    """This agent's notes, newest first. Owner only."""
    await _own_agent_or_403(user.email, agent_id)
    return {"notes": await agent_memory.list_notes(user.email, agent_id)}


@router.delete("/{agent_id}/memory/{note_id}")
async def memory_forget(agent_id: str, note_id: str,
                        user: CurrentUser = Depends(current_user)) -> dict:
    await _own_agent_or_403(user.email, agent_id)
    return {"forgotten": await agent_memory.delete_note(user.email, agent_id, note_id)}


@router.delete("/{agent_id}/memory")
async def memory_forget_all(agent_id: str,
                            user: CurrentUser = Depends(current_user)) -> dict:
    await _own_agent_or_403(user.email, agent_id)
    return {"forgotten": await agent_memory.clear_notes(user.email, agent_id)}
```

Check the router prefix: `grep -n "include_router(routes_agents" main.py` shows the prefix (expected `/agents`), so the page calls `/api/tasks/agents/memory` and `/api/tasks/agents/<id>/memory`.

**Step 4: Run, expect pass**

Run: `python -m pytest tests/test_agent_memory_routes.py tests/test_agents_speak.py -q && python -c "import routes_agents"` (from `mcp-servers/tasks`, with `DATABASE_URL` unset the import must still succeed).
Expected: all passed.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_agents.py mcp-servers/tasks/tests/test_agent_memory_routes.py
git -c core.safecrlf=false commit -m "A person can read and forget what their own agent remembers" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: The card shows and forgets memory

**Files:**
- Modify: `mcp-servers/tasks/static/agents.html` (`card()` at line 1076, `render()` at line 1504, the click handler that reads `data-act`)
- Test: `mcp-servers/tasks/tests/test_agents_page_memory.py`

**Step 1: Write the failing test**

```python
"""The memory line on the card. Structural, like test_agents_page_access."""
import os

PAGE = os.path.join(os.path.dirname(__file__), "..", "static", "agents.html")


def _page():
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


def test_every_owned_card_has_a_memory_line_and_a_show_control():
    page = _page()
    assert 'data-memory-for="' in page
    assert 'data-act="memory"' in page
    assert "/api/tasks/agents/memory" in page
    assert 'data-act="forget"' in page
    assert 'data-act="forget-all"' in page


def test_the_words_are_plain():
    page = _page()
    assert "Forget" in page
    assert "Forget all" in page
    assert "Nothing remembered yet." in page
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agents_page_memory.py -q`
Expected: 2 failed.

**Step 3: Edit agents.html**

In `card()`, after the `card-sys` div and before `card-chips`, insert (owner cards only):

```javascript
        (mine
          ? '<div class="card-memory" data-memory-for="' + esc(m.id) + '">'
            + '<span class="memory-count"></span>'
            + '<button class="link-btn" type="button" data-act="memory">Show</button>'
            + '<div class="memory-list" hidden></div>'
            + "</div>"
          : "") +
```

Add CSS next to `.card-sys`:

```css
    .card-memory { font-size: 12px; color: var(--muted, #6b7280); margin: 6px 0 2px; }
    .card-memory .link-btn { background: none; border: 0; padding: 0 0 0 8px; color: inherit; text-decoration: underline; cursor: pointer; font: inherit; }
    .memory-list { margin-top: 6px; }
    .memory-list .note { display: flex; gap: 8px; align-items: flex-start; padding: 3px 0; border-top: 1px solid var(--line, #e5e7eb); }
    .memory-list .note span { flex: 1; }
```

Add these functions after `loadActivity()`:

```javascript
    // Memory: how many notes each agent holds, painted the way activity is.
    async function loadMemoryCounts() {
      try {
        var body = await getJson("/api/tasks/agents/memory");
        var counts = (body && body.counts) || {};
        document.querySelectorAll("[data-memory-for]").forEach(function (el) {
          var n = counts[el.getAttribute("data-memory-for")] || 0;
          el.querySelector(".memory-count").textContent =
            "Memory: " + n + (n === 1 ? " note" : " notes");
        });
      } catch (e) {
        // Decoration, same as activity.
      }
    }

    async function showMemory(agentId, wrap) {
      var list = wrap.querySelector(".memory-list");
      if (!list.hidden) { list.hidden = true; return; }
      list.innerHTML = "";
      try {
        var body = await getJson("/api/tasks/agents/" + encodeURIComponent(agentId) + "/memory");
        var notes = (body && body.notes) || [];
        if (!notes.length) {
          list.innerHTML = '<div class="note"><span>Nothing remembered yet.</span></div>';
        }
        notes.forEach(function (n) {
          var row = document.createElement("div");
          row.className = "note";
          row.innerHTML = "<span>" + esc(n.content) + "</span>"
            + '<button class="link-btn" type="button" data-act="forget" data-note="'
            + esc(n.id) + '">Forget</button>';
          list.appendChild(row);
        });
        if (notes.length) {
          var all = document.createElement("div");
          all.className = "note";
          all.innerHTML = '<span></span><button class="link-btn" type="button" '
            + 'data-act="forget-all">Forget all</button>';
          list.appendChild(all);
        }
      } catch (e) {
        list.innerHTML = '<div class="note"><span>Could not read the notes.</span></div>';
      }
      list.hidden = false;
    }

    async function forgetMemory(agentId, noteId) {
      var url = "/api/tasks/agents/" + encodeURIComponent(agentId) + "/memory"
        + (noteId ? "/" + encodeURIComponent(noteId) : "");
      var r = await fetch(url, { method: "DELETE", headers: authHeaders() });
      if (!r.ok) throw new Error("http " + r.status);
    }
```

In `render()`, after `loadActivity();` add `loadMemoryCounts();`.

In the card click handler (search for `data-act` and `"edit"` to find the `switch` or `if` chain that handles `edit`, `delete`, `duplicate`, `more`), add:

```javascript
        if (act === "memory") {
          showMemory(card.getAttribute("data-agent-id"), card.querySelector(".card-memory"));
          return;
        }
        if (act === "forget" || act === "forget-all") {
          var agentId = card.getAttribute("data-agent-id");
          var noteId = act === "forget" ? btn.getAttribute("data-note") : "";
          forgetMemory(agentId, noteId).then(function () {
            var wrap = card.querySelector(".card-memory");
            wrap.querySelector(".memory-list").hidden = true;
            showMemory(agentId, wrap);
            loadMemoryCounts();
          }).catch(function () { showError("Could not forget that."); });
          return;
        }
```

Use the same variable names the handler already uses for the card element and the clicked button; read them from the surrounding code rather than assuming `card` and `btn`.

**Step 4: Run, expect pass**

Run: `python -m pytest tests/test_agents_page_memory.py tests/test_agents_page_access.py -q`
Expected: all passed. Also open the file and check the inserted JS has balanced braces: `node -e "new Function(require('fs').readFileSync('static/agents.html','utf8').split('<script>')[1].split('</script>')[0])"` (if node is available) must print nothing.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/test_agents_page_memory.py
git -c core.safecrlf=false commit -m "The agent card shows what it remembers and lets its owner forget a note" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Compose defaults and the two scripts

**Files:**
- Modify: `docker-compose.unified.yml` (tasks env after `GATEWAY_MODEL` at line 450; the `OPENAI_API_CONFIGS` line 772)
- Modify: `mcp-servers/tasks/routes_agents.py` (`_default_model` line 78)
- Create: `scripts/move_agents_to_free_model.py`
- Create: `scripts/set_openrouter_allowlist.py`
- Test: `mcp-servers/tasks/tests/test_agent_seed.py` (check the default assertion)

**Step 1: Write the failing test**

Run `grep -n "gpt-4o-mini" mcp-servers/tasks/tests/test_agent_seed.py`. If a test asserts the fallback default, change its expectation to `nvidia/nemotron-3-super-120b-a12b:free`; if none does, append:

```python
def test_new_agents_start_on_the_free_model_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_DEFAULT_MODEL", raising=False)
    assert routes_agents._default_model() == "nvidia/nemotron-3-super-120b-a12b:free"
```

**Step 2: Run, expect failure**

Run: `python -m pytest tests/test_agent_seed.py -q`
Expected: 1 failed.

**Step 3: Implement**

`routes_agents._default_model`:

```python
def _default_model() -> str:
    """The platform default, read at call time so tests can monkeypatch it.

    Falls back to the first free model in the pool (see
    agent_runner.FREE_MODELS). It was gpt-4o-mini until 2026-09-15, when
    every agent moved to free models.
    """
    return os.environ.get("AGENT_DEFAULT_MODEL",
                          "nvidia/nemotron-3-super-120b-a12b:free")
```

Compose, tasks service, after the `GATEWAY_MODEL` line at 450:

```yaml
      # Agents run on free OpenRouter models since 2026-09-15. The first id
      # is what a new agent starts on; the tool loop moves down the list
      # when a provider fails (agent_runner.FREE_MODELS). Every id here must
      # also be in the OpenRouter allowlist below (OPENAI_API_CONFIGS) or
      # Open WebUI will not route to it. Reasoning is off for free models:
      # measured 2026-09-15, a truncated reply with it on leaked the model's
      # thinking into the answer.
      - AGENT_DEFAULT_MODEL=${AGENT_DEFAULT_MODEL:-nvidia/nemotron-3-super-120b-a12b:free}
      - AGENT_FREE_MODELS=${AGENT_FREE_MODELS:-nvidia/nemotron-3-super-120b-a12b:free,nex-agi/nex-n2.5-pro:free,nex-agi/nex-n2.5-mini:free}
      - AGENT_FREE_REASONING=${AGENT_FREE_REASONING:-none}
      - AGENT_REFLECT_MODEL=${AGENT_REFLECT_MODEL:-}
```

Compose line 772, the new allowlist (the persisted config in the database wins over this line; the script below sets both):

```yaml
      - 'OPENAI_API_CONFIGS={"2":{"enable":true,"model_ids":["nvidia/nemotron-3-super-120b-a12b:free","nex-agi/nex-n2.5-pro:free","nex-agi/nex-n2.5-mini:free","cohere/north-mini-code:free","nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free","nvidia/nemotron-3-ultra-550b-a55b:free","google/gemini-2.5-flash-lite","openai/gpt-5-mini","anthropic/claude-haiku-4.5"]}}'
```

Create `scripts/set_openrouter_allowlist.py`:

```python
"""Set the OpenRouter model allowlist in Open WebUI without a restart.

Run on the server:
  OPENWEBUI_API_KEY=... python3 scripts/set_openrouter_allowlist.py           # show
  OPENWEBUI_API_KEY=... python3 scripts/set_openrouter_allowlist.py --apply   # write

Reads /openai/config as an admin, replaces model_ids on the connection whose
URL is openrouter.ai, and posts the whole config back. Open WebUI's persisted
config wins over the compose environment, so editing the compose line alone
changes nothing on a running box; this is what changes it. Keys are read
and sent back untouched and are never printed.
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

WANTED = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nex-agi/nex-n2.5-pro:free",
    "nex-agi/nex-n2.5-mini:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemini-2.5-flash-lite",
    "openai/gpt-5-mini",
    "anthropic/claude-haiku-4.5",
]


def call(path, payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


cfg = call("/openai/config")
urls = cfg.get("OPENAI_API_BASE_URLS") or []
idx = next((str(i) for i, u in enumerate(urls) if "openrouter.ai" in u), None)
if idx is None:
    sys.exit("no openrouter.ai connection in OPENAI_API_BASE_URLS")
configs = cfg.get("OPENAI_API_CONFIGS") or {}
before = (configs.get(idx) or {}).get("model_ids") or []
print("connection", idx, "before:", json.dumps(before))
print("after:   ", json.dumps(WANTED))
if "--apply" not in sys.argv:
    print("dry run; pass --apply to write")
    sys.exit(0)
configs[idx] = dict(configs.get(idx) or {}, enable=True, model_ids=WANTED)
cfg["OPENAI_API_CONFIGS"] = configs
out = call("/openai/config/update", cfg)
now = ((out.get("OPENAI_API_CONFIGS") or {}).get(idx) or {}).get("model_ids")
print("written:", json.dumps(now))
models = call("/api/models")
ids = {m.get("id") for m in (models.get("data") or [])}
missing = [m for m in WANTED if m not in ids]
print("visible in /api/models:", "all" if not missing else "MISSING " + json.dumps(missing))
```

Create `scripts/move_agents_to_free_model.py`:

```python
"""Move every agent to the free model. Dry run unless --apply.

Run on the server:
  OPENWEBUI_API_KEY=... python3 scripts/move_agents_to_free_model.py
  OPENWEBUI_API_KEY=... python3 scripts/move_agents_to_free_model.py --apply
  OPENWEBUI_API_KEY=... python3 scripts/move_agents_to_free_model.py --apply --only agent-ada-a1bc

Needs an admin key: Open WebUI lets an admin update any user's model, and
the agents belong to four people. Prints a before/after table and nothing
else. Ends by calling /api/models, which rebuilds the model cache that
otherwise answers "Model not found" for a moved agent.
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
TARGET = os.environ.get("AGENT_DEFAULT_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

APPLY = "--apply" in sys.argv
ONLY = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None


def call(path, payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


rows, page = [], 1
while True:
    listed = call(f"/api/v1/models/list?page={page}")
    batch = listed.get("items") or []
    rows.extend(batch)
    total = listed.get("total")
    if not batch or not isinstance(total, int) or len(rows) >= total:
        break
    page += 1

agents = [r for r in rows if str(r.get("id", "")).startswith("agent-")]
if ONLY:
    agents = [r for r in agents if r["id"] == ONLY]
print("%-34s %-28s -> %s" % ("agent", "base now", "base after"))
for a in agents:
    base = a.get("base_model_id") or ""
    after = TARGET if base != TARGET else "(already)"
    print("%-34s %-28s -> %s" % (a["id"], base, after))
if not APPLY:
    print("dry run; pass --apply to write")
    sys.exit(0)

moved = 0
for a in agents:
    if a.get("base_model_id") == TARGET:
        continue
    body = {"id": a["id"], "name": a.get("name"), "base_model_id": TARGET,
            "meta": a.get("meta") or {}, "params": a.get("params") or {},
            "access_grants": a.get("access_grants") or [],
            "is_active": a.get("is_active", True)}
    call(f"/api/v1/models/id/{a['id']}/update", body)
    moved += 1
print("moved:", moved)
call("/api/models")
check = {r["id"]: r.get("base_model_id") for r in
         (call("/api/v1/models/list?page=1").get("items") or [])
         if str(r.get("id", "")).startswith("agent-")}
wrong = {k: v for k, v in check.items() if (not ONLY or k == ONLY) and v != TARGET}
print("verified:", "all on " + TARGET if not wrong else "STILL WRONG " + json.dumps(wrong))
```

Check the update payload fields against `/api/v1/models/list` output on the server before applying: the row carries `access_grants` in this Open WebUI version (see `_body_for` in routes_agents.py, which creates with the same fields).

**Step 4: Run, expect pass**

Run: `python -m pytest tests/test_agent_seed.py -q && python -m py_compile ../../scripts/move_agents_to_free_model.py ../../scripts/set_openrouter_allowlist.py && docker compose -f ../../docker-compose.unified.yml config -q 2>/dev/null || echo "compose config check skipped locally"`
Expected: tests pass, both scripts compile.

**Step 5: Commit**

```bash
git add docker-compose.unified.yml mcp-servers/tasks/routes_agents.py mcp-servers/tasks/tests/test_agent_seed.py scripts/move_agents_to_free_model.py scripts/set_openrouter_allowlist.py
git -c core.safecrlf=false commit -m "Free models by default: compose pool, the allowlist setter and the agent mover" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Full local suite, then push

**Step 1: Run the three suites**

```bash
cd mcp-servers/tasks && python -m pytest tests/ -q -p no:cacheprovider 2>&1 | tail -5
cd ../../webhook-handler && python -m pytest tests/ -q 2>&1 | tail -3
cd ../api-gateway && python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: tasks about 3,900 passed, 3 failed (the pre-existing local-only ones: check they are the same three as on 2026-09-14), about 170 setup errors (no Postgres) including `test_agent_memory_db.py`; webhook-handler and api-gateway unchanged from 2026-09-14.

**Step 2: Push**

```bash
gh auth switch -u Jacintalama
git fetch fork && git rebase fork/main && git push fork main
```

---

### Task 13: Deploy and the DB tier

**Step 1: Sweep first**

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && cat .deploy-state && git -c safe.directory=/root/proxy-server fetch origin -q && git -c safe.directory=/root/proxy-server branch -r --contains $(python3 -c "import json;print(json.load(open(\".deploy-state\"))[\"sha\"])")'
```

Expected: `origin/main` contains the deployed sha (706ebc015 or later). If not, stop and reconcile before shipping.

**Step 2: Ship the changed files, one per scp**

From the repo root, for each of:
`mcp-servers/tasks/agent_memory.py`, `mcp-servers/tasks/agent_runner.py`, `mcp-servers/tasks/routes_agent_turn.py`, `mcp-servers/tasks/routes_agents.py`, `mcp-servers/tasks/routes_agent_chat.py`, `mcp-servers/tasks/migrations/049_agent_memory.sql`, `mcp-servers/tasks/static/agents.html`, `docker-compose.unified.yml`, `scripts/move_agents_to_free_model.py`, `scripts/set_openrouter_allowlist.py`, and every new or changed test file:

```bash
git archive --format=tar HEAD <the list of paths> | ssh root@46.224.193.25 'cd /root/proxy-server && tar -xf -'
```

(`git archive` writes LF, so no `sed -i 's/\r$//'` is needed.) Then verify: for each path, `md5sum` on the server equals `git show HEAD:<path> | md5sum` locally.

**Step 3: Rebuild tasks and check the migration**

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks && sleep 20 && docker logs tasks --since 2m 2>&1 | grep -i -E "migration|049|error" | head; docker exec postgres sh -c "psql -U \$POSTGRES_USER -d openwebui -At -c \"\\d tasks.agent_memory\""; curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz'
```

Expected: the table exists with 8 columns, healthz answers.

**Step 4: DB tier in the container**

Use the recipe from memory `lesson_container_db_test_runner.md`: copy the test in with `docker cp`, run with `AIUI_TEST_DB=1` and the DSN sed `s|/openwebui$|/aiui_test|`, detached with setsid, read the log:

```bash
ssh root@46.224.193.25 'docker exec -e AIUI_TEST_DB=1 tasks sh -lc "cd /app && export DATABASE_URL=\$(echo \$DATABASE_URL | sed -e \"s|/openwebui\$|/aiui_test|\") && python -m pytest tests/test_agent_memory_db.py -q 2>&1 | tail -5"'
```

Expected: 3 passed. The aiui_test database must have the tasks schema and migration 049; if the table is missing there, run the migration SQL against aiui_test by hand first (`psql -d aiui_test -f`), it is idempotent.

**Step 5: Allowlist, then the agent mover, Ada only**

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && export OPENWEBUI_API_KEY=$(grep -E "^OPENWEBUI_API_KEY=" .env | cut -d= -f2-) && python3 scripts/set_openrouter_allowlist.py && python3 scripts/set_openrouter_allowlist.py --apply && python3 scripts/move_agents_to_free_model.py --only agent-ada-a1bc && python3 scripts/move_agents_to_free_model.py --apply --only agent-ada-a1bc'
```

Expected: "visible in /api/models: all", then "verified: all on nvidia/nemotron-3-super-120b-a12b:free".

**Step 6: Record the deploy**

Write `.deploy-state` with the pushed sha, `deployed_at` now in UTC, `deployed_by` `manual@dev`, after backing up the old one.

---

### Task 14: Live end to end on Ada

Everything below runs on the server. `SECRET` is `INTERNAL_CALLBACK_SECRET` from `.env`, read into a shell variable, never printed. `EMAIL` is `alamajacintg04@gmail.com`. The internal turn endpoint is `http://127.0.0.1:8210/agents/turn` from inside the tasks container (use `docker exec tasks python3 -c` with httpx, the way the context probe was done).

**Step 1: A tool turn on the free model**

Post `{"user_email": EMAIL, "agent_id": "agent-ada-a1bc", "messages": [{"role": "user", "content": "List my schedules and say how many there are."}]}`.
Expected: an answer naming the schedules (the owner has them; compare against `SELECT count(*) FROM tasks.schedules WHERE user_email = ...`). In `docker logs tasks --since 3m`: no "chat completion failed"; one `execute_tool_call` line or the tool result in the answer.

**Step 2: A turn that settles something**

Post the message: "From now on I want my daily digest at 7am Manila time, and my main client is called Northwind Traders. Confirm in one line."
Expected: a one line confirmation. Within 60 seconds `docker logs tasks --since 2m | grep reflection` shows `reflection for agent-ada-a1bc: N new notes, M new facts` with N+M >= 1. Then:

```sql
SELECT content, source FROM tasks.agent_memory WHERE agent_id = 'agent-ada-a1bc';
SELECT content FROM public."memory" WHERE user_id = 'd741f063-d6b4-4d28-9abb-9bf30b43fa9e';
```

Expected: at least one row mentioning 7am or Northwind.

**Step 3: A fresh conversation that asks for it back**

Post, with NO history, the single message: "What time do I want my daily digest, and who is my main client? Answer from what you remember."
Expected: the answer contains "7" and "Northwind". This is the proof: neither word is in the request.

**Step 4: Reasoning stays out of the answer**

Inspect the three answers above for the strings "The user", "We must", "<think" or "reasoning". Expected: none. Also `docker logs open-webui --since 10m | grep -c reasoning_tokens` is not needed; instead re-run Step 3 through Open WebUI directly with the admin key and `model: agent-ada-a1bc` and read `usage.completion_tokens_details.reasoning_tokens`. Expected: 0.

**Step 5: A forced fallback**

Inside the container, run `_chat` against a dead primary with the real pool:

```bash
docker exec tasks python3 - <<'PY'
import asyncio, agent_runner
from owui_token import mint_owui_token
async def main():
    tok = mint_owui_token("d741f063-d6b4-4d28-9abb-9bf30b43fa9e", ttl_seconds=300)
    agent = {"id": "google/gemma-4-26b-a4b-it:free", "base_model_id": "google/gemma-4-26b-a4b-it:free", "params": {"system": "Answer in one word."}}
    out = await agent_runner._chat(token=tok, model="google/gemma-4-26b-a4b-it:free",
        messages=[{"role": "user", "content": "Say ok."}], tool_ids=None,
        user_email="alamajacintg04@gmail.com", tool_mode="read_only", agent=agent,
        max_iterations=2, timeout=60)
    print(out)
asyncio.run(main())
PY
```

Expected: a printed answer ("ok" or similar) and in `docker logs tasks --since 2m` a line `free model google/gemma-4-26b-a4b-it:free failed for ..., trying nvidia/nemotron-3-super-120b-a12b:free`. If gemma happens to answer that minute, the test proves nothing; note it and move on, the unit tests cover the switch.

**Step 6: The page**

```bash
curl -s -o /tmp/agents.html -w "%{http_code}\n" https://ai-ui.coolestdomain.win/tasks/static/agents.html && grep -c 'data-act="memory"' /tmp/agents.html && md5sum /tmp/agents.html && git show HEAD:mcp-servers/tasks/static/agents.html | md5sum
```

Expected: 200, a count of 1 or more, equal hashes. Then GET `/api/tasks/agents/agent-ada-a1bc/memory` as the owner (the OWUI API key is the owner's key) and expect the notes from Step 2. DELETE one and GET again.

**Step 7: Move the other ten and smoke each**

```bash
python3 scripts/move_agents_to_free_model.py && python3 scripts/move_agents_to_free_model.py --apply
```

Then for each of the ten, post one internal turn as its owner with "Reply with the single word ok." Expected: ten answers, none the busy sentence, none the callback sentence. Owners: `agent-mia-2201` is the caller's; `agent-scout-7d88` and `agent-triage-256e` belong to `ivandermuega@gmail.com`; the seven others to `ralphbenitez32@gmail.com`. The reflection skips these turns (under 40 characters), so nothing is stored for them.

**Step 8: Counts and cost line**

Record for the report: agents on free models (expect 11 of 11), reflections stored, OpenRouter `usage_daily` from `/api/v1/auth/key` before and after (expect unchanged: free models cost 0).

---

### Task 15: Memory and EOD

1. Update `MEMORY.md` and add `project_agent_subconscious_and_free_models.md` in the memory directory: what shipped, the pool, the reflection limits, the allowlist change, and that Ralph's seven agents were moved on the owner's instruction.
2. Write the EOD in the owner's format: numbered plain text, Done / In progress / Needs you.
