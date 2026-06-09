import json, pathlib

WF = pathlib.Path(__file__).resolve().parents[2] / "n8n-workflows" / "recruiting-outreach.json"


def test_workflow_is_valid_and_has_chain():
    data = json.loads(WF.read_text(encoding="utf-8"))
    names = [n["name"] for n in data["nodes"]]
    types = [n["type"] for n in data["nodes"]]
    assert "n8n-nodes-base.webhook" in types
    assert "n8n-nodes-base.gmail" in types
    assert types.count("n8n-nodes-base.googleSheets") >= 2  # read + append
    assert "n8n-nodes-base.respondToWebhook" in types
    wh = next(n for n in data["nodes"] if n["type"] == "n8n-nodes-base.webhook")
    assert wh["parameters"]["path"] == "recruiting-outreach"
    assert data["connections"]  # has wiring
