"""A light build ends up looking like an ordinary finished build.

Everything downstream was written before this lane existed: the chat
watcher, publishing, the version list, rollback, the appearance panel.
None of them know what a lane is, and none of them should have to. So
the runner's job is to leave exactly the rows the agent path leaves.

The model call and the commit are stubbed. What is being tested is what
happens around them, especially when they go wrong, because a build that
fails silently leaves somebody's task running forever.
"""
import asyncio

import pytest

import build_progress
import light_build
import light_runner


def _page():
    import app_theme
    tokens = "".join("  %s: %s;\n" % (t.name, t.default) for t in app_theme.TOKENS)
    return ("<!doctype html><html><head><title>Bean There</title>"
            "<script src=\"https://cdn.tailwindcss.com\"></script>"
            "<style>:root{\n" + tokens + "}</style></head>"
            "<body><h1>Bean There</h1></body></html>")


@pytest.fixture
def spy(monkeypatch, tmp_path):
    """Records what the runner did, without a model, a DB or a repo."""
    seen = {"steps": [], "finished": None, "commits": [], "asks": []}

    async def say(task_id, step):
        seen["steps"].append(step)

    async def finish(task_id, execution_id, *, status, result, slug):
        seen["finished"] = {"status": status, "result": result, "slug": slug}

    async def commit(slug, *, message, actor_email):
        seen["commits"].append(slug)
        return "abc1234"

    monkeypatch.setattr(build_progress, "_write_seam", say)
    monkeypatch.setattr(light_runner, "_finish", finish)
    monkeypatch.setattr(light_runner.app_git, "sweep_app_commit", commit)
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    seen["root"] = tmp_path
    return seen


def _answers(monkeypatch, spy, *pages):
    """The model returns these in turn."""
    queue = list(pages)

    async def ask(description, slug, app_name, complaint):
        spy["asks"].append(complaint)
        return queue.pop(0) if queue else ""

    monkeypatch.setattr(light_runner, "_ask_for_the_page", ask)


def _run(**kw):
    kw.setdefault("slug", "bean-there")
    kw.setdefault("app_name", "Bean There")
    kw.setdefault("description", "a coffee shop landing page")
    asyncio.run(light_runner.run_light_build("t-1", "e-1", **kw))


# --- the ordinary case ---------------------------------------------------

def test_it_finishes_the_task_the_way_the_agent_path_does(monkeypatch, spy):
    _answers(monkeypatch, spy, _page())
    _run()
    assert spy["finished"]["status"] == "completed"
    assert spy["finished"]["slug"] == "bean-there"
    assert "bean-there" in spy["finished"]["result"]


def test_it_writes_one_file_and_a_readme(monkeypatch, spy):
    _answers(monkeypatch, spy, _page())
    _run()
    folder = spy["root"] / "bean-there"
    assert (folder / "index.html").exists()
    assert (folder / "README.md").exists()
    assert not (folder / "src").exists(), "a simple site is one file"


def test_it_walks_its_own_three_steps(monkeypatch, spy):
    """Not the agent's six. There is no baseline to take, nothing to
    autofix and no browser to open."""
    _answers(monkeypatch, spy, _page())
    _run()
    assert spy["steps"] == list(build_progress.LIGHT_ORDER)


def test_the_app_is_committed_so_it_has_history(monkeypatch, spy):
    """Version history is `git log -- apps/<slug>/`. Skipping the commit
    would mean a light-lane app could never be rolled back."""
    _answers(monkeypatch, spy, _page())
    _run()
    assert spy["commits"] == ["bean-there"]


def test_the_page_can_be_restyled_the_moment_it_is_built(monkeypatch, spy):
    """Otherwise the appearance panel offers to upgrade an app made
    thirty seconds ago."""
    _answers(monkeypatch, spy, _page())
    _run()
    import app_theme
    written = (spy["root"] / "bean-there" / "index.html").read_text(
        encoding="utf-8")
    assert app_theme.is_themeable(written)


# --- when it goes wrong --------------------------------------------------

