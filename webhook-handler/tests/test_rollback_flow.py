"""End to end through the chat flow, with the tasks service faked.

The property that matters most is at the bottom: a rollback must never happen
without the user confirming a specific version they were shown. Everything else
here is about turning failures into sentences instead of stack traces.
"""
from unittest.mock import MagicMock

import pytest

from handlers import intent_router
from handlers.commands import CommandRouter


class FakeTasks:
    """Stands in for the tasks service. Records what it was asked to do so the
    tests can assert on the absence of a rollback, not just its presence."""

    def __init__(self, *, projects=None, resolve=None, rollback=None, raises=None):
        self._projects = projects if projects is not None else [{"slug": "shop"}]
        self._resolve = resolve or {}
        self._rollback = rollback or {"ok": True, "noop": False}
        self._raises = raises
        self.rollbacks: list[tuple[str, str]] = []
        self.resolved: list[tuple[str, str]] = []

    async def list_projects(self, user_email):
        return self._projects

    async def resolve_rollback(self, user_email, slug, phrase):
        self.resolved.append((slug, phrase))
        if self._raises:
            raise self._raises
        return self._resolve

    async def rollback_app(self, user_email, slug, sha):
        self.rollbacks.append((slug, sha))
        if self._raises:
            raise self._raises
        return self._rollback


def _version(short="d4d4d4d", message="add checkout"):
    return {"sha": short + "0" * (40 - len(short)), "short_sha": short,
            "message": message, "date": "2026-08-01T14:22:00", "status": "ok"}


RESOLVED = {
    "target": _version(),
    "reason": "'add cart' failed — this is the last version that worked before it",
    "needs_user_choice": False,
    "candidates": [],
}


EMAIL = "jacint@example.com"


def _handlers(tasks, classify_result):
    """A real CommandRouter with the classifier pinned and the tasks client faked."""
    router = CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map={"u1": EMAIL}, tasks_client=tasks,
    )

    async def fake_classify(text, openwebui, model):
        return classify_result

    intent_router.classify = fake_classify  # module-level seam, restored by fixture
    return router


class Ctx:
    """Minimal context for the confirm step."""
    platform = "discord"
    user_id = "u1"
    user_name = "tester"
    channel_id = "c1"
    arguments = ""
    respond_components = None

    def __init__(self):
        self.said: list[str] = []

    async def respond(self, text, *a, **k):
        self.said.append(text)


@pytest.fixture(autouse=True)
def _restore_classify():
    real = intent_router.classify
    yield
    intent_router.classify = real


def _rollback_intent(app="", point="before it broke", confidence=0.95):
    return intent_router.IntentResult(
        "rollback_app", confidence, "roll it back", app=app, point=point)


# ---------------------------------------------------------------------------
# The happy path: resolve first, show the target, only then act.
# ---------------------------------------------------------------------------

async def test_the_target_is_resolved_before_the_user_is_asked():
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "go back to before it broke", threshold=0.6, email=EMAIL)
    assert step.kind == "confirm"
    assert tasks.resolved == [("shop", "before it broke")]


async def test_nothing_is_rolled_back_merely_by_asking():
    """The single most important test in this file."""
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    await h.plan_chat_step("u1", "go back to before it broke", threshold=0.6, email=EMAIL)
    assert tasks.rollbacks == [], "a rollback happened before the user confirmed"


async def test_the_confirm_shows_the_version_and_the_reason():
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "go back to before it broke", threshold=0.6, email=EMAIL)
    assert "d4d4d4d" in step.text
    assert "add checkout" in step.text
    assert "add cart" in step.text


async def test_confirming_rolls_back_to_exactly_the_sha_that_was_shown():
    """Pinned at resolve time. If it re-resolved on confirm, a build landing in
    between would silently change the destination."""
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "go back to before it broke", threshold=0.6, email=EMAIL)

    ctx = Ctx()

    await h.run_confirmed_intent(ctx, step.token)
    assert tasks.rollbacks == [("shop", _version()["sha"])]
    assert ctx.said and "shop" in ctx.said[0]


