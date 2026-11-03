"""Skills suggested for an agent from its role and instructions (2026-11-03).

Lukas: an agent made from the main chat should come with the skills its role
needs, without anyone ticking boxes. These run against the real catalogue in
agent_skills/, not a fixture, because what is being tested is whether the
real skills match real descriptions.
"""
import agent_skills


def test_an_inbox_agent_is_offered_the_inbox_skills():
    got = agent_skills.suggest("Inbox assistant. Triage my inbox and draft "
                               "replies to customers")
    assert got[0] == "inbox-triage"
    assert "draft-reply" in got
    assert len(got) <= agent_skills.SUGGEST_LIMIT


def test_an_incidental_word_is_not_a_reason_to_add_a_skill():
    """Measured: the best any skill scores for a bookkeeper is 1, a word
    somewhere in a description. Adding those would hand an agent unrelated
    instructions on every turn."""
    assert agent_skills.suggest("Bookkeeper. Keep the books straight.") == []


def test_nothing_to_go_on_suggests_nothing():
    assert agent_skills.suggest("") == []
    assert agent_skills.suggest(None) == []
