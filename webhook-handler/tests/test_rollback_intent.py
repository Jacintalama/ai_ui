"""The chat side of "go back to before it broke".

Two things are being pinned here:

1. The classifier can recognise the request and pull out WHICH app and WHICH
   point in time, without disturbing the intents that already work.
2. The model's answer is never trusted. Rollback mutates the user's app, so a
   model that names a version outside the candidate list must be rejected
   rather than acted on — the same class of mistake as the git-commit bug that
   silently broke history for 43 of 47 apps.
"""
import pytest

from handlers import intent_cards, intent_router
from handlers.intent_router import parse_classification, pick_from_candidates


def _cand(short, message):
    return {"sha": short + "0" * (40 - len(short)), "short_sha": short,
            "message": message, "date": "2026-08-01T14:22:00", "status": "ok"}


CANDIDATES = [
    _cand("d4d4d4d", "add checkout"),
    _cand("c3c3c3c", "style the header"),
    _cand("b2b2b2b", "add products page"),
]


# ---------------------------------------------------------------------------
# The intent exists and does not disturb what already works.
# ---------------------------------------------------------------------------

def test_rollback_app_is_a_known_intent():
    assert "rollback_app" in intent_router.INTENTS


def test_the_intents_that_already_shipped_are_untouched():
    for intent in ("build_app", "schedule_task", "make_video", "find_jobs",
                   "find_engineers", "summarize_email", "web_research",
                   "daily_briefing", "my_workspace", "question"):
        assert intent in intent_router.INTENTS


def test_rollback_does_not_ask_a_clarifying_question_first():
    """EXECUTABLE intents get a clarify round. Rollback must not: we resolve the
    target and show it, which IS the clarification, and it is a better one."""
    assert "rollback_app" not in intent_router.EXECUTABLE


def test_the_classifier_prompt_teaches_the_new_intent():
    system = intent_router.build_classify_messages("x")[0]["content"]
    assert "rollback_app" in system
    # Assert on the JSON KEYS. Plain "app" is a substring of build_app and
    # rollback_app, so it passed even with the whole field clause deleted.
    assert '"app":' in system and '"point":' in system, (
        "the prompt must ask for the two fields the resolver needs")


# ---------------------------------------------------------------------------
# Parsing: app + point come through.
# ---------------------------------------------------------------------------

def test_parse_extracts_the_app_and_the_point_in_time():
    raw = ('{"intent":"rollback_app","confidence":0.9,'
           '"detail":"roll back the shop app",ّ'
           '"app":"shop","point":"before the cart broke"}').replace("ّ", "")
    res = parse_classification(raw)
    assert res.intent == "rollback_app"
    assert res.app == "shop"
    assert res.point == "before the cart broke"


def test_app_and_point_default_to_empty_for_other_intents():
    raw = '{"intent":"build_app","confidence":0.9,"detail":"a shop"}'
    res = parse_classification(raw)
    assert res.app == "" and res.point == ""


def test_a_rollback_with_no_named_app_still_parses():
    raw = ('{"intent":"rollback_app","confidence":0.9,"detail":"undo that",'
           '"app":"","point":"before it broke"}')
    res = parse_classification(raw)
    assert res.intent == "rollback_app"
    assert res.app == ""
    assert res.point == "before it broke"


def test_a_malformed_reply_is_still_a_safe_question():
    assert parse_classification("not json at all").intent == "question"


# ---------------------------------------------------------------------------
# The model may only RANK. It may never invent.
# ---------------------------------------------------------------------------

def test_the_model_can_pick_one_of_the_real_candidates():
    assert pick_from_candidates('{"sha": "c3c3c3c"}', CANDIDATES)["short_sha"] == "c3c3c3c"


def test_a_one_or_two_character_sha_is_not_an_answer():
    """Review: `{"sha": "d"}` resolved to whichever candidate was newest, so a
    model that effectively shrugged still produced a definite pick. Git's own
    minimum unambiguous length is 7."""
    for shrug in ("d", "d4", "d4d", "d4d4d", "d4d4d4"):
        assert pick_from_candidates('{"sha": "%s"}' % shrug, CANDIDATES) is None, shrug


def test_a_prefix_matching_two_candidates_is_rejected_as_ambiguous():
    ambiguous = CANDIDATES + [_cand("d4d4d4dbeef", "a near-identical sha")]
    assert pick_from_candidates('{"sha": "d4d4d4d"}', ambiguous) is None


def test_a_sha_outside_the_candidate_list_is_refused():
    """The whole safety property. A hallucinated SHA that reached
    rollback_app_core would either error in the user's face or, worse, match
    some unrelated commit in the monorepo."""
    assert pick_from_candidates('{"sha": "deadbee"}', CANDIDATES) is None


def test_a_plausible_but_absent_sha_is_refused():
    assert pick_from_candidates('{"sha": "a1a1a1a"}', CANDIDATES) is None


def test_an_empty_or_garbled_model_reply_is_refused():
    for raw in ("", "   ", "I think you want the second one", "{}", "null"):
        assert pick_from_candidates(raw, CANDIDATES) is None, raw


def test_no_candidates_means_nothing_can_be_picked():
    assert pick_from_candidates('{"sha": "c3c3c3c"}', []) is None


def test_a_full_length_sha_matches_its_short_candidate():
    full = CANDIDATES[0]["sha"]
    assert pick_from_candidates('{"sha": "%s"}' % full, CANDIDATES)["short_sha"] == "d4d4d4d"


def test_the_returned_object_is_the_candidate_itself_not_a_copy():
    """Callers pass this straight to the rollback route; a reconstructed dict
    could drift from the real version entry."""
    got = pick_from_candidates('{"sha": "b2b2b2b"}', CANDIDATES)
    assert got is CANDIDATES[2]


# ---------------------------------------------------------------------------
# What the user is shown before they agree.
# ---------------------------------------------------------------------------

def test_the_confirm_names_the_app_the_version_and_the_reason():
    line = intent_cards.rollback_confirm_line(
        "shop", _cand("d4d4d4d", "add checkout"),
        "'add cart' failed — this is the last version that worked before it")
    assert "shop" in line
    assert "d4d4d4d" in line
    assert "add checkout" in line
    assert "add cart" in line, "the user must be able to check the reasoning"


def test_the_confirm_says_the_rollback_is_undoable():
    """rollback_app_core commits on top of HEAD rather than rewriting history,
    so this is true — and it is the difference between a scary button and a
    safe one."""
    line = intent_cards.rollback_confirm_line(
        "shop", _cand("d4d4d4d", "add checkout"), "some reason")
    assert "undo" in line.lower() or "still" in line.lower()


def test_the_confirm_never_claims_a_rollback_has_already_happened():
    line = intent_cards.rollback_confirm_line(
        "shop", _cand("d4d4d4d", "add checkout"), "some reason")
    lowered = line.lower()
    for past_tense in ("rolled back", "reverted", "restored it", "has been"):
        assert past_tense not in lowered, (
            f"{past_tense!r} implies it is already done; nothing has happened yet")


def test_the_intent_has_a_human_verb_for_the_generic_cards():
    assert "rollback_app" in intent_cards._VERB
    assert intent_cards._VERB["rollback_app"].strip()
