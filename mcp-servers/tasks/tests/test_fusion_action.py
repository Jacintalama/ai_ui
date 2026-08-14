"""The Fuse action's answer collection.

The action file ships to Open WebUI, not to this service, but the one piece of
real logic in it is working out which answers belong to a turn. Open WebUI keeps
a multi-model turn as sibling assistant messages sharing a parentId, so getting
this wrong means fusing the wrong answers, or one answer against itself. That is
worth a test even though the file lives elsewhere.
"""
import importlib.util
import pathlib

import pytest

from conftest import repo_root_or_skip

ACTION_PATH = (repo_root_or_skip()
               / "open-webui-functions" / "fusion_action.py")


def _load():
    spec = importlib.util.spec_from_file_location("fusion_action", ACTION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def action():
    return _load().Action()


def test_action_file_exists():
    assert ACTION_PATH.is_file(), f"missing: {ACTION_PATH}"


def test_collects_sibling_answers_from_a_multi_model_turn(action):
    # The real Open WebUI shape: two assistant messages sharing one parentId.
    body = {
        "id": "a1",
        "messages": [
            {"id": "u1", "role": "user", "content": "what is the cap?"},
            {"id": "a1", "role": "assistant", "parentId": "u1",
             "model": "gpt-5.6-sol", "content": "32k"},
            {"id": "a2", "role": "assistant", "parentId": "u1",
             "model": "o4-mini", "content": "8k"},
        ],
    }
    question, answers = action._collect_answers(body, "a1")
    assert question == "what is the cap?"
    assert [(a["model"], a["content"]) for a in answers] == [
        ("gpt-5.6-sol", "32k"), ("o4-mini", "8k")]


def test_ignores_answers_from_a_different_turn(action):
    # Fusing this turn's answer against a previous turn's would be nonsense.
    body = {
        "id": "a3",
        "messages": [
            {"id": "u1", "role": "user", "content": "old question"},
            {"id": "a1", "role": "assistant", "parentId": "u1",
             "model": "gpt-5.5", "content": "old answer"},
            {"id": "u2", "role": "user", "content": "new question"},
            {"id": "a3", "role": "assistant", "parentId": "u2",
             "model": "gpt-5.5", "content": "new A"},
            {"id": "a4", "role": "assistant", "parentId": "u2",
             "model": "o4-mini", "content": "new B"},
        ],
    }
    question, answers = action._collect_answers(body, "a3")
    assert question == "new question"
    assert [a["content"] for a in answers] == ["new A", "new B"]
    assert "old answer" not in [a["content"] for a in answers]


def test_skips_an_empty_sibling(action):
    # A model that errored (as gpt-5.6-sol did on tool calls) leaves an empty
    # message. Feeding "" to the judge is noise at best.
    body = {
        "id": "a1",
        "messages": [
            {"id": "u1", "role": "user", "content": "q"},
            {"id": "a1", "role": "assistant", "parentId": "u1",
             "model": "gpt-5.5", "content": "real"},
            {"id": "a2", "role": "assistant", "parentId": "u1",
             "model": "broken", "content": "   "},
        ],
    }
    _, answers = action._collect_answers(body, "a1")
    assert [a["model"] for a in answers] == ["gpt-5.5"]


def test_single_model_turn_yields_one_answer(action):
    body = {
        "id": "a1",
        "messages": [
            {"id": "u1", "role": "user", "content": "q"},
            {"id": "a1", "role": "assistant", "parentId": "u1",
             "model": "gpt-5.5", "content": "only"},
        ],
    }
    question, answers = action._collect_answers(body, "a1")
    assert question == "q"
    assert len(answers) == 1


def test_falls_back_when_there_are_no_sibling_ids(action):
    # Not every payload carries ids/parentIds. Take the trailing assistant run
    # and the user turn that prompted it rather than returning nothing.
    body = {
        "id": "",
        "messages": [
            {"role": "user", "content": "flat question"},
            {"role": "assistant", "model": "gpt-5.5", "content": "A"},
            {"role": "assistant", "model": "o4-mini", "content": "B"},
        ],
    }
    question, answers = action._collect_answers(body, "")
    assert question == "flat question"
    assert [a["content"] for a in answers] == ["A", "B"]


def test_unnamed_model_does_not_crash(action):
    body = {
        "id": "a1",
        "messages": [
            {"id": "u1", "role": "user", "content": "q"},
            {"id": "a1", "role": "assistant", "parentId": "u1", "content": "x"},
        ],
    }
    _, answers = action._collect_answers(body, "a1")
    assert answers[0]["model"] == "a model"


def test_judge_dropdown_matches_the_registry():
    # A judge the registry does not know is a 400 at fuse time, which the user
    # would only find out after picking it.
    import typing

    import fusion_engine
    mod = _load()
    ids = set(typing.get_args(mod.JudgeId))
    assert ids == set(fusion_engine.PROVIDER_REGISTRY), (
        f"dropdown drifted: only-in-tool={ids - set(fusion_engine.PROVIDER_REGISTRY)}, "
        f"missing={set(fusion_engine.PROVIDER_REGISTRY) - ids}")


def test_default_judge_is_a_real_model():
    import fusion_engine
    mod = _load()
    assert mod.Action.UserValves().fuse_with in fusion_engine.PROVIDER_REGISTRY
