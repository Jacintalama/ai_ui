"""Which model an agent's words come from (2026-10-27).

An agent is an Open WebUI workspace model: a name, instructions, tools and a
base model. Until now the base model WAS the language model, and a mention
of the agent in the main chat (@Ada) went to that model through Open WebUI's
own loop: no brief, no skills, no memory, no access level, none of what the
agent has everywhere else. For the mention to run OUR loop, the base model
has to be the IO pipe, which hands the message to the tasks service. The
language model then has to live somewhere else: meta.llm.

So an agent has two things that used to be one:

- base_model_id: the pipe (BASE, "io.io"), so a mention reaches us. An
  agent somebody put on a plain model directly, through the API or an
  older page, still has its model here, and still works as before.
- meta.llm: the language model the agent's words come from, read by the
  runner, the page and the summaries through llm_of.

The runner posts to llm_of(agent) directly, with the agent's instructions
in front, exactly as it already did when falling down the free pool. It
must never post the agent's id when the base is a pipe: the pipe would ask
the service, the service would run the agent, and so on until Open WebUI
fell over (measured 2026-09-10, see routes_agent_turn.CALLBACK_MODEL_IDS).
"""
from __future__ import annotations

import os

#: Model ids that are pipes which call BACK into the tasks service. An
#: agent on one of these runs only through meta.llm. Regenerate with:
#:   select id from public.function
#:    where type='pipe' and content like '%/agents/chat%';
#: then map each pipe to its model id: pipe "io" registers model "io.io".
CALLBACK_IDS = frozenset({"auto_router.auto", "io.io"})


def base_model() -> str:
    """The base model every new agent is made on: the IO pipe. Read at
    call time so a deployment can name the pipe differently."""
    return os.environ.get("AGENT_BASE_MODEL", "io.io") or "io.io"


def is_callback(model_id) -> bool:
    return isinstance(model_id, str) and model_id in CALLBACK_IDS


def llm_of(agent: dict | None) -> str | None:
    """The language model this agent's words come from, or None when it
    has none that can answer.

    meta.llm when the base is a pipe; the base itself otherwise. An agent
    on a pipe with no meta.llm is one made before 2026-10-27 that somebody
    put on Auto or IO by hand: it cannot run, and the caller says so."""
    if not isinstance(agent, dict):
        return None
    base = agent.get("base_model_id")
    if not is_callback(base):
        return base if isinstance(base, str) and base else None
    meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
    llm = meta.get("llm")
    if isinstance(llm, str) and llm.strip() and not is_callback(llm.strip()):
        return llm.strip()
    return None


def on_pipe(agent: dict | None) -> bool:
    """Whether a turn for this agent must post its language model directly:
    the base is a pipe and meta.llm names a real model."""
    return (isinstance(agent, dict) and is_callback(agent.get("base_model_id"))
            and llm_of(agent) is not None)


def can_run(agent: dict | None) -> bool:
    """Whether this agent has a model that can answer at all."""
    return llm_of(agent) is not None
