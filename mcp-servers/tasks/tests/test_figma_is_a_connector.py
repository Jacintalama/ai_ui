"""Figma: read a design so it can be built, as you, with a personal token.

Read off Figma's REST API docs (2026-11-25) first, because three facts
shape everything here:

**There is no way to list somebody's files.** Every tool starts from a
file's link, and the frame is in the link too, written 1-2 where the API
writes 1:2.

**Reading a design is rationed.** Since 2025-11-17 a file on the free
Starter plan allows about 6 reads a month and a View or Collab seat about
20. So one read carries as much as it can (an outline built to be read
once), the tools say which calls count, and a 429 says why and when.

**A frame's JSON is enormous.** The outline keeps one line per layer:
name, size, auto-layout, colour, font and the words.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import account_summary as acc
import agent_jev
import agent_tools
import app_triage
import connections as C
import figma_args as F
import mytools

HERE = os.path.dirname(__file__)
PANEL = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")
TENANTS = os.path.join(HERE, "..", "..", "..", "mcp-proxy", "tenants.py")

KEY = "AbCdEf1234567890XyZ"
LINK = "https://www.figma.com/design/%s/My-Site?node-id=12-345&t=abc" % KEY


class _R:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)
        self.headers = headers or {}

    def json(self):
        return self._payload


def _tool(name):
    return next(t for t in mytools.PROVIDER_TOOLS["figma"] if t.name == name)


def _solid(r, g, b, a=1.0, opacity=None):
    p = {"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": a}}
    if opacity is not None:
        p["opacity"] = opacity
    return [p]


HERO = {
    "id": "1:2", "type": "FRAME", "name": "Hero",
    "absoluteBoundingBox": {"width": 1440, "height": 800},
    "layoutMode": "VERTICAL", "itemSpacing": 24,
    "paddingTop": 64, "paddingRight": 120, "paddingBottom": 64,
    "paddingLeft": 120, "primaryAxisAlignItems": "CENTER",
    "fills": _solid(0.06, 0.09, 0.16), "cornerRadius": 12,
    "effects": [{"type": "DROP_SHADOW", "visible": True}],
    "children": [
        {"id": "1:3", "type": "TEXT", "name": "Headline",
         "characters": "Build  faster\nwith IO",
         "style": {"fontFamily": "Inter", "fontSize": 64,
                   "fontWeight": 700, "lineHeightPx": 72,
                   "textAlignHorizontal": "CENTER"},
         "fills": _solid(1, 1, 1),
         "absoluteBoundingBox": {"width": 600, "height": 144}},
        {"id": "1:4", "type": "RECTANGLE", "name": "Hidden",
         "visible": False},
        {"id": "1:5", "type": "INSTANCE", "name": "Button/Primary",
         "fills": _solid(0.49, 0.55, 1, opacity=0.5),
         "strokes": _solid(0, 0, 0), "strokeWeight": 1,
         "absoluteBoundingBox": {"width": 160, "height": 48}},
    ],
}


# --- the credential --------------------------------------------------------

def test_figma_is_a_provider():
    p = C.provider("figma")
    assert p is not None and p.label == "Figma"


def test_the_token_goes_in_figmas_own_header():
    auth = C.vendor_auth("figma", {"token": "figd_abc"})
    assert auth.base_url == "https://api.figma.com"
    assert auth.headers == {"X-Figma-Token": "figd_abc"}
    assert auth.params == {}


def test_a_missing_token_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("figma", {})
    assert "token" in str(e.value)


def test_the_form_says_where_the_token_lives_and_which_scopes():
    p = C.provider("figma")
    assert [f.name for f in p.fields] == ["token"]
    assert "Security" in p.where and "Personal access tokens" in p.where
    for scope in F.SCOPES:
        assert scope in p.where, scope


def test_the_probe_asks_who_the_token_belongs_to():
    p = C.provider("figma")
    assert (p.probe_path, p.probe_method) == ("/v1/me", "GET")
    assert C.account_label("figma", {"id": "1", "handle": "me",
                                     "email": "me@x.com"}) == "me@x.com"
    assert C.account_label("figma", {"handle": "me"}) == "me"


# --- links ----------------------------------------------------------------

@pytest.mark.parametrize("given, key, node", [
    (LINK, KEY, "12:345"),
    ("figma.com/design/%s/My-Site" % KEY, KEY, ""),
    ("https://www.figma.com/file/%s/Old?node-id=1%%3A2" % KEY, KEY, "1:2"),
    ("https://www.figma.com/proto/%s/Flow?node-id=3-4" % KEY, KEY, "3:4"),
    ("https://www.figma.com/board/%s/Jam" % KEY, KEY, ""),
    ("https://www.figma.com/design/%s/branch/BrAnCh12345678/x" % KEY,
     "BrAnCh12345678", ""),
    ("https://www.figma.com/design/%s/x/branch/BrAnCh12345678/x" % KEY,
     "BrAnCh12345678", ""),
    (KEY, KEY, ""),
])
def test_a_file_and_its_frame_come_out_of_the_link(given, key, node):
    assert F.from_link(given) == (key, node)


@pytest.mark.parametrize("given", [
    "", "my landing page", "https://evil.example.com/design/%s/x" % KEY,
    "https://www.figma.com/community/plugin/123"])
def test_anything_else_is_not_a_figma_file(given):
    assert F.from_link(given)[0] == ""


def test_frames_are_read_from_ids_links_and_lists():
    assert F.node_ids("12-345, 1:2 " + LINK) == ["12:345", "1:2"]
    assert F.node_ids(["I5:6;7:8", "bad", "9-9"]) == ["I5:6;7:8", "9:9"]


async def test_the_link_is_enough_to_read_a_frame():
    args, problem = await F.prepare("get_frame", {"file": LINK})
    assert problem is None
    assert args["file_key"] == KEY and args["ids"] == "12:345"


async def test_frames_named_separately_win_over_the_links_frame():
    args, _ = await F.prepare("get_frame_image",
                              {"file": LINK, "frames": "1-2,3:4"})
    assert args["ids"] == "1:2,3:4"


async def test_a_frame_is_needed_to_read_one():
    _, problem = await F.prepare("get_frame",
                                 {"file": "figma.com/design/%s/x" % KEY})
    assert problem and "Copy link to selection" in problem


async def test_something_that_is_not_a_link_says_how_to_get_one():
    _, problem = await F.prepare("get_file", {"file": "my homepage design"})
    assert problem and "Copy link" in problem


async def test_whoami_needs_no_link():
    args, problem = await F.prepare("whoami", {})
    assert problem is None and args == {}


# --- the outline ----------------------------------------------------------

def test_one_line_per_layer_with_what_a_build_needs():
    text = F.outline(HERO)
    lines = text.splitlines()
    assert lines[0] == ('FRAME "Hero" 1440x800 column gap 24 pad 64 120 64 '
                        '120 justify center fill #0F1729 radius 12 shadow '
                        '[1:2]')
    assert lines[1] == ('  TEXT "Headline" 600x144 text "Build faster with '
                        'IO" font Inter 64/72 700 align center color #FFFFFF '
                        '[1:3]')
    assert lines[2].startswith('  INSTANCE "Button/Primary" 160x48 fill '
                               '#7D8CFF 50% border 1 #000000')


def test_a_hidden_layer_is_left_out():
    assert "Hidden" not in F.outline(HERO)


def test_a_big_frame_is_cut_and_says_how_to_ask_for_less():
    big = {"id": "0:1", "type": "FRAME", "name": "Page", "children": [
        {"id": "9:%d" % i, "type": "TEXT", "name": "t%d" % i,
         "characters": "x" * 150} for i in range(400)]}
    text = F.outline(big, budget=3_000)
    assert len(text) < 3_400
    assert "more layers were left out" in text and "by its id" in text


def test_a_file_outline_is_its_pages_and_their_frames():
    payload = {"name": "Site", "lastModified": "2026-11-20T10:00:00Z",
               "editorType": "figma", "document": {"children": [
                   {"id": "0:1", "name": "Home", "children": [
                       HERO, {"id": "2:1", "type": "FRAME", "name": "Gone",
                              "visible": False}]}]}}
    out = F.file_outline(payload)
    assert out["name"] == "Site" and out["pages"][0]["name"] == "Home"
    assert out["pages"][0]["frames"] == [
        {"id": "1:2", "name": "Hero", "type": "FRAME", "size": "1440x800"}]


def test_a_frame_the_file_does_not_have_is_said_to_be_missing():
    out = F.nodes_outline({"name": "Site", "nodes": {
        "1:2": {"document": HERO}, "9:9": None}})
    assert out["frames"][0]["outline"].startswith('FRAME "Hero"')
    assert out["frames"][1] == {"id": "9:9", "missing": True}


def test_pictures_say_which_frames_could_not_be_drawn():
    out = F.images({"err": None, "images": {"1:2": "https://x/a.png",
                                            "3:4": None}})
    assert out["images"] == {"1:2": "https://x/a.png"}
    assert out["could_not_draw"] == ["3:4"] and "30 days" in out["note"]


def test_comments_are_flattened_to_who_said_what_where():
    rows = F.comments({"comments": [{
        "id": "c1", "message": "Make this bigger", "created_at": "t",
        "resolved_at": None, "parent_id": "", "user": {"handle": "ana"},
        "client_meta": {"node_id": "1:2"}}]})
    assert rows == [{"id": "c1", "message": "Make this bigger", "by": "ana",
                     "at": "t", "resolved": False, "reply_to": None,
                     "on_frame": "1:2"}]


def test_a_comment_needs_words_and_a_reply_names_its_thread():
    with pytest.raises(ValueError):
        F.comment_body({"message": "  "})
    assert F.comment_body({"message": "Done", "reply_to": "c1"}) == {
        "message": "Done", "comment_id": "c1"}


# --- the tools -------------------------------------------------------------

READS = {"whoami", "get_file", "get_file_info", "get_frame",
         "get_frame_image", "list_comments"}
WRITES = {"add_comment"}


def test_six_reads_one_write_and_nothing_that_edits_the_design():
    tools = {t.name: t for t in mytools.PROVIDER_TOOLS["figma"]}
    assert set(tools) == READS | WRITES
    assert {n for n, t in tools.items() if mytools._writes(t)} == WRITES


@pytest.mark.parametrize("name", sorted(READS))
def test_a_read_only_agent_may_run_the_reads(name):
    assert not agent_tools.is_write_tool("my-figma_" + name)


def test_a_read_only_agent_may_not_comment():
    assert agent_tools.is_write_tool("my-figma_add_comment")


@pytest.mark.parametrize("name", ["get_file", "get_frame", "get_frame_image"])
def test_the_rationed_calls_say_so(name):
    assert "limit" in _tool(name).summary.lower()


def test_the_file_outline_asks_for_pages_and_frames_only():
    assert mytools._query_for(_tool("get_file"), {})["depth"] == 2


def test_a_picture_is_a_png():
    q = mytools._query_for(_tool("get_frame_image"), {"ids": "1:2"})
    assert q["ids"] == "1:2" and q["format"] == "png"


# --- a rationed vendor says why, and when --------------------------------

def test_a_429_says_when_to_try_again():
    said = mytools._refusal(_R(429, {}, {"Retry-After": "600"}), "Figma",
                            {"token": "figd_x"}, "figma", "get_file")
    assert "10 minutes" in said and "Figma" in said


def test_figmas_monthly_cap_on_a_view_seat_is_explained():
    said = mytools._refusal(_R(429, {}, {"Retry-After": "345600",
                                         "X-Figma-Rate-Limit-Type": "low",
                                         "X-Figma-Plan-Tier": "pro"}),
                            "Figma", {"token": "figd_x"}, "figma", "get_frame")
    assert "4 days" in said
    assert "View" in said and "Full or Dev seat" in said


def test_figmas_starter_plan_cap_is_explained():
    said = mytools._refusal(_R(429, {}, {"X-Figma-Plan-Tier": "starter",
                                         "X-Figma-Rate-Limit-Type": "high"}),
                            "Figma", {"token": "figd_x"}, "figma", "get_frame")
    assert "Starter" in said


def test_any_vendors_429_says_it_is_limiting_not_broken():
    said = mytools._refusal(_R(429, {"message": "Too many"}), "Todoist",
                            {"token": "t"}, "todoist", "list_tasks")
    assert "limiting" in said and "Reconnect" not in said


# --- the rest of the wiring ----------------------------------------------

def test_mytools_runs_the_prepare_step_for_figma():
    assert mytools.PREPARE.get("figma") is not None


def test_the_panel_offers_figma_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'figma'" in l]
    assert line and "real: true" in line[0] and "token: true" in line[0]


def test_mcp_proxy_can_reach_the_figma_tools():
    src = open(TENANTS, encoding="utf-8").read()
    assert 'server_id="my-figma"' in src
    assert 'MCP_MYTOOLS_URL + "/figma"' in src


def test_the_triage_agent_knows_what_figma_is_for():
    app = app_triage.APPS.get("figma")
    assert app is not None and app.label == "Figma"
    assert "design" in app.note.lower()
    assert set(app.tools) <= {t.name for t in mytools.PROVIDER_TOOLS["figma"]}
    assert "edit the design" in app.cannot.lower()


def test_the_router_can_pick_it_because_the_note_says_its_name():
    note = " ".join(str(agent_jev.TOOL_NOTES.get("server:mcp-proxy", "")).split())
    assert "figma" in note.lower()


def test_the_making_clause_names_a_comment():
    making = " ".join(str(agent_jev.MAKES_CLAUSE).split()).lower()
    assert "comment" in making


def test_the_assistant_counts_it_among_the_apps_you_can_connect():
    assert "figma" in acc.ALL_PROVIDER_IDS
    assert acc.connect_hint("figma")["label"] == "Figma"
