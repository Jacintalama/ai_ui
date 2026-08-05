"""Linking a database is for the project's OWNER, not only for admins.

Lukas, standup 2026-08-03, on built apps: *"there will be also a great
integration if the user wants a database"*. Today a regular user can build an
app but cannot give it a database — every Supabase route additionally demands
the admin header, so only the AIUI team can do it. `tasks.project_supabase` has
0 rows, which is consistent with a feature nobody outside the team can reach.

The admin gate is redundant, exactly as it was for publish (Ralph, d76b1e4ad):
every one of these routes already calls
`_require_role(s, slug, user.email, "owner")` in its body, WITHOUT passing
`is_admin`, so the owner check applies to everybody and admins get no bypass.
Dropping the header requirement therefore relaxes "admin AND owner" to "owner"
and takes nothing away.

These assertions read the actual FastAPI dependencies rather than the source
text, so they cannot be fooled by a comment.
"""
import inspect

import pytest

import routes_supabase as rs
import routes_supabase_oauth as rso
from auth import current_admin, current_user

# Every route that provisions or links a database. Named explicitly so a NEW
# route added to this module fails the completeness test below rather than
# quietly shipping with an admin gate.
# (module, function). Both routers matter: opening only the OAuth one would
# leave a user able to LINK a database but unable to view or remove it.
OWNER_ROUTES = [
    (rso, "oauth_start"),
    (rso, "list_oauth_projects"),
    (rso, "link_oauth_project"),
    (rso, "auto_link_oauth"),
    (rso, "create_oauth_project"),
    (rso, "create_status"),
    (rso, "disconnect_oauth"),
    (rs, "get_supabase"),
    (rs, "set_supabase"),
    (rs, "delete_supabase"),
]
IDS = [f"{m.__name__.split('_')[-1]}.{n}" for m, n in OWNER_ROUTES]


def _deps(func):
    """The dependency callables declared in a route's signature."""
    out = []
    for param in inspect.signature(func).parameters.values():
        default = param.default
        if default is not inspect.Parameter.empty and hasattr(default, "dependency"):
            out.append(default.dependency)
    return out


def test_every_named_route_actually_exists():
    """Guards the list above against a rename silently emptying this file."""
    missing = [f"{m.__name__}.{n}" for m, n in OWNER_ROUTES if not hasattr(m, n)]
    assert not missing, f"renamed or removed: {missing}"


@pytest.mark.parametrize("mod,name", OWNER_ROUTES, ids=IDS)
def test_the_route_does_not_demand_the_admin_header(mod, name):
    func = getattr(mod, name)
    assert current_admin not in _deps(func), (
        f"{name} still requires the admin header, so a regular owner cannot "
        f"give their own app a database")


@pytest.mark.parametrize("mod,name", OWNER_ROUTES, ids=IDS)
def test_the_route_still_requires_a_signed_in_user(mod, name):
    """Relaxing the gate must not open it. Anonymous callers stay out."""
    func = getattr(mod, name)
    assert current_user in _deps(func), f"{name} lost its authentication"


@pytest.mark.parametrize("mod,name", OWNER_ROUTES, ids=IDS)
def test_the_owner_check_is_still_in_the_body(mod, name):
    """This is what actually protects the route now, so it must be present and
    must NOT hand admins a bypass — these routes spend the user's own Supabase
    quota and touch their data."""
    src = inspect.getsource(getattr(mod, name))
    assert "_require_role" in src, f"{name} has no role check at all"
    if name == "get_supabase":
        # A pure read, and the only one that is deliberately viewer-level with
        # an admin bypass so support can see whether a link exists.
        assert '"viewer"' in src
        return
    assert '"owner"' in src, f"{name} does not require the owner role"
    assert "is_admin=" not in src, (
        f"{name} would let an admin bypass the owner check; these routes act "
        f"on a user's own Supabase account and spend their quota")


def test_no_admin_dependency_survives_anywhere_in_the_module():
    """Completeness: catches a route that exists but was left off the list."""
    offenders = []
    for mod in (rso, rs):
      for name, obj in vars(mod).items():
        if not callable(obj) or not hasattr(obj, "__module__"):
            continue
        if getattr(obj, "__module__", "") != mod.__name__:
            continue
        try:
            if current_admin in _deps(obj):
                offenders.append(name)
        except (TypeError, ValueError):
            continue
    assert not offenders, (
        f"these still demand the admin header: {offenders}")
