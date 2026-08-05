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

    def __init__(self, *, projects=None, resolve=None, rollback=None, raises=None,
                 resolve_second=None):
        self._projects = projects if projects is not None else [{"slug": "shop"}]
        self._resolve = resolve or {}
        # A DIFFERENT answer on the second call, so an implementation that
        # re-resolves at confirm time instead of using the pinned sha is
        # detectable. Review proved the old fake could not tell them apart.
        self._resolve_second = resolve_second
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
        if len(self.resolved) > 1 and self._resolve_second is not None:
            return self._resolve_second
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


async def _email() -> str:
    """The lazy resolver plan_chat_step now takes."""
    return EMAIL


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
    step = await h.plan_chat_step("u1", "go back to before it broke", threshold=0.6, resolve_email=_email)
    assert step.kind == "confirm"
    assert tasks.resolved == [("shop", "before it broke")]


async def test_nothing_is_rolled_back_merely_by_asking():
    """The single most important test in this file."""
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    await h.plan_chat_step("u1", "go back to before it broke", threshold=0.6, resolve_email=_email)
    assert tasks.rollbacks == [], "a rollback happened before the user confirmed"


async def test_the_confirm_shows_the_version_and_the_reason():
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "go back to before it broke", threshold=0.6, resolve_email=_email)
    assert "d4d4d4d" in step.text
    assert "add checkout" in step.text
    assert "add cart" in step.text


async def test_confirming_rolls_back_to_exactly_the_sha_that_was_shown():
    """Pinned at resolve time. If it re-resolved on confirm, a build landing in
    between would silently change the destination.

    REWRITTEN after review, which proved the old version of this test passed
    against a deliberately broken implementation that re-resolved at confirm
    time. The fake now returns a DIFFERENT version on a second resolve, so
    re-resolving is detectable, and the resolve count is asserted.
    """
    other = _version("9999999", "a build that landed after we asked")
    tasks = FakeTasks(
        resolve=RESOLVED,
        resolve_second={"target": other, "reason": "newer",
                        "needs_user_choice": False, "candidates": []},
    )
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "go back to before it broke",
                                  threshold=0.6, resolve_email=_email)

    ctx = Ctx()
    await h.run_confirmed_intent(ctx, step.token)

    assert len(tasks.resolved) == 1, (
        f"re-resolved at confirm time ({len(tasks.resolved)} resolves); the "
        "shown sha must be the one used")
    assert tasks.rollbacks == [("shop", _version()["sha"])]
    assert tasks.rollbacks[0][1] != other["sha"], "used the newer version"
    assert ctx.said and "shop" in ctx.said[0]


# ---------------------------------------------------------------------------
# Which app? Never guess between two.
# ---------------------------------------------------------------------------

async def test_the_only_app_is_used_when_the_user_names_none():
    tasks = FakeTasks(projects=[{"slug": "shop"}], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent(app=""))
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, resolve_email=_email)
    assert step.kind == "confirm"
    assert tasks.resolved[0][0] == "shop"


async def test_a_named_app_is_used_even_when_several_exist():
    tasks = FakeTasks(projects=[{"slug": "shop"}, {"slug": "blog"}], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent(app="blog"))
    step = await h.plan_chat_step("u1", "roll blog back", threshold=0.6, resolve_email=_email)
    assert tasks.resolved[0][0] == "blog"
    assert step.kind == "confirm"


async def test_two_apps_and_no_name_asks_instead_of_guessing():
    tasks = FakeTasks(projects=[{"slug": "shop"}, {"slug": "blog"}], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent(app=""))
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, resolve_email=_email)
    assert step.kind != "confirm"
    assert "shop" in step.text and "blog" in step.text
    assert tasks.rollbacks == []


async def test_no_apps_at_all_says_so_plainly():
    tasks = FakeTasks(projects=[], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, resolve_email=_email)
    assert step.kind != "confirm"
    assert "built" in step.text.lower() or "no app" in step.text.lower()


async def test_a_named_app_the_user_does_not_own_is_not_silently_swapped():
    tasks = FakeTasks(projects=[{"slug": "shop"}], resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent(app="somebody-elses-app"))
    step = await h.plan_chat_step("u1", "roll it back", threshold=0.6, resolve_email=_email)
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
    step = await h.plan_chat_step("u1", "make it blue again", threshold=0.6, resolve_email=_email)
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
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, resolve_email=_email)
    assert step.kind != "confirm"
    assert "nothing to go back to" in step.text


# ---------------------------------------------------------------------------
# Failures become sentences.
# ---------------------------------------------------------------------------

async def test_a_dirty_tree_is_explained_not_dumped():
    from clients.tasks import TasksAPIError
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, resolve_email=_email)
    tasks._raises = TasksAPIError(409, "apps/shop/ has uncommitted changes")

    ctx = Ctx()

    await h.run_confirmed_intent(ctx, step.token)
    assert ctx.said, "the user must be told something"
    assert "Traceback" not in ctx.said[0]
    assert "unsaved" in ctx.said[0].lower() or "changes" in ctx.said[0].lower()


