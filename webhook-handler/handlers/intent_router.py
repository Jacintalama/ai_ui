"""The just-chat brain: read a plain sentence -> an intent + a decision.

Two pure functions (build_classify_messages, parse_classification) plus a pure
decide(), and one thin async classify() that calls the model. The pure parts
carry the tests; classify() is a small wrapper. No platform/UI code here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

# Actionable intents the bot can route, plus the safe default "question".
INTENTS = (
    "build_app", "schedule_task", "make_video", "find_jobs",
    "find_engineers", "summarize_email", "web_research", "daily_briefing",
    "my_workspace", "rollback_app", "question",
)

# Intents the bot runs end-to-end from chat -> these get a clarify question first.
EXECUTABLE = ("build_app", "schedule_task")

# Actionable intents whose confirm opens a form (modal / studio) rather than
# running directly. The platform confirm handlers open these; everything else
# actionable runs on confirm.
FORM = ("make_video", "find_jobs", "find_engineers")

# What the bot is about to do, phrased for the clarify prompt.
_CLARIFY_VERB = {
    "build_app": "build a website or app",
    "schedule_task": "set up a recurring or scheduled task",
}

# Deterministic question used when the model call fails or returns nothing.
_CLARIFY_FALLBACK = {
    "build_app": "Happy to build it. What kind of site is it, and who's it for?",
    "schedule_task": "Sure. What should I do, and how often or when?",
}


@dataclass
class IntentResult:
    intent: str
    confidence: float
    detail: str  # the request restated as a short instruction (carried forward)
    when: str = ""  # schedule_task only: the time/recurrence phrase ("every morning at 8am")
    task: str = ""  # schedule_task only: what to do ("summarize my emails")
    app: str = ""    # rollback_app only: which app, if the user named one ("shop")
    point: str = ""  # rollback_app only: where to go back to ("before the cart broke")


@dataclass
class Action:
    kind: str  # "confirm" | "suggest" | "answer"
    intent: str
    detail: str


def build_classify_messages(text: str) -> list[dict]:
    """The classification prompt. Pure -- no I/O."""
    system = (
        "You are an intent classifier for the AIUI assistant. Read the user's "
        "message and decide what they want. Reply with ONLY a JSON object, no "
        'prose: {"intent": <one of: ' + ", ".join(INTENTS) + ">, "
        '"confidence": <number 0..1>, "detail": <the request restated as a short '
        'instruction, no greeting>, "when": <for schedule_task only: the time or '
        'recurrence phrase, e.g. "every morning at 8am"; else "">, "task": <for '
        'schedule_task only: what to do, e.g. "summarize my emails"; else "">, '
        '"app": <for rollback_app only: the app they named, e.g. "shop"; "" if '
        'they did not name one>, "point": <for rollback_app only: where to go '
        'back to, in their own words, e.g. "before the cart broke"; else "">}. '
        "Guidance: build_app = make a website/app/form/landing page. "
        "schedule_task = anything recurring or time-based. make_video = a video. "
        "find_jobs = the user is job hunting. find_engineers = the user wants to "
        "hire. summarize_email = inbox/email. web_research = look something up. "
        "daily_briefing = a recurring morning summary/briefing/digest (prefer it "
        "over schedule_task when they ask for a daily briefing or morning update). "
        "my_workspace = the user wants to see or manage their own stuff (their "
        "apps, schedules, videos; e.g. 'my workspace', 'my apps', 'what have I "
        "made', 'show my stuff'). "
        "rollback_app = undo a change to an app they already built and go back "
        "to an earlier version (e.g. 'go back to before the cart broke', 'undo "
        "that', 'revert the shop to when it worked'). Put their description of "
        'the point in time in "point" verbatim -- do not rephrase it. '
        'If it is just a question, small talk, or you are unsure, use "question" '
        "with a low confidence. Output JSON only."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text or ""},
    ]


def _extract_json(raw: str) -> str:
    """Pull the first {...} block out of a model reply (tolerate code fences)."""
    s = (raw or "").strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no json object")
    return s[start:end + 1]


def parse_classification(raw: str, fallback_detail: str = "") -> IntentResult:
    """Parse the model's JSON. Anything off -> a safe 'question' result."""
    try:
        data = json.loads(_extract_json(raw))
        intent = str(data.get("intent", "")).strip()
        if intent not in INTENTS:
            return IntentResult("question", 0.0, fallback_detail)
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        detail = str(data.get("detail") or fallback_detail).strip()
        when = str(data.get("when") or "").strip()
        task = str(data.get("task") or "").strip()
        app = str(data.get("app") or "").strip()
        point = str(data.get("point") or "").strip()
        return IntentResult(intent, conf, detail, when=when, task=task,
                            app=app, point=point)
    except Exception:  # noqa: BLE001 - any malformed reply degrades to a question
        return IntentResult("question", 0.0, fallback_detail)


