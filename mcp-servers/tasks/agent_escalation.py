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
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeGuard


def _int_env(name: str, default: int) -> int:
    """An integer setting, or the default when it is unset or not a number.

    A typo in compose must not take the tasks service down at import, which
    is what a bare int() would do.
    """
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


#: The model a free agent moves to. AGENT_PAID_MODEL= set blank in .env
#: switches the feature off, and so does AGENT_PAID_DAILY_CAP=0. Blank
#: reaches this process only because compose declares it
#: ${AGENT_PAID_MODEL-gpt-5.5} with no colon; ${VAR:-default} would hand
#: over the default instead. Unset (the line deleted) means gpt-5.5.
PAID_MODEL = os.environ.get("AGENT_PAID_MODEL", "gpt-5.5").strip()

#: Sent as reasoning_effort on paid completions. AGENT_PAID_REASONING= set
#: blank in .env sends nothing, declared with no colon in compose for the
#: same reason. none, not low: gpt-5.5 on /v1/chat/completions refuses
#: function tools with low (HTTP 400, measured 2026-09-17) and names none as
#: the value that works. Blank would leave it to OpenAI's default, which was
#: not measured.
PAID_REASONING = os.environ.get("AGENT_PAID_REASONING", "none").strip()

#: The least a paid completion is allowed. A caller's own timeout wins when
#: it is longer (a schedule's 240 seconds).
PAID_TIMEOUT_SECONDS = _int_env("AGENT_PAID_TIMEOUT_SECONDS", 90)

#: Paid turns per person per UTC day. 0 switches the feature off. Blank is
#: not an off switch: compose and _int_env both read it as 40.
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

def parse_prices(raw: str) -> dict[str, tuple[float, float]]:
    """"gpt-5.5=5:30,gpt-5-mini=0.25:2" as {id: (input, output)}, in US
    dollars per million tokens. A malformed entry is skipped rather than
    guessed at, so a typo costs that model its price, not the service."""
    out: dict[str, tuple[float, float]] = {}
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


def cost_of(model: str, prompt_tokens: int,
            completion_tokens: int) -> float | None:
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


def _is_count(value: object) -> TypeGuard[int | float]:
    """A token count a reply actually gave, as opposed to junk or nothing.

    json.loads accepts NaN, Infinity and 1e999, and int() raises on the first
    two, so a finite check keeps one bad number from failing the turn.
    """
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _count(value: object) -> int:
    return int(value) if _is_count(value) else 0


@dataclass
class TurnUsage:
    """What one turn spent, summed over every completion that answered.

    Filled in by agent_runner._chat as it goes and written with the run by
    agent_activity.finish_run, so a turn that stops to ask still records
    what it spent before it stopped.

    One turn can use a free id and the paid model (free decides and then
    moves, or paid fails and free writes up), and the row has one model and
    one pair of token counts. So: model is the paid model once any paid
    completion answered, otherwise the last free id; prompt_tokens and
    completion_tokens are totals over every completion, free included; and
    cost_usd prices only the paid completions, because free ids cost 0.
    Checking a cost therefore means the paid completions' own counts, which
    agent_runner logs one line each ("paid completion for ...").
    """
    run_id: str | None = None
    model: str | None = None
    escalation: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = 0.0

    def add(self, model: str, usage: object) -> None:
        free = isinstance(model, str) and model.endswith(":free")
        paid_answered = (isinstance(self.model, str)
                         and not self.model.endswith(":free"))
        if not (free and paid_answered):
            self.model = model
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

# Tightened after review on 2026-09-18, when "set up a meeting with the store
# manager", "create an API key for stripe", "update the zip code on my
# shipping address", "fix the issue with my calendar invite" and "there was
# an error: the invoice is wrong" all went to the paid model. The cases are
# pinned in tests/test_agent_escalation_rules.py.

