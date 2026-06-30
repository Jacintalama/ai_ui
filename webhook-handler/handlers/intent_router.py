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
    "question",
)


@dataclass
class IntentResult:
    intent: str
    confidence: float
    detail: str  # the request restated as a short instruction (carried forward)
    when: str = ""  # schedule_task only: the time/recurrence phrase ("every morning at 8am")
    task: str = ""  # schedule_task only: what to do ("summarize my emails")


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
        'schedule_task only: what to do, e.g. "summarize my emails"; else "">}. '
        "Guidance: build_app = make a website/app/form/landing page. "
        "schedule_task = anything recurring or time-based. make_video = a video. "
        "find_jobs = the user is job hunting. find_engineers = the user wants to "
        "hire. summarize_email = inbox/email. web_research = look something up. "
        "daily_briefing = a recurring morning summary/briefing/digest (prefer it "
        "over schedule_task when they ask for a daily briefing or morning update). "
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
        return IntentResult(intent, conf, detail, when=when, task=task)
    except Exception:  # noqa: BLE001 - any malformed reply degrades to a question
        return IntentResult("question", 0.0, fallback_detail)


def decide(result: IntentResult, threshold: float = 0.6) -> Action:
    """Pure routing decision. build_app -> confirm (we run it, so ask first);
    other actionable intents -> suggest (point at the right tool); a plain
    question or anything below the confidence threshold -> answer."""
    if result.intent == "question" or result.confidence < threshold:
        return Action("answer", "question", result.detail)
    if result.intent in ("build_app", "daily_briefing", "schedule_task"):
        return Action("confirm", result.intent, result.detail)
    return Action("suggest", result.intent, result.detail)


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
