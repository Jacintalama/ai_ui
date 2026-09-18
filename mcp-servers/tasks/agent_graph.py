"""What this person actually has, put in front of an agent before it answers.

The Brain assembles this already: apps, chats, schedules, files, collections,
videos, with live counts. Every ordinary model gets it, because Open WebUI runs
a global inlet filter that fetches /graph/mine/context and puts it in the
conversation. An agent turn never passes through that filter. It is a direct
API call from this service, so seven agents have been answering questions about
this person's work while the one block describing that work went only to models
they do not use.

Read once per round, not once per agent. A room of seven agents answering one
question is seven turns, and _assemble_live reads the whole account each time.
The caller builds this and hands the same block to everybody, exactly as it
does with history.

Fail open, like agent_memory.recall_block: a turn without the graph is a turn,
a turn that waits on the graph is an outage.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

#: One read of the account, with a ceiling. Six, because that is what the Open
#: WebUI filter already gives this same read for an ordinary model
#: (knowledge_graph_memory_filter, timeout_seconds), and an agent should not
#: keep somebody waiting longer for the same block. It is an optional
#: improvement to an answer they are getting either way.
GRAPH_TIMEOUT_SECONDS = 6.0

#: How many graph nodes the retrieval chain may put in the block. The same
#: default the inlet filter uses, so an agent sees what a plain model sees.
GRAPH_LIMIT = 6

#: Said before the block so the model knows it is looking at this person's own
#: account rather than at something they typed.
HEADING = ("This is what this person has right now, read from their account. "
           "Use it when it answers the question, and say nothing about it "
           "when it does not:")


async def _build(user_email: str, question: str) -> str:
    # Imported here rather than at module scope: routes_knowledge_graph pulls
    # in the embedding stack and the graph's own router, and this module is
    # imported by the turn path, which must not grow that dependency for a
    # feature that fails open anyway.
    import routes_knowledge_graph as graph
    out = await graph.context_for(user_email, question, GRAPH_LIMIT)
    return str((out or {}).get("context") or "")


async def graph_block(user_email: str, question: str = "") -> str:
    """The person's graph context as one block, or "".

    include_team is left at its default, so an admin asking through an agent
    sees their own account and not the org's. The filter passes an admin's
    team material because a person asking in their own chat is asking as
    themselves; an agent runs unattended on a schedule as well, and the same
    block would then be delivered to a channel.
    """
    if not user_email:
        return ""
    read = asyncio.ensure_future(_build(user_email, question))
    try:
        context = await asyncio.wait_for(read, timeout=GRAPH_TIMEOUT_SECONDS)
    except Exception:                                       # noqa: BLE001
        # Cancelling is ours to do: wait_for cancels on timeout, but a
        # failure raised from inside leaves nothing running, and a caller
        # that is going to answer anyway must not leave a connection held
        # against a database that just refused it.
        read.cancel()
        logger.warning("could not read the knowledge graph for a turn",
                       exc_info=True)
        return ""
    context = (context or "").strip()
    return HEADING + "\n" + context if context else ""
