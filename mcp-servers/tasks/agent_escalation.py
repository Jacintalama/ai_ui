"""When an agent on a free model moves to the paid model, and what it cost.

Free models answer ordinary questions well. What they do badly is long, many
round work: building an app, changing code, chasing an error. The owner asked
on 2026-09-17 for that switch to happen on its own, so nobody has to open an
agent's card and change its model for one job and then change it back.

Pure on purpose: no database and no HTTP. agent_runner asks the questions
here and does the switching, agent_activity counts and records. Everything a
test needs to pin a decision is a plain function of its arguments, and the
two pieces of state that are not (the sticky window and the once a day note)
take an explicit clock.

Design: docs/plans/2026-09-17-agent-paid-escalation-design.md.
"""
import contextlib
import contextvars
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone


def _int_env(name: str, default: int) -> int:
    """An integer setting, or the default when it is unset or not a number.

    A typo in compose must not take the tasks service down at import, which
    is what a bare int() would do.
    """
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


#: The model a free agent moves to. Blank switches the feature off.
PAID_MODEL = os.environ.get("AGENT_PAID_MODEL", "gpt-5.5").strip()

#: Sent as reasoning_effort on paid completions. Blank sends nothing.
PAID_REASONING = os.environ.get("AGENT_PAID_REASONING", "low").strip()

#: The least a paid completion is allowed. A caller's own timeout wins when
#: it is longer (a schedule's 240 seconds).
PAID_TIMEOUT_SECONDS = _int_env("AGENT_PAID_TIMEOUT_SECONDS", 90)

#: Paid turns per person per UTC day. 0 switches the feature off.
DAILY_CAP = _int_env("AGENT_PAID_DAILY_CAP", 40)

#: How long an agent stays on the paid model for this person after a paid
#: completion, refreshed by every paid completion.
STICKY_SECONDS = _int_env("AGENT_PAID_STICKY_SECONDS", 900)

#: Extra tool rounds the paid model gets when a free turn ran out of rounds.
PAID_EXTRA_ROUNDS = _int_env("AGENT_PAID_EXTRA_ROUNDS", 3)

#: A carried conversation longer than this, in characters, moves to paid.
CONVERSATION_CHARS = _int_env("AGENT_PAID_CONVERSATION_CHARS", 60000)

#: A single message from the person longer than this moves to paid.
MESSAGE_CHARS = _int_env("AGENT_PAID_MESSAGE_CHARS", 2000)

REASON_BUILD = "build"
REASON_CODE = "code"
REASON_ERROR = "error"
REASON_LONG_MESSAGE = "long_message"
REASON_LONG_CONVERSATION = "long_conversation"
REASON_STICKY = "sticky"
REASON_HEAVY_TOOL = "heavy_tool"
REASON_EMPTY = "empty_answer"
REASON_POOL_SPENT = "pool_spent"
REASON_ROUNDS_CAP = "rounds_cap"

#: Tools that mean the agent is changing an app. No agent tool builds a new
#: app today (open-webui-functions/*_tool.py, 2026-09-17); add its name here
#: if one appears.
HEAVY_TOOLS = frozenset({"propose_app_change", "apply_app_change"})

#: Said once a day, per person, when a turn would have moved and could not.
CAP_NOTE = ("Today's limit of %d turns on the stronger model is used up, so "
            "this answer comes from the free model.")


def enabled() -> bool:
    return bool(PAID_MODEL) and DAILY_CAP > 0


def paid_timeout(timeout: float) -> float:
    return max(float(timeout), float(PAID_TIMEOUT_SECONDS))


# --- cost -------------------------------------------------------------------

def parse_prices(raw: str) -> dict:
    """"gpt-5.5=5:30,gpt-5-mini=0.25:2" as {id: (input, output)}, in US
    dollars per million tokens. A malformed entry is skipped rather than
    guessed at, so a typo costs that model its price, not the service."""
    out = {}
    for part in (raw or "").split(","):
        name, sep, value = part.strip().partition("=")
        if not sep or not name.strip():
            continue
        given_in, _sep, given_out = value.partition(":")
        try:
            out[name.strip()] = (float(given_in), float(given_out))
        except ValueError:
            continue
    return out


#: Read 2026-09-17 from developers.openai.com/api/docs/pricing: gpt-5.5 is
#: $5.00 input and $30.00 output per million tokens.
PRICES = parse_prices(os.environ.get("AGENT_PAID_PRICES", "gpt-5.5=5:30"))


def cost_of(model: str, prompt_tokens: int, completion_tokens: int):
    """What one completion cost in dollars, or None when nothing says.

    Free ids cost nothing. A model with no price is None rather than 0, so a
    row never claims a paid run was free.
    """
    if isinstance(model, str) and model.endswith(":free"):
        return 0.0
    price = PRICES.get(model)
    if price is None:
        return None
    return (prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(int(value), 0)


@dataclass
class TurnUsage:
    """What one turn spent, summed over every completion that answered.

    Filled in by agent_runner._chat as it goes and written with the run by
    agent_activity.finish_run, so a turn that stops to ask still records
    what it spent before it stopped.
    """
    run_id: str | None = None
    model: str | None = None
    escalation: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = 0.0

    def add(self, model: str, usage) -> None:
        self.model = model
        free = isinstance(model, str) and model.endswith(":free")
        if not isinstance(usage, dict):
            # No usage on a paid reply means the cost is unknown, not zero.
            if not free:
                self.cost_usd = None
            return
        prompt = _count(usage.get("prompt_tokens"))
        completion = _count(usage.get("completion_tokens"))
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        cost = cost_of(model, prompt, completion)
        if cost is None or self.cost_usd is None:
            self.cost_usd = None
        else:
            self.cost_usd += cost
