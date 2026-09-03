"""What the code tool is allowed to do without being asked twice.

The classifier decides what an unattended agent may run, so its answer for
these five names is a security decision, not a naming detail.
"""
import os
import re

import httpx

from agent_tools import READ_METHODS, is_write_tool

TOOL = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "open-webui-functions", "code_tool.py")


def _source():
    with open(TOOL, encoding="utf-8") as fh:
        return fh.read()


def _tool(handler):
    """The real Tools object with its HTTP calls captured. Loads the
    file the same way the structural tests read it, so these exercise
    the shipped source rather than a copy."""
    ns = {"__name__": "code_tool_under_test"}
    exec(open(TOOL, encoding="utf-8").read(), ns)
    tools = ns["Tools"]()
    tools.valves.tasks_url = "http://tasks:8210"
    tools.valves.internal_secret = "test-secret"

    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    return tools, _factory


USER = {"email": "someone@example.com"}


def test_reading_is_never_a_write():
    for name in ("list_my_apps", "read_app_file", "search_my_app"):
        assert is_write_tool(name) is False, name


def test_proposing_is_not_a_write():
    """It writes a token row and changes nothing an app owner would
    notice. A Read only agent must be able to say what it would change."""
    assert is_write_tool("propose_app_change") is False
    assert "propose_app_change" in READ_METHODS


def test_applying_is_a_write():
    """The one call that can start a build. If this ever reads as a read,
    an unattended Read only agent could change a live app."""
    assert is_write_tool("apply_app_change") is True
    assert "apply_app_change" not in READ_METHODS


def test_the_tool_exposes_exactly_the_five_functions():
    source = _source()
    # Excludes a leading underscore so a private helper such as _call,
    # which is also "async def _call(self", is not counted as a sixth
    # public function.
    found = {name for name in re.findall(r"async def (\w+)\(self", source)
             if not name.startswith("_")}
    assert found == {"list_my_apps", "read_app_file", "search_my_app",
                     "propose_app_change", "apply_app_change"}


def test_the_tool_holds_no_filesystem_or_routing_logic():
    """Every decision belongs to the service, so Discord, Telegram and
    the web chat all answer the same way. A path check here would be a
    second, divergent copy of the one in app_code_access, which is the
    exact shape that produced this feature's worst defects."""
    source = _source()
    assert "os.path" not in source
    assert "pathlib" not in source
    assert "open(" not in source
    assert "resolve" not in source


def test_the_tool_never_deletes():
    source = _source().lower()
    for word in ("delete", "unlink", "rmtree", "remove"):
        assert word not in source, word


def test_apply_takes_only_a_token():
    """A slug argument here would invite the model to pick the app at
    confirm time, which is exactly what the stored proposal prevents.
    Checks the exact parameter list, not just the literal spelling
    "slug", so renaming that argument (to "app", say) cannot satisfy
    this by accident. test_apply_sends_only_the_email_and_the_token
    backs this up on the actual wire."""
    source = _source()
    match = re.search(r"async def apply_app_change\(self,\s*([^)]*)\)", source)
    assert match
    params = {p.split(":")[0].strip() for p in match.group(1).split(",")}
    assert params == {"token", "__user__"}


async def test_every_call_hits_the_endpoint_it_should(monkeypatch):
    """The five calls and their exact wire shape. Renaming a parameter,
    changing a path, or switching a method are all invisible to a test
    that greps the source, and all five ship a tool that cannot work."""
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path,
                     dict(request.url.params),
                     request.headers.get("X-Internal-Secret")))
        return httpx.Response(200, json={
            "apps": ["shop"], "text": "hi", "matches": [],
            "token": "abc", "slug": "shop", "description": "make it blue"})

    tools, factory = _tool(handler)
    monkeypatch.setattr(httpx, "AsyncClient", factory)

    await tools.list_my_apps(__user__=USER)
    await tools.read_app_file("shop", "index.html", __user__=USER)
    await tools.search_my_app("shop", "button", __user__=USER)
    await tools.propose_app_change("shop", "make it blue", __user__=USER)
    await tools.apply_app_change("abc", __user__=USER)

    methods_and_paths = [(m, p) for m, p, _, _ in seen]
    assert methods_and_paths == [
        ("GET", "/code/apps"),
        ("GET", "/code/file"),
        ("GET", "/code/search"),
        ("POST", "/code/propose"),
        ("POST", "/code/apply"),
    ]
    assert all(secret == "test-secret" for _, _, _, secret in seen)
    assert seen[0][2] == {"user_email": "someone@example.com"}
    assert seen[1][2] == {"user_email": "someone@example.com",
                          "slug": "shop", "path": "index.html"}
    assert seen[2][2] == {"user_email": "someone@example.com",
                          "slug": "shop", "query": "button"}


async def test_apply_sends_only_the_email_and_the_token(monkeypatch):
    """Task 4 deleted ApplyIn.slug, and pydantic drops unknown fields
    silently rather than erroring, so an extra field here would be lost
    without a sound. Assert the body, not the signature."""
    bodies = []

    def handler(request):
        import json as _json
        bodies.append(_json.loads(request.content))
        return httpx.Response(200, json={"task_id": "t", "slug": "shop",
                                         "description": "make it blue"})

    tools, factory = _tool(handler)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    await tools.apply_app_change("abc", __user__=USER)
    assert set(bodies[0]) == {"user_email", "token"}


async def test_propose_shows_the_servers_description_not_its_own(monkeypatch):
    """The person approves what the server stored. If the tool printed
    its own argument, a change normalised differently on the way in
    would be approved as one thing and run as another."""
    def handler(request):
        return httpx.Response(200, json={"token": "abc", "slug": "shop",
                                         "description": "WHAT WAS STORED"})

    tools, factory = _tool(handler)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    out = await tools.propose_app_change("shop", "what the model typed",
                                         __user__=USER)
    assert "WHAT WAS STORED" in out
    assert "what the model typed" not in out


async def test_an_anonymous_caller_reaches_nothing(monkeypatch):
    """No email means no request at all, not a request without one."""
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={})

    tools, factory = _tool(handler)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    for coro in (tools.list_my_apps(__user__={}),
                 tools.read_app_file("shop", "x", __user__={}),
                 tools.apply_app_change("abc", __user__={})):
        assert "could not tell whose account" in await coro
    assert calls == []
