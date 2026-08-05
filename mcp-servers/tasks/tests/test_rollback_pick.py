"""Turning "go back to before it broke" into one specific version.

Lukas, standup 2026-08-03: "If I just tell the LLM go back to the working part
where we didn't start doing this feature that broke it, the LLM usually knows
where to go back to and does it."

The picker is pure on purpose. Rollback MUTATES the user's app, and this repo's
most expensive lesson is that a prompt is not a guarantee (the git-commit bug
silently broke history for 43 of 47 apps). So the decision is made by rules that
can be tested exhaustively with canned data, and the model — which sees no more
than these rules do — is only ever allowed to rank candidates the rules already
produced.

The load-bearing invariant, asserted throughout: a returned target is always an
element of the input list. The picker can never name a version that
does not exist.
"""
import pytest

from rollback_pick import choose_rollback_target


def v(sha, message, *, status="ok", is_current=False, date="2026-08-01T10:00:00"):
    """One version, shaped like routes_projects.VersionEntry."""
    return {
        "sha": sha * 8 if len(sha) < 8 else sha,
        "short_sha": (sha * 8)[:7] if len(sha) < 8 else sha[:7],
        "date": date,
        "author": "jacint",
        "message": message,
        "status": status,
        "is_current": is_current,
    }


# Newest first, the order git log returns and list_app_versions_core preserves.
BROKE = [
    v("e", "add cart", status="error", is_current=True, date="2026-08-02T09:00:00"),
    v("d", "add checkout", date="2026-08-01T14:22:00"),
    v("c", "style the header", date="2026-08-01T11:00:00"),
    v("b", "add products page", date="2026-07-31T16:00:00"),
    v("a", "Initial build", date="2026-07-31T09:00:00"),
]


# ---------------------------------------------------------------------------
# The sentence Lukas actually said.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "go back to before it broke",
    "go back to the working part where we didn't start doing this feature that broke it",
    "revert to when it worked",
    "take it back to before the error",
    "restore the last working version",
])
def test_before_it_broke_picks_the_last_good_version(phrase):
    """Deterministic: newest error is 'add cart', so the target is the newest
    ok version older than it."""
    choice = choose_rollback_target(BROKE, phrase)
    assert choice.target is not None, f"no target for {phrase!r}"
    assert choice.target["message"] == "add checkout"
    assert not choice.needs_user_choice


def test_before_it_broke_explains_itself_by_naming_the_failure():
    """The reason has to be checkable by the user, not 'trust me'."""
    choice = choose_rollback_target(BROKE, "go back to before it broke")
    assert "add cart" in choice.reason, (
        f"reason must name the failing version, got {choice.reason!r}")


def test_target_is_always_a_member_of_the_input_list():
    """The invariant. A fabricated SHA would be rolled back to and fail, or
    worse, succeed against something unintended."""
    choice = choose_rollback_target(BROKE, "go back to before it broke")
    assert any(x["sha"] == choice.target["sha"] for x in BROKE)


# ---------------------------------------------------------------------------
# "before the <thing>" — the feature is named instead of the failure.
# ---------------------------------------------------------------------------

def test_before_a_named_feature_picks_the_version_prior_to_it():
    choice = choose_rollback_target(BROKE, "go back to before the cart")
    assert choice.target["message"] == "add checkout"
    assert not choice.needs_user_choice


def test_before_a_named_feature_reason_quotes_that_feature():
    choice = choose_rollback_target(BROKE, "go back to before the cart")
    assert "add cart" in choice.reason


def test_named_feature_matches_case_insensitively():
    choice = choose_rollback_target(BROKE, "undo everything since the CHECKOUT")
    assert choice.target["message"] == "style the header"


def test_named_feature_wins_over_the_error_rule():
    """'before the checkout' must mean checkout, even though a later version
    failed. The user named something specific; honour it."""
    choice = choose_rollback_target(BROKE, "go back to before the checkout")
    assert choice.target["message"] == "style the header", (
        "the explicit feature name must beat the generic error rule")


def test_a_named_feature_nobody_recognises_does_not_silently_fall_through():
    """If the user names something that is not in the history, guessing via
    another rule would look like it worked. Ask instead."""
    choice = choose_rollback_target(BROKE, "go back to before the newsletter signup")
    assert choice.needs_user_choice
    assert choice.target is None


# ---------------------------------------------------------------------------
# An explicit SHA always wins.
# ---------------------------------------------------------------------------

