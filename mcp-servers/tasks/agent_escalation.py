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
import math
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
            price = (float(given_in), float(given_out))
        except ValueError:
            continue
        # float() reads "nan", "inf" and "-5" happily, and any of them would
        # be written to cost_usd as if it were a price.
        if all(math.isfinite(p) and p >= 0 for p in price):
            out[name.strip()] = price
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


def _is_count(value) -> bool:
    """A token count a reply actually gave, as opposed to junk or nothing.

    json.loads accepts NaN, Infinity and 1e999, and int() raises on the first
    two, so a finite check keeps one bad number from failing the turn.
    """
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _count(value) -> int:
    return int(value) if _is_count(value) else 0


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
        given_prompt = usage.get("prompt_tokens")
        given_completion = usage.get("completion_tokens")
        prompt = _count(given_prompt)
        completion = _count(given_completion)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        if not free and not (_is_count(given_prompt)
                             or _is_count(given_completion)):
            # A usage of {}, of nulls, or of names this does not read says no
            # more than no usage, and pricing it at 0 tokens would record a
            # paid reply as $0.00.
            self.cost_usd = None
            return
        cost = cost_of(model, prompt, completion)
        if cost is None or self.cost_usd is None:
            self.cost_usd = None
        else:
            self.cost_usd += cost


# --- the rules --------------------------------------------------------------

_BUILD = re.compile(
    r"\b(?:build|create|make(?!\s+sure)|generate|scaffold|develop|code up|"
    r"spin up|set up)\b[^.?!\n]{0,40}?\b(?:apps?|application|web ?sites?|"
    r"sites?|web ?pages?|landing pages?|pages?|dashboards?|games?|api|"
    r"backend|frontend|extension|bot|plugin|portal|store|shop)\b")

_CODE = re.compile(
    r"\b(?:refactor|debug|debugging|implement)\b"
    r"|\bwrite\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|some\s+)?(?:code|script|"
    r"function|class|query|regex|tests?|component|endpoint|migration|"
    r"program)\b"
    r"|\bfix\b[^.?!\n]{0,30}?\b(?:bugs?|errors?|code|build|tests?|"
    r"crash(?:es)?|issues?|page|app|site|feature)\b"
    r"|\badd\b[^.?!\n]{0,30}?\b(?:feature|endpoint|component|function)\b"
    r"|\bapp builder\b")

_ERROR = re.compile(
    r"traceback \(most recent call last\)"
    r"|\bstack ?trace\b"
    r"|\b[a-z]*(?:error|exception):\s"
    r"|^\s*at \S+ \(\S+:\d+:\d+\)",
    re.MULTILINE)


def rule_reason(text) -> str | None:
    """Why this message needs the paid model, or None. Read from what the
    person typed, never from an instruction this service added."""
    raw = text if isinstance(text, str) else ""
    if not raw.strip():
        return None
    low = raw.lower()
    if "```" in raw:
        return REASON_CODE
    if _ERROR.search(low):
        return REASON_ERROR
    if _BUILD.search(low):
        return REASON_BUILD
    if _CODE.search(low):
        return REASON_CODE
    if len(raw) > MESSAGE_CHARS:
        return REASON_LONG_MESSAGE
    return None


_QUESTION_START = re.compile(
    r"^\s*(?:what|what's|whats|when|where|who|whom|whose|which|why|how)\b")
_REQUEST_START = re.compile(
    r"^\s*(?:please|can you|could you|would you|will you|can we|could we|"
    r"let's|lets)\b")
_TASK_WORDS = re.compile(
    r"\b(?:apps?|site|website|pages?|build|builds|code|files?|bugs?|errors?|"
    r"fail(?:s|ed|ing)?|broken|deploy(?:ed)?|change|changes|fix|feature|"
    r"buttons?|style|colou?rs?|layout|design|preview|tests?|component|"
    r"header|footer|logo|font|images?|database|login|form)\b")


def is_plain_question(text) -> bool:
    """A question about something other than the work in hand.

    "What is on my calendar tomorrow?" goes back to the free model even while
    an agent is mid build. "Can you make it blue?" is a request in a question's
    clothes, and "why did the build fail?" is about the work, so neither is.
    """
    low = (text if isinstance(text, str) else "").strip().lower()
    if not low or _REQUEST_START.search(low):
        return False
    if not (low.endswith("?") or _QUESTION_START.search(low)):
        return False
    return not _TASK_WORDS.search(low)


def looks_like_pass(content) -> bool:
    """The room's PASS, in the shapes models send it."""
    text = content if isinstance(content, str) else ""
    return text.strip().strip('."\'').upper() == "PASS"


def names_heavy_tool(calls) -> bool:
    for call in calls if isinstance(calls, list) else []:
        fn = call.get("function") if isinstance(call, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str) and name.strip() in HEAVY_TOOLS:
            return True
    return False


def conversation_chars(messages) -> int:
    total = 0
    for m in messages if isinstance(messages, list) else []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(p.get("text") or "") for p in content
                         if isinstance(p, dict)
                         and isinstance(p.get("text"), str))
    return total


def too_long(messages) -> bool:
    return conversation_chars(messages) > CONVERSATION_CHARS


# --- who is asking ----------------------------------------------------------

@dataclass(frozen=True)
class Intent:
    """What a turn's caller knows about the person asking.

    person_text is what they typed. may_pass is true in the room when this
    agent was not named and may answer PASS. follow_up is true when the turn
    continues one that stopped to ask.
    """
    person_text: str = ""
    may_pass: bool = False
    follow_up: bool = False


_current = contextvars.ContextVar("agent_escalation_intent", default=None)


def current_intent() -> Intent | None:
    return _current.get()


@contextlib.contextmanager
def asking(intent: Intent):
    """Carry an intent to the turn beneath this call without changing the
    signature of everything in between. Reset on the way out, so it never
    leaks to the next agent in the room."""
    token = _current.set(intent)
    try:
        yield intent
    finally:
        _current.reset(token)


# --- sticky window ----------------------------------------------------------

_windows: dict = {}


def _key(user_email, agent_id) -> tuple:
    return ((user_email or "").strip().lower(), agent_id or "")


def mark_paid(user_email, agent_id, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if len(_windows) > 500:
        for k in [k for k, until in _windows.items() if until <= now]:
            _windows.pop(k, None)
    _windows[_key(user_email, agent_id)] = now + STICKY_SECONDS


def in_window(user_email, agent_id, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    key = _key(user_email, agent_id)
    until = _windows.get(key)
    if until is None:
        return False
    if until <= now:
        _windows.pop(key, None)
        return False
    return True


def decide(intent: Intent, window_open: bool) -> str | None:
    """Why this turn starts on the paid model, or None."""
    reason = rule_reason(intent.person_text)
    if reason:
        return reason
    if not window_open:
        return None
    if intent.follow_up:
        return REASON_STICKY
    if is_plain_question(intent.person_text):
        return None
    return REASON_STICKY


# --- the once a day note ----------------------------------------------------

_noted: set = set()


def take_cap_note(user_email, today: str | None = None) -> str:
    """The cap note the first time today, "" after that."""
    day = today or datetime.now(timezone.utc).date().isoformat()
    key = ((user_email or "").strip().lower(), day)
    if key in _noted:
        return ""
    if len(_noted) > 1000:
        for old in [k for k in _noted if k[1] != day]:
            _noted.discard(old)
    _noted.add(key)
    return CAP_NOTE % DAILY_CAP
