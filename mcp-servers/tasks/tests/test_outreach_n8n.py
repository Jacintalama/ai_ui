import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import outreach
from outreach import Candidate


class _Resp:
    def __init__(self, code=200, text='{"sent":2,"saved":1,"sheet_url":"http://s"}'):
        self.status_code = code; self.text = text
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=None)
    def json(self):
        import json; return json.loads(self.text)


class _Client:
    last = {}
    def __init__(self, timeout): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json):
        _Client.last = {"url": url, "json": json}; return _Resp()


@pytest.mark.asyncio
async def test_post_outreach_url_and_payload(monkeypatch):
    monkeypatch.setattr(outreach.httpx, "AsyncClient", _Client)
    out = await outreach.post_outreach_to_n8n("Python role", [
        Candidate(name="A", email="a@x.com", subject="s", body="b")])
    assert out["sent"] == 2
    assert _Client.last["url"].endswith("/webhook/recruiting-outreach")
    assert _Client.last["json"]["job_title"] == "Python role"
    assert _Client.last["json"]["candidates"][0]["email"] == "a@x.com"
