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


@pytest.mark.asyncio
async def test_fan_out_parallel_and_drops_failures(monkeypatch):
    async def fake_call(model_id, messages, *, max_tokens, timeout_s, client):
        if model_id == "gpt-4o":
            raise RuntimeError("boom")
        return f"answer from {model_id}"
    monkeypatch.setattr(fe, "call_model", fake_call)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        answers = await fe.fan_out([{"role": "user", "content": "q"}],
                                   ["gpt-4o", "claude-opus-4-8"],
                                   max_tokens=100, timeout_s=5, client=client)
    by = {a.model: a for a in answers}
    assert by["gpt-4o"].ok is False and "boom" in by["gpt-4o"].error
    assert by["claude-opus-4-8"].ok is True and "claude-opus-4-8" in by["claude-opus-4-8"].text


def test_build_judge_messages_only_ok_answers_and_instruction():
    answers = [fe.PanelAnswer("gpt-5.5", True, "GPT says X"),
               fe.PanelAnswer("gpt-4o", False, error="dead"),
               fe.PanelAnswer("claude-opus-4-8", True, "Claude says Y")]
    msgs = fe.build_judge_messages("what is X?", answers)
    joined = " ".join(m["content"] for m in msgs)
    assert "consensus" in joined.lower() and "contradiction" in joined.lower()
    assert "GPT says X" in joined and "Claude says Y" in joined
    assert "dead" not in joined  # failed answers excluded


@pytest.mark.asyncio
async def test_fuse_all_panel_failed_yields_error(monkeypatch):
    async def all_fail(messages, panel, *, max_tokens, timeout_s, client):
        return [fe.PanelAnswer(m, False, error="x") for m in panel]
    monkeypatch.setattr(fe, "fan_out", all_fail)
    out = "".join([c async for c in fe.fuse([{"role": "user", "content": "q"}], "budget")])
    assert "could not" in out.lower() or "unavailable" in out.lower()


@pytest.mark.asyncio
async def test_fuse_judge_fails_falls_back_to_panel_answer(monkeypatch):
    async def two_ok(messages, panel, *, max_tokens, timeout_s, client):
        return [fe.PanelAnswer("gpt-4o", True, "short"),
                fe.PanelAnswer("claude-haiku-4-5-20251001", True, "a much longer better answer")]
    async def judge_boom(judge_id, judge_messages, *, client):
        raise RuntimeError("judge down")
        yield  # pragma: no cover
    monkeypatch.setattr(fe, "fan_out", two_ok)
    monkeypatch.setattr(fe, "_stream_judge", judge_boom)
    out = "".join([c async for c in fe.fuse([{"role": "user", "content": "q"}], "budget")])
    assert "a much longer better answer" in out and "judge unavailable" in out.lower()


@pytest.mark.asyncio
async def test_fuse_streams_judge_output_in_order(monkeypatch):
    async def two_ok(messages, panel, *, max_tokens, timeout_s, client):
        return [fe.PanelAnswer("gpt-4o", True, "A"), fe.PanelAnswer("claude-haiku-4-5-20251001", True, "B")]
    async def judge_stream(judge_id, judge_messages, *, client):
        for piece in ["Final ", "synthesized ", "answer."]:
            yield piece
    monkeypatch.setattr(fe, "fan_out", two_ok)
    monkeypatch.setattr(fe, "_stream_judge", judge_stream)
    chunks = [c async for c in fe.fuse([{"role": "user", "content": "q"}], "quality")]
    assert "".join(chunks).endswith("Final synthesized answer.")
