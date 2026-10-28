"""The Automations chat tool: rules from a sentence in the main chat.

Jev picks it for "when X happens, have Y do Z"; the assistant asks Yes/No
before the write (create, pause, delete and run are writes by name); the
tool sends only the person's email and says what it did in a sentence."""
import importlib.util
import pathlib

import agent_jev
import agent_tools

RULES = [{"id": "a1", "name": "New website lead", "agent_id": "agent-ada-1", "agent_name": "Ada",
          "deliver_to": "discord", "enabled": True,
          "hook_url": "https://io.example.com/api/tasks/hooks/hk_tok"},
         {"id": "a2", "name": "Invoice paid", "agent_id": "agent-mia-1", "agent_name": "Mia",
          "deliver_to": "chat", "enabled": False, "hook_url": "https://io.example.com/api/tasks/hooks/hk_two"}]


def _tool():
    path = pathlib.Path(__file__).resolve().parents[3] / "open-webui-functions" / "automations_tool.py"
    spec = importlib.util.spec_from_file_location("automations_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Tools()


def _wire(tool, rules=None, replies=None):
    calls = []

    async def call(method, path, email, json_body=None):
        calls.append((method, path, email, json_body))
        if path == "/api/tasks/automations" and method == "GET":
            return True, {"automations": list(RULES if rules is None else rules)}
        for key, reply in (replies or {}).items():
            if (method, path) == key:
                return reply
        return True, {}
    tool._call = call
    return calls


def test_jev_knows_the_tool_and_what_it_is_for():
    note = agent_jev.TOOL_NOTES["automations"]
    assert "happens" in note and "timer" in note


def test_the_writes_ask_first_and_the_listing_does_not():
    assert agent_tools.is_write_tool("create_automation")
    assert agent_tools.is_write_tool("pause_automation")
    assert agent_tools.is_write_tool("delete_automation")
    assert agent_tools.is_write_tool("run_automation")
    assert not agent_tools.is_write_tool("list_my_automations")


async def test_the_tool_makes_a_rule_as_the_person_and_hands_back_the_url():
    tool = _tool()
    calls = _wire(tool, replies={("POST", "/api/tasks/automations"): (True, {
        "name": "New website lead", "agent_name": "Ada", "deliver_to": "discord",
        "hook_url": "https://io.example.com/api/tasks/hooks/hk_tok"})})
    said = await tool.create_automation("New website lead", "Ada", "Write a first reply.",
                                        deliver_to="discord", __user__={"email": "r@example.com"})
    assert said.startswith("Made the automation New website lead. Ada will do that")
    assert "https://io.example.com/api/tasks/hooks/hk_tok" in said
    assert "in your Discord thread" in said and "Only an agent set to All" in said
    assert calls == [("POST", "/api/tasks/automations", "r@example.com",
                      {"name": "New website lead", "agent": "Ada",
                       "instructions": "Write a first reply.", "deliver_to": "discord"})]


async def test_a_refusal_is_passed_on_as_the_servers_sentence():
    tool = _tool()
    _wire(tool, replies={("POST", "/api/tasks/automations"): (False, "No agent called 'Zed'. Your agents: Ada, Mia.")})
    said = await tool.create_automation("Lead", "Zed", "Do x.", __user__={"email": "r@example.com"})
    assert said == "Nothing was made: No agent called 'Zed'. Your agents: Ada, Mia."
    assert "who is asking" in await tool.create_automation("Lead", "Ada", "x", __user__={})


async def test_listing_reads_as_a_sentence():
    tool = _tool()
    _wire(tool)
    said = await tool.list_my_automations(__user__={"email": "r@example.com"})
    assert said == ("Your automations: New website lead: Ada, answers in your Discord thread; "
                    "Invoice paid: Mia, answers in the agent's chat (paused).")
    _wire(tool, rules=[])
    assert "no automations yet" in await tool.list_my_automations(__user__={"email": "r@example.com"})


async def test_pause_resume_and_delete_find_the_rule_by_name():
    tool = _tool()
    calls = _wire(tool)
    email = {"email": "r@example.com"}
    assert await tool.pause_automation("new website lead", __user__=email) == \
        "Paused New website lead. Its URL answers nothing until you resume it."
    assert calls[-1] == ("PATCH", "/api/tasks/automations/a1", "r@example.com", {"enabled": False})
    assert await tool.resume_automation("invoice", __user__=email) == "Resumed Invoice paid. Its URL works again."
    assert calls[-1] == ("PATCH", "/api/tasks/automations/a2", "r@example.com", {"enabled": True})
    assert await tool.delete_automation("Invoice paid", __user__=email) == "Deleted Invoice paid. Its URL no longer works."
    assert calls[-1] == ("DELETE", "/api/tasks/automations/a2", "r@example.com", None)
    said = await tool.delete_automation("something else", __user__=email)
    assert said.startswith("I could not tell which automation you mean.") and "New website lead" in said
    assert len([c for c in calls if c[0] == "DELETE"]) == 1


async def test_running_one_now_returns_the_answer_and_where_it_went():
    tool = _tool()
    calls = _wire(tool, replies={("POST", "/api/tasks/automations/a1/run"): (True, {
        "status": "done", "answer": "Replied to Bo.", "notes": [], "delivered": "discord"})})
    said = await tool.run_automation("New website lead", note="Bo from Acme asked for a quote",
                                     __user__={"email": "r@example.com"})
    assert said == "New website lead ran. The answer went in your Discord thread.\n\nReplied to Bo."
    assert calls[-1][3] == {"payload": {"note": "Bo from Acme asked for a quote"}}
    _wire(tool, replies={("POST", "/api/tasks/automations/a1/run"): (True, {
        "status": "failed", "answer": "", "notes": ["The agent could not finish this run."]})})
    said = await tool.run_automation("New website lead", __user__={"email": "r@example.com"})
    assert said == "New website lead did not finish: The agent could not finish this run."


def test_no_dashes_in_the_tool_copy():
    path = pathlib.Path(__file__).resolve().parents[3] / "open-webui-functions" / "automations_tool.py"
    text = path.read_text(encoding="utf-8")
    assert "\u2014" not in text and "\u2013" not in text
