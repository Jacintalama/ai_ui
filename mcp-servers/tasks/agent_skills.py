"""Skills an agent can be given: ready-made instructions for one kind of job.

A skill is a folder under agent_skills/ holding a SKILL.md in the Agent Skills
open format (agentskills.io): YAML frontmatter with `name` and `description`,
then the instructions. `allowed-tools` is a real field in that format and
carries what it says here, the tools the skill needs, so the form can tell
somebody to tick Gmail rather than letting the skill quietly do nothing.

Two things about this platform shape everything below.

The agents here are Open WebUI model rows talking to gpt-4o-mini through a
plain tool loop. They have no filesystem and no way to read a file on demand,
so the spec's progressive disclosure has to happen on this side: the body of a
chosen skill is injected into the turn, whole. That is why the bodies are
short and why there is a hard cap on the total.

And which skills an agent has lives on the agent's row, while the skills
themselves ship with the image. The two can disagree: an agent can name a
skill that a later deploy renamed or removed. That case degrades to leaving it
out, never to a turn that fails.
"""
import logging
import os
import re

try:
    import yaml
except ImportError:                                         # pragma: no cover
    # PyYAML is declared in requirements.txt, and it was present in the image
    # before it was declared, as an undeclared transitive dependency of
    # something else. That is exactly the arrangement that disappears on a
    # rebuild, and this module is imported at startup by the agent turn
    # router, which main.py imports. A hard import here would turn a missing
    # library into the whole tasks service failing to boot, so it degrades to
    # no skills instead, which is a feature switched off rather than a
    # platform down.
    yaml = None

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "agent_skills")

#: One skill's instructions. The spec suggests under 5000 tokens for an agent
#: that can read files on demand. These are pasted into the prompt of a small
#: model instead, so the ceiling is far lower and is enforced by a test rather
#: than left to whoever writes the next skill.
MAX_SKILL_CHARS = 4000

#: Every chosen skill together. The turn also carries the identity brief and
#: the conversation, and the conversation is the thing being answered, so the
#: skills may not crowd it out. Sized to leave the 24000 character history
#: budget in routes_agent_chat comfortably intact.
MAX_TOTAL_CHARS = 8000

#: How many of the skills that did not fit get named. Naming all of them was
#: fine at ten and became the largest thing in the prompt at forty.
NAMED_WHEN_DROPPED = 5

_CACHE: dict | None = None


def _tags_from(meta: dict) -> list:
    """What this skill is about, for the filter chips and the search box.

    They live under `metadata`, which the Agent Skills spec defines as a free
    map of string to string. Putting them there rather than inventing a
    top-level key keeps these valid skills that another runtime can read.

    Everything about the shape is defensive: `metadata` is optional, every
    skill written before tags existed has none, and the value is whatever
    somebody typed. A tag list is a nice-to-have, so nothing here may be a
    reason for a skill not to load.
    """
    data = meta.get("metadata")
    raw = data.get("tags") if isinstance(data, dict) else None
    if isinstance(raw, list):
        parts = [str(t) for t in raw]
    elif isinstance(raw, str):
        parts = raw.split(",")
    else:
        return []
    return [t for t in (p.strip().lower() for p in parts) if t]


def _parse(text: str, folder: str) -> dict | None:
    """One SKILL.md into a dict, or None if it is not a usable skill.

    Never raises. A malformed file is one skill missing from a list, which is
    survivable; an exception here would be raised inside every agent turn on
    the platform, which is not.
    """
    try:
        if not text.startswith("---"):
            raise ValueError("no frontmatter")
        _, front, body = text.split("---", 2)
        meta = yaml.safe_load(front) or {}
        if not isinstance(meta, dict):
            raise ValueError("frontmatter is not a mapping")
        name = meta.get("name")
        description = meta.get("description")
        if not isinstance(name, str) or not isinstance(description, str):
            raise ValueError("name and description are both required")
        tools = meta.get("allowed-tools") or ""
        return {
            "name": name.strip(),
            "folder": folder,
            "description": " ".join(description.split()),
            "tools": tools.split() if isinstance(tools, str) else [],
            "tags": _tags_from(meta),
            "body": body.strip(),
        }
    except Exception:                                       # noqa: BLE001
        logger.warning("skill %s could not be read", folder, exc_info=True)
        return None


