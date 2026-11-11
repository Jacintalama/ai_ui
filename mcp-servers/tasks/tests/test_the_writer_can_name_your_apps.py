"""The skill writer can name a connected app's tools (2026-11-11).

Found by using the writer for real, which nobody had done since it shipped
on 2026-11-04. Asked for a skill whose whole job was writing a Trello card,
on an account with Trello connected, it picked:

    gmail, calendar, documents, gdrive, remember, server:mcp-proxy

Not one Trello tool. Measured cause, not guessed: `tools_for_email` returns
17 tools and none of them is Trello, because every connected app, ClickUp
and Trello and GitHub and n8n and Notion and the rest, is collapsed into a
single entry:

    - server:mcp-proxy (Your connected apps)

So that was the only item on the list that could possibly cover Trello. The
model's pick was CORRECT given what it was shown. This is #177 one layer
up: there `update_task` was not in the top ten for an "assign" sentence, so
a duplicate was the only move, and the fix was to change what the model was
shown rather than to blame it.

WHY THE UMBRELLA IS NOT THE BUG, and must not be removed. It has three
callers and it is right for two of them:

    /agents/tools                       the agent form, where it is ONE
                                        checkbox meaning "all my apps"
    routes_agent_turn._every_tool_for   the ids an agent may reach
    draft_skill / save_my_skill         the writer, which writes PROSE

`tools_for_email`'s own comment records that hiding the umbrella once
silently stripped Ada's only tool, so this fixes the writer's view alone
and leaves that function untouched.
"""
import skill_writer
import user_skills


BASE = {"gmail": "Gmail", "calendar": "Calendar", "gdrive": "Google Drive",
        "documents": "Documents", "remember": "Memory",
        "server:mcp-proxy": "Your connected apps"}


# --- expanding the umbrella -------------------------------------------------

def test_nothing_connected_leaves_the_list_alone():
    assert skill_writer.with_connected_apps(BASE, {}) == BASE


def test_a_connected_app_becomes_a_tool_the_model_can_name():
    out = skill_writer.with_connected_apps(BASE, {"trello": "Trello"})
    assert "my-trello" in out


def test_the_label_says_it_is_their_own_account():
    """The point of the per-user tools. A label that just said "Trello"
    would read like the shared connector."""
    out = skill_writer.with_connected_apps(BASE, {"trello": "Trello"})
    assert "Trello" in out["my-trello"]
    assert "own" in out["my-trello"].lower()


def test_several_apps_all_appear():
    out = skill_writer.with_connected_apps(
        BASE, {"trello": "Trello", "clickup": "ClickUp", "github": "GitHub"})
    assert {"my-trello", "my-clickup", "my-github"} <= set(out)


def test_the_umbrella_stays():
    """An agent still needs server:mcp-proxy ticked to reach any of them,
    so removing it here would produce a skill naming tools the agent cannot
    actually be given."""
    out = skill_writer.with_connected_apps(BASE, {"trello": "Trello"})
    assert "server:mcp-proxy" in out


def test_the_original_list_is_not_mutated():
    """BASE is handed in by a caller that uses it afterwards for the tool
    warning."""
    before = dict(BASE)
    skill_writer.with_connected_apps(BASE, {"trello": "Trello"})
    assert BASE == before


def test_an_app_already_listed_is_not_doubled():
    listed = dict(BASE)
    listed["my-trello"] = "Trello, your own account"
    out = skill_writer.with_connected_apps(listed, {"trello": "Trello"})
    assert len([k for k in out if k == "my-trello"]) == 1


def test_a_blank_app_id_is_ignored():
    out = skill_writer.with_connected_apps(BASE, {"": "Nothing"})
    assert "my-" not in out


# --- what the model then actually reads ------------------------------------

def test_the_prompt_offers_the_app_by_id():
    tools = skill_writer.with_connected_apps(BASE, {"trello": "Trello"})
    blob = str(skill_writer.prompt_for("put my report on Trello", tools, 4000))
    assert "my-trello" in blob


def test_the_prompt_without_the_fix_offers_no_trello_id():
    """The regression this exists to prevent, stated as the measurement
    that found it: the word Trello appears only because the JOB says it."""
    blob = str(skill_writer.prompt_for("put my report on Trello", BASE, 4000))
    assert "my-trello" not in blob


def test_the_prompt_still_tells_it_to_use_only_listed_ids():
    tools = skill_writer.with_connected_apps(BASE, {"trello": "Trello"})
    blob = str(skill_writer.prompt_for("anything", tools, 4000))
    assert "allowed-tools only ids from that list" in blob


def test_a_person_with_nothing_connected_still_gets_the_no_tools_wording():
    blob = str(skill_writer.prompt_for("anything", {}, 4000))
    assert "connected no tools" in blob


# --- and the warning must not then fire on a tool they DO have -------------

def test_naming_the_app_tool_does_not_warn_that_it_is_unconnected():
    """`save_my_skill` warns about tools not in the known list. Expanding
    the list for the prompt but not for the warning would produce a skill
    that warns about the very tool it was told to use."""
    tools = skill_writer.with_connected_apps(BASE, {"trello": "Trello"})
    assert user_skills.tool_warning(["my-trello"], tools) == ""


def test_a_tool_they_really_lack_still_warns():
    tools = skill_writer.with_connected_apps(BASE, {"trello": "Trello"})
    said = user_skills.tool_warning(["my-clickup"], tools)
    assert said and "my-clickup" in said



# --- the label source, which I got wrong first time -----------------------

def test_the_connectable_apps_all_have_a_real_label():
    """Caught 2026-11-11 by checking against the live database rather than
    the tests: `routes_agents._label_for` covers gmail, calendar, gdrive
    and the umbrella only, so for a proxy app it hands back the raw id.
    My first fix used it and would have written "trello, your own account"
    into every prompt. connections.PROVIDERS is where the labels live."""
    import connections as C
    for pid, want in (("trello", "Trello"), ("clickup", "ClickUp"),
                      ("github", "GitHub"), ("notion", "Notion")):
        provider = C.provider(pid)
        assert provider is not None, pid
        assert getattr(provider, "label", "") == want, pid


def test_the_label_is_not_taken_from_the_agent_form_table():
    """Structural, because the bug was invisible in behaviour: the id and
    the label differ only in case, so a wrong source still produced a
    working prompt that read badly. Assert the statement, not the name."""
    import inspect

    import routes_agents
    src = inspect.getsource(routes_agents._connected_apps_for)
    # Comments and docstrings stripped: the function explains in prose why
    # it does NOT use _label_for, and matching that sentence would pass the
    # test for the wrong reason, or fail it for the wrong reason.
    code = "\n".join(line.split("#", 1)[0]
                     for line in src.splitlines()
                     if not line.strip().startswith("#"))
    code = code.split('"""')[0] + "".join(code.split('"""')[2:])
    assert "C.provider(" in code, code
    assert "_label_for" not in code, code


def test_a_provider_with_no_label_falls_back_to_its_id():
    out = skill_writer.with_connected_apps(BASE, {"weirdapp": ""})
    assert out["my-weirdapp"] == "weirdapp, your own account"
