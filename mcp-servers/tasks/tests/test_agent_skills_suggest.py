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


def test_a_persons_own_skill_can_be_suggested_from_the_pool_given():
    """A person's own skills (user_skills) sit beside the built-in ones, so
    the pool is the caller's to pass. Tags are empty on those, so the name
    and description carry the match."""
    import user_skills
    pool = user_skills.merge(agent_skills.load_all(), [
        {"name": "invoice-chaser", "description": "Chase unpaid invoices.",
         "tools": ["gmail"], "body": "x"}])
    got = agent_skills.suggest("Invoice chaser for unpaid invoices", pool=pool)
    assert got[0] == "invoice-chaser"
    # Without the pool it does not exist.
    assert "invoice-chaser" not in agent_skills.suggest("Invoice chaser for unpaid invoices")