def load_all(refresh: bool = False) -> dict:
    """Every skill on disk, keyed by name. Read once and kept.

    They ship inside the image and change only on deploy, so re-reading ten
    files on every agent turn would buy nothing.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    if yaml is None:
        logger.warning("PyYAML is missing, so no skills can be read")
        _CACHE = {}
        return _CACHE
    out: dict = {}
    try:
        folders = sorted(os.listdir(SKILLS_DIR))
    except OSError:
        logger.warning("no skills directory at %s", SKILLS_DIR)
        folders = []
    for folder in folders:
        path = os.path.join(SKILLS_DIR, folder, "SKILL.md")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            logger.warning("could not open skill %s", folder, exc_info=True)
            continue
        skill = _parse(text, folder)
        if skill:
            out[skill["name"]] = skill
    _CACHE = out
    return out


def catalogue() -> list:
    """What the page shows: enough to choose from, and no instructions.

    The bodies are the whole point of a skill and are large. Sending ten of
    them to a page that draws ten checkboxes would put the entire library into
    every page load for nothing.
    """
    return [{"name": s["name"], "description": s["description"],
             "tools": list(s["tools"]), "tags": list(s["tags"])}
            for s in sorted(load_all().values(), key=lambda s: s["name"])]


#: How many matches a search hands back. These go into a tool result the model
#: reads, so the list has to be short enough to act on rather than a second
#: catalogue to wade through.
SEARCH_LIMIT = 5

#: Words that match everything and so tell us nothing about what somebody
#: wants. Without this, "can you find a skill for email" scores every skill
#: whose description contains "use when".
_STOPWORDS = frozenset({
    "a", "an", "and", "the", "for", "of", "to", "in", "on", "is", "it", "my",
    "me", "i", "you", "can", "do", "does", "how", "what", "with", "that",
    "this", "use", "used", "using", "when", "skill", "skills", "please",
    "help", "need", "want", "get", "make", "any", "some", "there",
})


def _words(text) -> list:
    if not isinstance(text, str):
        return []
    out = []
    for raw in re.split(r"[^a-z0-9]+", text.lower()):
        if len(raw) > 2 and raw not in _STOPWORDS:
            out.append(raw)
    return out


def _score(skill: dict, wanted: list) -> int:
    """How well this skill answers that request.

    Weighted by where the word was found, because the three places mean
    different things. A word in the NAME is what the skill is called, a word
    in a TAG is the area it belongs to, and a word in the description is a
    detail that may be incidental.
    """
    name = set(_words(skill["name"]))
    tags = set(w for t in skill["tags"] for w in _words(t))
    desc = set(_words(skill["description"]))
    hits = 0
    for w in wanted:
        if w in name:
            hits += 8
        elif w in tags:
            hits += 4
        elif w in desc:
            hits += 1
    return hits


def search(query, limit: int = SEARCH_LIMIT) -> list:
    """The skills that best answer a plain-language request.

    This is what makes a library of 64 usable at all. An agent can carry about
    13 of them, so the other 51 are unreachable unless somebody predicted in
    advance that they would be needed. Searching costs one sentence in the
    brief rather than the 10,858 characters a full catalogue would.

    Descriptions only, never bodies: five bodies would be most of a turn.
    """
    wanted = _words(query)
    if not wanted:
        return []
    scored = []
    for skill in load_all().values():
        n = _score(skill, wanted)
        if n:
            scored.append((n, skill))
    # Name as the tiebreak so the same query gives the same answer twice.
    scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    return [{"name": s["name"], "description": s["description"],
             "tools": list(s["tools"]), "tags": list(s["tags"])}
            for _n, s in scored[:max(1, int(limit or SEARCH_LIMIT))]]


def body_of(name) -> str | None:
    """One skill's instructions, or None.

    A dictionary lookup on a name that came from a model is the whole
    defence, and it is deliberate: nothing here builds a path out of it. The
    schedules tool grew a directory traversal exactly by rebuilding a path
    from a model's argument, and it would have deleted stored credentials.
    """
    if not isinstance(name, str):
        return None
    skill = load_all().get(name.strip())
    return skill["body"] if skill else None


def _ids_from(meta) -> list:
    if not isinstance(meta, dict):
        return []
    ids = meta.get("skillIds")
    if not isinstance(ids, list):
        return []
    return [i for i in ids if isinstance(i, str)]


def selected(meta) -> list:
    """The skills this agent has, in the order they were chosen.

    Order is kept because it is the only signal available about which one
    matters most, and it is what a person sees on the card.
    """
    known = load_all()
    return [known[i] for i in _ids_from(meta) if i in known]


def brief_for(meta) -> str:
    """The chosen skills as one block of text for the turn, or "".

    Empty for an agent with no skills, which is every agent that predates this
    and the default for a new one, so the ordinary turn is unchanged to the
    character.

    Cuts to fit, and says so when it does. Cutting is right: the conversation
    has to survive. Cutting quietly is not, because the one person who knows a
    skill was ticked is the person watching it appear to be ignored.
    """
    picked = selected(meta)
    if not picked:
        return ""

    head = ("You have been given the following ready-made instructions for "
            "particular jobs. When one of them fits what is being asked, "
            "follow it exactly, in preference to your own general approach.")
    parts = [head]
    used = len(head)
    dropped = []
    for skill in picked:
        block = "\n\n## Skill: %s\n%s" % (skill["name"], skill["body"])
        if used + len(block) > MAX_TOTAL_CHARS:
            dropped.append(skill["name"])
            continue
        parts.append(block)
        used += len(block)
    if dropped:
        # Named, but not all of them. With forty skills in the library this
        # note grew longer than the budget it exists to protect, which a test
        # caught: an apology for cutting that is itself the biggest thing in
        # the prompt is worse than the cut.
        shown = dropped[:NAMED_WHEN_DROPPED]
        rest = len(dropped) - len(shown)
        names = ", ".join(shown) + (" and %d more" % rest if rest else "")
        parts.append(
            "\n\nThese skills are also yours but were not included this time, "
            "because there was not room: %s. Say so if one of them is what "
            "was being asked for." % names)
    return "".join(parts)