def test_a_named_sha_is_used_verbatim():
    choice = choose_rollback_target(BROKE, f"roll back to {BROKE[3]['short_sha']}")
    assert choice.target["sha"] == BROKE[3]["sha"]
    assert not choice.needs_user_choice


def test_a_sha_that_is_not_in_this_apps_history_is_refused():
    """A real SHA from a DIFFERENT app must not be accepted here."""
    choice = choose_rollback_target(BROKE, "roll back to 9f9f9f9")
    assert choice.target is None
    assert choice.needs_user_choice


# ---------------------------------------------------------------------------
# "undo" / one step back.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", ["undo that", "one step back", "go back one version"])
def test_undo_steps_back_exactly_one_version(phrase):
    choice = choose_rollback_target(BROKE, phrase)
    assert choice.target["message"] == "add checkout"


def test_undo_with_only_one_version_has_nowhere_to_go():
    choice = choose_rollback_target([v("a", "Initial build", is_current=True)], "undo")
    assert choice.target is None
    assert "only" in choice.reason.lower() or "one" in choice.reason.lower()


# ---------------------------------------------------------------------------
# Nothing matched: show the list, never pick arbitrarily.
# ---------------------------------------------------------------------------

def test_an_unmatched_phrase_asks_instead_of_guessing():
    choice = choose_rollback_target(BROKE, "make it blue again")
    assert choice.target is None
    assert choice.needs_user_choice
    assert choice.candidates, "must hand back something to choose from"


def test_candidates_are_real_versions_from_the_list():
    choice = choose_rollback_target(BROKE, "make it blue again")
    shas = {x["sha"] for x in BROKE}
    assert all(c["sha"] in shas for c in choice.candidates)


def test_the_current_version_is_never_offered_as_a_rollback_target():
    """Rolling back to where you already are is a no-op dressed as an action."""
    choice = choose_rollback_target(BROKE, "make it blue again")
    assert all(not c.get("is_current") for c in choice.candidates)


# ---------------------------------------------------------------------------
# Degenerate histories: say so rather than inventing an answer.
# ---------------------------------------------------------------------------

def test_no_versions_at_all():
    choice = choose_rollback_target([], "go back to before it broke")
    assert choice.target is None
    assert choice.needs_user_choice is False, (
        "there is nothing to choose from, so this is a plain no, not a question")
    assert "no" in choice.reason.lower()


def test_before_it_broke_when_nothing_ever_broke():
    clean = [v("c", "style", is_current=True), v("b", "add page"), v("a", "Initial build")]
    choice = choose_rollback_target(clean, "go back to before it broke")
    assert choice.target is None
    assert choice.needs_user_choice, "offer the list rather than claiming a failure"


def test_every_version_failed_so_there_is_no_good_one():
    allbad = [
        v("c", "third try", status="error", is_current=True),
        v("b", "second try", status="error"),
        v("a", "first try", status="error"),
    ]
    choice = choose_rollback_target(allbad, "go back to before it broke")
    assert choice.target is None, "must not offer a version we know is broken"


def test_the_failure_is_the_oldest_version_so_nothing_precedes_it():
    oldest_broke = [
        v("b", "second", is_current=True),
        v("a", "Initial build", status="error"),
    ]
    choice = choose_rollback_target(oldest_broke, "go back to before it broke")
    assert choice.target is None


def test_a_rollback_commit_is_not_treated_as_a_feature_to_go_back_before():
    """Rollback commits are bookkeeping. Picking "before" one would walk the
    user backwards through their own undo history."""
    hist = [
        v("d", "Rollback apps/shop/ to bbbbbbb", status="rollback", is_current=True),
        v("c", "add cart", status="error"),
        v("b", "add checkout"),
        v("a", "Initial build"),
    ]
    choice = choose_rollback_target(hist, "go back to before it broke")
    assert choice.target["message"] == "add checkout"


def test_an_empty_phrase_asks_rather_than_defaulting():
    choice = choose_rollback_target(BROKE, "")
    assert choice.target is None
    assert choice.needs_user_choice


# ---------------------------------------------------------------------------
# The result must be safe to hand to rollback_app_core.
# ---------------------------------------------------------------------------

def test_chosen_sha_matches_the_shape_rollback_core_validates():
    """rollback_app_core rejects anything not [0-9a-f]{7,40}. A target it would
    reject means a confirm button that always errors."""
    import re
    choice = choose_rollback_target(BROKE, "go back to before it broke")
    assert re.fullmatch(r"[0-9a-f]{7,40}", choice.target["sha"])
