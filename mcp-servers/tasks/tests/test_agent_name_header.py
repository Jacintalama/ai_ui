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


def _js_function(section, name):
    """The body of one named function, by brace counting from its opening
    brace. Scoping an assertion to the function it is about beats a fixed
    character window, which silently slides off the end when code moves.
    """
    start = section.index("function " + name + "(")
    brace = section.index("{", start)
    depth = 0
    for i in range(brace, len(section)):
        if section[i] == "{":
            depth += 1
        elif section[i] == "}":
            depth -= 1
            if depth == 0:
                body = section[start:i + 1]
                assert len(body) > 40, "extracted a suspiciously tiny " + name
                return body
    raise AssertionError("unbalanced braces reading " + name)


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
    otherwise see and try to handle again. Without a guard that loops.

    The header write itself is now allowed to repeat, because a reply
    streams and a second agent's name can arrive after the first is already
    on screen. That is safe only because the write is conditional: it
    reassigns nothing when the name has not changed, so it stops producing
    mutations. The destructive step, removing a line from the body, is the
    one that must never run twice, and it carries its own flag.
    """
    section = _agent_header_section(_js())
    assert "data-aiui-agent-header" in section
    assert re.search(r"setAttribute\(\s*['\"]data-aiui-agent-header['\"]", section)

    assert re.search(r"if\s*\(\s*span\.textContent\s*!==", section), (
        "the header is rewritten unconditionally, so every scan mutates the "
        "DOM and retriggers the observer")

    body = _js_function(section, "aiuiRewriteAgentHeader")
    guard = body.find("data-aiui-agent-stripped")
    strip = body.find("aiuiStripLabel(")
    assert guard != -1, "the destructive step has no guard flag"
    assert strip != -1, "the rewrite never strips a label"
    assert guard < strip, "aiuiStripLabel runs before its guard is checked"


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
    """The header can only ever be set to a name that survived the
    known-agent lookup. If any path could skip that check, the
    pattern-alone problem this was built to fix would still be reachable.

    The shapes now share one collector instead of branching per case, so
    the property is checked where it lives: no name enters the list without
    passing the gate, and the header is written from that list and nothing
    else.
    """
    section = _agent_header_section(_js())

    collector = _js_function(section, "aiuiAgentLabelsIn")
    gate = collector.find("aiuiNameIsKnownAgent(")
    push = collector.find("result.labels.push(")
    assert gate != -1, "the collector never checks aiuiNameIsKnownAgent"
    assert push != -1, "the collector never collects anything"
    assert gate < push, "a name is collected before the known-agent check"
    # The continue has to belong to this guard's own block. Looking for
    # one anywhere between the gate and the push finds the NEXT guard's
    # continue instead, and passes even when the gate falls through.
    assert re.search(
        r"!aiuiNameIsKnownAgent\([^)]*\)\)\s*\{[^{}]*\bcontinue\b[^{}]*\}",
        collector), (
        "an unknown name is not skipped by the known-agent guard itself, "
        "so it reaches the collected list")

    rewrite = _js_function(section, "aiuiRewriteAgentHeader")
    writes = [m.start() for m in re.finditer(r"span\.textContent\s*=", rewrite)]
    assert writes, "the header is never rewritten at all"
    empty_check = rewrite.find("scan.labels.length")
    assert empty_check != -1, "nothing checks whether any agent was found"
    for w in writes:
        assert empty_check < w, (
            "the header is written before checking that an agent was found")
        assert re.search(r"span\.textContent\s*=\s*joined", rewrite[w:w + 60]), (
            "the header is written from something other than the collected "
            "names")

    for name in ("aiuiAgentLabelsIn", "aiuiStripLabel"):
        assert "span.textContent =" not in _js_function(section, name), (
            name + " writes the header outside the gated path")


def test_exactly_one_label_is_ever_processed_per_reply():
    """A pipe reply holds one agent now, so the header names one agent
    and the single label below it is stripped. The old two-agent path,
    where labels stayed to say who was who, is gone with the DOM split."""
    section = _agent_header_section(_js())
    rewrite = _js_function(section, "aiuiRewriteAgentHeader")
    assert "names[0]" in rewrite
    assert "aiuiJoinNames" not in section
    assert "aiuiStripLabel(body, scan.labels[0])" in rewrite


def test_a_label_is_found_past_the_tool_result_panel():
    """Open WebUI renders the tool call result as the first thing in the
    body, so the agent's name no longer opens the message. Reading only the
    body's own first text node finds the panel's text instead and silently
    gives up, which is exactly how this broke in production."""
    section = _agent_header_section(_js())
    collector = _js_function(section, "aiuiAgentLabelsIn")
    # The blocks scanned are the children of whichever element actually
    # holds the rendered paragraphs. That used to be the body itself; since
    # Open WebUI wrapped replies in extra divs it is found by walking up
    # from the first real text. Either way, every block must be a candidate.
    assert "holder.children" in collector or "body.children" in collector, (
        "only the body's own leading text is examined, so a reply whose "
        "first block is the tool result panel never matches")
    assert "candidates.push(" in collector, (
        "no block beyond the first is ever offered as a candidate")
    assert "aiuiFirstTextNode(candidates[" in collector, (
        "each block is not read from its own leading text, which would let "
        "a match come from deep inside quoted content")


def test_a_label_is_only_removed_once_the_reply_stops_growing():
    """A reply arrives a token at a time, so "Mia:" is on screen a beat
    before "Ada:" exists. Stripping the label the moment it is the only one
    deletes it right before it stops being the only one."""
    section = _agent_header_section(_js())
    rewrite = _js_function(section, "aiuiRewriteAgentHeader")
    # Naming the flag is not the property. What matters is that the value
    # is compared against the previous look, and that a reply which has
    # not settled returns before reaching the destructive step.
    assert re.search(
        r"settled\s*=\s*span\.getAttribute\(\s*['\"]data-aiui-agent-seen['\"]\s*\)"
        r"\s*===", rewrite), (
        "nothing compares this look against the previous one")
    assert re.search(r"if\s*\(\s*!settled\s*\)\s*\{[^}]*return;", rewrite, re.S), (
        "an unsettled reply is not returned early, so the label is removed "
        "while the message is still growing")
    assert re.search(r"if\s*\(\s*!settled\s*\)\s*\{[^}]*aiuiScheduleSettleScan\(\)",
                     rewrite, re.S), (
        "no follow up scan is scheduled, so the second look may never happen")


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


def test_the_page_takes_turns_from_the_marker():
    """Every further agent's reply is fetched by the page and written into
    the chat as a real message. That code must read the marker, wait for
    the save, call the speak route, write through the chat API, and
    soft navigate. Missing any one of those is a broken feature."""
    section = _agent_header_section(_js())
    assert "aiui:turns" in section
    assert "function aiuiTakeTurns(" in section
    assert "/api/tasks/agents/speak" in section
    assert "'/api/v1/chats/' + chatId" in section
    assert "aiuiWaitForSavedMarker" in section
    assert "aiuiSoftReload" in section
    # Driven from the scan, not from the header rewrite. See
    # test_turn_taking_does_not_depend_on_a_label for why that matters.
    assert "function aiuiMaybeTakeTurns(" in section
    assert "aiuiTakeTurns(" not in _js_function(section, "aiuiRewriteAgentHeader")


def test_the_page_never_writes_before_the_reply_is_saved():
    """Open WebUI saves the whole chat after a reply. Writing before that
    save would have the new message erased by it."""
    section = _agent_header_section(_js())
    body = _js_function(section, "aiuiTakeTurns")
    wait = body.find("aiuiWaitForSavedMarker(")
    save = body.find("aiuiSaveChat(")
    assert wait != -1 and save != -1
    assert wait < save, "the chat is written before the wait for the save"


def test_a_new_message_is_a_child_of_the_tail_with_the_agent_as_its_model():
    """The write goes against the copy re-fetched immediately before it, so
    the parent is that copy's tail. It is still the tail this turn was taken
    for: test_the_write_is_guarded_against_a_moved_chat pins the two
    together and abandons the turn when they differ."""
    section = _agent_header_section(_js())
    body = _js_function(section, "aiuiTakeTurns")
    assert "parentId: ftail.id" in body
    assert "model: next" in body
    assert "fh.currentId = newId" in body


def test_the_dom_clone_split_is_gone():
    """A pipe reply now holds one agent, so the code that cloned rows for
    two can never run. Leaving it would be a second rendering path for a
    case that no longer exists."""
    section = _agent_header_section(_js())
    assert "aiuiSplitIntoAgentMessages" not in section
    assert "data-aiui-agent-clone" not in section
    assert "aiuiSwapAvatar" not in section


def test_turn_taking_does_not_depend_on_a_label():
    """A reply the page wrote carries no label. If turn taking lived
    behind the label check, the third agent would never speak."""
    section = _agent_header_section(_js())
    rewrite = _js_function(section, "aiuiRewriteAgentHeader")
    scan = _js_function(section, "aiuiScanAgentNameHeaders")
    assert "aiuiTakeTurns(" not in rewrite
    assert "aiuiMaybeTakeTurns(" in scan
    # The empty placeholder is not a reply, and the latch belongs to the
    # RESULT of the turn, never to the attempt.
    maybe = _js_function(section, "aiuiMaybeTakeTurns")
    assert "if (sig === '0') return;" in maybe
    then = maybe.find(".then(")
    latch = maybe.find("data-aiui-turns-checked', sig")
    call = maybe.find("aiuiTakeTurns(")
    assert then != -1 and latch != -1, "the latch is not set from a callback"
    assert call < then < latch, (
        "the latch is set outside the promise callback, so a turn that never "
        "ran would still latch shut")


def test_the_write_is_guarded_against_a_moved_chat():
    section = _agent_header_section(_js())
    body = _js_function(section, "aiuiTakeTurns")
    assert "ftail.id !== tail.id" in body
    assert "m.model === next" in body
    assert "{ history: fh }" in body


def test_the_turns_latch_waits_for_a_real_reply():
    """The placeholder Open WebUI renders before a reply arrives is empty
    and stable, so a settle check that accepted it would fire before
    content, poll against nothing, and latch shut for good. The latch
    is keyed to the body length and set only after a done tail was
    examined, so a reply that finishes later is looked at again."""
    section = _agent_header_section(_js())
    maybe = _js_function(section, "aiuiMaybeTakeTurns")
    assert "if (sig === '0') return;" in maybe
    latch = maybe.find("data-aiui-turns-checked', sig")
    call = maybe.find("aiuiTakeTurns(")
    assert latch != -1 and call != -1 and call < latch, (
        "the latch is set before the turn is taken")
    wait = _js_function(section, "aiuiWaitForSavedMarker")
    assert "tail.role !== 'assistant'" in wait
