# Just-Chat Intent Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make plain-English messages work — when a user types a normal sentence on Slack (mentions + DMs) or via `/aiui <text>` on Discord, the bot understands the intent and either builds the app (after one tap) or points them to the right tool, instead of giving a generic lecture.

**Architecture:** One shared brain (`handlers/intent_router.py`) with two pure functions and a thin model call. A pure card builder (`handlers/intent_cards.py`). The shared `CommandRouter` owns a pending-intent store and the "run a confirmed intent" logic. Two classify wiring points (the Discord/Slack `/aiui` fallthrough in `commands.py`, and the Slack message handlers in `slack.py`), and two confirm-button handlers (`discord_commands.py`, `slack_interactions.py`) that copy the existing schedule-confirm pattern. Everything behind an `INTENT_ROUTER` flag; off = today's behavior exactly.

**Tech Stack:** Python 3.13, FastAPI, pytest. LLM via `OpenWebUIClient.chat_completion(messages=, model=)`. Discord interactions API + Slack Events/Block-Kit. No new dependencies.

**v1 scope (faithful to the approved spec, sequenced):**
- `build_app`: full path — confirm card, then "Yes, do it" runs the real build with the typed description (reuses `run_panel_build`). This is the audit's #1 blocker ("build doesn't build").
- other actionable intents (`schedule_task`, `make_video`, `find_jobs`, `find_engineers`, `summarize_email`, `web_research`): recognized, and answered with a "suggest" message that names what was understood and shows the entry buttons. The classifier already returns the full intent set, so extending any of these to a full run later is a `decide()` + `run_confirmed_intent()` change only.
- `question` / low confidence: normal AI answer (unchanged).
- Task 9 (optional, in this plan) extends `schedule_task` to a full prefilled run.

**Run tests from** `webhook-handler/` so `from handlers import ...` resolves:
`cd webhook-handler && python -m pytest tests/<file> -v`

---

## File Structure

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `webhook-handler/handlers/intent_router.py` | Create | Pure `build_classify_messages`, `parse_classification`, `decide`; thin async `classify`. The brain. |
| `webhook-handler/handlers/intent_cards.py` | Create | Pure confirm/suggest card builders + the `aiuiintent:` button-id constants. |
| `webhook-handler/config.py` | Modify (~line 114) | Add the `INTENT_ROUTER` flag. |
| `webhook-handler/handlers/commands.py` | Modify (parse_command ~193; `__init__` ~161; `execute` ~233; new methods) | NATURAL fallthrough, pending store, `_handle_natural`, `run_confirmed_intent`, `answer_intent`, `park_intent`, `cancel_intent`. |
| `webhook-handler/handlers/discord_commands.py` | Modify (`_handle_message_component` ~256) | Route `aiuiintent:confirm/cancel:*` like the schedule-confirm buttons. |
| `webhook-handler/handlers/slack.py` | Modify (`__init__` ~16; `_handle_mention` ~81; `_handle_direct_message` ~143) | Classify a typed message; show the confirm/suggest card; hold a router ref. |
| `webhook-handler/handlers/slack_interactions.py` | Modify (`_handle_block_actions` ~142) | Route `aiuiintent:confirm/cancel:*` to the router. |
| `webhook-handler/main.py` | Modify (~line 173) | Give the Slack events handler the shared router. |
| `webhook-handler/tests/test_intent_router.py` | Create | Unit tests for the brain. |
| `webhook-handler/tests/test_intent_cards.py` | Create | Unit tests for the cards. |
| `webhook-handler/tests/test_intent_wiring.py` | Create | Wiring tests for `_handle_natural` + Slack classify. |
| `webhook-handler/tests/test_command_router.py` | Modify (line 27) | Update the fallthrough assertion to NATURAL. |

---

## Task 1: Config flag

**Files:**
- Modify: `webhook-handler/config.py:114` (after `discord_user_email_map_raw`)

- [ ] **Step 1: Add the flag field**

In `config.py`, inside `class Settings`, add after the `discord_user_email_map_raw` line (~114):

```python
    # Just-chat intent router. Off by default; flip with env INTENT_ROUTER=1.
    # Off = exactly today's behavior (plain text -> generic answer).
    intent_router_enabled: bool = Field(default=False, alias="INTENT_ROUTER")
```

