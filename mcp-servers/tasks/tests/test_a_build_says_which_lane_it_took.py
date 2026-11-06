"""A build says which lane it took, so a slow one is not a mystery.

The open half of the light lane. Since 2026-11-05 a plain site is written
by one model call in under a minute, and anything needing login, a
database or a template goes to the full builder and takes several
minutes. The platform behaved differently and said nothing.

That was an explicit anti-goal in the design: "the light lane quietly
taking a job it cannot do, and somebody getting a worse app without being
told". Half of it was closed, because the lane refuses the job correctly.
This closes the other half.

Two surfaces, on purpose:
  - the CHAT TEXT, which the tool writes and which survives a reload
  - the step panel, while the build runs

The reason the chat text matters more is the bug I fixed the same day: a
panel drawn only at the moment something happened was gone for good after
a reload, and the person was left with nothing.
"""
import os

import pytest

import build_progress
import light_build

HERE = os.path.dirname(__file__)
ROUTES = os.path.join(HERE, "..", "routes_aiuibuilder.py")
PANEL = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")
TOOL = os.path.join(HERE, "..", "..", "..", "open-webui-functions", "code_tool.py")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _spawn_body():
    src = _read(ROUTES)
    start = src.index("async def _create_and_spawn_build(")
    return src[start:src.index("\nasync def ", start + 10)]


# --- one decider ---------------------------------------------------------

def test_a_plain_site_takes_the_light_lane_and_needs_no_explanation():
    lane, why = light_build.lane_for("a coffee shop landing page")
    assert lane == light_build.LANE_LIGHT
    assert why is None


def test_a_site_with_login_goes_to_the_full_builder_with_the_reason():
    lane, why = light_build.lane_for("a members area where people log in")
    assert lane == light_build.LANE_AGENT
    assert why and "log in" in why


def test_a_template_goes_to_the_full_builder_and_says_so():
    """A template is multi-file by definition, so it cannot take a lane
    that writes exactly one file. Nothing in the WORDS asks for a backend,
    so without this the person would be told a plain site is coming and
    then wait minutes."""
    lane, why = light_build.lane_for("a tidy portfolio", template_key="portfolio")
    assert lane == light_build.LANE_AGENT
    assert why and "template" in why.lower()


def test_the_description_is_still_read_when_a_template_is_named():
    """Both are reasons to use the agent. The one that names what the
    person actually asked for is the more useful sentence."""
    lane, why = light_build.lane_for("a shop with a cart", template_key="portfolio")
    assert lane == light_build.LANE_AGENT
    assert "cart" in why


def test_the_spawn_asks_lane_for_and_nothing_else():
    """The anti-goal is the route and the build disagreeing about which
    lane was used, which would make the sentence a lie. One function
    decides and both read it."""
    body = _spawn_body()
    assert "light_build.lane_for(" in body
    assert "light_build.needs_the_agent(" not in body, (
        "a second decider, so the note and the build can drift apart")


def test_the_lane_is_still_decided_before_the_guard():
    """Deciding after would mean a light build was already refused by the
    time anyone asked whether it needed an agent."""
    body = _spawn_body()
    assert body.index("light_build.lane_for(") < body.index("A build is already running")


# --- the sentence --------------------------------------------------------

def test_the_light_note_says_it_will_be_quick():
    said = light_build.lane_note(light_build.LANE_LIGHT, None)
    assert "minute" in said
    assert "full builder" not in said.lower(), (
        "a plain site is not going to the full builder, so saying so is a lie")


def test_the_agent_note_carries_the_reason_word_for_word():
    """The reason is already a sentence written for a person. Rewriting it
    here would be a second copy to keep in step."""
    lane, why = light_build.lane_for("an app where people sign up")
    said = light_build.lane_note(lane, why)
    assert why in said


def test_the_agent_note_warns_it_is_the_slow_one():
    """The whole point. Somebody who knows a build takes minutes is
    waiting; somebody who does not is watching a broken platform."""
    lane, why = light_build.lane_for("a dashboard with live analytics")
    said = light_build.lane_note(lane, why)
    assert "minutes" in said