def test_a_cut_off_page_is_asked_for_again_with_the_reason(monkeypatch, spy):
    """The usual failure is a page that hit the token limit. A model
    fixes that when told, so one retry is worth more than one failure."""
    _answers(monkeypatch, spy, "<!doctype html><html><head><title>x</title>",
             _page())
    _run()
    assert spy["finished"]["status"] == "completed"
    assert spy["asks"][0] is None
    assert spy["asks"][1] and "cut off" in spy["asks"][1]


def test_it_gives_up_after_one_retry_rather_than_forever(monkeypatch, spy):
    _answers(monkeypatch, spy, "nope", "still nope")
    _run()
    assert len(spy["asks"]) == 2
    assert spy["finished"]["status"] == "failed"


def test_a_failure_says_what_went_wrong_and_what_to_do(monkeypatch, spy):
    _answers(monkeypatch, spy, "nope", "still nope")
    _run()
    said = spy["finished"]["result"]
    assert "could not be finished" in said
    assert "again" in said.lower()
    assert spy["finished"]["slug"] is None, (
        "a failed build must not claim it built an app")


def test_a_model_that_raises_still_finishes_the_task(monkeypatch, spy):
    """The anti-goal: a task left running forever, with the chat watching
    something that will never land."""
    async def boom(*a, **kw):
        raise RuntimeError("the model is down")
    monkeypatch.setattr(light_runner, "_ask_for_the_page", boom)
    _run()
    assert spy["finished"]["status"] == "failed"
    assert "the model is down" in spy["finished"]["result"]


def test_a_commit_that_fails_does_not_lose_the_build(monkeypatch, spy):
    """Fails open, like every other sweep. The site is already on disk
    and serves; a failed commit costs history, not the build."""
    async def boom(*a, **kw):
        raise RuntimeError("git is unhappy")
    monkeypatch.setattr(light_runner.app_git, "sweep_app_commit", boom)
    _answers(monkeypatch, spy, _page())
    _run()
    assert spy["finished"]["status"] == "completed"


def test_nothing_is_written_when_the_page_is_refused(monkeypatch, spy):
    """A half-written app folder would be published as a broken site."""
    _answers(monkeypatch, spy, "nope", "still nope")
    _run()
    assert not (spy["root"] / "bean-there").exists()


# --- the cap -------------------------------------------------------------

def test_there_is_a_limit_on_how_many_run_at_once():
    """The point of the lane is that several run together. The point of
    the cap is that nothing runs away.

    Measured on the server 2026-11-05: six at once cost about 7MB in
    total, so this does not protect memory. It protects the model bill
    and the provider's rate limit, which is why it is not simply
    unbounded.
    """
    assert light_runner.CONCURRENCY >= 2, "then it is not a parallel lane"
    assert light_runner.CONCURRENCY <= 50, "nothing should run away"


def test_it_covers_everybody_on_the_platform_at_once():
    """Nine people were registered when this was written. A cap below
    that would still refuse somebody while others build, which is the
    bug this lane exists to fix."""
    assert light_runner.CONCURRENCY >= 9


def test_the_cap_is_settable_without_changing_code():
    """So it can be tuned from .env on the server. It is read at start,
    so it needs a restart, which is a deploy: that is a property worth
    knowing rather than one to hide."""
    src = open(light_runner.__file__, encoding="utf-8").read()
    assert 'os.environ.get("LIGHT_BUILD_CONCURRENCY"' in src
    import os.path
    compose = os.path.join(os.path.dirname(light_runner.__file__),
                           "..", "..", "docker-compose.unified.yml")
    with open(compose, encoding="utf-8") as fh:
        assert "LIGHT_BUILD_CONCURRENCY=${LIGHT_BUILD_CONCURRENCY:-" in fh.read(), (
            "not exposed in compose, so it cannot be set without a code change")


def test_the_slots_are_made_once(monkeypatch):
    """A Semaphore binds to the running loop, so making it at import time
    binds it to the wrong one."""
    monkeypatch.setattr(light_runner, "_slots", None)

    async def twice():
        return light_runner.slots() is light_runner.slots()

    assert asyncio.run(twice()) is True
