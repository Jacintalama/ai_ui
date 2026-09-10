"""Skills an agent can be given, in the Agent Skills open format.

A skill is a folder holding a SKILL.md: frontmatter with a name and a
description, then instructions. The description is what the page shows and
what a person picks from; the body is what actually reaches the model.

The bodies matter more than usual here. They are injected into a gpt-4o-mini
prompt rather than read by a model with a filesystem, so a skill that is too
long is a skill that gets half followed, and one that quietly fails to parse
is a checkbox that lies.
"""
import pytest

import agent_skills


def test_the_skills_on_disk_actually_load():
    """The whole feature is files in a directory. If loading finds nothing,
    every test below passes vacuously and the page shows an empty list."""
    all_skills = agent_skills.load_all()
    assert len(all_skills) >= 10, len(all_skills)


@pytest.mark.parametrize("skill", sorted(agent_skills.load_all().values(),
                                         key=lambda s: s["name"]),
                         ids=lambda s: s["name"])
def test_every_skill_matches_the_spec(skill):
    name = skill["name"]
    assert 1 <= len(name) <= 64
    assert name == name.lower()
    assert not name.startswith("-") and not name.endswith("-")
    assert "--" not in name
    assert all(c.isalnum() or c == "-" for c in name), name
    assert 1 <= len(skill["description"]) <= 1024


@pytest.mark.parametrize("skill", sorted(agent_skills.load_all().values(),
                                         key=lambda s: s["name"]),
                         ids=lambda s: s["name"])
def test_the_name_matches_its_folder(skill):
    """The spec requires it, and the page addresses a skill by folder name."""
    assert skill["name"] == skill["folder"]


@pytest.mark.parametrize("skill", sorted(agent_skills.load_all().values(),
                                         key=lambda s: s["name"]),
                         ids=lambda s: s["name"])
def test_the_description_says_when_to_use_it(skill):
    """A description is not a label. It is what a person reads to decide, and
    later what a matcher reads to choose, so "Helps with email" is a defect."""
    assert "use when" in skill["description"].lower(), skill["description"]


@pytest.mark.parametrize("skill", sorted(agent_skills.load_all().values(),
                                         key=lambda s: s["name"]),
                         ids=lambda s: s["name"])
def test_the_body_is_short_enough_to_be_followed(skill):
    """These go into the prompt whole. The spec suggests under 5000 tokens for
    a model that can read files on demand; this one cannot, and it is mini, so
    the ceiling here is much lower and is checked rather than hoped at."""
    assert 0 < len(skill["body"]) <= agent_skills.MAX_SKILL_CHARS, len(skill["body"])


@pytest.mark.parametrize("skill", sorted(agent_skills.load_all().values(),
                                         key=lambda s: s["name"]),
                         ids=lambda s: s["name"])
def test_every_tool_a_skill_needs_is_one_this_platform_has(skill):
    """A skill naming a tool nobody has is a skill that silently does nothing,
    and the form promises to tell people which tool to tick."""
    known = {"server:mcp-proxy", "gmail", "calendar", "gdrive", "documents",
             "excel_creator", "executive_dashboard", "remember", "schedules",
             "account", "code"}
    assert set(skill["tools"]) <= known, set(skill["tools"]) - known


def test_the_catalogue_carries_no_bodies():
    """What the browser gets. Bodies are the agent's instructions, they are
    large, and shipping ten of them to a page that draws checkboxes would put
    the whole library in every page load."""
    for row in agent_skills.catalogue():
        assert set(row) == {"name", "description", "tools", "tags"}


# --- choosing them --------------------------------------------------------

def test_an_agent_with_no_skills_gets_nothing():
    """The ordinary case, and the one that must not add a word to the brief:
    every agent that existed before this feature has no skills."""
    assert agent_skills.selected({}) == []
    assert agent_skills.brief_for({}) == ""
    assert agent_skills.brief_for(None) == ""


def test_a_chosen_skill_reaches_the_brief():
    out = agent_skills.brief_for({"skillIds": ["inbox-triage"]})
    assert "Inbox triage" in out
    assert "Needs a reply today" in out


def test_a_skill_that_no_longer_exists_is_ignored_not_fatal():
    """Skills ship with the image; an agent's list is stored on its row. A
    renamed or removed skill must degrade to "that one is gone", never to an
    agent that cannot answer at all."""
    out = agent_skills.brief_for({"skillIds": ["inbox-triage", "no-such-skill"]})
    assert "Inbox triage" in out
    assert "no-such-skill" not in out


def test_junk_in_the_stored_list_is_survived():
    """meta comes off a database row a model-facing API writes."""
    for junk in (None, "inbox-triage", 5, {"a": 1}, [1, 2], [None]):
        agent_skills.brief_for({"skillIds": junk})


def test_the_order_chosen_is_the_order_taught():
    picked = agent_skills.selected({"skillIds": ["spreadsheet", "inbox-triage"]})
    assert [s["name"] for s in picked] == ["spreadsheet", "inbox-triage"]


