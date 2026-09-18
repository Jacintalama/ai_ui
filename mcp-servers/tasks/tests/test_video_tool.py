"""Making a video without asking the person for screenshots.

Ralph, 2026-09-18: a skill for video generation, so an agent can work in it.
The platform can already film a site by itself (capture-from-url), so an agent
never needs an upload; what was missing was a tool that walks the three steps,
because a draft is inert until something queues it.

video_tool.py installs into an Open WebUI tool row and nothing in the service
imports it, so it is loaded from its path, like the pipe tests.
"""
import importlib.util
import os

import pytest

TOOL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "video_tool.py")

WHO = {"email": "owner@example.com"}
JOB = "8a2851d8-3aa9-4963-a987-a71df3bc40db"
SITE = "https://example.com/"


def _load():
    spec = importlib.util.spec_from_file_location("video_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tools():
    return _load().Tools()


def _script(tools, replies):
    """Answer each call in order, recording what was asked."""
    seen = []

    async def call(method, path, email, json_body=None):
        seen.append({"method": method, "path": path, "email": email,
                     "body": json_body})
        return replies[len(seen) - 1] if len(seen) <= len(replies) else (True, {})

    tools._call = call
    return seen


async def test_it_films_the_site_and_queues_it(tools):
    seen = _script(tools, [
        (True, {"id": JOB, "slug": "vid-8a2851d8", "status": "collecting"}),
        (True, {"stored": 4}),
        (True, {"status": "queued", "queue_position": 0}),
    ])
    said = await tools.make_video(SITE, "Example tour", __user__=WHO)

    assert [c["path"] for c in seen] == [
        "/api/video-jobs/draft",
        "/api/video-jobs/%s/capture-from-url" % JOB,
        "/api/video-jobs/%s/queue" % JOB,
    ]
    assert seen[1]["body"]["url"] == SITE
    assert all(c["email"] == "owner@example.com" for c in seen)
    assert "rendering" in said and JOB in said


async def test_nothing_is_uploaded_and_nothing_is_asked_for(tools):
    """The whole point. The platform opens the site itself, so the person is
    never asked for screenshots."""
    _script(tools, [(True, {"id": JOB}), (True, {}), (True, {"status": "queued"})])
    said = await tools.make_video(SITE, __user__=WHO)
    assert "screenshot" not in said.lower()


async def test_a_queue_position_is_passed_on(tools):
    _script(tools, [(True, {"id": JOB}), (True, {}),
                    (True, {"status": "queued", "queue_position": 3})])
    said = await tools.make_video(SITE, __user__=WHO)
    assert "3 ahead" in said


async def test_a_site_it_will_not_film_is_explained(tools):
    """Private and internal addresses are refused on purpose. The person can
    act on that, so it survives as the service's own sentence."""
    seen = _script(tools, [
        (True, {"id": JOB}),
        (False, "That address is not one this platform will open."),
    ])
    said = await tools.make_video("http://192.168.0.1/", __user__=WHO)
    assert said == "That address is not one this platform will open."
    assert len(seen) == 2, "it queued a video with nothing captured"


async def test_the_daily_limit_is_not_a_crash(tools):
    _script(tools, [(True, {"id": JOB}), (True, {}),
                    (False, "Daily video limit reached")])
    said = await tools.make_video(SITE, __user__=WHO)
    assert "Daily video limit reached" in said


async def test_no_address_means_no_draft(tools):
    seen = _script(tools, [])
    said = await tools.make_video("   ", __user__=WHO)
    assert "address" in said.lower()
    assert seen == [], "it created a draft with nowhere to point it"


async def test_an_unknown_caller_makes_nothing(tools):
    """The email comes from Open WebUI, never from a parameter: a model that
    could name the user could make videos as somebody else."""
    seen = _script(tools, [])
    said = await tools.make_video(SITE, __user__={})
    assert seen == []
    assert "who is asking" in said


async def test_a_job_id_that_is_not_an_id_never_becomes_a_url(tools):
    """httpx resolves dot segments before sending, so an unchecked id is a way
    to call a different endpoint as this person."""
    seen = _script(tools, [])
    said = await tools.video_status("../connections/github", __user__=WHO)
    assert seen == []
    assert said == "That is not a video id."


async def test_a_finished_video_hands_over_the_link(tools):
    _script(tools, [(True, {"title": "Example tour", "status": "done",
                            "output_available": True,
                            "share_url": "https://ai-ui.example/watch"})])
    said = await tools.video_status(JOB, __user__=WHO)
    assert "https://ai-ui.example/watch" in said
    assert "ready" in said.lower()


async def test_a_finished_video_with_no_link_says_where_to_look(tools):
    """The share link needs a signing secret this platform may not have set.
    Saying "ready" with nowhere to go is worse than naming the page."""
    _script(tools, [(True, {"title": "Example tour", "status": "done",
                            "output_available": False})])
    said = await tools.video_status(JOB, __user__=WHO)
    assert "Video page" in said


async def test_a_waiting_video_says_how_far_off_it_is(tools):
    _script(tools, [(True, {"title": "Example tour", "status": "queued",
                            "queue_position": 2})])
    said = await tools.video_status(JOB, __user__=WHO)
    assert "2 ahead" in said


async def test_a_failed_video_says_why(tools):
    _script(tools, [(True, {"title": "Example tour", "status": "failed",
                            "error": "the render ran out of memory"})])
    said = await tools.video_status(JOB, __user__=WHO)
    assert "failed" in said and "out of memory" in said


async def test_the_list_is_readable(tools):
    _script(tools, [(True, {"videos": [
        {"id": JOB, "title": "Example tour", "status": "done"},
        {"id": JOB, "title": "Shop walkthrough", "status": "rendering"}]})])
    said = await tools.list_my_videos(__user__=WHO)
    assert "Example tour" in said and "rendering" in said


async def test_no_videos_is_said_plainly(tools):
    _script(tools, [(True, {"videos": []})])
    assert await tools.list_my_videos(__user__=WHO) == "There are no videos yet."