- [ ] **Step 2: Verify it loads**

Run: `cd webhook-handler && python -c "from config import settings; print(settings.intent_router_enabled)"`
Expected: `False`

- [ ] **Step 3: Commit**

```bash
git add webhook-handler/config.py
git commit -m "feat(intent-router): add INTENT_ROUTER flag (default off)"
```

---

## Task 2: The brain — pure functions

**Files:**
- Create: `webhook-handler/handlers/intent_router.py`
- Test: `webhook-handler/tests/test_intent_router.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_intent_router.py`:

```python
from handlers import intent_router as ir


def test_build_classify_messages_has_system_and_user():
    msgs = ir.build_classify_messages("build me a form")
    assert msgs[0]["role"] == "system"
    assert "JSON" in msgs[0]["content"] or "json" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "build me a form"}


def test_parse_good_json():
    r = ir.parse_classification('{"intent":"build_app","confidence":0.9,"detail":"a form"}')
    assert (r.intent, r.detail) == ("build_app", "a form")
    assert r.confidence == 0.9


def test_parse_tolerates_code_fence_and_prose():
    raw = 'Sure!\n```json\n{"intent":"make_video","confidence":0.8,"detail":"x"}\n```'
    r = ir.parse_classification(raw)
    assert r.intent == "make_video"


def test_parse_unknown_intent_falls_back_to_question():
    r = ir.parse_classification('{"intent":"order_pizza","confidence":0.99}', fallback_detail="hi")
    assert r.intent == "question" and r.confidence == 0.0 and r.detail == "hi"


def test_parse_garbage_falls_back():
    r = ir.parse_classification("not json at all", fallback_detail="orig")
    assert r.intent == "question" and r.detail == "orig"


def test_parse_clamps_confidence():
    assert ir.parse_classification('{"intent":"build_app","confidence":5}').confidence == 1.0


def test_decide_question_is_answer():
    assert ir.decide(ir.IntentResult("question", 0.9, "x")).kind == "answer"


def test_decide_low_confidence_is_answer():
    assert ir.decide(ir.IntentResult("build_app", 0.3, "x")).kind == "answer"


def test_decide_build_is_confirm():
    a = ir.decide(ir.IntentResult("build_app", 0.8, "a form"))
    assert a.kind == "confirm" and a.intent == "build_app" and a.detail == "a form"


def test_decide_other_actionable_is_suggest():
    assert ir.decide(ir.IntentResult("make_video", 0.8, "x")).kind == "suggest"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_intent_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'handlers.intent_router'`

- [ ] **Step 3: Implement the module**

Create `webhook-handler/handlers/intent_router.py`:

```python
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
    "find_engineers", "summarize_email", "web_research", "question",
)


@dataclass
class IntentResult:
    intent: str
    confidence: float
    detail: str  # the request restated as a short instruction (carried forward)


@dataclass
class Action:
    kind: str  # "confirm" | "suggest" | "answer"
    intent: str
    detail: str


def build_classify_messages(text: str) -> list[dict]:
    """The classification prompt. Pure — no I/O."""
    system = (
        "You are an intent classifier for the AIUI assistant. Read the user's "
        "message and decide what they want. Reply with ONLY a JSON object, no "
        'prose: {"intent": <one of: ' + ", ".join(INTENTS) + ">, "
        '"confidence": <number 0..1>, "detail": <the request restated as a short '
        'instruction, no greeting>}. '
        "Guidance: build_app = make a website/app/form/landing page. "
        "schedule_task = anything recurring or time-based. make_video = a video. "
        "find_jobs = the user is job hunting. find_engineers = the user wants to "
        "hire. summarize_email = inbox/email. web_research = look something up. "
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
        return IntentResult(intent, conf, detail)
    except Exception:  # noqa: BLE001 - any malformed reply degrades to a question
        return IntentResult("question", 0.0, fallback_detail)


def decide(result: IntentResult, threshold: float = 0.6) -> Action:
    """Pure routing decision. build_app -> confirm (we run it, so ask first);
    other actionable intents -> suggest (point at the right tool); a plain
    question or anything below the confidence threshold -> answer."""
    if result.intent == "question" or result.confidence < threshold:
        return Action("answer", "question", result.detail)
    if result.intent == "build_app":
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd webhook-handler && python -m pytest tests/test_intent_router.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Add the async classify test**

Append to `tests/test_intent_router.py`:

```python
import pytest


