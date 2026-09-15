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
