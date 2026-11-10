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
#: One agent asked another. Nobody is watching THIS conversation: the owner
#: is talking to the agent that asked, so a prompt raised here would ask them
#: about a conversation they are not in, and answering it would need the
#: colleague's reply written back into a turn that is paused mid-sentence.
#: So `ask` narrows here instead of prompting, which makes ApprovalRequired
#: impossible inside a handoff rather than merely unlikely.
SURFACE_COLLEAGUE = "colleague"
#: Something outside ran the agent through an automation key
#: (routes_automation): an n8n workflow, a script. Nobody is watching, as
#: on a schedule, and there is no schedule row to read a tool_mode from, so
#: it behaves exactly like a colleague's turn: only `all` acts.
SURFACE_AUTOMATION = "automation"


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


#: What a person chose in the chat composer, for this conversation.
#:
#: Three choices because three things are genuinely different. Without the
#: middle one `manual` and `auto` would be the same setting, since the main
#: chat already asks: what separates them is whether a standing rule is
#: allowed to answer in the person's place.
CHAT_MANUAL = "manual"   #: ask every time, and let no rule answer for me
CHAT_AUTO = "auto"       #: rules answer what they cover, the rest asks
CHAT_SKIP = "skip"       #: never ask
CHAT_CHOICES = frozenset({CHAT_MANUAL, CHAT_AUTO, CHAT_SKIP})

#: Narrowest to widest. The order IS the safety property: a chat choice may
#: move a named agent down this list and never up it.
_WIDTH = {MODE_READ_ONLY: 0, MODE_ASK: 1, MODE_FULL: 2}


def _chosen(choice) -> str | None:
    """The choice if it is one of ours, else None.

    It arrives from a browser, so anything may turn up here. Unrecognised
    reads as "they have not chosen", never as the widest option: that
    direction is the one that costs something.
    """
    return choice if isinstance(choice, str) and choice in CHAT_CHOICES \
        else None


#: What Open WebUI's own composer menu calls the two postures it offers
#: (InputMenu.svelte in 0.12.0, behind `chat.tool_permissions.enable`).
#: Its menu is the control Ralph asked for, so these are the words that
#: actually arrive from a person; ours above are what they mean here.
APPROVAL_ASK = "ask"
APPROVAL_FULL = "full"

_FROM_APPROVAL_MODE = {APPROVAL_ASK: CHAT_AUTO, APPROVAL_FULL: CHAT_SKIP}


def choice_from_approval_mode(mode) -> str | None:
    """Open WebUI's composer menu, read as one of our own choices.

    Their menu has two items and no third, so CHAT_MANUAL is not
    reachable from there and is left to our own route.

    Anything else, including None, reads as "nobody has chosen". That
    matters more here than in `_chosen`, and it is why the CALLER must
    hand this the value off the CHAT row rather than off the turn's
    metadata: `main.py` writes `full` into the metadata whenever it has
    nothing to say (the feature off, an automation, a channel), while
    `handleToolApprovalModeChange` writes the chat's own
    `params.tool_approval_mode` only when somebody clicks. The key being
    there at all is the record of intent.

    Never raises.
    """
    if not isinstance(mode, str):
        return None
    return _FROM_APPROVAL_MODE.get(mode.strip().lower())


def rules_apply(choice) -> bool:
    """Whether a standing rule may answer in this person's place.

    Only `manual` turns them off, and only for the chat it was chosen in.
    A rule the person wrote is still THEIR decision, so this is not a
    safety control; it is for the times they want to watch each one go by.
    """
    return _chosen(choice) != CHAT_MANUAL


def with_chat_choice(mode: str, choice, ceiling: str | None) -> str:
    """`mode`, adjusted by what the person chose in this conversation.

    `ceiling` is the agent's own level, or None when there is no agent row
    behind the turn. That distinction is the whole of the rule:

    * A NAMED AGENT has a ceiling its owner set, and this may only narrow
      it. "An agent's level is a CEILING... two controls that can each
      widen the other is how permission systems get holes" is the reason
      this module exists, and a menu in a chat window does not overrule a
      level somebody chose deliberately.
    * THE MAIN CHAT's assistant has no agent row: `_resolve_agent_row`
      hands back MODE_ASK for it with no level at all. There is nothing to
      widen, so the person's choice for their own chat is simply honoured.

    Never raises.
    """
    chosen = _chosen(choice)
    if chosen is None:
        return mode
    wanted = MODE_FULL if chosen == CHAT_SKIP else MODE_ASK
    if ceiling is None:
        return wanted
    # Narrower of the two, by width. Never the wider.
    return wanted if _WIDTH.get(wanted, 0) < _WIDTH.get(mode, 0) else mode


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

    if surface == SURFACE_AUTOMATION:
        # Since approvals have an id (agent_approvals, 2026-10-28) an
        # automation's agent on Ask asks like a channel's: the question is
        # written down, delivered, and answered from the Agents page, the
        # main chat or a standing rule. Before that it could only read.
        if level == LEVEL_ALL:
            return MODE_FULL
        if level == LEVEL_ASK:
            return MODE_ASK
        return MODE_READ_ONLY

    if surface == SURFACE_COLLEAGUE:
        # Only a level the owner set to `all` acts. tool_mode is ignored
        # entirely rather than defaulted: reading it here would give a
        # caller a way to widen a read-only agent, which is the hole this
        # module exists to close.
        if level == LEVEL_ALL:
            return MODE_FULL
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
    if surface == SURFACE_COLLEAGUE:
        return ("another agent asked this one, and it is not set to act on "
                "its own")
    if surface == SURFACE_AUTOMATION:
        if level is None:
            return "this agent has not been given access to change things"
        return "this agent is set to read only"
    if level == LEVEL_ASK:
        return "a scheduled run has nobody to ask"
    if level == LEVEL_READ:
        return "this agent is set to read only"
    return "this schedule is set to read only"