class _FakeLLM:
    def __init__(self, reply): self._reply = reply
    async def chat_completion(self, messages, model): return self._reply


@pytest.mark.asyncio
async def test_classify_happy_path():
    llm = _FakeLLM('{"intent":"build_app","confidence":0.9,"detail":"a form"}')
    r = await ir.classify("build me a form", llm, "m")
    assert r.intent == "build_app"


@pytest.mark.asyncio
async def test_classify_empty_reply_is_question():
    r = await ir.classify("hi", _FakeLLM(""), "m")
    assert r.intent == "question"


class _BoomLLM:
    async def chat_completion(self, messages, model): raise RuntimeError("down")


@pytest.mark.asyncio
async def test_classify_model_error_is_question():
    r = await ir.classify("anything", _BoomLLM(), "m")
    assert r.intent == "question" and r.detail == "anything"
```

- [ ] **Step 6: Run the async tests**

Run: `cd webhook-handler && python -m pytest tests/test_intent_router.py -v`
Expected: PASS (13 passed). If you see "async def functions are not natively supported", confirm `pytest-asyncio` is installed (other async tests in this repo rely on it) and that `asyncio_mode = auto` is set, or keep the explicit `@pytest.mark.asyncio` markers above.

- [ ] **Step 7: Commit**

```bash
git add webhook-handler/handlers/intent_router.py webhook-handler/tests/test_intent_router.py
git commit -m "feat(intent-router): classify + decide brain (pure, tested)"
```

---

## Task 3: The confirm/suggest cards

**Files:**
- Create: `webhook-handler/handlers/intent_cards.py`
- Test: `webhook-handler/tests/test_intent_cards.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_intent_cards.py`:

```python
from handlers import intent_cards as ic


def test_confirm_components_discord_carry_token():
    comps = ic.confirm_components_discord("tok123")
    ids = [c["custom_id"] for c in comps[0]["components"]]
    assert ic.INTENT_CONFIRM_PREFIX + "tok123" in ids
    assert ic.INTENT_CANCEL_PREFIX + "tok123" in ids


def test_confirm_blocks_slack_carry_token():
    blocks = ic.confirm_blocks_slack("tok9", "Want me to build it?")
    actions = [b for b in blocks if b["type"] == "actions"][0]
    ids = [e["action_id"] for e in actions["elements"]]
    assert ic.INTENT_CONFIRM_PREFIX + "tok9" in ids
    assert ic.INTENT_CANCEL_PREFIX + "tok9" in ids


def test_confirm_line_names_build():
    assert "build" in ic.confirm_line("build_app", "a form").lower()


def test_suggest_line_names_the_intent():
    assert "video" in ic.suggest_line("make_video").lower()


def test_lines_handle_unknown_intent_gracefully():
    assert isinstance(ic.confirm_line("weird", ""), str)
    assert isinstance(ic.suggest_line("weird"), str)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_intent_cards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'handlers.intent_cards'`

- [ ] **Step 3: Implement the module**

Create `webhook-handler/handlers/intent_cards.py`:

```python
"""Confirm/suggest cards for the intent router. Pure builders, tested like
onboarding.py. Reuses the existing Discord/Slack button helpers so styling
stays consistent."""
from __future__ import annotations

from handlers.app_builder_panel import (
    ACTION_ROW, STYLE_SUCCESS, STYLE_PRIMARY, _button,
)
from handlers.slack_app_builder_panel import _button as _slack_button

INTENT_CONFIRM_PREFIX = "aiuiintent:confirm:"
INTENT_CANCEL_PREFIX = "aiuiintent:cancel:"

_VERB = {
    "build_app": "build a website",
    "schedule_task": "set up a scheduled task",
    "make_video": "make a video",
    "find_jobs": "find jobs for you",
    "find_engineers": "find engineers to hire",
    "summarize_email": "summarize your email",
    "web_research": "research that for you",
}


def confirm_line(intent: str, detail: str) -> str:
    return f"Sounds like you want me to {_VERB.get(intent, 'help with that')}. Want me to start?"


def suggest_line(intent: str) -> str:
    return (
        f"Sounds like you want me to {_VERB.get(intent, 'help with that')}. "
        "Tap a button below to start, or just ask me anything."
    )


