"""What an agent remembers between conversations, the parts with no I/O.

The key, the recall block and the reflection parser are pure, so they are
tested directly. The store is tested against real Postgres in the container
(test_agent_memory_db.py) because a fake session would only prove what the
fake imagined.
"""
import json

import agent_memory as am


def test_the_key_collapses_case_punctuation_and_whitespace():
    a = am.memory_key("Prefers replies in Tagalog.")
    b = am.memory_key("  prefers   replies, in TAGALOG ")
    assert a == b == "prefers replies in tagalog"


def test_the_key_is_capped_so_a_long_note_still_dedups():
    assert len(am.memory_key("x" * 500)) == 120


def test_an_empty_store_renders_nothing():
    """Byte identical turns for agents with no memory: the block must be
    empty, not a heading over nothing."""
    assert am.render_recall([], []) == ""


def test_notes_come_first_then_facts_with_their_headings():
    out = am.render_recall(["Sends the digest at 7am Manila time."],
                           ["Client is called Northwind."])
    assert out.index("Your notes from earlier conversations") < out.index(
        "Known about this person")
    assert "- Sends the digest at 7am Manila time." in out
    assert "- Client is called Northwind." in out


def test_the_block_stays_inside_its_budget_and_keeps_the_newest():
    notes = ["note %d %s" % (i, "n" * 100) for i in range(40)]
    facts = ["fact %d %s" % (i, "f" * 100) for i in range(40)]
    out = am.render_recall(notes, facts)
    assert len(out) <= am.RECALL_BUDGET_CHARS
    # Newest first is the caller's order; the first note must survive.
    assert "note 0 " in out
    assert "fact 0 " in out


def test_the_parser_reads_json_wrapped_in_prose_and_fences():
    text = ('Here you go:\n```json\n{"notes": ["Did the weekly review."], '
            '"facts": ["Lives in Cebu."]}\n```')
    notes, facts = am.parse_reflection(text)
    assert notes == ["Did the weekly review."]
    assert facts == ["Lives in Cebu."]


def test_the_parser_drops_questions_pass_short_and_over_three():
    text = json.dumps({
        "notes": ["What does he want?", "PASS", "short", "Keeps Friday free.",
                  "Second real note here.", "Third real note here.",
                  "Fourth real note here."],
        "facts": [42, "", "Prefers short answers."]})
    notes, facts = am.parse_reflection(text)
    assert notes == ["Keeps Friday free.", "Second real note here.",
                     "Third real note here."]
    assert facts == ["Prefers short answers."]


def test_the_parser_caps_each_item_at_two_hundred_characters():
    notes, _ = am.parse_reflection(json.dumps({"notes": ["y" * 300]}))
    assert len(notes[0]) == 200


def test_garbage_parses_to_nothing():
    assert am.parse_reflection("no json here") == ([], [])
    assert am.parse_reflection("") == ([], [])


def test_should_reflect_needs_a_real_message_and_a_real_answer():
    assert am.should_reflect("Set the digest to 7am Manila time from now on.",
                             "Done, 7am Manila it is.")
    assert not am.should_reflect("hi", "Hello.")
    assert not am.should_reflect("Set the digest to 7am Manila time from now on.", "PASS")
    assert not am.should_reflect("Set the digest to 7am Manila time from now on.", "")
    assert not am.should_reflect(
        "Set the digest to 7am Manila time from now on.",
        "This agent is set to a model that cannot run an agent.")


def test_the_prompt_carries_what_is_already_known():
    prompt = am.reflection_prompt("Ada", ["Already knows this."],
                                  ["Client is Northwind."],
                                  "Move the digest to 7am.", "Done.")
    assert "Ada" in prompt
    assert "Already knows this." in prompt
    assert "Client is Northwind." in prompt
    assert "Move the digest to 7am." in prompt
    assert '{"notes": [], "facts": []}' in prompt
