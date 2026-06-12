"""Pure logic of scripts/setup_voice_agent.py (no HTTP)."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "setup_voice_agent",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "setup_voice_agent.py",
)
sva = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sva)


def test_three_tools_defined_with_secret_header():
    tools = sva.build_tool_definitions("sssh")
    names = [t["name"] for t in tools]
    assert names == ["list_templates", "start_build", "build_status"]
    for t in tools:
        assert t["type"] == "webhook"
        api = t["api_schema"]
        assert api["url"] == f"https://ai-ui.coolestdomain.win/webhook/voice/{t['name']}"
        assert api["method"] == "POST"
        assert api["request_headers"]["X-Voice-Secret"] == "sssh"


def test_start_build_schema_requires_description():
    tools = {t["name"]: t for t in sva.build_tool_definitions("x")}
    body = tools["start_build"]["api_schema"]["request_body_schema"]
    assert body["required"] == ["description"]
    assert "template_key" in body["properties"]
    body_status = tools["build_status"]["api_schema"]["request_body_schema"]
    assert body_status["required"] == []


def test_plan_tool_changes_is_idempotent():
    wanted = sva.build_tool_definitions("x")
    existing = [
        {"id": "tool_1", "tool_config": {"name": "start_build"}},
        {"id": "tool_2", "tool_config": {"name": "status"}},  # unrelated, untouched
    ]
    creates, updates = sva.plan_tool_changes(existing, wanted)
    assert [t["name"] for t in creates] == ["list_templates", "build_status"]
    assert [u[0] for u in updates] == ["tool_1"]


def test_merged_tool_ids_preserves_existing():
    merged = sva.merged_tool_ids(["a", "b"], ["b", "c", "d"])
    assert merged == ["a", "b", "c", "d"]


def test_prompt_contains_flow_and_keeps_existing_capabilities():
    p = sva.AGENT_PROMPT
    assert "template, or a blank project" in p
    assert "list_templates" in p and "start_build" in p and "build_status" in p
    assert "never read the whole list aloud" in p.lower()
    # the pre-existing capabilities must survive the prompt rewrite
    for cap in ("status:", "pr-review", "Default repository"):
        assert cap in p
