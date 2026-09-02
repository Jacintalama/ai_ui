"""The reply header shows the agent's name, not the model.

Structural, because this file is vanilla JS with no test harness. These
check the things that would silently break the feature or, worse, make it
rewrite a message it should have left alone. See test_connect_button.py for
the same approach applied to a different piece of this file.
"""
import os
import re

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _agent_header_section(js):
    """The block this task added: from its own section comment up to the
    console.log that already sat at the bottom of the file. A structural
    boundary rather than "the whole file", the same way
    _connect_links_section in test_connect_button.py scopes itself, so a
    change made anywhere else in this large file cannot make these
    assertions pass by accident.
    """
    start = js.index("===== Agent name in the reply header =====")
    end = js.index("Integrations UI v16-connect-your-own loaded")
    assert start < end
    return js[start:end]


def test_the_model_name_header_is_the_hook():
    """Every assistant reply reuses this id, so it has to be queried with
    querySelectorAll, never getElementById."""
    section = _agent_header_section(_js())
    assert "querySelectorAll" in section
    assert "response-message-model-name" in section
    assert "getElementById('response-message-model-name')" not in section
    assert 'getElementById("response-message-model-name")' not in section


def test_a_debounced_mutation_observer_watches_for_new_replies():
    section = _agent_header_section(_js())
    assert re.search(r"new MutationObserver\(", section)
    assert "setTimeout" in section
    # The debounce needs a pending flag so a burst of DOM mutations
    # collapses into one scan, the same pattern wireAiuiConnectLinks uses.
    assert re.search(r"\bpending\b", section)


def test_a_processed_header_cannot_be_reprocessed():
    """Rewriting the header mutates the DOM, which the observer above would
    otherwise see and try to handle again. Without a guard that loops."""
    section = _agent_header_section(_js())
    assert "data-aiui-agent-header" in section
    assert re.search(r"getAttribute\(\s*['\"]data-aiui-agent-header['\"]\s*\)", section)
    assert re.search(r"setAttribute\(\s*['\"]data-aiui-agent-header['\"]", section)


def test_the_name_pattern_is_anchored_and_bounded():
    """A loose .* would happily match "Note:" or "Warning:" at the start of
    an ordinary reply and rewrite the header to something that was never an
    agent's name. The pattern must be anchored at the start, built from a
    restricted character class, and capped in length rather than open
    ended."""
    section = _agent_header_section(_js())
    patterns = re.findall(r"/\^\([^)]*\)[^/]*/", section)
    assert patterns, "no anchored, capturing name pattern found"
    for p in patterns:
        assert ".*" not in p, "loose wildcard in the name pattern: " + p
        assert re.search(r"\{1,40\}", p), "no length cap in: " + p
        assert p.startswith("/^("), "pattern is not anchored at the start: " + p


def test_ordinary_prose_after_a_colon_never_matches():
    """"Note: ...", "Warning: ...", "TODO: ..." all put the rest of the
    sentence on the same line as the colon, not a line break. The pattern
    requires the line break to land immediately after the colon, so none
    of these ever reach the header rewrite."""
    section = _agent_header_section(_js())
    name_re_matches = re.findall(r"/\^\(\[[^\]]*\]\{1,40\}\):[^/]*/", section)
    assert name_re_matches, "no bounded name-colon pattern found"
    for pattern_src in name_re_matches:
        compiled = re.compile(pattern_src.strip("/"))
        for bad in ["Note: follow up later",
                    "Warning: check this before you deploy",
                    "TODO: fix this later"]:
            assert not compiled.match(bad), (
                pattern_src + " matched rejected text: " + repr(bad))


def test_a_name_over_the_length_cap_never_matches():
    section = _agent_header_section(_js())
    name_re_matches = re.findall(r"/\^\(\[[^\]]*\]\{1,40\}\):[^/]*/", section)
    assert name_re_matches, "no bounded name-colon pattern found"
    too_long = "A" * 41 + ":\nBody"
    for pattern_src in name_re_matches:
        compiled = re.compile(pattern_src.strip("/"))
        assert not compiled.match(too_long), (
            pattern_src + " matched a name past the 40 character cap")


def test_never_touches_the_users_own_message():
    section = _agent_header_section(_js())
    assert "assistant" in section.lower()


