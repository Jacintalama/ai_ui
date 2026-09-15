"""The memory line on the card. Structural, like test_agents_page_access."""
import os
import re

PAGE = os.path.join(os.path.dirname(__file__), "..", "static", "agents.html")


def _page():
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


def _js_function(page, name):
    """The body of one named function, by brace counting from its opening
    brace. The same technique test_agent_name_header.py uses, and for the
    same reason: an assertion scoped to the function it is about cannot be
    satisfied by a coincidence somewhere else in a 2,500 line file.
    """
    start = page.index("function " + name + "(")
    brace = page.index("{", start)
    depth = 0
    for i in range(brace, len(page)):
        if page[i] == "{":
            depth += 1
        elif page[i] == "}":
            depth -= 1
            if depth == 0:
                body = page[start:i + 1]
                assert len(body) > 40, "extracted a suspiciously tiny " + name
                return body
    raise AssertionError("unbalanced braces reading " + name)


def _paren_group(text, start):
    """The text of the parenthesised group that opens at start, by paren
    counting. card() is built as one long expression, so the branch a piece
    of markup belongs to is a parenthesised group rather than a block.
    """
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError("unbalanced parentheses reading a branch of card()")


def _forget_branch(page):
    """The forget branch of the card click handler, bounded by the branch
    that follows it. The handler is an anonymous listener, so there is no
    function to brace count; the next branch is the honest boundary.
    """
    start = page.index('if (btn.dataset.act === "forget"')
    end = page.index('if (btn.dataset.act === "edit")', start)
    assert start < end
    return page[start:end]


def test_every_owned_card_has_a_memory_line_and_a_show_control():
    page = _page()
    assert 'data-memory-for="' in page
    assert 'data-act="memory"' in page
    assert "/api/tasks/agents/memory" in page
    assert 'data-act="forget"' in page
    assert 'data-act="forget-all"' in page


def test_the_words_are_plain():
    page = _page()
    assert "Forget all" in page
    assert "Nothing remembered yet." in page


def test_an_owner_is_never_told_their_own_agent_is_not_theirs():
    """The service answers 403 with that sentence both when the agent really
    belongs to somebody else and when Open WebUI cannot be reached to say
    who owns what. Rendering the detail as written would tell an owner their
    own agent is not theirs every time the model listing hiccups, so the
    page says it could not read the notes and leaves the diagnosis out of
    it.
    """
    page = _page()
    assert "That is not one of your agents." not in page
    assert "Could not read the notes." in page


def test_the_memory_line_is_only_built_for_owned_cards():
    """Notes are private to the person the agent wrote them about, and the
    listing an admin sees carries everybody's agents. The markup has to sit
    inside the owner branch of card(), not merely be hidden afterwards.
    """
    body = _js_function(_page(), "card")
    at = body.index("data-memory-for")
    opener = body.rfind("(mine", 0, at)
    assert opener != -1, "the memory line is not inside a mine branch at all"
    group = _paren_group(body, opener)
    assert "data-memory-for" in group, (
        "the memory line sits outside the mine branch that precedes it")
    assert re.search(r':\s*""\s*\)$', group), (
        "the branch for somebody else's card renders something other than "
        "nothing")


def test_the_show_control_is_a_disclosure():
    """Show and Hide are the same button, so anything reading the page out
    loud has to be told which of the two it currently is. The page already
    does this for its other disclosures; this one was the exception."""
    page = _page()
    assert 'aria-expanded="false">Show</button>' in page
    body = _js_function(page, "showMemory")
    assert '"aria-expanded", "true"' in body
    assert '"aria-expanded", "false"' in body
    assert '"Hide"' in body and '"Show"' in body


def test_a_second_click_cannot_double_the_list():
    """Two fast clicks on Show sent two reads, and both appended: three
    notes came back as six rows. The second click has to find the first one
    still out and do nothing."""
    body = _js_function(_page(), "showMemory")
    guard = body.find('dataset.loading === "1"')
    assert guard != -1, "nothing stops a second read while the first is out"
    toggle = body.find("list.hidden = true")
    assert toggle != -1 and toggle < guard, (
        "the guard runs before the toggle, so a click that should close the "
        "list is swallowed instead")
    assert body.count('dataset.loading = ""') >= 1, "the flag is never cleared"
    assert "finally" in body, (
        "the flag is not cleared on the failure path, so one failed read "
        "locks the list shut for good")


def test_forgetting_everything_asks_first():
    """Deleting an agent asks, and that is recoverable by making another
    one. Emptying a memory is not recoverable at all, and had no question
    on it. One note is still forgotten on the click: it was read before it
    went, and it is one note."""
    branch = _forget_branch(_page())
    assert "This cannot be undone." in branch
    assert re.search(r'forget-all"\s*&&\s*!window\.confirm\(', branch), (
        "the question is not gated to forget-all, or is not asked at all")
    confirm = branch.index("window.confirm(")
    call = branch.index("forgetMemory(")
    assert confirm < call, "the notes are deleted before the question is put"
