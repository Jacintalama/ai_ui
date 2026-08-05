"""The resolve route: read-only, owner-scoped, and it must never mutate.

Full behavior needs the DB tier; this pins the contract that can be checked
without it. Assert via app.openapi(), NOT app.routes — container FastAPI 0.139
includes routers lazily (memory lesson).
"""
import inspect

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


def test_resolve_never_calls_the_thing_that_mutates():
    """The whole point of a separate resolve step: the user sees the target
    before anything is written. Guard by source, so a future edit that wires
    rollback_app_core in here fails loudly."""
    src = inspect.getsource(routes_aiuibuilder.resolve_rollback_target)
    assert "rollback_app_core" not in src, (
        "resolve must not roll back — it exists so the user can confirm first")
    for verb in ("checkout", "commit"):
        assert verb not in src, f"resolve must not run git {verb}"


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
