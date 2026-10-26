"""Small Jev checks beside the team decider (agent_jev).

The answers the readers are tested against are real: one call made from the
tasks container on 2026-10-23 with a Choice, a Noul and a Score in it
(tests/fixtures/jev_real_2026_10_23.json, request and response verbatim).
"""
import asyncio
import json
import pathlib

import httpx
import pytest

import agent_jev as j

REAL = json.loads((pathlib.Path(__file__).parent / "fixtures"
                   / "jev_real_2026_10_23.json").read_text())["response"]


def _reply(qtype: str, **answer) -> dict:
    """A response shaped like REAL, holding one answer under id q."""
    return {"model": "jev-1.13.0",
            "answers": {"q": {"type": qtype, **answer}},
            "usage": {"input_tokens": 300, "output_tokens": 20}}


def _real(qid: str) -> dict:
    """REAL's answer to one question, moved under id q."""
    return {"model": REAL["model"], "answers": {"q": REAL["answers"][qid]},
            "usage": REAL["usage"]}


@pytest.fixture
def seams(monkeypatch):
    """A key, a stub Jev and a stub record. state["reply"] is what Jev
    answers; state["error"] is raised instead when set."""
    calls = {"post": [], "record": []}
    state = {"reply": None, "error": None}

    async def post(body, key):
        calls["post"].append((body, key))
        if state["error"] is not None:
            raise state["error"]
        return state["reply"]

    async def record(row):
        calls["record"].append(row)

    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    monkeypatch.delenv("JEV_MODEL", raising=False)
    monkeypatch.delenv("JEV_DAILY_CALLS", raising=False)
    monkeypatch.setattr(j, "_post", post)
    monkeypatch.setattr(j, "record", record)
    monkeypatch.setattr(j, "_calls", {"day": "", "n": 0})
    return calls, state


QUESTION = {"type": "noul", "instructions": "Is it raining?"}


# --- the core ---------------------------------------------------------------

async def test_no_key_means_no_call_and_no_record(seams, monkeypatch):
    calls, _ = seams
    monkeypatch.setenv("TYPESAFE_API_KEY", " ")
    assert await j.ask("p@example.com", "test", "state", QUESTION) is None
    assert calls == {"post": [], "record": []}


async def test_one_question_goes_to_the_pinned_model(seams):
    calls, state = seams
    state["reply"] = _real("noul_q")
    await j.ask("p@example.com", "test", "the state", QUESTION)
    body, key = calls["post"][0]
    assert key == "apikey_test"
    assert body == {"model": "jev-1.13.0", "state": "the state",
                    "questions": {"q": QUESTION}}


async def test_the_real_noul_is_read_as_its_probability(seams):
    _, state = seams
    state["reply"] = _real("noul_q")
    got = await j.ask("p@example.com", "test", "s", QUESTION)
    assert got.choice is None and got.value == 0.95
    assert got.model == "jev-1.13.0" and got.input_tokens == 448


async def test_the_real_choice_is_read_as_its_pick_and_confidence(seams):
    _, state = seams
    state["reply"] = _real("choice_q")
    got = await j.ask("p@example.com", "test", "s",
                      {"type": "choice", "instructions": "x",
                       "criteria": {"plain": "a", "work": "b"}})
    assert got.choice == "work" and got.value == 0.62


@pytest.mark.parametrize("reply", [
    None, {}, {"answers": {}}, _reply("noul", noul="high"),
    _reply("noul", noul=True), _reply("choice", choice=3, confidence=0.9),
    _reply("choice", choice="a", confidence=None), _reply("noul", noul=1.5)])
async def test_an_unreadable_answer_is_none(seams, reply):
    calls, state = seams
    state["reply"] = reply
    assert await j.ask("p@example.com", "test", "s", QUESTION) is None
    assert calls["record"][0]["reason"] == "unreadable answer"


@pytest.mark.parametrize("error,reason", [
    (httpx.ReadTimeout("slow"), "timeout"),
    (asyncio.TimeoutError(), "timeout"),
    (RuntimeError("HTTP 500"), "error: RuntimeError")])
