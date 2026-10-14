"""Reading the plan the lead agent wrote, and choosing who leads.

Pure: no model, no database, so every way a model can get the format wrong
is testable without one.

The lead answers a triage question with JSON (agent_job_triage). A free
model asked for JSON returns it fenced, wrapped in a sentence, with a name in
the wrong case, or not at all. Only the last of those is a reason to give up;
the others are read. Anything that does not add up to a sensible plan is
discarded whole, and None means the round runs exactly as it does today, so
being strict here costs one ordinary answer, never a broken job.
"""
import json
import re

#: A job of one step is just an answer from one agent, which the round already
#: gives. More than six is a plan nobody reads before pressing Start, and six
#: steps at up to five minutes each is already half an hour.
MIN_STEPS, MAX_STEPS = 2, 6

#: One sentence was asked for. A longer task is the model being wordy, not a
#: wrong plan, so it is cut rather than thrown away.
TASK_MAX_CHARS = 300

#: How a role reads as the one who runs things, when nobody is marked lead.
_LEAD_ROLE = re.compile(r"manager|lead|coordinator|project", re.IGNORECASE)


def _first_object(text: str) -> dict | None:
    """The first JSON object in the text that says what kind of answer it is.

    Tried at every "{" rather than with one regex over the whole text: a
    brace in the prose before the JSON, or a nested object inside it, would
    make a greedy or lazy pattern cut it in the wrong place.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
        except ValueError:
            obj = None
        if isinstance(obj, dict) and "kind" in obj:
            return obj
        start = text.find("{", start + 1)
    return None


def _names(roster) -> dict[str, str] | None:
    """{lower-case name: agent id}, or None when two agents share a name.

    A name that means two agents is a plan that could give a step to the
    wrong one, and waking the wrong agent is worse than waking none.
    """
    names: dict[str, str] = {}
    for a in roster if isinstance(roster, (list, tuple)) else []:
        if not isinstance(a, dict):
            continue
        name, agent_id = a.get("name"), a.get("id")
        if not isinstance(name, str) or not isinstance(agent_id, str):
            continue
        key = name.strip().lower()
        if not key:
            continue
        if key in names:
            return None
        names[key] = agent_id
    return names


def parse_triage(text: str, roster: list[dict]) -> list[dict] | None:
    """The lead's triage answer as steps, or None for "just answer it".

    Accepts the JSON object anywhere in the text (models wrap it in prose or
    a ```json fence). {"kind": "answer"} -> None. {"kind": "job", "steps":
    [{"agent": "<name>", "do": "<task>"}]} -> [{"agent_id", "task"}].
    Agent names are matched case-insensitively against the roster's names
    only. ANY problem returns None: unknown agent, fewer than 2 or more than
    6 steps, an empty task, bad JSON. None means the round runs as today.
    Tasks longer than TASK_MAX_CHARS are cut, not rejected.
    """
    if not isinstance(text, str) or not text:
        return None
    obj = _first_object(text)
    if obj is None or obj.get("kind") != "job":
        return None
    raw = obj.get("steps")
    if not isinstance(raw, list) or not MIN_STEPS <= len(raw) <= MAX_STEPS:
        return None
    names = _names(roster)
    if not names:
        return None

    steps = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        name, task = item.get("agent"), item.get("do")
        if not isinstance(name, str) or not isinstance(task, str):
            return None
        agent_id = names.get(name.strip().lower())
        task = task.strip()
        if agent_id is None or not task:
            return None
        steps.append({"agent_id": agent_id, "task": task[:TASK_MAX_CHARS]})
    return steps


def choose_lead(roster: list[dict]) -> dict | None:
    """meta.team_lead true wins; else the first agent whose meta.role matches
    /manager|lead|coordinator|project/i; else the first agent; None if empty."""
    agents = [a for a in (roster if isinstance(roster, (list, tuple)) else [])
              if isinstance(a, dict)]
    if not agents:
        return None

    def meta(a: dict) -> dict:
        m = a.get("meta")
        return m if isinstance(m, dict) else {}

    for a in agents:
        if meta(a).get("team_lead") is True:
            return a
    for a in agents:
        role = meta(a).get("role")
        if isinstance(role, str) and _LEAD_ROLE.search(role):
            return a
    return agents[0]