def test_the_total_is_capped_however_many_are_chosen(monkeypatch):
    """Skills share the turn with the conversation, and the conversation is
    the thing being answered. The cap is forced low here rather than relying
    on ten skills happening to exceed it: they do not today, so a test that
    assumed they did would pass while proving nothing."""
    monkeypatch.setattr(agent_skills, "MAX_TOTAL_CHARS", 1500)
    every = [s["name"] for s in agent_skills.catalogue()]
    out = agent_skills.brief_for({"skillIds": every})
    assert len(out) <= 1500 + 400, len(out)   # room for the note about drops


def test_a_dropped_skill_is_said_out_loud_rather_than_silently_cut(monkeypatch):
    """Cutting to fit is right; doing it quietly is not. An agent that was
    given a skill and never told about it looks broken to the one person who
    knows they ticked the box."""
    monkeypatch.setattr(agent_skills, "MAX_TOTAL_CHARS", 1500)
    every = [s["name"] for s in agent_skills.catalogue()]
    out = agent_skills.brief_for({"skillIds": every})
    assert "not included" in out.lower()
    # Some are named and the rest are counted. Naming every one of forty was
    # the flaw the cap test found; naming none would be the silent cut this
    # test exists to prevent.
    named = [n for n in every if n in out.split("not included")[-1]]
    assert named, "the dropped ones are not named at all"
    assert len(named) <= agent_skills.NAMED_WHEN_DROPPED + 1


def test_the_first_chosen_skills_are_the_ones_that_survive_the_cap(monkeypatch):
    """Order is the only signal about which skill matters most, so cutting
    takes from the end. Dropping the first one would make the ordering on the
    card a lie."""
    monkeypatch.setattr(agent_skills, "MAX_TOTAL_CHARS", 1500)
    out = agent_skills.brief_for(
        {"skillIds": ["inbox-triage", "spreadsheet", "weekly-review"]})
    assert "Inbox triage" in out
    assert "weekly-review" in out.split("not included")[-1]


def test_a_description_with_a_colon_in_it_still_loads():
    """Found by these tests, not by reading the code: "Summarise the week:
    what shipped" is a good description and invalid unquoted YAML, so the
    frontmatter parsed as nothing and the skill silently vanished from the
    list. The generator quotes properly now; this is the guard."""
    every = agent_skills.load_all()
    assert "weekly-review" in every
    assert ":" in every["weekly-review"]["description"]


# --- reaching the agent ---------------------------------------------------

# The checkbox is decoration until the body reaches the turn. This is the part
# that makes a skill real, so it is tested against the function the panel, the
# channels and a scheduled run all go through.

async def test_the_endpoint_offers_the_catalogue():
    from routes_agents import skills as skills_endpoint
    out = await skills_endpoint()
    names = [s["name"] for s in out["skills"]]
    assert "inbox-triage" in names
    assert all("body" not in s for s in out["skills"])


def test_an_agent_with_a_skill_is_told_it():
    from routes_agent_turn import _identity_line
    said = _identity_line(
        {"id": "a", "name": "Mia", "meta": {"skillIds": ["inbox-triage"]}},
        ["Mia"])["content"]
    assert "Needs a reply today" in said
    assert "Skill: inbox-triage" in said


def test_an_agent_with_no_skills_gets_the_brief_it_had():
    """Every agent that predates this has none, so the ordinary turn must be
    unchanged to the character."""
    from routes_agent_turn import _identity_line
    plain = _identity_line({"id": "a", "name": "Mia"}, ["Mia"])["content"]
    empty = _identity_line({"id": "a", "name": "Mia", "meta": {}},
                           ["Mia"])["content"]
    assert plain == empty
    assert "Skill:" not in plain


def test_a_skill_does_not_displace_who_the_agent_is():
    """The identity line fixed an agent that did not know its own name. A
    skill is added to that brief, never in place of it."""
    from routes_agent_turn import _identity_line
    said = _identity_line(
        {"id": "a", "name": "Mia", "role": "Receptionist",
         "meta": {"role": "Receptionist", "skillIds": ["inbox-triage"]}},
        ["Mia", "Ada"])["content"]
    assert "You are Mia, this person's receptionist." in said
    assert "Never answer for them" in said
    assert "Skill: inbox-triage" in said


def test_a_missing_yaml_switches_skills_off_rather_than_the_service(monkeypatch):
    """PyYAML was in the image as an undeclared transitive dependency, which
    is the arrangement that disappears on a rebuild. This module is imported
    at startup by the turn router, which main.py imports, so a hard import
    would turn a missing library into the whole platform failing to boot."""
    monkeypatch.setattr(agent_skills, "yaml", None)
    monkeypatch.setattr(agent_skills, "_CACHE", None)
    assert agent_skills.load_all(refresh=True) == {}
    assert agent_skills.catalogue() == []
    assert agent_skills.brief_for({"skillIds": ["inbox-triage"]}) == ""


