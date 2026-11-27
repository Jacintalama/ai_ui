"""write_skill asks a model to draft, which took 9 to 19 s on 2026-11-26.

The Skills tool gave every call 20 s, so a slow draft was cut off and the
person read "Could not write that skill just now: " with nothing after it
(an httpx timeout has an empty message). Live: Dev called it twice from the
Save as your skill button and both failed that way.
"""
import importlib.util
import pathlib

import httpx


def _skills_tool():
    path = (pathlib.Path(__file__).resolve().parents[3]
            / "open-webui-functions" / "skills_tool.py")
    spec = importlib.util.spec_from_file_location("skills_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Tools()


class _Client:
    """Stands in for httpx.AsyncClient and records the timeout it was given."""
    seen: list = []

    def __init__(self, timeout=None, **_):
        _Client.seen.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        raise httpx.ReadTimeout("")


async def test_the_draft_gets_a_minute_and_a_short_call_does_not(monkeypatch):
    tool = _skills_tool()
    _Client.seen = []
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    await tool.write_skill("summarise a webhook", __user__={"email": "r@example.com"})
    await tool.save_skill("abc", __user__={"email": "r@example.com"})
    assert _Client.seen[0] >= 60
    assert _Client.seen[1] == tool.valves.timeout_seconds


async def test_a_slow_draft_says_so_and_that_nothing_was_saved(monkeypatch):
    tool = _skills_tool()
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    said = await tool.write_skill("summarise a webhook", __user__={"email": "r@example.com"})
    assert said == ("The skill writer took too long this time. Nothing was "
                    "saved. Ask me to try again.")


async def test_another_failure_still_names_what_went_wrong(monkeypatch):
    tool = _skills_tool()

    async def down(path, payload, email, timeout=None):
        raise httpx.ConnectError("")
    tool._post = down
    said = await tool.write_skill("summarise a webhook", __user__={"email": "r@example.com"})
    assert said == "Could not write that skill just now: ConnectError"