def build_rollback_pick_messages(phrase: str, candidates: list[dict]) -> list[dict]:
    """Ask the model to choose among versions that ALREADY EXIST. Pure -- no I/O.

    The list is supplied in the prompt and the answer is validated against it by
    pick_from_candidates, so the model's job is ranking, never naming. It has no
    information the deterministic rules lack (same messages, same dates); its
    only edge is paraphrase -- matching "the checkout thing" to "add payment
    flow" -- which is exactly what a keyword rule cannot do.
    """
    listing = "\n".join(
        f"- {c.get('short_sha', '')}  {c.get('message', '')}  ({c.get('date', '')})"
        for c in candidates
    )
    system = (
        "The user wants to roll an app back to an earlier version. Below are the "
        "ONLY versions that exist. Pick the single one they mean.\n\n"
        f"{listing}\n\n"
        'Reply with ONLY a JSON object: {"sha": "<the short sha of your pick>"}. '
        "You must copy a sha from the list exactly. If none of them clearly "
        'match what the user said, reply {"sha": ""}.'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": phrase or ""},
    ]


def pick_from_candidates(raw: str, candidates: list[dict]) -> dict | None:
    """Validate a model's pick against the real list. Pure -- no I/O.

    Returns the candidate OBJECT (not a copy, not a reconstruction) or None.
    None means "the model did not give us a usable answer" and the caller must
    fall back to showing the list -- never to picking something itself.

    This is the safety boundary. Rollback mutates the user's app, and a
    hallucinated sha would either error in the user's face or, worse, match an
    unrelated commit elsewhere in the monorepo.
    """
    if not candidates:
        return None
    try:
        data = json.loads(_extract_json(raw))
    except Exception:  # noqa: BLE001 - any malformed reply -> no pick
        return None
    if not isinstance(data, dict):
        return None
    sha = str(data.get("sha") or "").strip().lower()
    # A short prefix is not an answer. Review showed `{"sha": "d"}` resolved to
    # whichever candidate happened to be newest, so a model that effectively
    # shrugged still produced a definite pick. Git's own minimum is 7.
    if len(sha) < 7:
        return None
    hits = [c for c in candidates
            if str(c.get("sha", "")).lower().startswith(sha)
            or sha.startswith(str(c.get("short_sha", "")).lower() or "\0")]
    # Ambiguity is not a decision either: two candidates sharing a prefix means
    # we do not know which was meant.
    return hits[0] if len(hits) == 1 else None


def build_clarify_messages(intent: str, text: str) -> list[dict]:
    """Prompt the model for ONE short, specific clarifying question. Pure -- no I/O."""
    verb = _CLARIFY_VERB.get(intent, "help with that")
    system = (
        "You are AIUI, a sharp, warm assistant. The user wants you to " + verb + ". "
        "Read their message and reply with ONE short, specific question that gets the "
        "single most important missing detail so you can do it well. If they already "
        "gave plenty of detail, ask a brief 'Anything you'd like to add before I "
        "start?'. Reply with ONLY the question -- one friendly sentence, no preamble, "
        "no lists, no quotes."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text or ""},
    ]


def parse_clarify(raw: str, intent: str) -> str:
    """First non-empty line of the model reply, quotes stripped; else the fallback."""
    for line in (raw or "").splitlines():
        line = line.strip().strip('"').strip("'").strip()
        if line:
            return line
    return _CLARIFY_FALLBACK.get(intent, "Could you tell me a bit more?")


async def clarify_question(intent: str, text: str, openwebui, model: str) -> str:
    """Thin wrapper: build -> model -> parse. Never raises; falls back on failure."""
    try:
        raw = await openwebui.chat_completion(
            messages=build_clarify_messages(intent, text), model=model,
        )
    except Exception:  # noqa: BLE001 - model/network failure -> deterministic fallback
        return _CLARIFY_FALLBACK.get(intent, "Could you tell me a bit more?")
    if not raw:
        return _CLARIFY_FALLBACK.get(intent, "Could you tell me a bit more?")
    return parse_clarify(raw, intent)


def decide(result: IntentResult, threshold: float = 0.6) -> Action:
    """Pure routing decision. A plain question or anything below the confidence
    threshold -> answer. Every actionable intent -> confirm (a real button):
    build/schedule are clarified first, the rest run or open their form on Yes."""
    if result.intent == "question" or result.confidence < threshold:
        return Action("answer", "question", result.detail)
    return Action("confirm", result.intent, result.detail)


async def classify(text: str, openwebui, model: str) -> IntentResult:
    """Thin wrapper: build messages -> model -> parse. Never raises."""
    try:
        raw = await openwebui.chat_completion(
            messages=build_classify_messages(text), model=model,
        )
    except Exception:  # noqa: BLE001 - model/network failure -> safe default
        return IntentResult("question", 0.0, text or "")
    if not raw:
        return IntentResult("question", 0.0, text or "")
    return parse_classification(raw, fallback_detail=text or "")
