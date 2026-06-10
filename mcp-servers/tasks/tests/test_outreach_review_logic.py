import outreach
from outreach import Candidate


def _found():
    return [
        Candidate(name="A", github_url="gh/a", email="a@x.com", subject="S", body="B"),
        Candidate(name="B", github_url="gh/b", email=None, subject="", body=""),
    ]


def test_build_review_candidates_ids_and_defaults():
    rc = outreach.build_review_candidates(_found())
    assert [c["id"] for c in rc] == ["c0", "c1"]
    assert rc[0]["selected"] is True and rc[0]["status"] == "draft"
    assert rc[1]["selected"] is False and rc[1]["status"] == "no_email"
    assert rc[1]["email"] == ""


def test_apply_edit_add_email_makes_sendable():
    rc = outreach.build_review_candidates(_found())
    rc = outreach.apply_candidate_edit(rc, "c1", email="b@x.com")
    assert rc[1]["status"] == "draft" and rc[1]["email"] == "b@x.com"
    rc = outreach.apply_candidate_edit(rc, "c1", selected=True)
    assert rc[1]["selected"] is True


def test_apply_edit_clearing_email_deselects():
    rc = outreach.build_review_candidates(_found())
    rc = outreach.apply_candidate_edit(rc, "c0", email="")
    assert rc[0]["status"] == "no_email" and rc[0]["selected"] is False


def test_set_selection_only_emailable():
    rc = outreach.build_review_candidates(_found())
    rc = outreach.set_selection(rc, ["c0", "c1"])  # c1 has no email
    assert rc[0]["selected"] is True and rc[1]["selected"] is False


def test_sendable_candidates_and_summary():
    rc = outreach.build_review_candidates(_found())
    send = outreach.sendable_candidates(rc)
    assert [c.name for c in send] == ["A"]
    assert outreach.review_summary(rc) == {"total": 2, "emailable": 1, "selected": 1}
