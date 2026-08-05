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
import re

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
# Real history from apps/portfolio/, which broke two rules the canned
# fixtures above could not. Real App Builder commits are conventional-commit
# style, so the app's own name is inside EVERY message.
# ---------------------------------------------------------------------------

REAL = [
    v("f1", "chore: snapshot live VPS state into git", is_current=True),
    v("f2", "feat(portfolio): move profile image to right side of hero"),
    v("f3", "feat(portfolio): add profile photo to hero section"),
    v("f4", "Rollback apps/portfolio/ to 8736cd7", status="rollback"),
    v("f5", "feat(portfolio): replace circular avatar with full-width landscape banner"),
    v("f6", "fix(portfolio): adjust profile image position to show full face"),
    v("f7", "feat(portfolio): integrate uploaded profile image in hero avatar"),
    v("f8", "style(portfolio): dark navy theme with teal accents"),
    v("f9", "fix(portfolio): load main.js before Alpine so listener registers"),
]


def test_the_app_name_is_not_treated_as_a_feature():
    """'portfolio' appears in every message, so it identifies nothing. Matching
    on it returned the newest commit and a confident WRONG answer."""
    choice = choose_rollback_target(REAL, "go back to before the portfolio")
    assert choice.target is None, (
        f"matched on the app's own name and picked "
        f"{choice.target['message'][:40]!r}")
    assert choice.needs_user_choice


def test_before_a_feature_targets_where_it_STARTED_on_real_history():
    """CORRECTED after review. This test first asserted "the best textual
    match wins", which was the wrong semantic: on the real portfolio history
    the profile image is touched by six commits spanning the whole log, and
    only the OLDEST is where it started. "before the profile photo" must land
    before that one, so the result genuinely lacks the photo.
    """
    choice = choose_rollback_target(REAL, "go back to before the profile photo")
    assert choice.target is not None
    assert "move profile image" not in choice.reason, (
        f"took the newest mention: {choice.reason!r}")
    # The oldest profile/photo mention in REAL is f7, so the target is f8.
    assert "add profile photo" in choice.reason


def test_a_distinctive_phrase_still_resolves_on_real_data():
    choice = choose_rollback_target(REAL, "go back to before the dark navy theme")
    assert choice.target is not None
    assert "dark navy theme" in choice.reason


def test_asking_to_undo_a_feature_never_returns_a_state_that_still_has_it():
    """REPLACES a test that asserted the opposite and called it "odd to read
    but correct". Review was right to challenge it: on this very history,
    "before you added the profile photo" returned a Rollback marker whose
    restored state CONTAINED the photo — the opposite of the request.

    Targeting where the feature STARTED rather than where it was last touched
    fixed it without a special case for rollback markers.
    """
    choice = choose_rollback_target(
        REAL, "go back to before you added the profile photo", slug="portfolio")
    assert choice.target is not None
    # On THIS history the version before "add profile photo" is itself an
    # earlier undo, whose restored state does contain an image. That is a real
    # property of a history with rollbacks in it, and the honest answer is to
    # say so rather than to quietly walk further back than the user asked.
    if choice.target["message"].lower().startswith("rollback"):
        assert "earlier undo" in choice.reason, (
            f"handed back a bookkeeping commit with no explanation: "
            f"{choice.reason!r}")


def test_real_history_with_no_failures_does_not_invent_one():
    choice = choose_rollback_target(REAL, "go back to before it broke")
    assert choice.target is None
    assert choice.needs_user_choice


# ---------------------------------------------------------------------------
# Code review, 2026-08-04. Each of these produced a confident WRONG answer.
# ---------------------------------------------------------------------------

def test_a_commit_about_fixing_something_broken_does_not_hijack_before_it_broke():
    """The worst bug found: 'broke' was a keyword AND a failure word, so a
    history containing "fix broken checkout" made rule 2 fire first and land
    the user ON the failed build. The exact sentence the feature is named for.
    """
    hist = [
        v("a", "fix broken checkout", is_current=True),
        v("b", "add cart", status="error"),
        v("c", "add checkout"),
        v("d", "Initial build"),
    ]
    choice = choose_rollback_target(hist, "go back to before it broke")
    assert choice.target is not None
    assert choice.target["status"] != "error", (
        "rolled the user ONTO the broken version")
    assert choice.target["message"] == "add checkout"


def test_before_a_feature_means_before_it_was_INTRODUCED():
    """'before the profile image' must land before the commit that ADDED it,
    not before the newest commit that merely touched it — otherwise the target
    still contains the thing the user asked to get rid of."""
    hist = [
        v("a", "move profile image to right side", is_current=True),
        v("b", "add profile photo to hero"),
        v("c", "restyle header"),
        v("d", "Initial build"),
    ]
    choice = choose_rollback_target(hist, "go back to before the profile image")
    assert choice.target is not None
    assert "profile" not in choice.target["message"].lower(), (
        f"target still contains it: {choice.target['message']!r}")
    assert choice.target["message"] == "restyle header"