#: The thing being built has to be software, and it has to be what the verb
#: makes: the head of the phrase after it, not a word forty characters on.
#: "make dinner plans after the game" reaches "after" before it reaches
#: "game", and a word in _NOT_A_MODIFIER ends the phrase. Only function
#: words end it: what the app is for (an expense tracker, a tax calculator,
#: a job board) is a modifier like any other.
_BUILD_VERB = (r"\b(?:build|create|make(?!\s+sure)|generate|scaffold|develop|"
               r"code up|spin up|set up)\s+(?:(?:me|us)\s+)?")
_DETERMINER = r"(?:(?:a|an|the|my|our|this|that|some|another)\s+)?"
#: "to" and "and" end the phrase because "create a reminder to renew app
#: subscriptions" and "create an invoice and email app receipts" make a
#: reminder and an invoice. A to-do is the one thing "to" names, so "to-do"
#: is a modifier anywhere and "to do" right after the determiner.
_NOT_A_MODIFIER = (r"(?:a|an|the|my|our|your|his|her|their|this|that|for|with|"
                   r"after|before|about|to|from|on|in|at|of|by|and|or|but|"
                   r"which|where|who|when|so|if)")
_MODIFIERS = (r"(?:(?:to-do|(?!%s\b)[a-z0-9][\w'-]{0,30})\s+){0,3}"
              % _NOT_A_MODIFIER)
#: No store, shop, api key, meeting, plans or event. A site is not a site
#: visit, and an application is software only when it says so. A page is a
#: web page when it is a kind only a site has (contact, signup, pricing) or
#: is in an app or a site, and not when it is in a notebook or a doc.
_SOFTWARE = (
    r"(?:apps?|web ?apps?|(?:web|mobile|desktop|ios|android) applications?|"
    r"web ?sites?|sites?(?!\s+(?:visits?|surveys?|inspections?|meetings?|"
    r"managers?|plans?|walks?|tours?))|web ?pages?|"
    r"(?:landing|signup|sign-up|sign ?up|login|log-in|log ?in|sign-in|"
    r"sign ?in|contact|portfolio|pricing|checkout|settings|profile|admin|"
    r"product|about|home|404) pages?(?!\s+(?:notes?\b|in\s+(?:(?:my|the|a|"
    r"our)\s+)?(?:notebook|doc|document|notion|onenote)\b))|"
    r"pages?\s+(?:in|on|for|to)\s+(?:my|our|the)\s+(?:web ?apps?|apps?|"
    r"web ?sites?|sites?(?!\s+visits?))|"
    r"dashboards?|backend|back-end|frontend|front-end|"
    r"apis?(?!\s+(?:keys?|tokens?|secrets?|credentials?|access|accounts?))|"
    r"(?:browser|chrome|firefox|vs ?code) extensions?|bots?|plugins?|"
    r"online (?:store|shop)|web ?shop|e-?commerce (?:store|shop|site))\b")
#: "make a snake game" is a build; "make the game on Friday" is a calendar.
_GAME = (r"(?:a|an)\s+" + _MODIFIERS
         + r"games?\b(?!\s+(?:plans?|nights?|days?|shows?))")
_BUILD = re.compile(_BUILD_VERB + r"(?:" + _DETERMINER + r"(?:to do\s+)?"
                    + _MODIFIERS + _SOFTWARE + r"|" + _GAME + r")")

#: Codes that are not source code: a zip code, a promo code, a door code.
#: Whole words, so "navbar code" is still code. Left out on purpose because
#: they are as often source: order, ticket, tracking (an analytics snippet),
#: color (a hex value in css).
_NOT_SOURCE = "".join(r"(?<!\b%s )" % w for w in (
    "zip", "postal", "post", "promo", "promotional", "discount", "coupon",
    "voucher", "gift", "verification", "confirmation", "access", "security",
    "door", "gate", "alarm", "dress", "area", "country", "tax", "booking",
    "reference", "referral", "qr", "bar", "activation", "pin", "sort",
    "swift", "billing", "building", "morse", "parking", "wifi", "invite",
    "2fa", "otp", "one-time", "reservation", "voting", "fire"))
