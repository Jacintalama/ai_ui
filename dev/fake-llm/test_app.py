import os, json, pytest, httpx
os.environ["FAKE_DELAY_MS"] = "0"
from app import app

@pytest.fixture
def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

def _body(text, system="You are Ada, the project manager.", **kw):
    return {"model": "fake-agent", "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": text}], **kw}

async def test_models_lists_the_fake(client):
    r = await client.get("/v1/models")
    assert [m["id"] for m in r.json()["data"]] == ["fake-agent"]

async def test_a_plain_answer_names_the_agent(client):
    r = await client.post("/v1/chat/completions", json=_body("hello"))
    msg = r.json()["choices"][0]["message"]
    assert msg["role"] == "assistant" and msg["content"].startswith("Ada here.")

async def test_tool_scene_calls_the_first_offered_tool(client):
    tools = [{"type": "function", "function": {"name": "search_drive", "parameters": {}}}]
    r = await client.post("/v1/chat/completions", json=_body("scene:tool find it", tools=tools))
    calls = r.json()["choices"][0]["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search_drive"
    assert r.json()["choices"][0]["finish_reason"] == "tool_calls"

async def test_tool_result_turns_into_an_answer(client):
    body = _body("scene:tool find it")
    body["messages"] += [
        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function",
          "function": {"name": "search_drive", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"}]
    r = await client.post("/v1/chat/completions", json=body)
    assert r.json()["choices"][0]["message"]["content"] == "Ada used a tool."

async def test_fail_scene_is_a_500(client):
    r = await client.post("/v1/chat/completions", json=_body("scene:fail"))
    assert r.status_code == 500 and "error" in r.json()

async def test_pass_scene(client):
    r = await client.post("/v1/chat/completions", json=_body("scene:pass hi"))
    assert r.json()["choices"][0]["message"]["content"] == "PASS"

async def test_streaming_ends_with_done(client):
    r = await client.post("/v1/chat/completions", json=_body("hello", stream=True))
    assert r.text.rstrip().endswith("data: [DONE]")
