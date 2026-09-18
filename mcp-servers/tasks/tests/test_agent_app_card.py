"""An app an agent built or changed is something you can open.

Ralph, 2026-09-18: when an agent creates an app the reply should carry the app,
not a sentence about where to look for it. Rex's actual words in his screenshot
were "The approved change is ready in App Builder", which is true and gets
nobody to the page.

The card is derived from the answer's own text, so a reload draws what the
round drew. Nothing is stored for it and no extra plumbing carries it.
"""
import pytest

import agent_chat_render as render

BASE = "https://ai-ui.coolestdomain.win"
APP = BASE + "/apps/create-me-a-shoe-website-fe02/"


def test_an_answer_with_an_app_link_gets_a_card():
    said = render.agent_bubble("Rex", "Done, the page is live.\n" + APP)
    assert 'class="acard"' in said
    assert 'href="%s"' % APP in said
    assert "create-me-a-shoe-website-fe02" in said
    assert 'target="_blank"' in said and 'rel="noopener"' in said


def test_the_same_app_twice_is_one_card():
    """A model that repeats the link, or quotes itself, must not stack
    three identical cards under one answer."""
    said = render.agent_bubble("Rex", "%s and again %s" % (APP, APP))
    assert said.count('class="acard"') == 1


def test_two_different_apps_get_a_card_each():
    other = BASE + "/apps/ralph-portfolio/"
    said = render.agent_bubble("Rex", "%s\n%s" % (APP, other))
    assert said.count('class="acard"') == 2


BUILD = BASE + "/tasks/static/preview.html?task=8a2851d8-3aa9-4963-a987-a71df"


def test_a_build_in_progress_gets_a_card_too():
    """What an agent hands back the moment it starts a build. Without this the
    link arrives as bare text and the person lands on a list of twenty apps
    instead of on the one being built."""
    said = render.agent_bubble("Rex", "Building thunder-2b68 now.\n" + BUILD)
    assert 'class="acard"' in said
    assert 'href="%s"' % BUILD in said
    assert "Watch it build" in said


def test_a_build_card_is_drawn_once():
    said = render.agent_bubble("Rex", "%s and %s" % (BUILD, BUILD))
    assert said.count('class="acard"') == 1


def test_an_answer_with_no_app_link_gets_no_card():
    said = render.agent_bubble("Mia", "Nothing unread in your inbox.")
    assert "acard" not in said


@pytest.mark.parametrize("link", [
    "https://ai-ui.coolestdomain.win/app-builder",
    "https://ai-ui.coolestdomain.win/tasks/agents",
    "https://example.com/not-an-app/",
])
def test_other_links_are_left_alone(link):
    """App Builder is a page, not an app. A card that opened it would say
    "Open" over a slug the person never named."""
    assert "acard" not in render.agent_bubble("Ada", "See " + link)


def test_a_page_inside_an_app_is_a_link_and_not_the_app():
    deep = BASE + "/apps/shoe-site/about.html"
    assert "acard" not in render.agent_bubble("Kai", "Look at " + deep)


def test_the_card_escapes_what_the_model_wrote():
    """The content is model output and the slug comes out of it. This page
    has been through one XSS review already."""
    nasty = BASE + '/apps/x"onmouseover="alert(1)/'
    said = render.agent_bubble("Rex", nasty)
    assert 'onmouseover="alert(1)"' not in said
    assert "&quot;" in said or "acard" not in said


def test_a_replayed_answer_draws_the_same_card(tmp_path):
    """thread() rebuilds a saved conversation. A card that only appeared live
    would vanish on reload, which is how the panel used to lose its notes."""
    saved = [{"role": "user", "content": "build it", "turn_id": "t1"},
             {"role": "assistant", "agent_name": "Rex",
              "content": "Done.\n" + APP}]
    assert render.thread(saved).count('class="acard"') == 1