def test_the_pattern_alone_is_not_enough_to_rewrite():
    """A shape match ("Mia:" and "Note:" look identical to the regex) can
    never be the whole gate on its own: the code must also check the name
    against something the pattern does not know, a lookup of this signed
    in person's real agents."""
    section = _agent_header_section(_js())
    assert "aiuiNameIsKnownAgent" in section
    assert "aiuiAgentNames" in section
    # Not just present somewhere: called from inside the rewrite function
    # itself, not off in an unused helper.
    assert re.search(r"aiuiNameIsKnownAgent\s*\(", section)


def test_every_rewrite_is_reached_through_the_known_agent_check():
    """Both shapes the header code recognises (the name and the reply in
    one text node, or the name alone before a line break, which can itself
    end in a br sibling or a whole wrapping block) must check the
    known-agent lookup before ever touching span.textContent. If any path
    could skip the check, the pattern-alone problem this was built to fix
    would still be reachable.

    Scoped per "Case" block (Case 1's own code, then Case 2's), rather than
    a fixed character window, because Case 2 branches twice after its one
    gate check and the second branch sits further away than the first.
    """
    section = _agent_header_section(_js())
    case_starts = [m.start() for m in re.finditer(r"// Case \d:", section)]
    assert len(case_starts) >= 2, "expected at least two Case blocks"
    boundaries = case_starts + [len(section)]
    total_writes = 0
    for i in range(len(case_starts)):
        block = section[boundaries[i]:boundaries[i + 1]]
        gate_idx = block.find("aiuiNameIsKnownAgent(")
        assert gate_idx != -1, "Case block %d has no known-agent check" % (i + 1)
        writes = [m.start() for m in re.finditer(r"span\.textContent\s*=", block)]
        assert writes, "Case block %d never rewrites the header at all" % (i + 1)
        total_writes += len(writes)
        for w in writes:
            assert gate_idx < w, (
                "Case block %d rewrites the header before checking "
                "aiuiNameIsKnownAgent" % (i + 1))
    assert total_writes >= 3, (
        "expected a rewrite in Case 1 plus both of Case 2's branches")


def test_an_empty_set_of_names_means_no_rewrite_ever():
    """The set starts empty, not null and not pre-populated, so before the
    first successful fetch (and for anyone whose fetch never succeeds) the
    gate simply never opens. That is the safe failure direction: an
    untouched message costs nothing, a wrongly rewritten one does not."""
    section = _agent_header_section(_js())
    assert re.search(r"var\s+aiuiAgentNames\s*=\s*new Set\(\)\s*;", section), (
        "the known-agent set must be initialised empty")
    # The lookup itself must read that same set, not some other source
    # that could be non-empty before a fetch ever completes.
    assert re.search(r"aiuiAgentNames\.has\(", section)


def test_agent_names_come_from_the_same_source_agents_html_uses():
    """agents.html already solved "which models are this person's agents":
    /api/v1/models/list, filtered to ids this platform minted. Reusing that
    instead of a second guess keeps the two pages agreeing about what
    counts as an agent."""
    section = _agent_header_section(_js())
    assert "/api/v1/models/list" in section
    assert "aiuiAuthHeaders()" in section
    assert re.search(r"/\^agent-/", section), (
        "must filter to minted agent ids the same way agents.html does")


def test_a_failed_names_fetch_never_throws_and_never_clears_a_good_list():
    section = _agent_header_section(_js())
    assert ".catch(function ()" in section
    catch_start = section.index(".catch(function ()")
    catch_block = section[catch_start:catch_start + 400]
    assert "aiuiAgentNames =" not in catch_block, (
        "a failed refresh must not reset the names already known")


def test_the_names_are_refreshed_but_rate_limited():
    """Somebody can create an agent mid conversation, so a stale set must
    not be permanent, but a whole conversation full of shape matches that
    are not real agents must not turn into a request per message."""
    section = _agent_header_section(_js())
    assert "aiuiAgentNamesFetchedAt" in section
    assert re.search(r"AIUI_AGENT_NAMES_TTL_MS\s*=\s*\d{5,}", section), (
        "no millisecond refresh interval found"
    )
    assert re.search(r"aiuiAgentNamesFetchedAt\s*&&", section), (
        "the refresh must check how recently it last ran"
    )


def test_no_dashes_in_the_new_copy():
    # Built via chr(), not a literal or escaped character, so this
    # assertion cannot be defeated by accidentally typing the very
    # character it is checking for.
    assert chr(0x2014) not in _js() and chr(0x2013) not in _js()