# ---------------------------------------------------------------------------
# Which app? Never guess between two.
# ---------------------------------------------------------------------------

async def test_the_only_app_is_used_when_the_user_names_none():
    tasks = FakeTasks(projects=[{"slug": "shop"}], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent(app=""))
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, email=EMAIL)
    assert step.kind == "confirm"
    assert tasks.resolved[0][0] == "shop"


async def test_a_named_app_is_used_even_when_several_exist():
    tasks = FakeTasks(projects=[{"slug": "shop"}, {"slug": "blog"}], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent(app="blog"))
    step = await h.plan_chat_step("u1", "roll blog back", threshold=0.6, email=EMAIL)
    assert tasks.resolved[0][0] == "blog"
    assert step.kind == "confirm"


async def test_two_apps_and_no_name_asks_instead_of_guessing():
    tasks = FakeTasks(projects=[{"slug": "shop"}, {"slug": "blog"}], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent(app=""))
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, email=EMAIL)
    assert step.kind != "confirm"
    assert "shop" in step.text and "blog" in step.text
    assert tasks.rollbacks == []


async def test_no_apps_at_all_says_so_plainly():
    tasks = FakeTasks(projects=[], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, email=EMAIL)
    assert step.kind != "confirm"
    assert "built" in step.text.lower() or "no app" in step.text.lower()


async def test_a_named_app_the_user_does_not_own_is_not_silently_swapped():
    tasks = FakeTasks(projects=[{"slug": "shop"}], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent(app="somebody-elses-app"))
    step = await h.plan_chat_step("u1", "roll it back", threshold=0.6, email=EMAIL)
    assert step.kind != "confirm"
    assert tasks.rollbacks == []


# ---------------------------------------------------------------------------
# When the resolver cannot decide.
# ---------------------------------------------------------------------------

async def test_an_undecidable_phrase_offers_the_versions():
    tasks = FakeTasks(resolve={
        "target": None, "reason": "Which version should I go back to?",
        "needs_user_choice": True,
        "candidates": [_version("d4d4d4d", "add checkout"),
                       _version("c3c3c3c", "style the header")],
    })
    h = _handlers(tasks, _rollback_intent(point="make it blue again"))
    step = await h.plan_chat_step("u1", "make it blue again", threshold=0.6, email=EMAIL)
    assert step.kind != "confirm"
    assert "add checkout" in step.text and "style the header" in step.text
    assert tasks.rollbacks == []


async def test_nothing_possible_is_stated_as_a_sentence():
    tasks = FakeTasks(resolve={
        "target": None,
        "reason": "There are no saved versions for this app yet, so there is "
                  "nothing to go back to.",
        "needs_user_choice": False, "candidates": [],
    })
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, email=EMAIL)
    assert step.kind != "confirm"
    assert "nothing to go back to" in step.text


# ---------------------------------------------------------------------------
# Failures become sentences.
# ---------------------------------------------------------------------------

async def test_a_dirty_tree_is_explained_not_dumped():
    from clients.tasks import TasksAPIError
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, email=EMAIL)
    tasks._raises = TasksAPIError(409, "apps/shop/ has uncommitted changes")

    ctx = Ctx()

    await h.run_confirmed_intent(ctx, step.token)
    assert ctx.said, "the user must be told something"
    assert "Traceback" not in ctx.said[0]
    assert "unsaved" in ctx.said[0].lower() or "changes" in ctx.said[0].lower()


async def test_a_noop_does_not_claim_a_rollback_happened():
    tasks = FakeTasks(resolve=RESOLVED, rollback={"ok": True, "noop": True})
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, email=EMAIL)

    ctx = Ctx()

    await h.run_confirmed_intent(ctx, step.token)
    assert "already" in ctx.said[0].lower()


async def test_the_resolver_being_down_does_not_crash_the_chat():
    from clients.tasks import TasksAPIError
    tasks = FakeTasks(raises=TasksAPIError(0, "tasks service unreachable"))
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, email=EMAIL)
    assert step.kind != "confirm"
    assert step.text, "say something rather than nothing"
