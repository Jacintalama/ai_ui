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
         "connect": "#aiui-connect:gmail", "button": "Connect Gmail"}]


# --- "which skills should I use?" (2026-11-04) -------------------------------

POOL = {"inbox-triage": sk("inbox-triage", ["gmail"]),
        "draft-reply": sk("draft-reply", ["gmail"]),
        "day-ahead": sk("day-ahead", ["calendar", "gmail"]),
        "find-my-file": sk("find-my-file", ["gdrive"]),
        "daily-standup": sk("daily-standup", ["server:mcp-proxy"]),
        "shorten-this": sk("shorten-this", [])}


def test_overview_groups_ready_skills_by_the_app_that_makes_them_work():
    ov = F.overview(POOL, {"gmail"})
    assert ov["ready"] == [{"app": "gmail", "label": "Gmail",
                            "skills": ["draft-reply", "inbox-triage"]}]
    # day-ahead needs Calendar as well, so it waits on Calendar.
    apps = [c["app"] for c in ov["connect"]]
    assert apps == ["calendar", "gdrive", "tracker"]
    assert ov["connect"][0]["skills"] == ["day-ahead"]
    assert ov["connect"][0]["connect"] == "#aiui-connect:calendar"
    assert ov["no_connection"] == 1


def test_a_skill_needing_two_connected_apps_is_listed_once():
    ov = F.overview(POOL, {"gmail", "calendar"})
    listed = [s for g in ov["ready"] for s in g["skills"]]
    assert listed.count("day-ahead") == 1


def test_overview_text_has_buttons_and_says_what_to_do_next():
    text = F.overview_text(F.overview(POOL, {"gmail"}), mine=["invoice-chaser"])
    assert "Gmail: draft-reply, inbox-triage" in text
    assert "Your own skills: invoice-chaser" in text
    assert "Google Calendar would add: day-ahead" in text
    assert "[Connect Google Calendar](#aiui-connect:calendar)" in text
    assert "1 more skill needs nothing connected" in text
    assert text.rstrip().endswith("Ask me to add any of these to an agent.")


def test_with_nothing_connected_it_says_so_plainly():
    text = F.overview_text(F.overview(POOL, set()))
    assert "Nothing you have connected unlocks a skill yet." in text
    assert "[Connect Gmail](#aiui-connect:gmail)" in text


def test_a_long_group_is_cut_with_a_count():
    pool = {"s%02d" % i: sk("s%02d" % i, ["gmail"]) for i in range(12)}
    text = F.overview_text(F.overview(pool, {"gmail"}))
    assert "and 4 more" in text


# --- a Connect link the model left out (2026-11-04) -------------------------
# Live, the main chat's model read suggest_skills and then wrote "There's a
# Connect button above if you want that" with no link, so no button. Which
# links belong under an answer is decided here, not by the model.

TRACKER_NEED = {"app": "tracker", "label": F.LABELS["tracker"],
                "skills": ["daily-standup"], "connect": "#aiui-connect:trello",
                "button": "Connect a task tracker"}
GMAIL_NEED = {"app": "gmail", "label": "Gmail", "skills": ["inbox-triage"],
              "connect": "#aiui-connect:gmail", "button": "Connect Gmail"}


def test_an_app_the_answer_talks_about_connecting_gets_its_link():
    said = ("A task tracker connection (Trello, GitHub or ClickUp) would add "
            "daily-standup. There's a Connect button above if you want that.")
    assert F.missing_links(said, [TRACKER_NEED, GMAIL_NEED]) == [
        "[Connect a task tracker](#aiui-connect:trello)"]


def test_a_link_already_in_the_answer_is_not_added_twice():
    said = "Connect one. [Connect a task tracker](#aiui-connect:trello)"
    assert F.missing_links(said, [TRACKER_NEED]) == []


def test_an_answer_that_never_mentions_connecting_gets_nothing():
    """"Is there a skill for invoices" answered with a skill name is not an
    invitation to connect anything."""
    said = "Use invoice-chaser for that; it needs nothing connected."
    assert F.missing_links(said, [TRACKER_NEED]) == []


def test_only_the_apps_the_answer_names_get_a_link():
    said = "Connecting Gmail would add inbox-triage."
    assert F.missing_links(said, [TRACKER_NEED, GMAIL_NEED]) == [
        "[Connect Gmail](#aiui-connect:gmail)"]
    assert F.missing_links("", [GMAIL_NEED]) == []
    assert F.missing_links(said, []) == []