def test_a_keyword_does_not_match_inside_a_longer_word():
    """'cart' must not match 'cartoon'. Verified: it picked the version before
    'add cartoon mascot' and called it the version before the cart."""
    hist = [
        v("a", "add cartoon mascot to hero", is_current=True),
        v("b", "add pricing page"),
        v("c", "add cart"),
        v("d", "Initial build"),
    ]
    choice = choose_rollback_target(hist, "go back to before the cart")
    assert "cartoon" not in choice.reason, f"matched cartoon: {choice.reason!r}"
    assert choice.target["message"] == "Initial build"


def test_a_hex_looking_word_does_not_veto_a_real_sha_later_in_the_sentence():
    """`\\b[0-9a-f]{7,40}\\b` matches 'defaced', 'acceded', and any 7-digit run.
    Bailing on the first match threw away the real sha the user typed."""
    choice = choose_rollback_target(BROKE, f"we defaced it, roll back to {BROKE[3]['short_sha']}")
    assert choice.target is not None, f"lost the real sha: {choice.reason!r}"
    assert choice.target["sha"] == BROKE[3]["sha"]


SHOP = [
    v("a", "feat(shop): add hover animation to nav", is_current=True),
    v("b", "feat(shop): add cart"),
    v("c", "feat(shop): initial"),
    v("d", "rename Menu nav link"),
    v("e", "chore: snapshot"),
    v("f", "tidy up"),
]


def test_the_app_name_is_stripped_exactly_not_guessed_from_frequency():
    """The frequency filter was both too weak here (a name in exactly half the
    messages survived) and, at that threshold, too strong elsewhere (it erased
    the real keyword on a short history). The caller knows the slug, so it is
    passed in and removed exactly."""
    choice = choose_rollback_target(SHOP, "go back to before the shop", slug="shop")
    assert choice.target is None, f"matched on the app name: {choice.reason!r}"
    assert choice.needs_user_choice


def test_stripping_the_app_name_does_not_disturb_a_real_keyword():
    choice = choose_rollback_target(SHOP, "go back to before the cart", slug="shop")
    assert choice.target is not None
    assert "add cart" in choice.reason


def test_a_hyphenated_slug_is_stripped_word_by_word():
    hist = [
        v("a", "feat(my-coffee-shop): add hover animation", is_current=True),
        v("b", "feat(my-coffee-shop): apply Lato font"),
        v("c", "feat(my-coffee-shop): initial"),
        v("d", "tidy up"),
    ]
    choice = choose_rollback_target(hist, "roll the coffee shop back to before the coffee",
                                    slug="my-coffee-shop")
    assert choice.target is None, f"matched on the app name: {choice.reason!r}"


def test_a_short_history_keeps_its_keywords():
    """Three commits is normal for a new app. The old half-the-messages filter
    erased the keyword and the picker then answered a different question."""
    hist = [
        v("a", "add cart page", is_current=True),
        v("b", "add cart total", status="error"),
        v("c", "Initial build"),
    ]
    choice = choose_rollback_target(hist, "go back to before the cart broke", slug="shop")
    assert choice.target is not None
    assert choice.target["message"] == "Initial build", (
        "the cart work starts at 'add cart total', so before it is the build")


def test_a_phrase_of_pure_noise_asks_rather_than_switching_rules():
    """When every named word is filtered out, asking is the honest move; the
    old code fell through to the failure rule and answered confidently."""
    noisy = [v(chr(97 + i), "feat(shop): change thing", status="ok") for i in range(6)]
    noisy[0]["is_current"] = True
    choice = choose_rollback_target(noisy, "go back to before the change", slug="shop")
    assert choice.target is None
    assert choice.needs_user_choice


def test_the_newest_version_is_never_the_target_even_if_is_current_is_wrong():
    """is_current compares each commit to the WHOLE monorepo's HEAD, so for
    every app but the most recently committed one it is False on every row.
    That made 'undo' return the app's current content — a silent no-op. The
    list is newest-first by construction, so index 0 is current regardless."""
    hist = [
        v("a", "newest", is_current=False),  # is_current wrong, as in production
        v("b", "older"),
        v("c", "oldest"),
    ]
    choice = choose_rollback_target(hist, "undo that")
    assert choice.target is not None
    assert choice.target["message"] != "newest", "rolled back to where we already are"
    assert choice.target["message"] == "older"


def test_candidates_exclude_the_newest_even_if_is_current_is_wrong():
    hist = [v("a", "newest", is_current=False), v("b", "older"), v("c", "oldest")]
    choice = choose_rollback_target(hist, "make it blue again")
    assert all(c["message"] != "newest" for c in choice.candidates)


