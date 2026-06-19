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


def _find_log(cands):
    body = json.dumps({"candidates": cands})
    return json.dumps({"type": "result",
                       "result": f"```json\n{body}\n```\nCOMPLETED"}) + "\n"


def test_process_find_reverse_includes_meta_and_company_copy():
    log = _find_log([{"name": "Acme", "github_url": "https://acme.com/careers",
                      "email": "jobs@acme.com", "subject": "s", "body": "b"}])
    out = routes_outreach._process_outreach_find(
        log, job_title="Senior Python", count=10, direction="reverse",
        location="Berlin")
    assert out["status"] == "review"
    assert out["direction"] == "reverse"
    assert out["role"] == "Senior Python"
    assert out["location"] == "Berlin"
    assert out["found"] == 1


def test_process_find_reverse_not_found_company_copy():
    out = routes_outreach._process_outreach_find(
        _find_log([]), job_title="x", count=10, direction="reverse")
    assert out["status"] == "failed"
    assert "companies" in out["text"]
    assert out["direction"] == "reverse"


def test_process_find_hire_default_unchanged():
    out = routes_outreach._process_outreach_find(_find_log([]), job_title="x", count=10)
    assert out["status"] == "failed"
    assert "engineers" in out["text"]
    assert out["direction"] == "hire" and out["role"] == "x" and out["location"] == ""