_SOURCE_CODE = _NOT_SOURCE + r"code\b(?!\s+of\s+conduct)"
#: A script is a video's or a speech's as often as a program's.
_SCRIPT = (r"script(?![^.?!\n]{0,30}\b(?:video|youtube|speech|podcast|film|"
           r"movie|play|presentation|commercial|reel|tiktok|toast|episode|"
           r"scene|voiceover|webinar)\b)")
_LANGUAGE = (r"(?:(?:python|bash|shell|powershell|node|javascript|js|"
             r"typescript|sql|php|ruby|go)\s+)?")
#: What makes "fix the issue" about software: one of these later in the
#: same sentence.
_CODE_NEARBY = (r"(?:apps?|page|site(?!\s+visit)|website|web ?app|%s|feature|"
                r"button|login|signup|sign-up|checkout|css|html|component|"
                r"endpoint|api|server|database|deploy(?:ment)?|script|"
                r"function|build|frontend|backend)\b" % _SOURCE_CODE)

_CODE = re.compile(
    r"\b(?:refactor|debug|debugging)\b"
    # "implement the new expense policy" is not software.
    r"|\bimplement\b(?![^.?!\n]{0,30}\b(?:polic(?:y|ies)|plans?|"
    r"process(?:es)?|strateg(?:y|ies)|procedures?|rules?|guidelines?|"
    r"recommendations?|training|budget)\b)"
    r"|\b(?:write|generate)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|some\s+)?"
    + _LANGUAGE + r"(?:" + _SOURCE_CODE + r"|" + _SCRIPT + r"|function|"
    r"class|query|regex|tests?|component|endpoint|migration|"
    r"program(?=\s+(?:that|which|to|in)\b))\b"
    r"|\bfix\b[^.?!\n]{0,30}?\b(?:bugs?|" + _SOURCE_CODE + r"|build|tests?|"
    r"crash(?:es)?|page(?!\s+\d)|app|site(?!\s+visit)|website|feature)\b"
    # An error or an issue on its own is as often an invite or an invoice.
    r"|\bfix\b(?=[^.?!\n]{0,80}?\b" + _CODE_NEARBY + r")[^.?!\n]{0,30}?"
    r"\b(?:errors?|issues?|problems?)\b"
    r"|\badd\b[^.?!\n]{0,30}?\b(?:feature(?!\s+(?:story|stories|article|"
    r"piece|image|photo))|endpoint|component|function)\b"
    # "class" is left out: "change my yoga class to Friday" is a calendar
    # request, and the heavy_tool move still catches a class being changed.
    r"|\b(?:change|modify|edit|update|rewrite)\b[^.?!\n]{0,30}?\b(?:"
    + _SOURCE_CODE + r"|function|" + _SCRIPT + r"|component|css|html|"
    r"endpoint)\b"
    r"|\bapp builder\b")

