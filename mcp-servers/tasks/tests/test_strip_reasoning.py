"""A reasoning model's thinking never reaches a bubble (2026-10-17).

Seen on production with a free-pool model: paragraphs of "But wait, the
user is asking..." in Iris's answer, and once an empty bubble where the
answer should have been. The provider left the model's working inline.
"""
from agent_runner import strip_reasoning


def test_a_closed_think_block_is_dropped_wherever_it_sits():
    assert strip_reasoning("<think>hmm, what do they want</think>Thursday.") == "Thursday."
    assert strip_reasoning("Sure.<think>\nlet me check\n</think> Thursday.") == "Sure. Thursday."
    assert strip_reasoning("<THINKING>x</THINKING>\n\nDone.") == "Done."


def test_an_unclosed_tag_is_dropped_on_its_own():
    assert strip_reasoning("<think>\nI should say Thursday.") == "I should say Thursday."


def test_text_without_thinking_comes_back_as_it_was():
    assert strip_reasoning("I think Thursday.") == "I think Thursday."
    assert strip_reasoning("") == ""
    assert strip_reasoning(None) is None