def confirm_components_discord(token: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Yes, do it", INTENT_CONFIRM_PREFIX + token, STYLE_SUCCESS),
        _button("Just answer", INTENT_CANCEL_PREFIX + token, STYLE_PRIMARY),
    ]}]


def confirm_blocks_slack(token: str, line: str) -> list[dict]:
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": line}},
        {"type": "actions", "elements": [
            _slack_button("Yes, do it", INTENT_CONFIRM_PREFIX + token, primary=True),
            _slack_button("Just answer", INTENT_CANCEL_PREFIX + token),
        ]},
    ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd webhook-handler && python -m pytest tests/test_intent_cards.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/intent_cards.py webhook-handler/tests/test_intent_cards.py
git commit -m "feat(intent-router): confirm/suggest card builders (pure, tested)"
```

---

## Task 4: Router — pending store, NATURAL fallthrough, `_handle_natural`

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (imports top; `parse_command` ~193; `__init__` ~161; `execute` ~233; new methods)
- Modify: `webhook-handler/tests/test_command_router.py:27`
- Test: `webhook-handler/tests/test_intent_wiring.py`

- [ ] **Step 1: Update the existing fallthrough test (RED)**

In `webhook-handler/tests/test_command_router.py`, change the assertion at line 27:

```python
def test_unknown_text_becomes_natural_language():
    # Plain English (not a known subcommand, not "ask") routes to the intent
    # router via the NATURAL marker; with the flag off it still answers normally.
    assert CommandRouter.parse_command("what is MCP")[0] == "__natural__"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_command_router.py -v`
Expected: FAIL — currently returns `"ask"`, test wants `"__natural__"`.

- [ ] **Step 3: Add the NATURAL marker + change the fallthrough**

In `commands.py`, near the top-level constants (just above `class CommandRouter`), add:

```python
# Marker subcommand for plain-English input that matched no known command.
# Routed to the intent router in execute(); with the flag off it falls back to
# a normal /aiui ask answer, exactly as before.
NATURAL = "__natural__"
```

In `parse_command` (the final return, ~line 193), change:

```python
        # Unknown subcommand — treat entire text as an ask query
        return ("ask", text)
```
to:
```python
        # Unknown first word — plain English. Mark it NATURAL so execute() can
        # offer the intent router; falls back to a normal answer when the flag
        # is off (see _handle_natural).
        return (NATURAL, text)
```

- [ ] **Step 4: Run to verify the parse test passes**

Run: `cd webhook-handler && python -m pytest tests/test_command_router.py -v`
Expected: PASS

- [ ] **Step 5: Add imports, the pending store, and methods**

At the top of `commands.py`, ensure these imports exist (add any missing):

```python
import uuid
from handlers import intent_router, intent_cards
from config import settings
```

In `CommandRouter.__init__`, alongside `self._background_tasks: set = set()` (~line 161), add:

```python
        # token -> {"intent", "detail"} for a parked just-chat confirmation.
        self._pending_intents: dict[str, dict] = {}
```

In `execute()`, add a branch immediately before the final `else:` (the "Unknown command" arm, ~line 233):

```python
            elif ctx.subcommand == NATURAL:
                await self._handle_natural(ctx)
