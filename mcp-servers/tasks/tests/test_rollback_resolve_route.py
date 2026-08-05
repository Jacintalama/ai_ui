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
    assert "choose_rollback_target" in src
