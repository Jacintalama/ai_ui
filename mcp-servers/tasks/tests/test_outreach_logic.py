import json
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import outreach


def _stream_json(body: str) -> str:
    return json.dumps({"type": "result", "is_error": False, "result": body}) + "\n"


def test_extract_candidates_from_real_stream_json():
    cand_json = json.dumps({"candidates": [
        {"name": "A", "github_url": "https://github.com/a", "email": "a@x.com",
         "subject": "Hi A", "body": "..."},
        {"name": "B", "github_url": "https://github.com/b", "email": None,
         "subject": "Hi B", "body": "..."},
    ]})
    body = f"Here are the candidates:\n```json\n{cand_json}\n```\nCOMPLETED"
    out = outreach.extract_candidates(_stream_json(body))
    assert len(out.candidates) == 2
    assert out.candidates[0].email == "a@x.com"
    assert out.candidates[1].email is None


def test_extract_candidates_missing_block_returns_empty():
    out = outreach.extract_candidates(_stream_json("no json here\nCOMPLETED"))
    assert out.candidates == []


def test_cap_and_dedupe():
    from outreach import Candidate
    cands = [
        Candidate(name="A", github_url="g/a", email="a@x.com", subject="s", body="b"),
        Candidate(name="A2", github_url="g/a2", email="A@x.com", subject="s", body="b"),  # dup (case-insensitive)
        Candidate(name="C", github_url="g/c", email=None, subject="s", body="b"),
        Candidate(name="D", github_url="g/d", email="d@x.com", subject="s", body="b"),
    ]
    out = outreach.cap_and_dedupe(cands, count=2)
    emails = [c.email for c in out if c.email]
    assert "a@x.com" in [e.lower() for e in emails]
    assert len(emails) <= 2
    assert len(out) <= 3  # 2 emailed-cap + at most the kept no-email ones


def test_build_outreach_prompt_contains_contract():
    p = outreach.build_outreach_prompt("Python", "Berlin", "Hiring a dev", 8)
    assert "api.github.com/search/users" in p
    assert "GITHUB_TOKEN" in p
    assert "```json" in p
    assert "COMPLETED" in p
    assert "8" in p


def test_format_outreach_summary():
    s = outreach.format_outreach_summary(found=12, sent=8, saved=4, sheet_url="http://s")
    assert "8" in s and "4" in s


def test_build_outreach_prompt_hire_unchanged_by_direction_default():
    # Positional call and explicit direction="hire" must be byte-identical.
    p_default = outreach.build_outreach_prompt("Python", "Berlin", "Hiring a dev", 8)
    p_hire = outreach.build_outreach_prompt("Python", "Berlin", "Hiring a dev", 8,
                                            direction="hire")
    assert p_default == p_hire
    assert "recruiting research assistant" in p_hire
    assert "api.github.com/search/users" in p_hire


def test_build_outreach_prompt_reverse_branch():
    p = outreach.build_outreach_prompt("Senior Python backend", "Berlin",
                                       "10y Python, FastAPI, AWS", 5,
                                       direction="reverse")
    assert "on behalf of" in p.lower()            # acts for the seeker
    assert "companies hiring for" in p.lower()    # company-oriented search
    assert "WebSearch" in p and "WebFetch" in p   # web-search tools, not GitHub API
    assert "first person" in p.lower() or "first-person" in p.lower()
    assert "10y Python, FastAPI, AWS" in p        # seeker background grounded
    assert "5" in p                               # count threaded
    assert "```json" in p and "COMPLETED" in p    # SAME machine contract reused
    assert "github.com/search/users" not in p     # NOT the hire/GitHub flow


def test_format_outreach_summary_hire_default_unchanged():
    s = outreach.format_outreach_summary(found=12, sent=8, saved=4, sheet_url="http://s")
    assert "found 12 engineer(s)" in s
    assert "Emailed 8" in s and "Saved 4 to your sheet" in s


def test_format_outreach_summary_reverse_company_noun():
    s = outreach.format_outreach_summary(found=12, sent=8, saved=4, sheet_url="http://s",
                                         direction="reverse")
    assert "found 12 companies" in s
    assert "engineer" not in s
    assert "compan(y/ies)" not in s


def test_format_outreach_summary_reverse_singular_company():
    s = outreach.format_outreach_summary(found=1, sent=1, saved=1, sheet_url="http://s",
                                         direction="reverse")
    assert "found 1 company" in s
    assert "companies" not in s
    assert "compan(y/ies)" not in s


def test_build_review_candidates_profile_url_falls_back_to_github_url():
    """hire-mode row: profile_url is empty → fallback fills it from github_url."""
    from outreach import Candidate
    c = Candidate(name="Dev A", github_url="https://github.com/deva", profile_url="",
                  email="a@x.com", subject="Hi", body="body text")
    rows = outreach.build_review_candidates([c])
    assert len(rows) == 1
    assert rows[0]["github_url"] == "https://github.com/deva"
    assert rows[0]["profile_url"] == "https://github.com/deva"  # backward-compat fallback


def test_sendable_candidates_backward_compat_missing_profile_url_key():
    """Rows without a 'profile_url' key (old data) do not crash and default to ''."""
    cands = [
        {"id": "c0", "name": "Dev A", "github_url": "https://github.com/deva",
         # NOTE: no "profile_url" key — simulates data written before field was added
         "email": "a@x.com", "subject": "Hi", "body": "body text", "selected": True},
    ]
    result = outreach.sendable_candidates(cands)
    assert len(result) == 1
    assert result[0].github_url == "https://github.com/deva"
    assert result[0].profile_url == ""  # defaults to empty string via c.get("profile_url", "")


def test_hire_mode_github_url_survives_review_roundtrip():
    """hire-mode candidate: github_url flows through build_review_candidates then
    sendable_candidates without the link being silently lost."""
    from outreach import Candidate
    c = Candidate(name="Dev A", github_url="https://github.com/deva", profile_url="",
                  email="a@x.com", subject="Hi", body="body text")
    rows = outreach.build_review_candidates([c])
    # Backward-compat: profile_url was empty → filled from github_url
    assert rows[0]["profile_url"] == "https://github.com/deva"
    result = outreach.sendable_candidates(rows)
    assert len(result) == 1
    assert result[0].github_url == "https://github.com/deva"
    # profile_url was filled by build_review_candidates so it also survives
    assert result[0].profile_url == "https://github.com/deva"