async def test_a_slow_or_failing_jev_is_none(seams, error, reason):
    calls, state = seams
    state["error"] = error
    assert await j.ask("p@example.com", "test", "s", QUESTION) is None
    assert calls["record"][0]["reason"] == reason


async def test_the_daily_cap_stops_calls(seams, monkeypatch):
    calls, state = seams
    monkeypatch.setenv("JEV_DAILY_CALLS", "2")
    state["reply"] = _real("noul_q")
    for _ in range(3):
        await j.ask("p@example.com", "test", "s", QUESTION)
    assert len(calls["post"]) == 2
    assert calls["record"][-1]["reason"] == "daily cap"


async def test_the_row_holds_no_message_text(seams):
    calls, state = seams
    state["reply"] = _real("noul_q")
    await j.ask("p@example.com", "release", "my secret words", QUESTION)
    row = calls["record"][0]
    assert "secret" not in json.dumps(row, default=str)
    assert row["purpose"] == "release" and row["value"] == 0.95
    assert row["cost_usd"] == pytest.approx(448 * 0.042 / 1_000_000)


async def test_the_caller_can_say_what_it_did_with_the_answer(seams):
    calls, state = seams
    state["reply"] = _real("noul_q")
    await j.ask("p@example.com", "release", "s", QUESTION,
                outcome=lambda a: "released" if a.value >= 0.9 else "kept")
    assert calls["record"][0]["outcome"] == "released"


async def test_a_record_that_fails_still_returns_the_answer(seams,
                                                            monkeypatch):
    _, state = seams
    state["reply"] = _real("noul_q")

    async def broken(row):
        raise RuntimeError("db down")

    monkeypatch.setattr(j, "record", broken)
    got = await j.ask("p@example.com", "test", "s", QUESTION)
    assert got.value == 0.95


async def test_the_real_record_never_raises(monkeypatch):
    class Broken:
        async def __aenter__(self):
            raise RuntimeError("no database")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(j, "session", lambda: Broken())
    await j.record({"user_email": "p@example.com", "purpose": "test"})


# --- the paid move: plain question or the work in hand ----------------------

@pytest.mark.parametrize("reply,expected", [
    (_reply("choice", choice="plain", confidence=0.9), True),
    (_reply("choice", choice="work", confidence=0.9), False),
    (_real("choice_q"), False),         # work at 0.62, over the 0.6 cut
    (_reply("choice", choice="plain", confidence=0.59), None),
    (_reply("choice", choice="other", confidence=0.99), None),
])
async def test_plain_question(seams, reply, expected):
    calls, state = seams
    state["reply"] = reply
    assert await j.plain_question("p@example.com", "make it blue") is expected
    q = calls["post"][0][0]["questions"]["q"]
    assert q["type"] == "choice" and set(q["criteria"]) == {"plain", "work"}
    assert "make it blue" in calls["post"][0][0]["state"]
    assert calls["record"][0]["purpose"] == j.PURPOSE_PLAIN
    assert calls["record"][0]["outcome"] == {
        True: "plain", False: "work", None: "fallback"}[expected]


async def test_plain_question_with_no_key_is_none(seams, monkeypatch):
    calls, _ = seams
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    assert await j.plain_question("p@example.com", "make it blue") is None
    assert calls["post"] == []


# --- the reflection: is this turn worth remembering -------------------------

@pytest.mark.parametrize("noul,expected,outcome", [
    (0.1, False, "skip"), (0.3, False, "skip"), (0.31, None, "reflect"),
    (0.95, True, "reflect")])
async def test_worth_remembering(seams, noul, expected, outcome):
    calls, state = seams
    state["reply"] = _reply("noul", noul=noul)
    got = await j.worth_remembering("p@example.com", "my client is Northwind",
                                    "Noted.")
    assert got is expected
    body = calls["post"][0][0]
    assert body["questions"]["q"]["type"] == "noul"
    assert "my client is Northwind" in body["state"]
    assert "Noted." in body["state"]
    assert calls["record"][0]["purpose"] == j.PURPOSE_REFLECT
    assert calls["record"][0]["outcome"] == outcome