```

Add these methods to `CommandRouter` (place near `_handle_ask`):

```python
    async def _handle_natural(self, ctx: CommandContext) -> None:
        """Plain-English /aiui input. Flag off -> behave exactly like ask.
        Flag on -> classify and route: build_app -> a confirm card; other
        actionable intents -> a suggest message; question/unsure -> answer."""
        text = ctx.arguments or ctx.raw_text or ""
        ctx.arguments = text  # _handle_ask reads ctx.arguments
        if not settings.intent_router_enabled:
            await self._handle_ask(ctx)
            return
        result = await intent_router.classify(text, self.openwebui, self.ai_model)
        action = intent_router.decide(result)
        if action.kind == "answer":
            await self._handle_ask(ctx)
            return
        if action.kind == "confirm":
            token = self.park_intent(action.intent, action.detail)
            line = intent_cards.confirm_line(action.intent, action.detail)
            if ctx.respond_components:  # Discord can show buttons
                await ctx.respond_components(
                    line, intent_cards.confirm_components_discord(token))
            else:  # platform without components: answer normally instead
                await self._handle_ask(ctx)
            return
        # suggest
        await ctx.respond(intent_cards.suggest_line(action.intent))

    def park_intent(self, intent: str, detail: str) -> str:
        token = uuid.uuid4().hex[:16]
        self._pending_intents[token] = {"intent": intent, "detail": detail}
        return token

    def cancel_intent(self, token: str) -> None:
        self._pending_intents.pop(token, None)

    async def run_confirmed_intent(self, ctx: CommandContext, token: str) -> None:
        """The user tapped 'Yes, do it'. Build runs for real; other intents fall
        back to a suggest message (extended per-intent in later tasks)."""
        data = self._pending_intents.pop(token, None)
        if not data:
            await ctx.respond("That request expired — just type it again and I'll pick it up.")
            return
        if data["intent"] == "build_app":
            await self.run_panel_build(ctx, None, data["detail"])
            return
        await ctx.respond(intent_cards.suggest_line(data["intent"]))

    async def answer_intent(self, ctx: CommandContext, token: str) -> None:
        """The user tapped 'Just answer'. Answer their original text normally."""
        data = self._pending_intents.pop(token, None)
        ctx.arguments = (data or {}).get("detail", "") or ctx.arguments
        await self._handle_ask(ctx)
```

- [ ] **Step 6: Write wiring tests for `_handle_natural`**

Create `webhook-handler/tests/test_intent_wiring.py`. Mirror the router construction used in `tests/test_aiuibuilder_build.py` (same constructor args); the snippet below shows the shape — copy the exact `CommandRouter(...)` call from that file's fixture:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers import commands as cmd
from handlers import intent_router as ir
from handlers import intent_cards as ic


def _ctx(**kw):
    c = MagicMock()
    c.platform = kw.get("platform", "discord")
    c.raw_text = kw.get("text", "build me a form")
    c.arguments = kw.get("text", "build me a form")
    c.subcommand = cmd.NATURAL
    c.respond = AsyncMock()
    c.respond_components = AsyncMock()
    return c


def _router():
    r = cmd.CommandRouter(openwebui_client=MagicMock(), n8n_client=MagicMock(),
                          ai_model="m")  # copy the full arg list from test_aiuibuilder_build.py
    return r


@pytest.mark.asyncio
async def test_flag_off_falls_back_to_ask(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", False)
    r = _router()
    r._handle_ask = AsyncMock()
    await r._handle_natural(_ctx())
    r._handle_ask.assert_awaited_once()


@pytest.mark.asyncio
async def test_flag_on_build_shows_confirm_card(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "a form")))
    r = _router()
    ctx = _ctx()
    await r._handle_natural(ctx)
    ctx.respond_components.assert_awaited_once()
    assert len(r._pending_intents) == 1


@pytest.mark.asyncio
async def test_flag_on_question_answers(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "hi")))
    r = _router()
    r._handle_ask = AsyncMock()
    await r._handle_natural(_ctx(text="how are you"))
    r._handle_ask.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_confirmed_build_calls_run_panel_build(monkeypatch):
    r = _router()
    r.run_panel_build = AsyncMock()
    tok = r.park_intent("build_app", "a form")
    await r.run_confirmed_intent(_ctx(), tok)
    r.run_panel_build.assert_awaited_once()
    assert tok not in r._pending_intents


@pytest.mark.asyncio
async def test_run_confirmed_expired_token_is_graceful():
    r = _router()
    ctx = _ctx()
    await r.run_confirmed_intent(ctx, "nope")
    ctx.respond.assert_awaited_once()
```

- [ ] **Step 7: Run the wiring tests**

Run: `cd webhook-handler && python -m pytest tests/test_intent_wiring.py tests/test_command_router.py -v`
Expected: PASS. (If the router constructor needs more args, copy them verbatim from `tests/test_aiuibuilder_build.py`.)

