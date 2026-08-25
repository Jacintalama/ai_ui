"""Which of the caller's agents should answer this message.

An agent is an Open WebUI model row, so "routing to an agent" is choosing a
different model id. The hard part is not the routing, it is that the thing
choosing is a model reading a short message: it can be wrong, and it can invent
an id. So everything it returns is checked against the caller's own candidate
list before it is used.

Candidates are always built from a list fetched with the CALLER's token, so an
agent belonging to somebody else is never in scope to begin with.
"""
import logging

from gateway.owui import OWUIUserClient

log = logging.getLogger(__name__)

AGENT_PREFIX = "agent-"

#: A prompt sent on every message has to stay small, so the LISTING in that
#: prompt is capped (in build_messages) and each line is a name and a
#: one-liner rather than the agent's instructions. candidates() itself is
#: NOT capped: match_pin_request and the deleted-agent check need every
#: agent the caller really has, not just the ones that fit in the prompt.
MAX_CANDIDATES = 20
MAX_DESCRIPTION = 120
MAX_TEXT = 500

PIN_VERBS = ("use ", "switch to ", "talk to ")
UNPIN_PHRASES = (
    "stop using that", "stop using it", "stop using this",
    "back to normal", "use normal", "no agent",
)


def candidates(models: list[dict]) -> list[dict]:
    """The agents in a model list, as {id, name, description}.

    Filters on the id prefix, the same test the Agents page uses. Open WebUI's
    own workspace can create derived models that are not agents, and those have
    no business being routed to.

    Returns every agent the caller has, uncapped: this list is also what
    match_pin_request and the deleted-agent check see, and a pin on an agent
    that exists but got trimmed here must never be mistaken for a pin on an
    agent that was deleted. The cap that keeps the router prompt small is
    applied later, in build_messages, on the listing only.
    """
    # Not just a convenience. Callers hand this whatever the models endpoint
    # returned, and a stub or a proxy error page can make that something that
    # is not a list. Iterating it would raise from inside a helper that is
    # supposed to be pure, and surface as an unexplained failure.
    if not isinstance(models, list):
        return []

    out: list[dict] = []
    for m in models:
        # Same reasoning as the list check above, one level down: a schema
        # change or a partial error body embedded in a 200 can put a
        # malformed row next to well-formed ones, and one bad row must not
        # cost the caller every good one.
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or ""
        if not isinstance(mid, str) or not mid.startswith(AGENT_PREFIX):
            continue
        meta = m.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        name = m.get("name")
        if not isinstance(name, str):
            name = mid
        description = meta.get("description")
        if not isinstance(description, str):
            description = ""
        out.append({
            "id": mid,
            "name": name[:60],
            "description": description[:MAX_DESCRIPTION],
        })
    return out


def build_messages(text: str, cands: list[dict]) -> list[dict]:
    # Capped here, not in candidates(): this is the prompt that has to stay
    # small, not the list of what a pin or the deleted-agent check may see.
    listing = "\n".join(
        "%s | %s | %s" % (c["id"], c["name"], c["description"])
        for c in cands[:MAX_CANDIDATES])
    system = (
        "You route a message to the assistant that fits it best.\n"
        "Each line is: id | name | what it does.\n\n"
        + listing
        + "\n\nReply with exactly one id from that list, or the single word "
          "NONE if none of them clearly fits. Reply with nothing else. "
        # This sentence is deliberately worded to contain the phrase
        # "personal knowledge graph" in lower case, which is the marker the
        # global Open WebUI inlet filter (knowledge_graph_memory_filter.py,
        # _MEMORY_MARKER / _already_injected) checks for, case-insensitively,
        # to decide whether it has already run on this call. Without it, the
        # filter injects the caller's full retrieved context into a call that
        # only needs to answer with one id, which costs money for nothing and
        # can push a real id further from the top of what the model reads.
        # That filter is not version locked to this file: if it changes its
        # marker, this phrase has to change to match, or the skip stops
        # working silently.
        "This is a routing decision only, so ignore any personal knowledge "
        "graph context."
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": (text or "")[:MAX_TEXT]}]


def validate(answer: str | None, cands: list[dict]) -> dict | None:
    """The candidate the router named, or None.

    Untrusted input. A model can return an id that does not exist, or one
    belonging to another user, and either would route a real request somewhere
    it must not go. It can also be typed to return a string and hand back
    something else entirely, so the type is checked before anything that
    assumes it.
    """
    if not isinstance(answer, str):
        return None
    by_id = {c["id"]: c for c in cands}
    # Only the first non-blank line is ever inspected. This is deliberate, not
    # an oversight: the prompt tells the router to reply with nothing but the
    # id, so a real answer is one line. If it prefixes an explanation anyway,
    # a valid id further down is missed and the call falls back to no agent
    # rather than an agent chosen by scanning past disclaimer text it wasn't
    # supposed to write. That failure mode is the safe one.
    for line in answer.splitlines():
        cleaned = line.strip().strip('"\'`').strip()
        if not cleaned:
            continue
        return by_id.get(cleaned)
    return None


async def pick(owui: OWUIUserClient, text: str, cands: list[dict],
               router_model: str) -> dict | None:
    """Ask which agent fits. Returns the candidate, or None to answer normally.

    Never raises. The person is waiting for an answer, and a router that cannot
    make up its mind must not be able to stop them getting one. validate() is
    called inside the same try as the model call: it is typed to return a
    string, but a wrong or changed return shape must fail the same safe way as
    a network error, not raise past this function's own guarantee.
    """
    if not cands:
        return None
    try:
        answer = await owui.chat_completion(
            build_messages(text, cands), router_model)
        return validate(answer, cands)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: agent router did not answer, using the default "
                    "model", exc_info=True)
        return None


def _normalise(text: str) -> str:
    return (text or "").strip().rstrip(".!").strip().lower()


def match_pin_request(text: str, cands: list[dict]) -> dict | None:
    """The agent this message asks to switch to, or None.

    Deliberately narrow: the message must start with one of a few verbs and the
    REST of it must be exactly an agent's name. A looser match would swallow
    real requests that happen to begin with "use", and a message silently
    turning into a setting is worse than a router that picks wrong.
    """
    t = _normalise(text)
    for verb in PIN_VERBS:
        if t.startswith(verb):
            rest = t[len(verb):].strip()
            for c in cands:
                if rest == c["name"].strip().lower():
                    return c
    return None


def is_unpin_request(text: str) -> bool:
    return _normalise(text) in UNPIN_PHRASES


def pin_key(platform: str, chat_id: str) -> str:
    return "gateway:agent-pin:%s:%s" % (platform, chat_id)
