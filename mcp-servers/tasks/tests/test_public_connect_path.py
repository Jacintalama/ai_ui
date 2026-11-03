"""The one URL of ours that a person connecting ever sees.

An OAuth callback is not an internal route. It sits in the address bar
while somebody decides whether to trust us with their Trello or their
GitHub, and it is the string that gets registered with the vendor and then
shown on the vendor's own consent screen. It used to read:

    /api/tasks/connections/github/oauth/callback

Nothing about that was broken and nothing in it restricted anybody: it is
the gateway's prefix for a container that happens to be called `tasks`.
But "api/tasks" is the name of a container and a database schema, and a
person deciding whether to trust us should not be reading our plumbing to
do it. It reads this now:

    /connect/github/callback

Asked for on 2026-11-03, before the GitHub app was registered, because a
callback is awkward to change once a vendor has it.

**The old path still answers, and must.** Trello's one-click is live and
its tokens were issued against the old URL, and a registered callback that
stops answering is a connect that fails with nothing on screen to explain
it. One handler, two paths; the alias delegates rather than duplicating,
because that handler decides who a grant belongs to and a second copy
would be a second thing to keep right.

Four layers have to agree for this to work at all, which is why they are
all checked here: Caddy lets /connect/* through, the gateway sends it to
tasks, tasks serves it, and the redirect builder hands the vendor the same
string.
"""
import os
import re

import pytest

import routes_connections as R

HERE = os.path.dirname(__file__)
GATEWAY = os.path.join(HERE, "..", "..", "..", "api-gateway", "main.py")
CADDYFILE = os.path.join(HERE, "..", "..", "..", "Caddyfile")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --- what the vendor is told --------------------------------------------------

def test_the_registered_callback_says_what_it_does():
    assert (R._redirect_uri("github")
            == "https://ai-ui.coolestdomain.win/connect/github/callback")


@pytest.mark.parametrize("pid", ["github", "clickup", "notion", "trello"])
def test_every_app_gets_the_same_shape(pid):
    """A per-vendor special case is how one of them ends up registered with
    a URL nothing serves."""
    assert R._redirect_uri(pid).endswith("/connect/" + pid + "/callback")


def test_the_plumbing_is_not_in_the_url_any_more():
    url = R._redirect_uri("github")
    assert "/api/tasks" not in url
    assert "oauth" not in url, "nor the protocol, which is ours to know"


# --- both paths answer --------------------------------------------------------

def test_the_clean_path_is_served():
    paths = [r.path for r in R.public_router.routes]
    assert "/connect/{provider_id}/callback" in paths


def test_the_old_path_is_still_served():
    """Trello's tokens were issued against it. A registered callback that
    stops answering is a connect that fails with nothing to explain it."""
    # The router carries its own /connections prefix, and main.py mounts it
    # a second time under /api/tasks, which is where the public old URL
    # comes from.
    paths = [r.path for r in R.router.routes]
    assert "/connections/{provider_id}/oauth/callback" in paths


def test_there_is_one_handler_and_not_two():
    """The alias delegates. This handler decides whose grant a callback is,
    and two copies of that is two things to keep right."""
    import inspect
    body = inspect.getsource(R.oauth_callback_public)
    assert "oauth_callback(" in body
    assert "STATES.consume" not in body, "the alias is deciding things itself"


# --- the thing that would have broken quietly ---------------------------------

def test_the_trello_page_posts_to_an_absolute_url():
    """The page served at the callback reads Trello's token out of the
    fragment and posts it back. If it posted to a RELATIVE path, moving the
    page from /api/tasks/connections/... to /connect/... would have sent
    that token to a URL nothing serves, and the only symptom would have
    been the connect silently failing at the last step.

    It is absolute, so the page can be served from anywhere. Pinned,
    because the next person to move it will not think to check.
    """
    body = R._trello_catch_fragment("s1").body.decode("utf-8")
    assert "/api/tasks/connections/trello/oauth/token" in body
    assert not re.search(r"fetch\(['\"](?!/|https?:)", body), (
        "a relative fetch here breaks the moment the page is moved")


# --- the layers in front ------------------------------------------------------

def test_the_gateway_sends_connect_to_tasks():
    """Structural, because the gateway is a separate service with its own
    build context and is not importable from here."""
    src = _read(GATEWAY)
    branch = re.search(r'full_path\.startswith\("/connect/"\)\s*:\s*\n'
                       r'\s*backend_url = os\.getenv\("TASKS_URL"', src)
    assert branch, "/connect/ does not reach the tasks service"


def test_the_gateway_forwards_the_path_intact():
    """tasks mounts /connect/<app>/callback at its own root, so a stripped
    prefix would 404 after everything else had worked."""
    src = _read(GATEWAY)
    # THIS branch only, up to the next one. A fixed window spills into the
    # branch below, which assigns the same thing, so the test passed while
    # the prefix was being stripped.
    rest = src[src.index('full_path.startswith("/connect/")'):]
    branch = rest[:rest.index("\n    elif ")]
    # The whole statement, not a substring of it: `full_path[8:]` contains
    # "backend_path = full_path" and would have read as a pass while
    # forwarding /github/callback to a service that serves no such path.
    assert re.search(r"backend_path = full_path\s*(\n|#)", branch), (
        "the prefix is being altered before it reaches tasks")


def test_caddy_lets_connect_through():
    """Without this the path never reaches the gateway at all and lands on
    Open WebUI, which renders its own 404 for it."""
    assert re.search(r"handle /connect/\*\s*\{", _read(CADDYFILE))


def test_the_identity_headers_are_stripped_for_every_route():
    """The callback is authenticated by its signed state, not the session,
    so it must be reachable by a logged-out browser. That is only safe
    because the gateway strips client-supplied identity headers on the way
    through, for every route rather than per route."""
    src = _read(GATEWAY)
    stripped = src[src.index("_STRIPPED = {"):][:600]
    for header in ("x-user-email", "x-user-admin", "x-gateway-validated"):
        assert header in stripped, header