#: The shape of an error, not the word: a traceback, a named error or
#: exception, a bare "Error:" only with something code shaped on its line, a
#: file:line or a stack frame, or a 5xx next to a path. Searched in the text
#: as typed, because an errno like ENOENT is told from a word by its case.
_ERROR = re.compile(
    r"traceback \(most recent call last\)"
    r"|\bstack ?trace\b"
    # TypeError:, KeyError:, java.io.IOException:. Terror is a word.
    r"|\b(?!terror\b)[a-z_][\w.$]{0,120}(?:error|exception)\b:"
    r"|\b(?:error|exception|fatal):[^\n]{0,200}?(?:(?-i:\bE[A-Z]{3,}\b)|"
    r"module '|'[\w-]{0,80}[./_@:][\w./@:-]{0,120}'|"
    r"\"[\w-]{0,80}[./_@:][\w./@:-]{0,120}\"|"
    r"\b\w{1,80}\(\)|\w\.(?:py|js|mjs|cjs|ts|tsx|jsx|json|java|go|rb|php|"
    r"cs|cpp|rs|html|css|sql|ya?ml)\b|\b0x[0-9a-f]+\b|\bundefined\b|"
    r"\bnull\b|\bnonetype\b)"
    r"|^[ \t]*at \S{1,200} \(\S{1,300}:\d+(?::\d+)?\)"
    r"|^[ \t]*at [\w.$<>]{1,300}\([\w.]{1,200}:\d+\)"
    # Only the name.ext:line end of a path: matching the whole path let
    # "a.a.a.a" try every dot, a second of CPU on a 50,000 character paste.
    r"|\w\.(?:py|js|mjs|cjs|ts|tsx|jsx|java|go|rb|php|cs|c|cpp|h|rs|kt|"
    r"swift|vue|svelte):\d+"
    r"|\bfile \"[^\"\n]{1,300}\", line \d+"
    r"|(?:^|\s)/[\w-][\w./-]{0,200}[^\n]{0,40}?\b5\d\d\b"
    r"|\b5\d\d\b[^\n]{0,40}?(?:^|\s)/[\w-]",
    re.MULTILINE | re.IGNORECASE)


def rule_reason(text: object) -> str | None:
    """Why this message needs the paid model, or None. Read from what the
    person typed, never from an instruction this service added."""
    raw = text if isinstance(text, str) else ""
    if not raw.strip():
        return None
    low = raw.lower()
    if "```" in raw:
        return REASON_CODE
    if _ERROR.search(raw):
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


def is_plain_question(text: object) -> bool:
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


def names_heavy_tool(calls: object) -> bool:
    for call in calls if isinstance(calls, list) else []:
        fn = call.get("function") if isinstance(call, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str) and name.strip() in HEAVY_TOOLS:
            return True
    return False


def conversation_chars(messages: object) -> int:
    total = 0
    for m in messages if isinstance(messages, list) else []:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(p.get("text") or "") for p in content
                         if isinstance(p, dict)
                         and isinstance(p.get("text"), str))
        # The arguments of a tool call are carried in every later round too,
        # and a file body handed to apply_app_change can be most of them.
        calls = m.get("tool_calls")
        for call in calls if isinstance(calls, list) else []:
            fn = call.get("function") if isinstance(call, dict) else None
            arguments = fn.get("arguments") if isinstance(fn, dict) else None
            if isinstance(arguments, str):
                total += len(arguments)
    return total


def too_long(messages: object) -> bool:
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


_current: contextvars.ContextVar[Intent | None] = contextvars.ContextVar(
    "agent_escalation_intent", default=None)


def current_intent() -> Intent | None:
    return _current.get()


@contextlib.contextmanager
def asking(intent: Intent) -> Iterator[Intent]:
    """Carry an intent to the turn beneath this call without changing the
    signature of everything in between. Reset on the way out, so it never
    leaks to the next agent in the room."""
    token = _current.set(intent)
    try:
        yield intent
    finally:
        _current.reset(token)


# --- sticky window ----------------------------------------------------------

_windows: dict[tuple[str, str], float] = {}


def _key(user_email: str | None, agent_id: str | None) -> tuple[str, str]:
    return ((user_email or "").strip().lower(), agent_id or "")


def mark_paid(user_email: str | None, agent_id: str | None,
              now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if len(_windows) > 500:
        for k in [k for k, until in _windows.items() if until <= now]:
            _windows.pop(k, None)
    _windows[_key(user_email, agent_id)] = now + STICKY_SECONDS


def in_window(user_email: str | None, agent_id: str | None,
              now: float | None = None) -> bool:
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

_noted: set[tuple[str, str]] = set()


def take_cap_note(user_email: str | None, today: str | None = None) -> str:
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
