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


# --- scene:job: the team lead's triage (agent jobs, 2026-10-15) ---------------

def _triage(person_said):
    """What agent_job_triage sends: the room history, then its instruction."""
    return {"model": "fake-agent", "messages": [
        {"role": "system", "content": "You are Ada, the project manager."},
        {"role": "user", "content": person_said},
        {"role": "user", "content": "TEAM_TRIAGE. You lead this team: Ada, Mia, Dev. Reply with the JSON only."}]}

async def test_triage_of_a_job_scene_answers_a_three_step_plan(client):
    r = await client.post("/v1/chat/completions", json=_triage("scene:job prepare the weekly summary"))
    plan = json.loads(r.json()["choices"][0]["message"]["content"])
    assert plan["kind"] == "job"
    assert [s["agent"] for s in plan["steps"]] == ["Mia", "Ada", "Dev"]
    assert all(s["do"] for s in plan["steps"])

async def test_triage_of_anything_else_is_just_answer_and_instant(client, monkeypatch):
    import app as fake
    monkeypatch.setattr(fake, "_default_delay_ms", lambda: 60_000)
    r = await client.post("/v1/chat/completions", json=_triage("hello team"))
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == {"kind": "answer"}

async def test_a_step_brief_gets_the_normal_answer(client):
    brief = ("The person asked the team: scene:job prepare the weekly summary\n\n"
             "The plan:\n1. Mia: Find the reports. <- this is your step")
    r = await client.post("/v1/chat/completions",
                          json=_body(brief, system="You are Mia, the receptionist."))
    assert r.json()["choices"][0]["message"]["content"].startswith("Mia here.")

async def test_a_step_brief_answers_its_own_step_in_one_line(client):
    brief = ("The person asked the team: scene:job prepare the weekly summary\n\n"
             "The plan:\n1. Mia: Find the three latest reports. <- this is your step\n"
             "2. Ada: Compare them.\n\nDo your step now and answer with its result only.")
    r = await client.post("/v1/chat/completions",
                          json=_body(brief, system="You are Mia, the receptionist."))
    assert r.json()["choices"][0]["message"]["content"] == (
        "Mia did: Find the three latest reports.")

async def test_the_leads_closing_brief_gets_one_line(client):
    brief = ("The person asked the team: scene:job prepare the weekly summary\n\n"
             "Step 1, Mia: Mia did: Find the reports.\n\n"
             "Write the person a short final answer from these results.")
    r = await client.post("/v1/chat/completions", json=_body(brief))
    assert r.json()["choices"][0]["message"]["content"] == (
        "Ada: all steps are done. Summary of the team's results.")
