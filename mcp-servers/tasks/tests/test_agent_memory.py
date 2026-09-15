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


from unittest.mock import AsyncMock, patch


async def test_recall_fails_open_when_the_database_is_down():
    with patch.object(am, "list_notes", new=AsyncMock(side_effect=RuntimeError("db"))), \
         patch.object(am, "list_facts", new=AsyncMock(return_value=["a fact"])):
        out = await am.recall_block("o@example.com", "agent-1")
    assert out == ""


async def test_recall_renders_both_stores_newest_first():
    with patch.object(am, "list_notes", new=AsyncMock(return_value=[
            {"id": "n1", "content": "newest note"}, {"id": "n2", "content": "older note"}])), \
         patch.object(am, "list_facts", new=AsyncMock(return_value=["a fact"])):
        out = await am.recall_block("o@example.com", "agent-1")
    assert out.index("newest note") < out.index("older note")
    assert "a fact" in out


def test_one_oversized_note_does_not_hide_the_notes_behind_it():
    """A single note too big for the budget used to end the loop, so every
    shorter note after it was dropped as well."""
    out = am.render_recall(["L" * 1500, "Sends the digest at 7am.",
                            "Keeps Friday free."], ["Client is Northwind."])
    assert "Sends the digest at 7am." in out
    assert "Keeps Friday free." in out


def test_a_full_block_ends_on_a_whole_line():
    """The final cut to RECALL_BUDGET_CHARS must never land mid word: each
    section has to pay for its own heading out of its own budget."""
    notes = ["note %d %s" % (i, "n" * 100) for i in range(40)]
    facts = ["fact %d %s" % (i, "f" * 100) for i in range(40)]
    out = am.render_recall(notes, facts)
    last = out.splitlines()[-1]
    assert last.startswith("- ")
    assert last[2:] in facts


def test_the_key_folds_accents_so_one_note_is_one_row():
    assert (am.memory_key("senor garcia prefers Spanish")
            == am.memory_key("Se\xf1or Garc\xeda prefers Spanish"))


def test_a_note_in_another_script_still_has_a_key():
    """An ASCII only strip emptied the key, and an empty key is never
    stored, so notes in Cyrillic, Japanese or Arabic vanished silently."""
    assert am.memory_key("\u041a\u043b\u0438\u0435\u043d\u0442 \u0441\u0435\u0432\u0435\u0440") != ""


async def test_a_malformed_note_id_is_a_miss_not_a_crash():
    """Reached from a path parameter, so it must not need a database to
    reject a string that cannot be a row."""
    assert await am.delete_note("o@example.com", "agent-1", "not-a-uuid") is False


async def test_storing_notes_fails_open_when_the_database_is_down():
    with patch.object(am, "session", side_effect=RuntimeError("db")):
        assert await am.add_notes("o@example.com", "agent-1", ["a real note here"]) == 0


async def test_storing_facts_fails_open_when_the_database_is_down():
    with patch.object(am, "session", side_effect=RuntimeError("db")):
        assert await am.add_facts("o@example.com", ["a real fact here"]) == 0
