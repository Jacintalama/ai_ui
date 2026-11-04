"""A skill waiting on an app, in the AI agent chat (2026-11-04).

Lukas, 2026-11-03: suggest skills from what the person has connected. Where
an agent holds a skill whose app is not connected, the chat says so above the
message box with a Connect button, and a Connect link in an agent's reply is
a button too. Both open the page's own Connections panel.

Run against the real agents.html, agent-chat.js and stylesheet, served the
way test_agents_roster.py serves them; only the API answers are stubbed.
"""
import json

import pytest

from tests.browser.test_agents_roster import (  # noqa: F401  (fixtures)
    BO, IRIS, TEMPLATES, browser, server, _wait_drawn)

IVY = {"id": "agent-ivy-0009", "name": "Ivy",
       "meta": {"role": "Inbox assistant", "toolIds": [],
                "skillIds": ["inbox-triage", "draft-reply", "shorten-this"]},
       "params": {}, "user_id": "me", "created_at": 3, "updated_at": 3}
ROSTER = [IRIS, BO, IVY]
IVY_ROW = '#roster-list .roster-row[data-agent-id="agent-ivy-0009"]'
BO_ROW = '#roster-list .roster-row[data-agent-id="agent-bo-0002"]'
EVERYONE_ROW = '#roster-list .roster-row[data-room="1"]'

GMAIL_NEED = [{"app": "gmail", "label": "Gmail",
               "skills": ["inbox-triage", "draft-reply"],
               "connect": "#aiui-connect:gmail", "button": "Connect Gmail"}]

#: What the thread route answers for Ivy: one reply carrying a Connect link,
#: in the markup agent_chat_render.agent_bubble writes.
IVY_THREAD = ('<div class="am agent" data-agent="Ivy"><div class="abody">'
              '<div class="awho">Ivy</div><div class="atext md">'
              'I cannot read your inbox yet.\n\n'
              '[Connect Gmail](#aiui-connect:gmail)</div></div></div>')


def _open(browser, server, needs=None):
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    asked = []

    def route(r):
        u = r.request.url
        if "/skills/needs" in u:
            asked.append(u)
            body = {"needs": GMAIL_NEED if needs is None else needs}
        elif "/api/v1/auths/" in u:
            body = {"id": "me", "email": "me@example.test"}
        elif "/models/list" in u:
            body = {"items": ROSTER, "total": len(ROSTER)}
        elif "/agents/activity" in u:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/templates" in u:
            body = {"templates": TEMPLATES}
        elif "/agents/chat/thread" in u:
            html = IVY_THREAD if "agent-ivy" in u else ""
            r.fulfill(status=200, content_type="text/html", body=html)
            return
        elif "/agents/chat/" in u:
            r.fulfill(status=200, content_type="text/html", body="")
            return
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
    _wait_drawn(pg, pg, True)
    pg.asked = asked
    return pg


def test_the_room_shows_no_notice(browser, server):
    pg = _open(browser, server)
    try:
        assert pg.locator("#ap-needs").is_hidden()
    finally:
        pg.close()


def test_an_agent_whose_skill_waits_on_gmail_says_so_with_a_button(browser, server):
    pg = _open(browser, server)
    try:
        pg.locator(IVY_ROW).click()
        notice = pg.locator("#ap-needs")
        notice.wait_for(state="visible")
        assert "inbox-triage and draft-reply need Gmail." in notice.inner_text()
        # Asked for this agent's skills, all of them, once.
        assert len(pg.asked) == 1
        assert "inbox-triage%2Cdraft-reply%2Cshorten-this" in pg.asked[0]
        btn = notice.locator("a", has_text="Connect Gmail")
        assert btn.get_attribute("href") == "#connections"
        btn.click()
        pg.locator("#connections-overlay").wait_for(state="visible")
    finally:
        pg.close()


def test_nothing_waiting_means_no_notice(browser, server):
    pg = _open(browser, server, needs=[])
    try:
        pg.locator(IVY_ROW).click()
        pg.wait_for_timeout(400)
        assert len(pg.asked) == 1
        assert pg.locator("#ap-needs").is_hidden()
    finally:
        pg.close()


def test_an_agent_with_no_skills_is_not_asked_about(browser, server):
    pg = _open(browser, server)
    try:
        pg.locator(IVY_ROW).click()
        pg.locator("#ap-needs").wait_for(state="visible")
        pg.locator(BO_ROW).click()
        pg.wait_for_timeout(400)
        assert pg.locator("#ap-needs").is_hidden()
        assert len(pg.asked) == 1
        pg.locator(EVERYONE_ROW).click()
        pg.wait_for_timeout(200)
        assert pg.locator("#ap-needs").is_hidden()
    finally:
        pg.close()


def test_a_connect_link_in_a_reply_is_a_button_that_opens_connections(browser, server):
    pg = _open(browser, server)
    try:
        pg.locator(IVY_ROW).click()
        link = pg.locator("#agent-thread .atext a", has_text="Connect Gmail")
        link.wait_for(state="visible")
        assert link.get_attribute("href") == "#connections"
        assert "btn" in (link.get_attribute("class") or "")
        link.click()
        pg.locator("#connections-overlay").wait_for(state="visible")
    finally:
        pg.close()
