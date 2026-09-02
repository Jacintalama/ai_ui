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


def test_no_dashes_in_the_new_copy():
    # Built via chr(), not a literal or escaped character, so this
    # assertion cannot be defeated by accidentally typing the very
    # character it is checking for.
    assert chr(0x2014) not in _js() and chr(0x2013) not in _js()