def test_no_lane_is_ever_left_without_a_sentence():
    """Including a lane name nobody recognises, because an empty note
    would render as a blank line in the chat."""
    for lane in (light_build.LANE_LIGHT, light_build.LANE_AGENT, "", "nonsense"):
        said = light_build.lane_note(lane, None)
        assert said.strip()
        assert said.strip().endswith(".")


@pytest.mark.parametrize("why", [w for _, w in light_build._NEEDS_A_BACKEND])
def test_every_reason_reads_as_a_finished_sentence(why):
    said = light_build.lane_note(light_build.LANE_AGENT, why)
    assert said.startswith("This")
    assert said.strip().endswith(".")
    assert ".." not in said


@pytest.mark.parametrize("why", [None] + [w for _, w in light_build._NEEDS_A_BACKEND])
def test_nothing_shown_to_a_person_uses_a_dash_for_punctuation(why):
    """Ralph's standing rule for anything a person reads."""
    for lane in (light_build.LANE_LIGHT, light_build.LANE_AGENT):
        said = light_build.lane_note(lane, why)
        assert "—" not in said
        assert "–" not in said


# --- what the route answers ----------------------------------------------

def _client():
    from main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def no_real_build(monkeypatch):
    import routes_aiuibuilder as rb

    async def fake_create(email, seed, description, template_key=None,
                          attachment_text=None, attachment_name=None):
        return ("11111111-1111-1111-1111-111111111111", "slug-a1b2")

    monkeypatch.setattr(rb, "_create_and_spawn_build", fake_create)