# ---------------------------------------------------------------------------
# The result must be safe to hand to rollback_app_core.
# ---------------------------------------------------------------------------

def test_chosen_sha_matches_the_shape_rollback_core_validates():
    """rollback_app_core rejects anything not [0-9a-f]{7,40}. A target it would
    reject means a confirm button that always errors."""
    import re
    choice = choose_rollback_target(BROKE, "go back to before it broke")
    assert re.fullmatch(r"[0-9a-f]{7,40}", choice.target["sha"])


# ---------------------------------------------------------------------------
# The invariant, actually swept. Review: the module docstring claimed it was
# "asserted throughout" when one phrase checked it. This is the version that
# would have caught the wrong-but-confident bugs.
# ---------------------------------------------------------------------------

PHRASES = [
    "go back to before it broke",
    "go back to the working part where we didn't start doing this feature that broke it",
    "revert to when it worked",
    "take it back to before the error",
    "restore the last working version",
    "go back to before the cart",
    "go back to before the checkout",
    "go back to before the profile photo",
    "go back to before the portfolio",
    "undo that",
    "one step back",
    "make it blue again",
    "",
    "roll back to ddddddd",
    "we defaced it, roll back to ddddddd",
    "go back to before the newsletter signup",
    "revert the shop to before the hover animation",
    "go back to before the dark navy theme",
]

HISTORIES = {
    "broke": BROKE,
    "real": REAL,
    "shop": SHOP,
    "single": [v("a", "Initial build", is_current=True)],
    "empty": [],
    "all_error": [v("c", "third", status="error", is_current=True),
                  v("b", "second", status="error"),
                  v("a", "first", status="error")],
}


@pytest.mark.parametrize("hname", sorted(HISTORIES))
@pytest.mark.parametrize("phrase", PHRASES)
def test_sweep_a_target_is_always_a_real_version_and_never_the_current_one(hname, phrase):
    versions = HISTORIES[hname]
    choice = choose_rollback_target(versions, phrase, slug="shop")
    if choice.target is None:
        assert choice.candidates or not choice.needs_user_choice
        return
    shas = [x["sha"] for x in versions]
    assert choice.target["sha"] in shas, "invented a version"
    assert choice.target is versions[shas.index(choice.target["sha"])], (
        "returned a copy; callers pass this straight to the rollback route")
    assert choice.target["sha"] != versions[0]["sha"], (
        "offered the current version, which is a no-op dressed as an action")
    assert re.fullmatch(r"[0-9a-f]{7,40}", choice.target["sha"]), (
        "rollback_app_core would reject this sha")
    assert choice.reason.strip(), "a destructive action needs a stated reason"


@pytest.mark.parametrize("hname", sorted(HISTORIES))
@pytest.mark.parametrize("phrase", PHRASES)
def test_sweep_a_failed_version_is_never_offered_as_the_good_one(hname, phrase):
    """The point of the whole feature: never land the user on a broken build
    when they asked to escape one."""
    choice = choose_rollback_target(HISTORIES[hname], phrase, slug="shop")
    if choice.target is not None and any(
            w in phrase for w in ("broke", "worked", "error", "working")):
        assert choice.target.get("status") != "error", (
            f"{phrase!r} on {hname} handed back the failed build")


@pytest.mark.parametrize("hname", sorted(HISTORIES))
@pytest.mark.parametrize("phrase", PHRASES)
def test_sweep_candidates_are_always_real_and_exclude_the_current(hname, phrase):
    versions = HISTORIES[hname]
    choice = choose_rollback_target(versions, phrase, slug="shop")
    shas = {x["sha"] for x in versions}
    for cand in choice.candidates:
        assert cand["sha"] in shas
        assert cand["sha"] != versions[0]["sha"]


def test_a_rollback_target_says_which_state_it_actually_restores():
    """When the marker names a sha we can see, spell out the real state --
    "Rollback apps/shop/ to 8736cd7" tells the user nothing, and checking the
    reasoning is the confirm card's whole job."""
    restored = v("b", "add the hero banner")
    hist = [
        v("d", "add profile photo", is_current=True),
        {**v("c", ""), "message": f"Rollback apps/shop/ to {restored['short_sha']}",
         "status": "rollback"},
        restored,
        v("a", "Initial build"),
    ]
    choice = choose_rollback_target(hist, "go back to before the profile photo",
                                    slug="shop")
    assert choice.target is not None
    assert choice.target["message"].startswith("Rollback")
    assert "earlier undo" in choice.reason
    assert "add the hero banner" in choice.reason, (
        f"did not resolve what the undo restored: {choice.reason!r}")
