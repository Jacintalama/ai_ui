"""The build tool hands out no URLs, because the page shows the thing.

A build used to answer "It takes a few minutes, watch it here: <url>",
and a change answered "Open it here: <url>". Both are a second way to
see something the reply already shows: the steps while it runs, and the
site itself when it is done. Ralph, 2026-11-05: "remove link please we
need to make sure its clean neat and very clean for the interface".

A URL cannot simply be deleted, because the page found the build BY
reading that URL out of the message. So the reply declares what it
carries instead, in a markdown link reference definition that renders as
nothing at all.

This drives the real tool with the HTTP call stubbed, rather than
reading its source, because what matters is the string a person ends up
looking at.
"""
import asyncio
import importlib.util
import os
import re

import pytest

TOOL = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "code_tool.py"))

TASK = "86028207-4ab0-45e6-ba6f-44d621e1e7d3"
URL = "https://ai-ui.coolestdomain.win/tasks/static/preview.html?task=" + TASK


def _tools(reply):
    """The real Tools, with the one network call answered by `reply`."""
    spec = importlib.util.spec_from_file_location("code_tool_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tools = mod.Tools()

    async def _call(method, route, **kw):
        return reply

    tools._call = _call
    tools._email = lambda u: "ralphbenitez32@gmail.com"
    tools._agent = lambda m: None
    return tools


def _run(coro):
    return asyncio.run(coro)


def _src():
    with open(TOOL, encoding="utf-8") as fh:
        return fh.read()


BUILT = {"task_id": TASK, "slug": "shoes-thunder-1a2b", "url": URL,
         "description": "a sporty landing page"}


# --- nothing a person has to click --------------------------------------

@pytest.mark.parametrize("call", ["create", "apply"])
def test_starting_a_build_hands_out_no_url(call):
    tools = _tools(BUILT)
    said = _run(tools.create_app("a shoe shop landing page")
                if call == "create" else tools.apply_app_change("tok"))
    assert "http" not in said, said
    assert "Watch it here" not in said
    assert "Open it here" not in said


@pytest.mark.parametrize("call", ["create", "apply"])
def test_it_says_which_build_so_the_page_can_show_it(call):
    """Deleting the URL without this would leave the page nothing to read
    and no panel would ever appear."""
    tools = _tools(BUILT)
    said = _run(tools.create_app("a shoe shop landing page")
                if call == "create" else tools.apply_app_change("tok"))
    assert said.rstrip().endswith("[aiui-artifact]: #build/" + TASK), said


@pytest.mark.parametrize("call", ["create", "apply"])
def test_the_declaration_is_alone_on_the_last_line(call):
    """A link reference definition renders as nothing only when it starts
    a line. Trailing it onto a sentence prints it to the person, which is
    the mistake the old HTML comment marker made."""
    tools = _tools(BUILT)
    said = _run(tools.create_app("x") if call == "create"
                else tools.apply_app_change("tok"))
    lines = said.rstrip().split("\n")
    assert lines[-1].startswith("[aiui-artifact]: ")
    assert lines[-2].strip() == "", "no blank line before the definition"


def test_a_finished_build_names_the_app_not_a_link():
    tools = _tools({"status": "completed", "slug": "shoes-thunder-1a2b",
                    "preview_url": "https://x/tasks/preview-app/shoes-thunder-1a2b/"})
    said = _run(tools.build_status(TASK))
    assert "http" not in said, said
    assert said.rstrip().endswith("[aiui-artifact]: #app/shoes-thunder-1a2b")
    assert "is built" in said


def test_a_build_that_failed_still_says_why():
    """Removing links must not remove the reason a build failed, which is
    often a billing refusal the owner can act on."""
    tools = _tools({"status": "failed", "slug": "shoes-thunder-1a2b",
                    "error": "insufficient credits"})
    said = _run(tools.build_status(TASK))
    assert "insufficient credits" in said


def test_a_reply_with_no_id_is_still_a_sentence():
    """The declaration is skipped rather than written half formed. A bare
    "[aiui-artifact]: #build/" would be a marker pointing at nothing."""
    tools = _tools({"slug": "shoes-thunder-1a2b", "description": "x"})
    said = _run(tools.create_app("x"))
    assert "[aiui-artifact]" not in said
    assert "shoes-thunder-1a2b" in said


# --- the model is told, because the model writes the reply ---------------

@pytest.mark.parametrize("method", ["create_app", "apply_app_change"])
def test_the_model_is_told_not_to_invent_a_link(method):
    """The tool's text is not what a person reads. The model paraphrases
    it, and in Ralph's chat it wrote the URL into its own sentence. The
    instruction has to be in the docstring, which is what the model is
    shown."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ct_doc", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    doc = " ".join((getattr(mod.Tools, method).__doc__ or "").split())
    assert "Do NOT write a link" in doc, doc
    assert "[aiui-artifact]" in doc
    assert "exactly as written" in doc


def test_no_method_of_this_tool_still_writes_a_url_line():
    """Counted across the whole file, so a fourth reply added later
    cannot quietly reintroduce one."""
    src = _src()
    assert "Watch it here" not in src
    assert "Open it here" not in src
    # The only remaining "url" uses are the valve and the HTTP call.
    offered = re.findall(r'said \+= "[^"]*(?:http|Open|Watch)[^"]*"', src)
    assert offered == [], offered