def _start(description, **extra):
    body = dict(description=description, **extra)
    r = _client().post("/api/aiuibuilder/build",
                       headers={"X-User-Email": "alice@x.com"}, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_the_build_response_says_the_lane(no_real_build):
    assert _start("a coffee shop landing page")["lane"] == "light"
    assert _start("a members area where people log in")["lane"] == "agent"


def test_the_build_response_carries_the_sentence(no_real_build):
    out = _start("a members area where people log in")
    assert "log in" in out["note"]
    assert "minutes" in out["note"]


def test_a_plain_build_is_told_it_will_be_quick(no_real_build):
    assert "minute" in _start("a one page site about bees")["note"]


def test_a_template_build_is_not_promised_a_minute(no_real_build):
    """The case a person cannot see coming from their own words."""
    out = _start("a tidy portfolio", template_key="portfolio")
    assert out["lane"] == "agent"
    assert "template" in out["note"].lower()


@pytest.mark.parametrize("key", ["blank", "custom"])
def test_a_key_that_means_no_template_is_still_the_light_lane(no_real_build, key):
    """The drift this is here to catch. `blank` and `custom` are not
    templates: they are how a template-less build is spelled by some
    callers, and the build normalises them to nothing.

    Read raw, the sentence would promise several minutes and the full
    builder for a build that takes under one, which is a worse failure
    than saying nothing at all.
    """
    out = _start("a one page site about bees", template_key=key)
    assert out["lane"] == "light"
    assert "minute" in out["note"]


def test_an_agent_started_build_gets_the_sentence_too():
    """A build an agent kicked off in the main chat is the same wait, and
    the agent has to be able to say why. Its route answers a dict rather
    than a model, so the keys are what is asserted."""
    src = _read(os.path.join(HERE, "..", "routes_code.py"))
    assert 'light_build.lane_for(description' in src
    assert '"note": light_build.lane_note(' in src


# --- the panel -----------------------------------------------------------

def test_each_lane_has_a_short_name():
    light = build_progress.lane_said("light")
    agent = build_progress.lane_said("agent")
    assert light and agent and light != agent
    assert len(light) <= 40 and len(agent) <= 40


def test_an_unknown_lane_still_has_a_name():
    assert build_progress.lane_said("nonsense") == build_progress.lane_said("agent")


def test_the_walk_is_served_with_its_lane_name():
    """The page must not hold its own copy of either name. There are
    already two places that show a step and the wording is served for
    exactly this reason."""
    import asyncio

    import routes_tasks

    body = asyncio.run(routes_tasks.build_steps(lane="light"))
    assert body["said"] == build_progress.lane_said("light")


def test_the_page_does_not_keep_its_own_copy_of_the_names():
    panel = _read(PANEL)
    for name in (build_progress.lane_said("light"), build_progress.lane_said("agent")):
        assert name not in panel, (
            "the lane name is hardcoded in the page, so the served one can "
            "change and the chat will not")


def test_the_panel_draws_the_name_of_the_lane_this_build_is_on():
    """Not whichever name was fetched first. The panel already made that
    mistake with the steps themselves and showed a three step build six
    rows."""
    src = _read(PANEL)
    body = src[src.index("function aiuiStepPanel("):]
    body = body[:body.index("\n  }\n")]
    assert "AIUI_LANE_SAID[aiuiLaneOf(task)]" in body


def test_the_name_is_kept_from_the_same_answer_as_the_steps():
    src = _read(PANEL)
    body = src[src.index("function aiuiLoadSteps("):]
    body = body[:body.index("\n  }\n")]
    assert "AIUI_LANE_SAID[key] = (body && body.said)" in body


# --- the page somebody watches while it runs -----------------------------

PAGE = os.path.join(HERE, "..", "static", "preview.html")


def test_each_lane_says_how_long_it_takes():
    light = build_progress.lane_wait("light")
    agent = build_progress.lane_wait("agent")
    assert "minute" in light and "minutes" in agent
    assert light != agent
    assert "tests" not in light, (
        "the light lane runs no tests, so it must not promise any")


def test_the_task_carries_that_sentence():
    """So the page can show it without knowing a single lane name."""
    import schemas

    out = _task_out(schemas, step="drafting")
    assert out.build_lane == "light"
    assert out.build_wait == build_progress.lane_wait("light")

    out = _task_out(schemas, step="smoking")
    assert out.build_lane == "agent"
    assert out.build_wait == build_progress.lane_wait("agent")


def _task_out(schemas, step):
    import datetime as _dt
    import uuid as _uuid
    return schemas.TaskOut(
        created_at=_dt.datetime(2026, 11, 6, 9, 0, 0),
        id=_uuid.uuid4(), meeting_id=_uuid.uuid4(), action_type="BUILD",
        description="a site", status="running", build_step=step,
        assignee_name="alice", assignee_email="alice@x.com",
        priority="NICE_TO_HAVE",
    )


def test_the_page_keeps_no_copy_of_either_sentence():
    """It held one sentence for both lanes and promised every build two
    to five minutes and a test run. 50 of the 51 apps in this repo are
    plain sites, so it was wrong far more often than it was right."""
    page = _read(PAGE)
    for said in build_progress.LANE_WAIT.values():
        assert said not in page, "wait wording copied into the page: " + said
    assert "2–5 minutes" not in page and "2-5 minutes" not in page


def test_the_page_says_it_on_every_poll_not_only_after_a_question():
    """The sub line used to be set only on the way back from a question,
    so a build that was never interrupted never showed the sentence."""
    page = _read(PAGE)
    assert "if (task.build_wait) $bovSub.textContent = task.build_wait;" in page


def test_nothing_a_person_reads_on_that_page_uses_a_dash_for_punctuation():
    page = _read(PAGE)
    overlay = page[page.index('id="build-sub"'):][:600]
    assert "—" not in overlay and "–" not in overlay


# --- the chat text -------------------------------------------------------

def test_the_build_tool_puts_the_sentence_in_the_reply():
    """The chat text is the only surface that survives a reload, which is
    the bug this platform already had once."""
    tool = _read(TOOL)
    assert 'data.get("note")' in tool


def test_the_build_tool_still_hands_over_no_link():
    """Guarding yesterday's work: the reply declares an artifact and never
    writes a URL."""
    tool = _read(TOOL)
    assert "[aiui-artifact]: #build/" in tool
    assert "Watch it here" not in tool
