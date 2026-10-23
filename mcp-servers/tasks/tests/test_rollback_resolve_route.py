"""The resolve route: read-only, owner-scoped, and it must never mutate.

Full behavior needs the DB tier; this pins the contract that can be checked
without it. Assert via app.openapi(), NOT app.routes — container FastAPI 0.139
includes routers lazily (memory lesson).
"""
import ast
import inspect
import textwrap

import routes_aiuibuilder
from main import app

PATH = "/api/aiuibuilder/{slug}/rollback/resolve"


def test_resolve_route_is_registered():
    assert PATH in set(app.openapi()["paths"].keys())


def test_resolve_is_a_get_not_a_post():
    """A GET is the contract that it changes nothing. If this ever becomes a
    POST, that promise is silently gone."""
    spec = app.openapi()["paths"][PATH]
    assert "get" in spec
    assert "post" not in spec, "resolving must stay side-effect free"


def test_resolve_takes_the_phrase_as_a_parameter():
    spec = app.openapi()["paths"][PATH]["get"]
    names = {p["name"] for p in spec.get("parameters", [])}
    assert "phrase" in names
    assert "slug" in names


def _called_names(func) -> set[str]:
    """Every name this function calls, via AST.

    Rewritten after review, which pointed out that grepping the source for
    "commit" fires on an innocent docstring edit (it did, immediately) while
    still passing if the mutation moved into a helper. Parsing the calls is
    both stricter and quieter.
    """
    src = textwrap.dedent(inspect.getsource(func))
    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            target = node.func
            while isinstance(target, ast.Attribute):
                names.add(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_resolve_never_calls_the_thing_that_mutates():
    """The whole point of a separate resolve step: the user sees the target
    before anything is written."""
    called = _called_names(routes_aiuibuilder.resolve_rollback_target)
    assert "rollback_app_core" not in called, (
        "resolve must not roll back — it exists so the user can confirm first")
    assert "_run_git" not in called, "resolve must not touch git directly"


def test_resolve_only_calls_things_that_read():
    """Whitelist rather than blacklist: a NEW mutating helper is caught even
    though nobody thought to ban it by name."""
    allowed = {
        "_validate_slug", "session", "_user_can_see_project", "_require_role",
        "list_app_versions_core", "choose_rollback_target", "model_dump",
        "_resolve",  # the picker, then Jev on a paraphrase; reads only
        "HTTPException", "Depends", "current_user", "Query", "get",
        "router", "v",  # the route decorator and a comprehension variable
    }
    unexpected = _called_names(routes_aiuibuilder.resolve_rollback_target) - allowed
    assert not unexpected, (
        f"resolve gained calls nobody vetted: {sorted(unexpected)}. If they "
        f"read only, add them to the whitelist.")


def test_resolve_is_owner_scoped_like_the_rollback_route():
    """Version history plus failure reasons is not public information."""
    src = inspect.getsource(routes_aiuibuilder.resolve_rollback_target)
    assert "_user_can_see_project" in src
    assert '_require_role' in src and '"owner"' in src


def test_resolve_uses_the_shared_version_list_not_its_own_git_call():
    """list_app_versions_core is what computes the ok/error/rollback status the
    picker depends on. A private git log here would lose it."""
    src = inspect.getsource(routes_aiuibuilder.resolve_rollback_target)
    assert "list_app_versions_core" in src
    assert "_resolve" in src
    # The rules still decide first; Jev only ever follows them.
    assert "choose_rollback_target" in inspect.getsource(
        routes_aiuibuilder._resolve)


# --- Jev on a paraphrase (agent_jev.rollback_version) -----------------------

import pytest  # noqa: E402

import agent_jev  # noqa: E402


def _v(c, message, status="ok"):
    return {"sha": c * 40, "short_sha": c * 7, "message": message,
            "status": status, "is_current": False}


HISTORY = [_v("e", "add cart"), _v("d", "add checkout"),
           _v("c", "style the header"), _v("a", "Initial build")]


@pytest.fixture
def jev(monkeypatch):
    asked = []
    state = {"pick": None}

    async def rollback_version(email, phrase, versions):
        asked.append((email, phrase, versions))
        return state["pick"]

    monkeypatch.setattr(agent_jev, "rollback_version", rollback_version)
    return asked, state


async def test_jev_names_where_a_paraphrase_arrived(jev):
    asked, state = jev
    state["pick"] = HISTORY[1]            # "add checkout"
    got = await routes_aiuibuilder._resolve(
        "o@example.com", HISTORY, "go back to before the payment step", "shop")
    assert got.target is HISTORY[2]
    assert asked[0][:2] == ("o@example.com",
                            "go back to before the payment step")


async def test_jev_unsure_leaves_the_question_to_the_person(jev):
    asked, _ = jev
    got = await routes_aiuibuilder._resolve(
        "o@example.com", HISTORY, "go back to before the payment step", "shop")
    assert got.needs_user_choice and got.target is None
    assert len(asked) == 1


async def test_jev_is_not_asked_when_a_rule_decided(jev):
    asked, _ = jev
    got = await routes_aiuibuilder._resolve(
        "o@example.com", HISTORY, "go back to before the checkout", "shop")
    assert got.target is HISTORY[2]
    assert asked == []


async def test_jev_is_not_asked_when_the_person_must_choose_anyway(jev):
    asked, _ = jev
    got = await routes_aiuibuilder._resolve(
        "o@example.com", HISTORY, "which one was nice", "shop")
    assert got.needs_user_choice
    assert asked == []