def test_pyyaml_is_a_declared_dependency():
    """The guard above keeps the service alive without it. This is what keeps
    the feature alive."""
    import pathlib
    reqs = (pathlib.Path(__file__).resolve().parents[1]
            / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "yaml" in reqs


# --- tags -----------------------------------------------------------------

# Tags ride in `metadata`, which the Agent Skills spec defines as a free map
# of string to string, so these stay valid skills another runtime can read
# rather than a fork of the format with an invented top-level key.

def test_every_skill_carries_at_least_one_tag():
    for skill in agent_skills.load_all().values():
        assert skill["tags"], skill["name"]


def test_tags_come_back_as_a_list_not_a_string():
    """The page filters on them and the search joins them. A bare string
    would silently match on substrings of other tags."""
    for skill in agent_skills.load_all().values():
        assert isinstance(skill["tags"], list)
        assert all(isinstance(t, str) and t == t.strip() for t in skill["tags"])


def test_the_catalogue_carries_the_tags():
    rows = agent_skills.catalogue()
    assert rows and all("tags" in r for r in rows)
    assert any("email" in r["tags"] for r in rows)


def test_a_skill_with_no_metadata_still_loads():
    """Every skill written before tags existed had none, and the spec makes
    metadata optional. A missing key must mean no tags, not no skill."""
    parsed = agent_skills._parse(
        "---\nname: x\ndescription: does a thing. Use when asked.\n---\nbody",
        "x")
    assert parsed is not None
    assert parsed["tags"] == []


def test_junk_metadata_does_not_take_the_skill_down():
    for junk in ("metadata: 5", "metadata:\n  tags: 7", "metadata: [1,2]"):
        parsed = agent_skills._parse(
            "---\nname: x\ndescription: d. Use when asked.\n%s\n---\nbody"
            % junk, "x")
        assert parsed is not None, junk
        assert parsed["tags"] == [], junk


def test_the_library_is_worth_browsing():
    """Ralph asked for more, and a tag filter with one entry per tag is not a
    filter. This is the floor, not a target."""
    every = agent_skills.load_all()
    tags = {t for s in every.values() for t in s["tags"]}
    assert len(every) >= 40, len(every)
    assert len(tags) >= 8, sorted(tags)


def test_the_note_about_dropped_skills_cannot_outgrow_the_budget(monkeypatch):
    """Found by the cap test the moment the library went from ten skills to
    forty: the note naming everything left out became larger than the budget
    it exists to protect. An apology for cutting that is itself the biggest
    thing in the prompt is worse than the cut."""
    monkeypatch.setattr(agent_skills, "MAX_TOTAL_CHARS", 1200)
    every = [s["name"] for s in agent_skills.catalogue()]
    out = agent_skills.brief_for({"skillIds": every})
    assert "and %d more" % (len(every) - 1 - agent_skills.NAMED_WHEN_DROPPED) in out
    assert len(out) < 2000, len(out)


# --- finding a skill you were never given -----------------------------------

# Measured before building: 64 skills, all bodies 37,990 chars, all
# descriptions 10,858, and an agent can hold about 13. So 51 of 64 are
# unreachable to any given agent, because a skill only works if somebody
# predicted in advance they would need it. Search makes them reachable at the
# cost of one sentence in the brief instead of a catalogue.

def test_search_finds_a_skill_by_what_it_is_for():
    hits = agent_skills.search("chase unpaid invoices")
    names = [h["name"] for h in hits]
    assert "follow-up-chaser" in names or "invoice-tracker" in names, names


def test_search_matches_the_name_itself():
    assert agent_skills.search("inbox triage")[0]["name"] == "inbox-triage"


def test_search_matches_a_tag():
    hits = [h["name"] for h in agent_skills.search("calendar")]
    assert any(h in hits for h in ("day-ahead", "meeting-scheduler",
                                   "protect-focus-time")), hits


def test_search_returns_the_description_not_the_body():
    """What comes back goes into a tool result the model reads. Bodies are
    600 characters each and five of them would be most of a turn."""
    for hit in agent_skills.search("email"):
        assert "body" not in hit
        assert hit["description"]


def test_search_is_capped():
    assert len(agent_skills.search("a", limit=3)) <= 3
    assert len(agent_skills.search("email")) <= 5


def test_a_query_matching_nothing_returns_nothing():
    """Better than five bad guesses. The agent is told to say so and get on
    with the job itself."""
    assert agent_skills.search("xylophone repair in antarctica") == []


def test_search_survives_junk():
    for junk in (None, "", "   ", 5, [], {"a": 1}):
        assert agent_skills.search(junk) == []


def test_a_better_match_comes_first():
    hits = agent_skills.search("write a document")
    assert hits[0]["name"] == "write-a-document", [h["name"] for h in hits]


def test_the_body_can_be_fetched_by_name():
    body = agent_skills.body_of("inbox-triage")
    assert "Needs a reply today" in body


def test_an_unknown_name_has_no_body():
    """The name comes from a model. A dict lookup is the whole defence: there
    is no path built from it, which is how the schedules tool grew a
    directory traversal that deleted stored credentials."""
    for bad in ("../secrets", "no-such-skill", "", None, 5,
                "inbox-triage/../../etc/passwd"):
        assert agent_skills.body_of(bad) is None
