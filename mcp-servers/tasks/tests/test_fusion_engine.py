import httpx
import pytest
import fusion_engine as fe


def test_registry_has_verified_models():
    for m in ["gpt-5", "gpt-5.5", "gpt-4o", "gpt-4.1", "o3",
              "claude-opus-4-8", "claude-sonnet-5", "claude-fable-5",
              "claude-haiku-4-5-20251001", "claude-opus-4-5"]:
        assert m in fe.PROVIDER_REGISTRY
    assert fe.PROVIDER_REGISTRY["gpt-5.5"].contract == "openai_new"
    assert fe.PROVIDER_REGISTRY["gpt-4o"].contract == "openai_legacy"
    assert fe.PROVIDER_REGISTRY["claude-opus-4-8"].provider == "anthropic"


def test_presets_default_and_valid():
    panel, judge = fe.resolve_preset("quality")
    assert panel == ["gpt-5.5", "claude-opus-4-8"] and judge == "claude-opus-4-8"
    panel, judge = fe.resolve_preset("budget")
    assert panel == ["gpt-4o", "claude-haiku-4-5-20251001"] and judge == "gpt-4o"
    with pytest.raises(KeyError):
        fe.resolve_preset("nope")


@pytest.mark.asyncio
async def test_call_model_openai_new_contract():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        import json
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi from gpt"}}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        out = await fe.call_model("gpt-5.5", [{"role": "user", "content": "q"}],
                                  max_tokens=100, timeout_s=5, client=client)
    assert out == "hi from gpt"
    assert "chat/completions" in captured["url"]
    assert captured["body"]["model"] == "gpt-5.5"
    assert captured["body"]["max_completion_tokens"] == 100
    assert "max_tokens" not in captured["body"]
    assert "temperature" not in captured["body"]
    assert captured["auth"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_call_model_openai_legacy_uses_max_tokens():
    def handler(request):
        import json
        b = json.loads(request.content)
        assert b["max_tokens"] == 50 and "max_completion_tokens" not in b
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await fe.call_model("gpt-4o", [{"role": "user", "content": "q"}],
                                  max_tokens=50, timeout_s=5, client=client)
    assert out == "ok"


@pytest.mark.asyncio
async def test_call_model_anthropic_contract():
    captured = {}

    def handler(request):
        import json
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["hdr"] = request.headers.get("x-api-key"), request.headers.get("anthropic-version")
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hi from claude"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await fe.call_model("claude-opus-4-8", [{"role": "user", "content": "q"}],
                                  max_tokens=100, timeout_s=5, client=client)
    assert out == "hi from claude"
    assert "/v1/messages" in captured["url"]
    assert captured["body"]["model"] == "claude-opus-4-8"
    assert captured["body"]["max_tokens"] == 100
    assert captured["hdr"][0] == fe._anthropic_key()
    assert captured["hdr"][1] == "2023-06-01"


@pytest.mark.asyncio
async def test_call_model_unknown_raises():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        with pytest.raises(KeyError):
            await fe.call_model("no-such-model", [], max_tokens=10, timeout_s=5, client=client)
