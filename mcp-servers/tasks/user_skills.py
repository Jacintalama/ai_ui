"""Skills somebody wrote for themselves (2026-11-03).

Built from docs/superpowers/specs/2026-09-09-agent-skill-writer-design.md,
which was written on 2026-09-09 and sat unbuilt. Its reasoning is not
repeated here; what is repeated is the handful of decisions that this code
would otherwise be free to get wrong.

**Why not import skills instead.** The design measured 1,225 SKILL.md files
across five public repositories: 2.9% usable, 42% needing a filesystem or a
shell, 17% too large to put in a prompt, 37.5% whose frontmatter did not
parse. Public skills are written for an agent that loads files on demand.
The agents here are small models with a prompt, so a skill arrives pasted
into that prompt, whole.

**The ceiling is per agent, not per library.** Measured on a real brief: one
skill costs about 950 characters, ten cost 7,600, and MAX_TOTAL_CHARS is
8,000 with the conversation itself budgeted at 24,000. So an agent holds
roughly ten; the library may be any size, and `agent_skills.brief_for`
already cuts to fit and names what it left out.

**A person's own skill beats a built-in of the same name, for that person.**
Anything else means a deploy that adds a built-in silently replaces one
somebody wrote.

Validation lives here and not in the route, because the draft endpoint is
allowed to produce something wrong and saving is not. A draft is a
suggestion; a saved skill is injected into every turn of every agent
holding it.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("user_skills")

#: The Agent Skills spec's shape for a name, which is also what the folders
#: in agent_skills/ look like, so a person's skill and a built-in one are
#: the same kind of thing with the same kind of id.
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_CHARS = 64

#: Long enough to say what the skill is for AND when to use it, which is the
#: part that makes a picker usable.
MAX_DESCRIPTION_CHARS = 1024

#: How many one person may keep. Not a prompt limit: an agent holds about
#: ten and `brief_for` enforces that. This is the picker limit, because a
#: list of four hundred checkboxes is unusable long before it is expensive.
MAX_PER_PERSON = 50


class TooMany(Exception):
    """This person is at MAX_PER_PERSON."""


def clean_name(value) -> str:
    """A name as it will be stored.

    Spaces and capitals are what somebody types, not a refusal: "Chase
    Invoices" is obviously `chase-invoices` and bouncing it teaches nothing.
    Anything else is left alone so `problem_with` can say what is wrong
    rather than silently storing something different from what was asked
    for.
    """
    text = " ".join(str(value or "").split()).lower()
    return re.sub(r"[\s_]+", "-", text)[:MAX_NAME_CHARS].strip("-")


def problem_with(name: str, description: str, body: str,
                 max_body_chars: int) -> str:
    """What is wrong with this skill, or "". The sentences are shown to the
    person, so they say what to change.

    `max_body_chars` is passed in rather than imported from agent_skills,
    because that module owns the number the prompt actually enforces and a
    second copy here would be free to drift from it.
    """
    if not name:
        return "Give the skill a name, like chase-invoices."
    if not NAME_RE.match(name):
        return ("A name is lowercase letters, digits and single hyphens, "
                "like chase-invoices.")
    if len(name) > MAX_NAME_CHARS:
        return "That name is longer than %d characters." % MAX_NAME_CHARS
    if not str(description or "").strip():
        return ("Say what the skill is for, and when to use it. That line "
                "is what everybody picks from.")
    if len(description) > MAX_DESCRIPTION_CHARS:
        return ("That description is %d characters. The limit is %d."
                % (len(description), MAX_DESCRIPTION_CHARS))
    if not str(body or "").strip():
        return "A skill needs instructions. Write what the agent should do."
    if len(body) > max_body_chars:
        return ("Those instructions are %d characters. The limit is %d, "
                "because the whole skill goes into the agent's prompt on "
                "every single message."
                % (len(body), max_body_chars))
    return ""


def tool_warning(tools, known: dict) -> str:
    """Why this skill may not work, or "". NEVER a refusal.

    A skill naming a tool somebody has not connected is the silent-failure
    case worth warning about. It is not worth refusing: people connect
    things later, and a refusal would be wrong the moment they did.

    `known` is tool id -> label, as the connections page has it.
    """
    wanted = [str(t).strip() for t in (tools or []) if str(t or "").strip()]
    missing = [t for t in wanted if t not in known]
    if not missing:
        return ""
    if len(missing) == 1:
        return ("This skill uses %s, which is not connected. It will still "
                "save, and that part will not work until it is."
                % missing[0])
    return ("This skill uses %s, which are not connected. It will still "
            "save, and those parts will not work until they are."
            % ", ".join(sorted(missing)))


def as_skill(row: dict) -> dict:
    """One stored row in the shape agent_skills hands out, so a person's own
    skill and a built-in one are interchangeable everywhere downstream.

    `mine` is the one field a built-in does not have. The page needs it to
    offer Delete on one and not the other, and it is a fact about the skill
    rather than a fact about the viewer, because these are already scoped to
    one person by the query that read them.
    """
    return {"name": row.get("name") or "",
            "description": row.get("description") or "",
            "tools": list(row.get("tools") or []),
            "tags": [],
            "body": row.get("body") or "",
            "mine": True}


def merge(built_in: dict, mine: list) -> dict:
    """Everything one person can pick from, keyed by name.

    A person's own skill WINS on a name collision. The alternative is a
    deploy that adds a built-in quietly replacing something somebody wrote,
    which is worse than a built-in being shadowed.
    """
    out = dict(built_in or {})
    for row in (mine or []):
        skill = as_skill(row)
        if skill["name"]:
            out[skill["name"]] = skill
    return out


# --- the store ------------------------------------------------------------
# Seams, so every rule above is tested without a database.

async def _rows_for(email: str) -> list[dict]:
    from sqlalchemy import select
    from db import session
    from models import UserSkill
    async with session() as s:
        rows = (await s.execute(
            select(UserSkill).where(UserSkill.user_email == email)
            .order_by(UserSkill.name))).scalars().all()
        return [{"id": str(r.id), "name": r.name, "description": r.description,
                 "tools": list(r.tools or []), "body": r.body} for r in rows]


async def _save_row(email: str, name: str, description: str, tools: list,
                    body: str) -> dict:
    from sqlalchemy import select, func
    from db import session
    from models import UserSkill
    async with session() as s:
        existing = (await s.execute(
            select(UserSkill).where(UserSkill.user_email == email,
                                    UserSkill.name == name))).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing is None:
            count = (await s.execute(
                select(func.count()).select_from(UserSkill)
                .where(UserSkill.user_email == email))).scalar_one()
            if count >= MAX_PER_PERSON:
                raise TooMany()
            existing = UserSkill(id=uuid.uuid4(), user_email=email, name=name,
                                 created_at=now)
            s.add(existing)
        existing.description = description
        existing.tools = list(tools or [])
        existing.body = body
        existing.updated_at = now
        await s.commit()
        return {"id": str(existing.id), "name": name,
                "description": description, "tools": list(tools or []),
                "body": body}


async def _delete_row(email: str, name: str) -> bool:
    from sqlalchemy import delete
    from db import session
    from models import UserSkill
    async with session() as s:
        out = await s.execute(delete(UserSkill).where(
            UserSkill.user_email == email, UserSkill.name == name))
        await s.commit()
        return bool(out.rowcount)


_rows_seam = _rows_for
_save_seam = _save_row
_delete_seam = _delete_row


async def mine(email: str) -> list[dict]:
    """This person's own skills. NEVER raises.

    A database that cannot be read costs the skills somebody wrote, and must
    not cost them the turn they are in the middle of. The built-in ones
    still work, which is what this platform did before any of this existed.
    """
    if not str(email or "").strip():
        return []
    try:
        return await _rows_seam(email)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read skills for this account", exc_info=True)
        return []


async def save(email: str, name: str, description: str, tools: list,
               body: str) -> dict:
    """Create or replace one of this person's skills. Raises TooMany."""
    return await _save_seam(email, name, description, list(tools or []), body)


async def delete(email: str, name: str) -> bool:
    """Remove one. Agents that referenced it are left alone: `selected()`
    already drops unknown names, and a missing skill degrades to being left
    out rather than to a turn that fails."""
    try:
        return await _delete_seam(email, name)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not delete a skill", exc_info=True)
        return False