async def test_the_reflection_check_reads_a_bounded_exchange(seams):
    calls, state = seams
    state["reply"] = _reply("noul", noul=0.9)
    await j.worth_remembering("p@example.com", "a" * 9000, "b" * 9000)
    assert len(calls["post"][0][0]["state"]) < 3000


# --- the rollback: which version added the thing ----------------------------

VERSIONS = [{"sha": c * 40, "short_sha": c * 7, "message": m}
            for c, m in [("e", "add cart"), ("d", "add checkout"),
                         ("c", "style the header"), ("a", "Initial build")]]


async def test_rollback_version_offers_each_version_by_short_sha(seams):
    calls, state = seams
    state["reply"] = _reply("choice", choice="eeeeeee", confidence=0.9)
    got = await j.rollback_version("p@example.com",
                                   "go back to before the shopping basket",
                                   VERSIONS)
    assert got is VERSIONS[0]
    q = calls["post"][0][0]["questions"]["q"]
    assert q["type"] == "choice"
    assert q["criteria"] == {"eeeeeee": "add cart", "ddddddd": "add checkout",
                             "ccccccc": "style the header",
                             "aaaaaaa": "Initial build"}
    assert "shopping basket" in calls["post"][0][0]["state"]
    assert calls["record"][0]["outcome"] == "picked"


@pytest.mark.parametrize("reply", [
    _reply("choice", choice="eeeeeee", confidence=0.5),
    _reply("choice", choice="zzzzzzz", confidence=0.99)])
async def test_rollback_version_unsure_or_unknown_is_none(seams, reply):
    calls, state = seams
    state["reply"] = reply
    assert await j.rollback_version("p@example.com", "before the basket",
                                    VERSIONS) is None
    assert calls["record"][0]["outcome"] == "fallback"


async def test_rollback_version_reads_at_most_the_newest_twelve(seams):
    calls, state = seams
    many = [{"sha": f"{i:040x}", "short_sha": f"{i:07x}",
             "message": f"change {i}"} for i in range(30)]
    state["reply"] = _reply("choice", choice=f"{0:07x}", confidence=0.9)
    await j.rollback_version("p@example.com", "before change", many)
    assert len(calls["post"][0][0]["questions"]["q"]["criteria"]) == 12


async def test_rollback_version_needs_two_versions_to_choose_from(seams):
    calls, _ = seams
    assert await j.rollback_version("p@example.com", "before x",
                                    VERSIONS[:1]) is None
    assert calls["post"] == []


# --- the reply check: did the chosen agent answer ---------------------------

@pytest.mark.parametrize("noul,expected,outcome", [
    (0.05, False, "not answered"), (0.3, False, "not answered"),
    (0.5, None, "answered"), (0.9, True, "answered")])
async def test_reply_answers(seams, noul, expected, outcome):
    calls, state = seams
    state["reply"] = _reply("noul", noul=noul)
    got = await j.reply_answers("p@example.com", "how many apps do I have",
                                "You have 4 apps.")
    assert got is expected
    body = calls["post"][0][0]
    assert body["questions"]["q"]["type"] == "noul"
    assert "how many apps do I have" in body["state"]
    assert "You have 4 apps." in body["state"]
    assert calls["record"][0]["purpose"] == j.PURPOSE_REPLY
    assert calls["record"][0]["outcome"] == outcome


# --- release: is the person done with the agent -----------------------------

@pytest.mark.parametrize("noul,expected,outcome", [
    (0.95, True, "released"), (0.6, True, "released"),
    (0.59, False, "kept"), (0.1, False, "kept")])
async def test_wants_release(seams, noul, expected, outcome):
    calls, state = seams
    state["reply"] = _reply("noul", noul=noul)
    assert await j.wants_release("p@example.com", "ok I'm done") is expected
    body = calls["post"][0][0]
    assert body["questions"]["q"]["type"] == "noul"
    assert "ok I'm done" in body["state"]
    assert calls["record"][0]["purpose"] == j.PURPOSE_RELEASE
    assert calls["record"][0]["outcome"] == outcome


async def test_release_with_no_answer_keeps_the_agent(seams):
    _, state = seams
    state["error"] = RuntimeError("down")
    assert await j.wants_release("p@example.com", "ok I'm done") is None
