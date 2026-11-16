"""A Publish recommendation carries a button (2026-11-16).

Live on 2026-11-13, "how do I put my landing page online" got the right
answer, "open the App Builder and click Publish", and nothing to click:
`with_buttons` only ever drew Connect buttons, so the platform's own
features came out as words. The button opens the App Builder, where every
app card has its Publish button; the chat does not know which app the
person means, so it opens the place, not a guess at the app.
"""
import app_triage

OPEN = "#aiui-open:app-builder"


def _plan(*ids, text=""):
    return app_triage.plan([(i, 0.95) for i in ids], set(), [], text=text)


def test_a_publish_answer_gets_a_publish_button_even_when_it_says_publish():
    """The live reply said "click Publish" itself, which is exactly the case
    the how-line stays out of; the button must not depend on that."""
    answer = "Open the landing page app in the App Builder and click Publish."
    out = app_triage.with_buttons(answer, _plan("publish"))
    assert out.rstrip().endswith("[Publish in App Builder](%s)" % OPEN)


def test_the_how_line_and_the_button_both_come_when_publish_was_not_said():
    out = app_triage.with_buttons("Sure, here is how.", _plan("publish"))
    assert app_triage.PLATFORM["publish"].how in out
    assert out.rstrip().endswith("[Publish in App Builder](%s)" % OPEN)


def test_vercel_alone_gets_its_own_label_and_the_same_place():
    out = app_triage.with_buttons(
        "Click Publish and choose Vercel.", _plan("vercel", text="vercel"))
    assert out.rstrip().endswith("[Deploy to Vercel in App Builder](%s)" % OPEN)


def test_publish_and_vercel_together_make_one_button():
    """Both open the same window, so two buttons would be one place twice."""
    p = _plan("publish", "vercel", text="put it on vercel")
    out = app_triage.with_buttons("Click Publish, then Vercel.", p)
    assert out.count(OPEN) == 1


def test_no_second_button_when_the_answer_already_has_it():
    answer = "Click [Publish in App Builder](%s)." % OPEN
    out = app_triage.with_buttons(answer, _plan("publish"))
    assert out.count(OPEN) == 1


def test_it_sits_on_the_one_button_line_with_the_connect_buttons():
    p = app_triage.plan([("publish", 0.95), ("github", 0.95)], set(), [])
    out = app_triage.with_buttons("Click Publish. GitHub keeps versions.", p)
    last = out.rstrip().splitlines()[-1]
    assert OPEN in last and app_triage.connect_href("github") in last


def test_a_reply_that_carried_the_button_counts_as_offered():
    msgs = [{"role": "user", "content": "put my site online"},
            {"role": "assistant",
             "content": "Here: [Publish in App Builder](%s)" % OPEN},
            {"role": "user", "content": "thanks"}]
    assert "publish" in app_triage.already_offered(msgs)


def test_only_the_app_builder_can_be_opened_from_a_reply():
    """The marker names a place; the page only honours places on this list."""
    assert app_triage.OPEN_PLACES == ("app-builder",)