- [ ] **Step 8: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_command_router.py webhook-handler/tests/test_intent_wiring.py
git commit -m "feat(intent-router): NATURAL fallthrough + router pending store + _handle_natural"
```

---

## Task 5: Discord confirm/cancel buttons

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (`_handle_message_component`, ~256, near the schedule-confirm branch at 325-333)

- [ ] **Step 1: Add the routing branch**

In `discord_commands.py`, import the constants at the top with the other handler imports:

```python
from handlers import intent_cards
```

In `_handle_message_component`, immediately after the `is_sched_cancel` block (line 333), add — copying the exact `_handle_panel_route(...)` call shape used by `is_sched_run` just below it:

```python
        if custom_id.startswith(intent_cards.INTENT_CONFIRM_PREFIX):
            token = custom_id[len(intent_cards.INTENT_CONFIRM_PREFIX):]
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_confirmed_intent(ctx, token),
                raw_text="intent confirm")
        if custom_id.startswith(intent_cards.INTENT_CANCEL_PREFIX):
            token = custom_id[len(intent_cards.INTENT_CANCEL_PREFIX):]
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.answer_intent(ctx, token),
                raw_text="intent answer")
```

> Note: `aiuiintent:` is a new, disjoint prefix — it cannot collide with `aiuibuild:`, `aiuisched:`, `aiuiout:`, `aiuivid:`, `aiuilink:`, or `cron`.

- [ ] **Step 2: Write the routing test**

Add to `webhook-handler/tests/test_app_builder_interactions.py` (it already builds a `DiscordCommandHandler` with a `MagicMock` router — reuse that fixture pattern):

```python
@pytest.mark.asyncio
async def test_intent_confirm_button_runs_confirmed_intent():
    from handlers import intent_cards
    discord = MagicMock()
    router = MagicMock()
    router.run_confirmed_intent = AsyncMock()
    handler = DiscordCommandHandler(discord_client=discord, command_router=router)
    payload = {"data": {"custom_id": intent_cards.INTENT_CONFIRM_PREFIX + "tok1"},
               "member": {"user": {"id": "100", "username": "x"}},
               "channel_id": "c", "token": "itok"}
    await handler._handle_message_component(payload)
    router.run_confirmed_intent.assert_awaited_once()
```

(Adjust the `payload` keys to match what other tests in this file pass to `_handle_message_component`; copy a working payload from an existing schedule-confirm test in the same file.)

- [ ] **Step 3: Run the test**

Run: `cd webhook-handler && python -m pytest tests/test_app_builder_interactions.py -k intent -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_app_builder_interactions.py
git commit -m "feat(intent-router): route Discord aiuiintent confirm/cancel buttons"
```

---

## Task 6: Slack — classify typed messages + hold a router ref

**Files:**
- Modify: `webhook-handler/handlers/slack.py` (`__init__` ~16; `_handle_mention` ~81; `_handle_direct_message` ~143)
- Modify: `webhook-handler/main.py` (~line 173)
- Test: `webhook-handler/tests/test_intent_wiring.py` (append)

- [ ] **Step 1: Give the Slack handler a router slot + classify helper**

In `slack.py`, add imports near the top:

```python
from handlers import intent_router, intent_cards
from config import settings
```

In `SlackWebhookHandler.__init__`, add a router slot (default None so existing construction keeps working):

```python
        self.router = None  # set in main.py to the shared CommandRouter
```

Add a private helper on the class (returns True if it handled the message as an intent, False to fall through to the generic answer):

```python
    async def _try_intent(self, text: str, channel: str, thread_ts=None) -> bool:
        """Flag-gated. build_app -> confirm card; other actionable -> suggest;
        question/unsure -> not handled (caller gives the normal answer)."""
        if not settings.intent_router_enabled or self.router is None:
            return False
        result = await intent_router.classify(text, self.openwebui, self.ai_model)
        action = intent_router.decide(result)
        if action.kind == "answer":
            return False
        if action.kind == "confirm":
            token = self.router.park_intent(action.intent, action.detail)
            line = intent_cards.confirm_line(action.intent, action.detail)
            await self.slack.post_message(
                channel=channel, text=line,
                blocks=intent_cards.confirm_blocks_slack(token, line),
                thread_ts=thread_ts)
            return True
        # suggest
        await self.slack.post_message(
            channel=channel, text=intent_cards.suggest_line(action.intent),
            thread_ts=thread_ts)
        return True
```

- [ ] **Step 2: Call it from both message handlers**

In `_handle_mention`, after the `looks_like_getting_started` block (line 88) and before building `system_prompt` (line 90), insert:

```python
        if await self._try_intent(clean_text, channel, thread_ts=thread_ts):
            return {"success": True, "message": "Intent handled"}
