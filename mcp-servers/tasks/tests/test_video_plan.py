"""Unit tests for video_plan.validate_plan. Pure functions, run fully offline.

Also includes one mocked generate_plan test that monkeypatches the anthropic
client so it never hits the network.
"""
import json

import anthropic
import pytest

from video_plan import PlanInvalid, generate_plan, validate_plan


def test_rejects_unknown_template():
    with pytest.raises(PlanInvalid):
        validate_plan(
            {"template_id": "nope", "title": "t", "scenes": [], "narration_script": "x"},
            available=["screenshot-1.png"],
        )


def test_rejects_missing_screenshot():
    p = {
        "template_id": "product_demo",
        "title": "t",
        "scenes": [
            {
                "screenshot": "screenshot-9.png",
                "caption": "c",
                "duration_s": 3.0,
                "transition": "crossfade",
            }
        ],
        "narration_script": "hi",
    }
    with pytest.raises(PlanInvalid):
        validate_plan(p, available=["screenshot-1.png"])


def test_accepts_valid_plan():
    p = {
        "template_id": "product_demo",
        "title": "t",
        "scenes": [
            {
                "screenshot": "screenshot-1.png",
                "caption": "c",
                "duration_s": 3.0,
                "transition": "crossfade",
            }
        ],
        "narration_script": "hi",
        "resolution": "720p",
    }
    validate_plan(p, available=["screenshot-1.png"])  # no raise


class _Block:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Msg:
    def __init__(self, content):
        self.content = content


class _Messages:
    def __init__(self, payload: str):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Msg([_Block(self._payload)])


class _FakeClient:
    def __init__(self, payload: str):
        self.messages = _Messages(payload)


async def test_generate_plan_parses_and_validates(monkeypatch):
    canned = {
        "template_id": "product_demo",
        "title": "Demo",
        "scenes": [
            {
                "screenshot": "screenshot-1.png",
                "caption": "c",
                "duration_s": 4.0,
                "transition": "cut",
            }
        ],
        "narration_script": "hi",
    }
    fake = _FakeClient(json.dumps(canned))
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: fake)

    result = await generate_plan("make a demo", ["screenshot-1.png"])

    assert result == canned
    # Confirm the call uses the current model id and structured-output API.
    sent = fake.messages.calls[0]
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_config"]["format"]["type"] == "json_schema"
