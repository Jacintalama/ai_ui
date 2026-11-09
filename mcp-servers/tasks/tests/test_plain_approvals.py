"""Starting a build or a video is asked in a sentence (2026-11-09).

Live, the question was "This will run: create_app / description: Tip
calculator, single page: bill amount input ... number of people to s /
name: Tip Calculator": a tool's name and arguments, cut off at 120
characters, shown to somebody being asked to spend money on it.

Every word still comes from the call's own arguments, so the question
cannot describe something other than what will run.
"""
import json

import routes_agent_turn as rt

LONG = "A tip calculator, single page, with " + ("many fields and options, " * 12)


def call(tool, **args):
    return {"function": {"name": tool, "arguments": json.dumps(args)}}


def test_a_build_is_asked_as_a_sentence_with_the_whole_description():
    q = rt.approval_question("", [call("create_app", name="Tip Calculator",
                                       description=LONG)])
    assert q.startswith("Build this app?")
    assert "Tip Calculator" in q
    assert LONG.strip() in q, "the description was cut at the old limit"
    assert "create_app" not in q and "description:" not in q
    assert q.endswith("Reply yes to let it, or no to skip.")


def test_a_named_agent_says_it_is_the_one_asking():
    q = rt.approval_question("Dev", [call("create_app", name="Shop", description="A shop")])
    assert q.startswith("Dev wants to build this app.")


def test_a_video_names_the_site():
    q = rt.approval_question("", [call("make_video", url="https://example.com",
                                       title="Promo", description="Short")])
    assert q.startswith("Make a video of https://example.com?")
    assert "Promo" in q and "Short" in q
    assert "make_video" not in q


def test_a_video_with_only_an_address_is_still_a_sentence():
    q = rt.approval_question("", [call("make_video", url="https://example.com")])
    assert q == ("Make a video of https://example.com?\n\n"
                 "Reply yes to let it, or no to skip.")


def test_a_very_long_description_has_an_end():
    q = rt.approval_question("", [call("create_app", name="X", description="y" * 5000)])
    assert len(q) < 800


def test_a_call_with_no_address_or_description_shows_the_call_itself():
    """Nothing to make a sentence from, so nothing is invented."""
    q = rt.approval_question("", [call("make_video")])
    assert "make_video" in q
    q = rt.approval_question("", [call("create_app")])
    assert "create_app" in q


def test_two_calls_at_once_keep_the_full_list():
    """A sentence about one of them would hide the other."""
    q = rt.approval_question("", [call("create_app", name="A", description="b"),
                                  call("send_email", to="x@example.com")])
    assert "create_app" in q and "send_email" in q


def test_every_other_tool_is_asked_exactly_as_before():
    q = rt.approval_question("Vera", [call("send_email", to="x@example.com")])
    assert q == ("Vera wants to run:\n  send_email\n     to: x@example.com\n\n"
                 "Reply yes to let it, or no to skip.")