```

In `_handle_direct_message`, after the `looks_like_getting_started` block (line 149) and before building `system_prompt` (line 151), insert:

```python
        if await self._try_intent(text, channel):
            return {"success": True, "message": "Intent handled"}
```

- [ ] **Step 3: Wire the router in main.py**

In `main.py`, just after the `command_router = CommandRouter(...)` block (after line 173), add:

```python
    # Let the Slack events handler offer the intent router (it parks/builds via
    # the shared router). Mirrors how the Discord client is attached at ~line 196.
    if settings.slack_bot_token:
        slack_handler.router = command_router
```

- [ ] **Step 4: Write the Slack classify tests**

Append to `webhook-handler/tests/test_intent_wiring.py`:

```python
from handlers import slack as slackmod


def _slack_handler():
    h = slackmod.SlackWebhookHandler(openwebui_client=MagicMock(),
                                     slack_client=MagicMock(), ai_model="m")
    h.slack.post_message = AsyncMock()
    h.router = MagicMock()
    h.router.park_intent = MagicMock(return_value="tok")
    return h


@pytest.mark.asyncio
async def test_slack_try_intent_off_returns_false(monkeypatch):
    monkeypatch.setattr(slackmod.settings, "intent_router_enabled", False)
    h = _slack_handler()
    assert await h._try_intent("build me a form", "c") is False


@pytest.mark.asyncio
async def test_slack_try_intent_build_posts_confirm(monkeypatch):
    monkeypatch.setattr(slackmod.settings, "intent_router_enabled", True)
    monkeypatch.setattr(slackmod.intent_router, "classify",
                        AsyncMock(return_value=ir.IntentResult("build_app", 0.9, "a form")))
    h = _slack_handler()
    assert await h._try_intent("build me a form", "c") is True
    h.slack.post_message.assert_awaited_once()
    h.router.park_intent.assert_called_once()


@pytest.mark.asyncio
async def test_slack_try_intent_question_returns_false(monkeypatch):
    monkeypatch.setattr(slackmod.settings, "intent_router_enabled", True)
    monkeypatch.setattr(slackmod.intent_router, "classify",
                        AsyncMock(return_value=ir.IntentResult("question", 0.9, "hi")))
    h = _slack_handler()
    assert await h._try_intent("how are you", "c") is False
```

- [ ] **Step 5: Run the tests**

Run: `cd webhook-handler && python -m pytest tests/test_intent_wiring.py tests/test_slack_event_handler.py -v`
Expected: PASS (existing Slack event tests still green — the greeting path is untouched).

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/handlers/slack.py webhook-handler/main.py webhook-handler/tests/test_intent_wiring.py
git commit -m "feat(intent-router): classify typed Slack messages (mention + DM), wire router"
```

---

## Task 7: Slack confirm/cancel buttons

**Files:**
- Modify: `webhook-handler/handlers/slack_interactions.py` (`_handle_block_actions`, ~142)

- [ ] **Step 1: Add the routing branch**

In `slack_interactions.py`, add the import near the other handler imports:

```python
from handlers import intent_cards
```

In `_handle_block_actions`, after `action_id` is read (line 142), add a branch that builds a DM-targeted context the same way the modal-submit build path does (see `_dm_context` at line 683 and its use at line 782) and calls the router:

```python
        if action_id.startswith(intent_cards.INTENT_CONFIRM_PREFIX):
            token = action_id[len(intent_cards.INTENT_CONFIRM_PREFIX):]
            ctx = self._dm_context(payload, raw_text="intent confirm")
            await self.router.run_confirmed_intent(ctx, token)
            return {}
        if action_id.startswith(intent_cards.INTENT_CANCEL_PREFIX):
            token = action_id[len(intent_cards.INTENT_CANCEL_PREFIX):]
            ctx = self._dm_context(payload, raw_text="intent answer")
            await self.router.answer_intent(ctx, token)
            return {}
```

> Before writing this, read `_dm_context` (slack_interactions.py:683) and the build path at line 782 to confirm the exact argument names; match them precisely (the call above assumes `_dm_context(payload, raw_text=...)` like the build flow uses).

- [ ] **Step 2: Write the routing test**

Add to `webhook-handler/tests/test_slack_schedule_interactions.py` (or the nearest Slack-interactions test file; reuse its handler fixture):