async def test_a_noop_does_not_claim_a_rollback_happened():
    tasks = FakeTasks(resolve=RESOLVED, rollback={"ok": True, "noop": True})
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, resolve_email=_email)

    ctx = Ctx()

    await h.run_confirmed_intent(ctx, step.token)
    assert "already" in ctx.said[0].lower()


async def test_the_resolver_being_down_does_not_crash_the_chat():
    from clients.tasks import TasksAPIError
    tasks = FakeTasks(raises=TasksAPIError(0, "tasks service unreachable"))
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6, resolve_email=_email)
    assert step.kind != "confirm"
    assert step.text, "say something rather than nothing"


# ---------------------------------------------------------------------------
# Review follow-ups: the model ranking is now wired, email is resolved lazily,
# and a non-owner hears the real reason.
# ---------------------------------------------------------------------------

class FakeOWUI:
    """Stands in for the model. Records whether it was consulted at all."""

    def __init__(self, reply=""):
        self.reply = reply
        self.calls: list[list[dict]] = []

    async def chat_completion(self, messages, model=None, **kw):
        self.calls.append(messages)
        return self.reply


UNDECIDED = {
    "target": None, "reason": "Which version should I go back to?",
    "needs_user_choice": True,
    "candidates": [_version("d4d4d4d", "add payment flow"),
                   _version("c3c3c3c", "restyle the header")],
}


async def test_the_model_ranks_candidates_when_the_rules_cannot_decide():
    """The paraphrase capability the spec is built around. Review found it was
    dead code with no production caller."""
    tasks = FakeTasks(resolve=UNDECIDED)
    h = _handlers(tasks, _rollback_intent(point="before the checkout thing"))
    h.openwebui = FakeOWUI('{"sha": "d4d4d4d"}')
    step = await h.plan_chat_step("u1", "before the checkout thing",
                                  threshold=0.6, resolve_email=_email)
    assert h.openwebui.calls, "the model was never consulted"
    assert step.kind == "confirm"
    assert "add payment flow" in step.text


async def test_a_model_pick_outside_the_candidates_falls_back_to_the_list():
    tasks = FakeTasks(resolve=UNDECIDED)
    h = _handlers(tasks, _rollback_intent(point="something odd"))
    h.openwebui = FakeOWUI('{"sha": "deadbeef1234567"}')
    step = await h.plan_chat_step("u1", "something odd",
                                  threshold=0.6, resolve_email=_email)
    assert step.kind != "confirm"
    assert "add payment flow" in step.text and "restyle the header" in step.text
    assert tasks.rollbacks == []


async def test_the_model_failing_still_shows_the_list():
    class Boom:
        async def chat_completion(self, *a, **k):
            raise RuntimeError("model down")

    tasks = FakeTasks(resolve=UNDECIDED)
    h = _handlers(tasks, _rollback_intent(point="something odd"))
    h.openwebui = Boom()
    step = await h.plan_chat_step("u1", "something odd",
                                  threshold=0.6, resolve_email=_email)
    assert step.kind != "confirm"
    assert "add payment flow" in step.text


async def test_the_model_is_not_consulted_when_the_rules_already_decided():
    """No LLM call on the common path — it is both slower and less certain."""
    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    h.openwebui = FakeOWUI('{"sha": "d4d4d4d"}')
    await h.plan_chat_step("u1", "go back to before it broke",
                           threshold=0.6, resolve_email=_email)
    assert h.openwebui.calls == []


async def test_email_is_not_resolved_for_an_ordinary_question():
    """Regression guard. Resolving eagerly put an HTTP call (Discord) or a
    rate-limited users.info (Slack) on the hot path of every chat message, and
    Discord's resolver can raise JSONDecodeError, which would have broken plain
    chat replies."""
    calls = []

    async def _counting_email():
        calls.append(1)
        return EMAIL

    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, intent_router.IntentResult("question", 0.9, "what is python"))
    await h.plan_chat_step("u1", "what is python", threshold=0.6,
                           resolve_email=_counting_email)
    assert calls == [], "resolved identity for a message that never needed it"


async def test_a_broken_email_resolver_does_not_crash_the_rollback():
    async def _boom():
        raise ValueError("Expecting value: line 1 column 1")

    tasks = FakeTasks(resolve=RESOLVED)
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6,
                                  resolve_email=_boom)
    assert step.kind != "confirm"
    assert step.text


async def test_a_member_who_is_not_the_owner_hears_the_real_reason():
    """list_projects is membership-scoped but resolve requires owner, so a
    viewer on a shared app used to be told the service was down."""
    from clients.tasks import TasksAPIError
    tasks = FakeTasks(raises=TasksAPIError(403, "Requires role owner"))
    h = _handlers(tasks, _rollback_intent())
    step = await h.plan_chat_step("u1", "undo that", threshold=0.6,
                                  resolve_email=_email)
    assert "owner" in step.text.lower()
    assert "couldn't reach" not in step.text.lower()
