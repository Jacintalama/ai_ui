"""Pure tests for the pre-build clarifying questions backend (Task 4):
prompt/parse helpers, the answer-request shape, and the timeout helper.

No DB required; everything here is a pure function or a pydantic model.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from claude_executor import (
    build_prebuild_questions_prompt,
    parse_prebuild_questions,
    questions_timed_out,
)
from routes_aiuibuilder import BuildAnswerRequest, _compose_questions_answer_text


# ---------------------------------------------------------------------------
# build_prebuild_questions_prompt
# ---------------------------------------------------------------------------

def test_prompt_instructs_no_questions_when_clear():
    prompt = build_prebuild_questions_prompt("build a todo list app")
    assert "NO_QUESTIONS" in prompt
    assert "build a todo list app" in prompt


def test_prompt_describes_json_shape():
    prompt = build_prebuild_questions_prompt("build something")
    assert '"questions"' in prompt
    assert '"q"' in prompt
    assert '"options"' in prompt
    # Caps are spelled out for the model.
    assert "3" in prompt
    assert "100" in prompt


def test_prompt_forbids_prose():
    prompt = build_prebuild_questions_prompt("build something")
    assert "nothing else" in prompt.lower() or "only" in prompt.lower()


# ---------------------------------------------------------------------------
# parse_prebuild_questions
# ---------------------------------------------------------------------------

def test_parse_no_questions_returns_none():
    assert parse_prebuild_questions("NO_QUESTIONS") is None
    assert parse_prebuild_questions("  NO_QUESTIONS  \n") is None


def test_parse_empty_returns_none():
    assert parse_prebuild_questions("") is None
    assert parse_prebuild_questions(None) is None


def test_parse_garbage_returns_none():
    assert parse_prebuild_questions("sure, let me think about that...") is None
    assert parse_prebuild_questions("{not valid json") is None


def test_parse_valid_json_returns_list():
    payload = json.dumps({
        "questions": [
            {"q": "Which color scheme?", "options": ["Light", "Dark"]},
            {"q": "Who is this for?", "options": ["Personal", "Team", "Public"]},
        ]
    })
    result = parse_prebuild_questions(payload)
    assert result == [
        {"q": "Which color scheme?", "options": ["Light", "Dark"]},
        {"q": "Who is this for?", "options": ["Personal", "Team", "Public"]},
    ]


def test_parse_missing_questions_key_returns_none():
    assert parse_prebuild_questions(json.dumps({"foo": "bar"})) is None


def test_parse_five_questions_trimmed_to_three():
    payload = json.dumps({
        "questions": [
            {"q": f"Question {i}?", "options": ["A", "B"]} for i in range(5)
        ]
    })
    result = parse_prebuild_questions(payload)
    assert result is not None
    assert len(result) == 3
    assert [q["q"] for q in result] == ["Question 0?", "Question 1?", "Question 2?"]


def test_parse_drops_malformed_options():
    payload = json.dumps({
        "questions": [
            {"q": "Too few options?", "options": ["Only one"]},
            {"q": "Too many options?", "options": ["A", "B", "C", "D", "E"]},
            {"q": "Fine one?", "options": ["A", "B"]},
            {"q": "", "options": ["A", "B"]},  # empty q dropped
            {"q": "No options key?"},
        ]
    })
    result = parse_prebuild_questions(payload)
    assert result == [{"q": "Fine one?", "options": ["A", "B"]}]


def test_parse_all_malformed_returns_none():
    payload = json.dumps({
        "questions": [
            {"q": "Bad?", "options": ["Only one"]},
            {"q": "", "options": ["A", "B"]},
        ]
    })
    assert parse_prebuild_questions(payload) is None


def test_parse_tolerates_surrounding_whitespace_and_prose_wrapper():
    payload = "  " + json.dumps({"questions": [{"q": "Ok?", "options": ["Yes", "No"]}]}) + "  \n"
    result = parse_prebuild_questions(payload)
    assert result == [{"q": "Ok?", "options": ["Yes", "No"]}]


def test_parse_from_stream_json_log():
    # Mirrors the shape _stream_claude's log takes: newline-delimited JSON
    # events, with the final assistant text carrying the payload.
    inner = json.dumps({"questions": [{"q": "Which style?", "options": ["Fun", "Serious"]}]})
    log = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": inner}]},
        }),
    ])
    result = parse_prebuild_questions(log)
    assert result == [{"q": "Which style?", "options": ["Fun", "Serious"]}]


# ---------------------------------------------------------------------------
# BuildAnswerRequest - accepts both {answer} and {answers}
# ---------------------------------------------------------------------------

def test_answer_request_accepts_free_text_answer():
    body = BuildAnswerRequest(answer="use blue")
    assert body.answer == "use blue"
    assert body.answers is None


def test_answer_request_accepts_structured_answers():
    body = BuildAnswerRequest(answers=["Dark", "Team"])
    assert body.answers == ["Dark", "Team"]
    assert body.answer is None


def test_answer_request_accepts_empty_answers_list_as_skip():
    body = BuildAnswerRequest(answers=[])
    assert body.answers == []


def test_answer_request_accepts_skip_literal():
    body = BuildAnswerRequest(answer="__skip__")
    assert body.answer == "__skip__"


def test_answer_request_rejects_neither_form():
    with pytest.raises(Exception):
        BuildAnswerRequest()


# ---------------------------------------------------------------------------
# _compose_questions_answer_text
# ---------------------------------------------------------------------------

def test_compose_answer_text_pairs_questions_and_answers():
    stored = [{"q": "Which color?", "options": ["Light", "Dark"]}, {"q": "Who for?", "options": ["Me", "Team"]}]
    text = _compose_questions_answer_text(stored, ["Dark", "Team"])
    assert "User choices:" in text
    assert "- Which color? -> Dark" in text
    assert "- Who for? -> Team" in text


def test_compose_answer_text_skip_on_empty_list():
    text = _compose_questions_answer_text([{"q": "x", "options": ["a", "b"]}], [])
    assert "skipped" in text.lower()
    assert "sensible defaults" in text.lower()


def test_compose_answer_text_skip_on_none():
    text = _compose_questions_answer_text(None, None)
    assert "skipped" in text.lower()


# ---------------------------------------------------------------------------
# questions_timed_out
# ---------------------------------------------------------------------------

def test_questions_timed_out_none_asked_at_is_false():
    assert questions_timed_out(None, datetime.now(timezone.utc)) is False


def test_questions_timed_out_false_before_boundary():
    asked_at = datetime.now(timezone.utc) - timedelta(minutes=9, seconds=59)
    assert questions_timed_out(asked_at, datetime.now(timezone.utc)) is False


def test_questions_timed_out_true_at_boundary():
    now = datetime.now(timezone.utc)
    asked_at = now - timedelta(minutes=10)
    assert questions_timed_out(asked_at, now) is True


def test_questions_timed_out_true_well_past():
    now = datetime.now(timezone.utc)
    asked_at = now - timedelta(minutes=30)
    assert questions_timed_out(asked_at, now) is True


def test_questions_timed_out_respects_custom_minutes():
    now = datetime.now(timezone.utc)
    asked_at = now - timedelta(minutes=4, seconds=59)
    assert questions_timed_out(asked_at, now, minutes=5) is False
    asked_at = now - timedelta(minutes=5)
    assert questions_timed_out(asked_at, now, minutes=5) is True