```python
@pytest.mark.asyncio
async def test_slack_intent_confirm_runs_router(monkeypatch):
    from handlers import intent_cards
    handler = _make_handler()  # reuse this file's existing fixture
    handler.router.run_confirmed_intent = AsyncMock()
    payload = {"type": "block_actions",
               "actions": [{"action_id": intent_cards.INTENT_CONFIRM_PREFIX + "tok"}],
               "user": {"id": "U1"}, "channel": {"id": "C1"}}
    await handler._handle_block_actions(payload)
    handler.router.run_confirmed_intent.assert_awaited_once()
```

(Copy the exact `payload` shape and fixture from an existing schedule-action test in the same file so `_dm_context` gets the fields it expects.)

- [ ] **Step 3: Run the test**

Run: `cd webhook-handler && python -m pytest tests/test_slack_schedule_interactions.py -k intent -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_slack_schedule_interactions.py
git commit -m "feat(intent-router): route Slack aiuiintent confirm/cancel buttons"
```

---

## Task 8: Full-suite regression + flag-off safety

**Files:** none (verification only)

- [ ] **Step 1: Run the whole webhook-handler suite**

Run: `cd webhook-handler && python -m pytest -q`
Expected: all green. Pay attention to `test_command_router.py`, `test_onboarding.py`, `test_slack_event_handler.py`, `test_app_builder_interactions.py` — none of the existing behaviors should have changed.

- [ ] **Step 2: Confirm flag-off is a true no-op**

With `INTENT_ROUTER` unset (default False): `_handle_natural` calls `_handle_ask`, and `_try_intent` returns False so Slack gives the normal answer. Confirm by reading the two methods — there is no other code path that runs when the flag is off.

- [ ] **Step 3: Commit any test fixes**

```bash
git add -A
git commit -m "test(intent-router): full-suite regression green, flag-off no-op verified"
```

---

## Task 9 (optional, same plan): `schedule_task` full prefilled run

Bring schedule up to the same "full run" level as build, completing the spec's "build + schedule get a prefilled run."

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (`run_confirmed_intent`, `decide` usage)

- [ ] **Step 1:** Read how a schedule is created from free text — `discord_commands.py:_offer_schedule_confirm` (1476) and the schedule parser (`handlers/schedule_parse.py`). Decide the smallest reuse: feed `detail` to the parser to split "when" vs "what", then call the same create path the schedule confirm uses.
- [ ] **Step 2:** In `intent_router.decide`, move `schedule_task` from "suggest" to "confirm".
- [ ] **Step 3:** In `run_confirmed_intent`, add a `schedule_task` branch that creates the schedule from `detail` (reusing the existing create path), with a test using a fake parser.
- [ ] **Step 4:** Update `tests/test_intent_router.py::test_decide_other_actionable_is_suggest` to use a still-suggested intent (e.g. `make_video`), and add `test_decide_schedule_is_confirm`.
- [ ] **Step 5:** Run `cd webhook-handler && python -m pytest tests/test_intent_router.py tests/test_intent_wiring.py -v`; commit.

---

## Notes for the implementer

- **Do not** flip `INTENT_ROUTER` on in any committed compose/env file in this plan. Turning it on in production is a separate, explicit deploy step (and `.env` is never touched per repo rules).
- **Pending store is in-memory** (mirrors the existing `_pending_schedules`). A redeploy drops parked intents; the confirm handler already degrades gracefully ("that request expired"). Moving it to the DB is a known follow-up (audit #18), out of scope here.
- **Cost:** one small `chat_completion` per natural message. It reuses the configured `ai_model`; no new model or key.
- **Discord no-slash typing** (a gateway message listener) is intentionally out of scope (the user chose "Slack full + Discord slash").
- **Slack slash vs free text:** Slack *free text* (DM/@mention) gets the full confirm card — this is Slack's primary mode and is fully handled (Task 6). Slack *slash* `/aiui build...` goes through `execute()`, which has only a text `respond` callback (no block poster), so it falls back to a normal answer rather than a card. That is a safe, deliberate v1 behavior; wiring a Slack-blocks response into the slash path is a minor follow-up, not a bug.
- Full live end-to-end test (Playwright + real Discord/Slack) happens at the end, across all three sub-projects, per the user.
