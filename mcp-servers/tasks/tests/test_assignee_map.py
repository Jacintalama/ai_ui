from assignee_map import TEAM_EMAIL, AssigneeMap


def test_resolves_known_prefix_case_insensitive():
    m = AssigneeMap.from_env_string("ralph:ralph@x,lukas:lukas@x")
    assert m.resolve("Ralph Benitez") == "ralph@x"
    assert m.resolve("LUKAS HERAJT") == "lukas@x"


def test_unknown_assignee_returns_team_sentinel():
    m = AssigneeMap.from_env_string("ralph:ralph@x")
    assert m.resolve("Some Other Person") == TEAM_EMAIL


def test_team_keyword_returns_team_sentinel():
    m = AssigneeMap.from_env_string("ralph:ralph@x")
    assert m.resolve("team") == TEAM_EMAIL


def test_empty_string_returns_team_sentinel():
    m = AssigneeMap.from_env_string("ralph:ralph@x")
    assert m.resolve("") == TEAM_EMAIL


def test_admin_emails_lists_all_known():
    m = AssigneeMap.from_env_string("ralph:ralph@x,lukas:lukas@x")
    assert set(m.admin_emails()) == {"ralph@x", "lukas@x"}
