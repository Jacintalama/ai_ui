import json, os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import routes_outreach


@pytest.mark.asyncio
async def test_process_completed_calls_n8n_and_summarizes(monkeypatch):
    cand = json.dumps({"candidates": [
        {"name": "A", "github_url": "g/a", "email": "a@x.com", "subject": "s", "body": "b"},
        {"name": "B", "github_url": "g/b", "email": None, "subject": "s", "body": "b"}]})
    log = json.dumps({"type": "result", "result":
        f"```json\n{cand}\n```\nCOMPLETED"}) + "\n"

    async def fake_post(job_title, candidates, **kw):
        return {"sent": 1, "saved": 1, "sheet_url": "http://sheet"}
    monkeypatch.setattr(routes_outreach.outreach, "post_outreach_to_n8n", fake_post)

    summary = await routes_outreach._process_outreach_result(
        log, job_title="Python", count=10)
    assert summary["status"] == "completed"
    assert summary["sent"] == 1 and summary["saved"] == 1
    assert summary["sheet_url"] == "http://sheet"
    assert summary["found"] == 2


@pytest.mark.asyncio
async def test_process_failed_agent():
    log = json.dumps({"type": "result", "result": "FAILED: github rate limit"}) + "\n"
    summary = await routes_outreach._process_outreach_result(log, job_title="x", count=10)
    assert summary["status"] == "failed"


@pytest.mark.asyncio
async def test_process_no_candidates():
    log = json.dumps({"type": "result", "result": "```json\n{\"candidates\":[]}\n```\nCOMPLETED"}) + "\n"
    summary = await routes_outreach._process_outreach_result(log, job_title="x", count=10)
    assert summary["status"] == "failed"
    assert summary["found"] == 0
