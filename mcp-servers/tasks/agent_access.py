"""What an agent may do, here, right now.

There is one answer to that and it lives in this file. The alternative is
what this codebase has done twice before: the same decision written in two
functions, where fixing one leaves the other open.

An agent's level is a CEILING. A schedule may narrow it and may never widen
it. Two controls that can each widen the other is how permission systems get
holes.

An absent level is not a default. It means the agent predates this feature
and has no opinion, so each caller falls back to what it did before, and
nothing that works today starts behaving differently.

None of this protects one user from another. The owner writes their own
agent row, so they can set their own agent to `all` whenever they like, and
that is intended: it is their agent acting on their own connected accounts.
Per-user scoping is done by X-User-Email and the per-user minted token, and
none of it changes here. What this protects against is an agent doing
something its owner did not intend, including at the prompting of text the
agent read somewhere else.
"""

#: What the owner picked, stored as meta.access on the agent's model row.
LEVEL_READ = "read"
LEVEL_ASK = "ask"
LEVEL_ALL = "all"
LEVELS = frozenset({LEVEL_READ, LEVEL_ASK, LEVEL_ALL})

#: What the tool loop is told. read_only and full are the values the
#: per-schedule tool_mode column has always used; ask is new.
MODE_READ_ONLY = "read_only"
MODE_ASK = "ask"
MODE_FULL = "full"

#: Where the agent is running. A channel has somebody watching who can be
#: asked; a schedule does not.
SURFACE_CHANNEL = "channel"
SURFACE_SCHEDULE = "schedule"


class ApprovalRequired(Exception):
    """The agent wants to do something it must ask about first.

    Raised out of the middle of the tool loop, carrying enough to pick the
    turn back up once an answer arrives. An exception rather than a third
    return value on purpose: this is an exceptional exit from a loop whose
    ordinary contract is "run until the model answers", and every existing
    caller of that loop unpacks two values.
    """

    def __init__(self, conversation: list[dict], calls: list[dict]):
        self.conversation = conversation
        self.calls = calls
        super().__init__("the agent needs approval before it can continue")


def level_of(meta) -> str | None:
    """The agent's own access level, or None when it has no opinion.

    Anything unrecognised reads as None rather than as a default. A junk
    value is not evidence of a choice, and treating it as one would hand an
    agent a permission nobody picked.
    """
    if not isinstance(meta, dict):
        return None
    value = meta.get("access")
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in LEVELS else None


def effective_mode(level: str | None, tool_mode: str | None,
                   surface: str) -> str:
    """What the tool loop is allowed to do for this run."""
    if surface == SURFACE_CHANNEL:
        # No schedule behind a channel message, so tool_mode is ignored
        # entirely rather than defaulted. Reading it here would give a caller
        # a way to widen a read-only agent.
        if level == LEVEL_ALL:
            return MODE_FULL
        if level == LEVEL_ASK:
            return MODE_ASK
        # LEVEL_READ, and None. Channels refuse every tool today, so
        # read-only for an agent with no opinion cannot regress anything.
        return MODE_READ_ONLY

    schedule_full = (tool_mode or MODE_READ_ONLY) == MODE_FULL
    if level is None:
        # Exactly today's behaviour, so an existing schedule set to full
        # keeps working.
        return MODE_FULL if schedule_full else MODE_READ_ONLY
    if level == LEVEL_ALL and schedule_full:
        return MODE_FULL
    # Everything else narrows, including ask: see the module docstring.
    return MODE_READ_ONLY


def refusal_reason(level: str | None, tool_mode: str | None,
                   surface: str) -> str:
    """Why a write was not run, as a lower-case clause with no full stop.

    It is interpolated into two different sentences, so it has to read as a
    fragment in both. Kept beside effective_mode so the two cannot drift:
    a refusal that explains the wrong rule is worse than no explanation.
    """
    if surface == SURFACE_CHANNEL:
        if level is None:
            # Distinct from LEVEL_READ on purpose: "set to read only" is
            # false for an agent that predates this feature and has never
            # had a level chosen at all.
            return "this agent has not been given access to change things"
        return "this agent is set to read only"
    if level == LEVEL_ASK:
        return "a scheduled run has nobody to ask"
    if level == LEVEL_READ:
        return "this agent is set to read only"
    return "this schedule is set to read only"
