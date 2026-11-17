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
