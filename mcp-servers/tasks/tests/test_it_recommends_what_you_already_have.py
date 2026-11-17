"""Inside a choice, the app you already have goes first.

Ralph, 2026-11-17, with his n8n API key on screen carrying every scope it
offers: "it all have access... though why the system recommend zappier".

n8n and Zapier are one `group`, which exists so the assistant presents a
choice with the case for each side rather than a recommendation pretending
to be one. That part is right and stays.

What was wrong is the ORDER. `plan` ranks by Jev's score alone, and
whether the person has already connected an app was written into the brief
and never used:

    ranked = sorted(..., key=lambda p: -p[1])        # score only
    apps.append({... "connected": a.id in have ...})  # recorded, not ranked

So a hair of score put the hosted paid one ahead of the self-hosted one
somebody already runs. Telling a person to go and get a second tool, while
the first sits connected, is the kind of advice that makes the whole
recommendation untrustworthy.

The rule is narrow on purpose. It reorders WITHIN a group, where both are
shown anyway, so nothing is added or removed and no comparison is hidden.
It only decides which one is named first. When both are connected or
neither is, Jev's order stands, because then there is nothing to go on but
the message.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import app_triage


def _ids(out):
    return [a["id"] for a in out["apps"]]


AUTOMATION = ("n8n", "zapier")


def test_the_two_are_still_one_choice():
    """The fix must not turn a comparison into a single recommendation."""
    a, b = (app_triage.APPS[i] for i in AUTOMATION)
    assert a.group and a.group == b.group
    assert a.pros and b.pros, "a choice with no case for each side"


def test_the_one_you_have_connected_leads():
    """Jev prefers Zapier by a hair; the person runs n8n."""
    out = app_triage.plan([("zapier", 0.93), ("n8n", 0.91)],
                          {"n8n"}, [], text="automate this")
    assert _ids(out)[0] == "n8n", (
        "recommended the one they do not have over the one they do: %s"
        % _ids(out))


def test_the_other_side_is_still_shown():
    out = app_triage.plan([("zapier", 0.93), ("n8n", 0.91)],
                          {"n8n"}, [], text="automate this")
    assert set(_ids(out)) >= set(AUTOMATION), (
        "the choice lost a side, which makes it a recommendation: %s"
        % _ids(out))


def test_it_works_the_other_way_round_too():
    """Nothing here prefers n8n. It prefers what the person has."""
    out = app_triage.plan([("n8n", 0.95), ("zapier", 0.80)],
                          {"zapier"}, [], text="automate this")
    assert _ids(out)[0] == "zapier", _ids(out)


def test_with_neither_connected_jev_decides():
    out = app_triage.plan([("zapier", 0.93), ("n8n", 0.91)],
                          set(), [], text="automate this")
    assert _ids(out)[0] == "zapier", (
        "with nothing to go on but the message, the score should stand")


def test_with_both_connected_jev_decides():
    out = app_triage.plan([("zapier", 0.93), ("n8n", 0.91)],
                          {"n8n", "zapier"}, [], text="automate this")
    assert _ids(out)[0] == "zapier", _ids(out)


def test_a_connection_does_not_drag_an_unpicked_app_in():
    """Being connected reorders a choice. It must not CREATE a
    recommendation Jev never made, or every connected app would be
    recommended for every message."""
    out = app_triage.plan([("airtable", 0.95)], {"n8n", "zapier"}, [],
                          text="save my leads")
    assert "n8n" not in _ids(out) and "zapier" not in _ids(out), (
        "a connected app was recommended without Jev picking it: %s"
        % _ids(out))


def test_a_timer_still_drops_the_pair():
    """The existing rule is untouched: a job on a timer is the platform's,
    so neither is offered unless the person named one."""
    out = app_triage.plan([("zapier", 0.93), ("n8n", 0.91),
                           ("gmail", 0.92)],
                          {"n8n"}, [app_triage.TIMER_TOOL],
                          text="every 8am read my email")
    assert "n8n" not in _ids(out) and "zapier" not in _ids(out), _ids(out)


def test_naming_one_still_beats_the_timer_rule():
    out = app_triage.plan([("n8n", 0.93)], {"n8n"},
                          [app_triage.TIMER_TOOL],
                          text="every 8am run my n8n workflow")
    assert "n8n" in _ids(out)


# --- and a choice you have already made is not offered again --------------

def test_having_one_side_means_the_other_is_not_pushed(   ):
    """Seen live 2026-11-17. With n8n connected and read working, a real
    turn ended:

        Recommended: Zapier, so IO can send data to a Zap you made,
        which starts it (it cannot create or change Zaps yet).
        [Connect Zapier]

    with n8n never mentioned. with_buttons skips a connected app, which
    is right for one app on its own and backwards for a CHOICE: it drops
    the side the person has and pushes the side they do not, turning
    "here are your two options" into "go and get the other one".

    Somebody who already has an automation tool connected does not need
    to be sold its competitor.
    """
    p = app_triage.plan([("zapier", 0.93), ("n8n", 0.91)],
                        {"n8n"}, [], text="automate this for me")
    out = app_triage.with_buttons("Here is what I found.", p)
    assert "Connect Zapier" not in out, (
        "offered the competitor of a tool they already have:\n" + out)
    assert "Recommended: Zapier" not in out, out


def test_with_neither_connected_the_choice_is_still_offered():
    """The group must not become invisible. Somebody with no automation
    tool should still be shown both."""
    p = app_triage.plan([("zapier", 0.93), ("n8n", 0.91)],
                        set(), [], text="automate this for me")
    out = app_triage.with_buttons("Here is what I found.", p)
    assert "Zapier" in out and "n8n" in out, (
        "a person with neither was shown no choice at all:\n" + out)


def test_an_unrelated_app_is_still_recommended():
    """Only the group is affected. A connected app elsewhere must not
    suppress a recommendation that has nothing to do with it."""
    p = app_triage.plan([("airtable", 0.95)], {"n8n"}, [],
                        text="save my leads somewhere")
    out = app_triage.with_buttons("Here is what I found.", p)
    assert "Airtable" in out, out


# --- the limit of an app you HAVE is the one that matters -----------------

CONNECTED = {"n8n"}
PICKS_N8N = [("n8n", 0.94)]


def _plan_n8n():
    return app_triage.plan(PICKS_N8N, CONNECTED, [], text="check n8n")


def test_the_limit_is_stated_when_the_answer_left_it_out():
    """Seen live 2026-11-17, two runs of one request, "create a test
    workflow in n8n and list my workflows".

    Run one said it plainly: "my n8n access is read-only: it can list
    workflows, read one, and view recent runs, but not create or edit
    them." Run two quietly dropped the create half and answered "No IO
    test workflow exists yet. If you build it in n8n ... I'll read it
    back", never saying it COULD not.

    The guarantee that the limit gets said lives in the loop over apps the
    person has NOT connected, and a connected app is skipped before it
    gets there. So the one app being used is the one whose limit is never
    guaranteed, which is backwards: that is the limit somebody is about to
    walk into.
    """
    answer = ("No IO test workflow exists yet. If you build it in n8n, "
              "let me know and I'll read it back.")
    out = app_triage.with_buttons(answer, _plan_n8n())
    assert "cannot yet create or change workflows" in out, (
        "the answer skipped the limit and so did the service:\n" + out)


def test_it_does_not_say_it_twice():
    """Run one's wording. The model already said it, in better words than
    ours, so the service stays quiet: the same thing twice in two voices
    is what the not-connected branch was written to avoid."""
    answer = ("My n8n access is read-only: it can list workflows, read "
              "one, and view recent runs, but not create or edit them.")
    out = app_triage.with_buttons(answer, _plan_n8n())
    assert out.strip() == answer.strip(), (
        "said the limit again under an answer that already said it:\n"
        + out)


def test_an_app_the_answer_never_mentioned_stays_quiet():
    """The limit belongs under an answer about that app, not stapled to
    every reply because the person happens to have it connected."""
    out = app_triage.with_buttons("Here are your Trello cards.",
                                  _plan_n8n())
    assert "n8n" not in out, out


def test_a_connected_app_still_gets_no_connect_button():
    out = app_triage.with_buttons(
        "No IO test workflow exists yet in n8n.", _plan_n8n())
    assert "aiui-connect:n8n" not in out, (
        "offered a Connect button for something already connected:\n"
        + out)
