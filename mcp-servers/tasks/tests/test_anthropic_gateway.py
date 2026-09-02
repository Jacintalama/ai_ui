"""Every raw call to the Anthropic Messages API goes through one gateway helper.

Why. On 2026-09-02 the platform had three places that spoke to Anthropic, and
they disagreed about where Anthropic was:

- The build agent (Claude Code CLI) and the video pipeline (`anthropic`
  SDK) both honoured `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`, so when the
  Anthropic key ran out of credit they were pointed at OpenRouter with one
  environment change and kept working. Proven from inside the tasks container:
  `claude-opus-4-8` answered via `anthropic/claude-opus-4.8`.
- `routes_tasks.py::chat` (the App Builder chat box) and `fusion_engine.py`
  used raw httpx with the host `https://api.anthropic.com` **as a string
  literal** and `x-api-key` only. The same environment change did nothing for
  them; they kept sending the dead key to the dead host.

So the same container was half on OpenRouter and half broken, and nothing said
so. This module pins the rule: raw callers build the URL and the auth headers
from the environment, the same way the SDK does, so one toggle moves all of
them. Two SDK behaviours are copied deliberately because they are what made the
video probe work:

1. When BOTH `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are set, the SDK
   sends both `x-api-key` and `Authorization: Bearer`. Anthropic reads the
   first, OpenRouter reads the second, and neither objects to the other. That is
   why a dead key sitting next to a live token did not break anything.
2. The base URL must not end in `/v1` and get `/v1/messages` appended, or you
   get `/v1/v1/messages` and a 404 that the CLI misreports as a missing model.
   The helper tolerates a base that already ends in `/v1`.
"""
import inspect
import json

import httpx
import pytest
from fastapi import HTTPException

import anthropic_gateway as gw
import fusion_engine
import routes_tasks


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------

def test_no_override_means_anthropic():
    assert gw.messages_url() == "https://api.anthropic.com/v1/messages"


def test_base_url_override_gets_v1_messages_appended(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    assert gw.messages_url() == "https://openrouter.ai/api/v1/messages"


def test_trailing_slash_on_the_base_is_harmless(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api/")
    assert gw.messages_url() == "https://openrouter.ai/api/v1/messages"


def test_a_base_that_already_ends_in_v1_is_not_doubled(monkeypatch):
    """The exact trap the CLI has: `.../api/v1` + `/v1/messages` = 404."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api/v1")
    assert gw.messages_url() == "https://openrouter.ai/api/v1/messages"


def test_an_empty_override_is_the_same_as_none(monkeypatch):
    """compose passes `${AGENT_BASE_URL:-}`, so unset arrives as empty string."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "")
    assert gw.messages_url() == "https://api.anthropic.com/v1/messages"


# ---------------------------------------------------------------------------
# Auth headers, mirroring the SDK
# ---------------------------------------------------------------------------

def test_key_only_sends_x_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1")
    assert gw.auth_headers() == {"x-api-key": "sk-ant-1"}


def test_token_only_sends_bearer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-or-1")
    assert gw.auth_headers() == {"Authorization": "Bearer sk-or-1"}


def test_both_send_both_like_the_sdk(monkeypatch):
    """A dead key beside a live token must not break the live token."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dead")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-or-live")
    h = gw.auth_headers()
    assert h["x-api-key"] == "sk-ant-dead"
    assert h["Authorization"] == "Bearer sk-or-live"


def test_neither_means_not_configured():
    assert gw.auth_headers() == {}
    assert gw.configured() is False


@pytest.mark.parametrize("var", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_either_credential_counts_as_configured(monkeypatch, var):
    monkeypatch.setenv(var, "x")
    assert gw.configured() is True


def test_blank_credentials_do_not_count(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "  ")
    assert gw.configured() is False


# ---------------------------------------------------------------------------
# The two raw callers use it
# ---------------------------------------------------------------------------

def _capturing_client(captured: dict, status: int = 200, body: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content or b"{}")
        return httpx.Response(status, json=body if body is not None else {
            "content": [{"type": "text", "text": "hello from the model"}]})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_neither_caller_hardcodes_the_anthropic_host():
    """The literal host was the bug. It may exist only in the gateway module."""
    assert "api.anthropic.com" not in inspect.getsource(routes_tasks)
    assert "api.anthropic.com" not in inspect.getsource(fusion_engine)


async def test_the_chat_seam_follows_the_gateway(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-or-live")
    captured: dict = {}
    reply = await routes_tasks._ask_anthropic(
        "you are a test", [{"role": "user", "content": "hi"}],
        client=_capturing_client(captured))
    assert reply == "hello from the model"
    assert captured["url"] == "https://openrouter.ai/api/v1/messages"
    assert captured["headers"]["authorization"] == "Bearer sk-or-live"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"


async def test_the_chat_seam_keeps_its_model_and_shape(monkeypatch):
    """Haiku, 700 tokens, system + messages. Verified resolvable on OpenRouter
    under this exact dated id on 2026-09-02, so no rename is needed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1")
    captured: dict = {}
    await routes_tasks._ask_anthropic(
        "sys", [{"role": "user", "content": "hi"}], client=_capturing_client(captured))
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-1"
    assert captured["json"]["model"] == "claude-haiku-4-5-20251001"
    assert captured["json"]["max_tokens"] == 700
    assert captured["json"]["system"] == "sys"
    assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]


async def test_the_chat_seam_maps_upstream_failure_to_502(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1")
    with pytest.raises(HTTPException) as e:
        await routes_tasks._ask_anthropic(
            "sys", [{"role": "user", "content": "hi"}],
            client=_capturing_client({}, status=400, body={"error": "credit balance is too low"}))
    assert e.value.status_code == 502
    assert "400" in e.value.detail


async def test_the_chat_seam_maps_transport_failure_to_502(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1")

    def boom(request):
        raise httpx.ConnectError("down")
    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    with pytest.raises(HTTPException) as e:
        await routes_tasks._ask_anthropic("sys", [{"role": "user", "content": "hi"}], client=client)
    assert e.value.status_code == 502


async def test_the_chat_seam_reports_an_empty_reply_honestly(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1")
    reply = await routes_tasks._ask_anthropic(
        "sys", [{"role": "user", "content": "hi"}],
        client=_capturing_client({}, body={"content": []}))
    assert reply == "(no reply generated)"


def test_the_chat_route_refuses_only_when_no_credential_exists():
    """The 503 used to key on ANTHROPIC_API_KEY alone, so a token-only gateway
    setup was refused as 'not configured' before it ever sent a request."""
    src = inspect.getsource(routes_tasks.chat)
    assert "anthropic_gateway.configured()" in src
    assert 'os.environ.get("ANTHROPIC_API_KEY")' not in src


async def test_fusion_follows_the_gateway_for_anthropic_models(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-or-live")
    captured: dict = {}
    text = await fusion_engine.call_model(
        "claude-sonnet-5", [{"role": "user", "content": "hi"}],
        max_tokens=10, timeout_s=5, client=_capturing_client(captured))
    assert text == "hello from the model"
    assert captured["url"] == "https://openrouter.ai/api/v1/messages"
    assert captured["headers"]["authorization"] == "Bearer sk-or-live"
    assert captured["json"]["model"] == "claude-sonnet-5"
