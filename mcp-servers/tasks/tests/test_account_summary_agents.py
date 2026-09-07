"""The account summary reports this person's assistants too.

Asked "who is read only and who is all access", nothing could answer: the only
tool that knows about agents is the one that RUNS them, and an agent inside a
turn must never reach that, or it starts a round inside a round while its
owner waits on the outer one. Reporting is safe; running is not.
"""
import account_summary as acc


async def test_it_reports_each_agent_and_the_access_it_was_given(monkeypatch):
    import routes_agent_turn

    async def listed(email):
        return [
            {"id": "a", "name": "Ada", "base_model_id": "gpt-4o-mini",
             "meta": {"access": "all", "toolIds": ["gmail", "account"]}},
            {"id": "m", "name": "Mia", "base_model_id": "gpt-4o-mini",
             "meta": {"access": "read", "toolIds": ["gmail"]}},
        ]

    monkeypatch.setattr(routes_agent_turn, "_agents_for", listed)
    got = await acc._own_agents("owner@example.com")
    assert [a["name"] for a in got] == ["Ada", "Mia"]
    assert got[0]["access"] == "full access"
    assert got[1]["access"] == "read only"
    assert got[0]["tools"] == 2


async def test_an_agent_nobody_chose_a_level_for_says_so(monkeypatch):
    """None is not the same as read only: it means nobody ever picked, which
    the owner can act on. Saying "read only" would hide that."""
    import routes_agent_turn

    async def listed(email):
        return [{"id": "a", "name": "Ada", "meta": {}}]

    monkeypatch.setattr(routes_agent_turn, "_agents_for", listed)
    got = await acc._own_agents("owner@example.com")
    assert got[0]["access"] == "not set, so it only reads"


async def test_a_junk_level_is_not_treated_as_a_choice(monkeypatch):
    import routes_agent_turn

    async def listed(email):
        return [{"id": "a", "name": "Ada", "meta": {"access": "superuser"}}]

    monkeypatch.setattr(routes_agent_turn, "_agents_for", listed)
    got = await acc._own_agents("owner@example.com")
    assert got[0]["access"] == "not set, so it only reads"


async def test_a_broken_listing_costs_the_rest_of_the_summary_nothing(monkeypatch):
    import routes_agent_turn

    async def broken(email):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(routes_agent_turn, "_agents_for", broken)
    assert await acc._own_agents("owner@example.com") == []


async def test_the_summary_still_answers_when_connections_cannot_be_read(monkeypatch):
    """A broken connection read used to return early, which would now also
    drop the agents. Both halves have to fail independently."""
    import routes_agent_turn

    async def broken(email):
        raise RuntimeError("no database")

    async def listed(email):
        return [{"id": "a", "name": "Ada", "meta": {"access": "ask"}}]

    monkeypatch.setattr(acc, "_connected_providers", broken)
    monkeypatch.setattr(routes_agent_turn, "_agents_for", listed)
    got = await acc.summarise("owner@example.com")
    assert got["connected"] == []
    assert [a["name"] for a in got["agents"]] == ["Ada"]
    assert got["agents"][0]["access"] == "can act, but asks first"


async def test_no_email_is_an_empty_answer_not_a_crash():
    got = await acc.summarise("")
    assert got == {"connected": [], "not_connected": [], "agents": []}
