"""Which apps a skill needs, and which of those a person has not connected
(2026-11-04, Lukas: suggest skills from what the user has connected)."""
import skill_fit as F


def sk(name, tools=()):
    return {"name": name, "tools": list(tools), "description": "", "tags": []}


def test_google_tools_are_needs_and_others_are_not():
    assert F.needs(sk("inbox-triage", ["gmail"])) == ["gmail"]
    # Always in the module's fixed order, so messages read the same twice.
    assert F.needs(sk("x", ["calendar", "gmail"])) == ["gmail", "calendar"]
    # Documents, Excel, memory and the rest work with nothing connected.
    assert F.needs(sk("x", ["documents", "remember", "excel_creator"])) == []


def test_tracker_skills_need_a_tracker_and_web_ones_do_not():
    assert F.needs(sk("backlog-groom", ["server:mcp-proxy"])) == ["tracker"]
    # Web search is a shared server, so research needs nothing of theirs.
    assert F.needs(sk("research-and-cite", ["server:mcp-proxy"])) == []


def test_missing_reads_the_persons_connections():
    s = sk("inbox-triage", ["gmail"])
    assert F.missing(s, set()) == ["gmail"]
    assert F.missing(s, {"gmail"}) == []
    t = sk("daily-standup", ["server:mcp-proxy"])
    assert F.missing(t, {"gmail"}) == ["tracker"]
    assert F.missing(t, {"github"}) == []
    assert F.missing(t, None) == ["tracker"]


def test_every_tracker_skill_is_a_real_skill():
    """A typo in the set would make a skill look ready when it is not."""
    import agent_skills
    known = agent_skills.load_all()
    assert set(F.TRACKER_SKILLS) <= set(known), set(F.TRACKER_SKILLS) - set(known)


def test_split_keeps_order_and_groups_what_is_missing():
    pool = {"a": sk("a", ["gmail"]), "b": sk("b"), "c": sk("c", ["gmail"]),
            "daily-standup": sk("daily-standup", ["server:mcp-proxy"])}
    ready, gaps = F.split(["a", "b", "nope", "c", "daily-standup"], pool, set())
    assert ready == ["b"]
    assert gaps == {"gmail": ["a", "c"], "tracker": ["daily-standup"]}
    ready, gaps = F.split(["a", "b"], pool, {"gmail"})
    assert ready == ["a", "b"] and gaps == {}


def test_connect_lines_name_the_skills_and_give_a_button_link():
    assert F.connect_lines({"gmail": ["a", "c"]}) == [
        "Connect Gmail to add: a, c",
        "[Connect Gmail](#aiui-connect:gmail)"]
    # Fixed order, whatever order the dict came in.
    lines = F.connect_lines({"tracker": ["daily-standup"], "calendar": ["day-ahead"]})
    assert lines == [
        "Connect Google Calendar to add: day-ahead",
        "[Connect Google Calendar](#aiui-connect:calendar)",
        "Connect a task tracker (Trello, GitHub or ClickUp) to add: daily-standup",
        "[Connect a task tracker](#aiui-connect:trello)"]
    assert F.connect_lines({}) == []


def test_connect_lines_for_skills_already_kept_say_so():
    assert F.connect_lines({"gmail": ["inbox-triage"]}, kept=True)[0] == (
        "Connect Gmail so these work: inbox-triage")


def test_needs_connect_is_the_same_facts_as_data():
    assert F.needs_connect({"gmail": ["a"]}) == [
        {"app": "gmail", "label": "Gmail", "skills": ["a"],
         "connect": "#aiui-connect:gmail"}]
