"""The #channels and #graph panels, Discord and Slack: pure builders.

Every other web feature the bots expose is a dedicated channel with a pinned
panel, so these two follow the same shape. What matters and is pinned here:
the custom_ids and action_ids the routing keys on, the link buttons pointing
at the real pages, and the Slack modal round-trip for the topic.
"""
from handlers import channels_panel as chan
from handlers import graph_panel as gp
from handlers import slack_channels_panel as schan
from handlers import slack_graph_panel as sgp

BASE = "https://ai-ui.coolestdomain.win"


# ---------------------------------------------------------------- Discord

def _buttons(payload):
    return payload["components"][0]["components"]


def test_channels_panel_has_a_status_button_and_a_link_to_the_page():
    p = chan.build_panel_payload(BASE + "/")
    by_label = {b["label"]: b for b in _buttons(p)}
    assert by_label["My channels"]["custom_id"] == chan.MY
    link = by_label["Link a channel"]
    assert link["style"] == 5 and link["url"] == f"{BASE}/channel"
    assert "custom_id" not in link, "a link button carries a url, not a custom_id"


def test_channels_predicates():
    assert chan.is_chan(chan.MY) and chan.is_my(chan.MY)
    assert not chan.is_chan("cron:list")
    assert not chan.is_chan("chan_my"), "Slack ids must not be mistaken for Discord ones"


def test_graph_panel_has_summary_ask_and_a_link_to_the_page():
    p = gp.build_panel_payload(BASE)
    by_label = {b["label"]: b for b in _buttons(p)}
    assert by_label["My graph"]["custom_id"] == gp.MY
    assert by_label["Ask the graph"]["custom_id"] == gp.ASK
    link = by_label["Open the graph"]
    assert link["style"] == 5 and link["url"] == f"{BASE}/tasks/graph"


def test_graph_predicates_tell_the_three_apart():
    assert gp.is_graph(gp.MY) and gp.is_my(gp.MY) and not gp.is_ask(gp.MY)
    assert gp.is_graph(gp.ASK) and gp.is_ask(gp.ASK)
    assert gp.is_graph(gp.ASK_MODAL) and gp.is_ask_modal(gp.ASK_MODAL)
    assert not gp.is_graph("graphite:x")


def test_graph_ask_modal_is_one_required_short_input():
    m = gp.build_ask_modal()
    assert m["custom_id"] == gp.ASK_MODAL
    inputs = [c for row in m["components"] for c in row["components"]]
    assert len(inputs) == 1
    (inp,) = inputs
    assert inp["type"] == 4 and inp["custom_id"] == gp.TOPIC_INPUT
    assert inp["style"] == 1 and inp["required"] is True
    assert inp["max_length"] == 200


def test_discord_panels_use_no_emoji():
    for text in (chan.build_panel_payload(BASE)["content"], gp.build_panel_payload(BASE)["content"]):
        assert all(ord(ch) < 0x2600 or ch in "•—" for ch in text), text


# ------------------------------------------------------------------ Slack

def _actions(blocks):
    return next(b for b in blocks if b["type"] == "actions")["elements"]


def test_slack_channels_blocks():
    blocks = schan.build_channels_blocks(BASE)
    assert blocks[0]["type"] == "header" and blocks[0]["text"]["text"] == "Channels"
    by_id = {e["action_id"]: e for e in _actions(blocks)}
    assert by_id[schan.MY_ACTION_ID]["style"] == "primary"
    assert by_id[schan.LINK_ACTION_ID]["url"] == f"{BASE}/channel"


def test_slack_graph_blocks():
    blocks = sgp.build_graph_blocks(BASE)
    by_id = {e["action_id"]: e for e in _actions(blocks)}
    assert set(by_id) == {sgp.MY_ACTION_ID, sgp.ASK_ACTION_ID, sgp.OPEN_ACTION_ID}
    assert by_id[sgp.OPEN_ACTION_ID]["url"] == f"{BASE}/tasks/graph"


def test_slack_graph_modal_round_trips_the_topic_and_origin():
    view = sgp.build_ask_modal("C123")
    assert view["type"] == "modal" and view["callback_id"] == sgp.ASK_MODAL_ID
    assert view["private_metadata"] == "C123"
    assert len(view["title"]["text"]) <= 24
    (block,) = view["blocks"]
    assert block["block_id"] == sgp.TOPIC_BLOCK_ID
    assert block["element"]["action_id"] == sgp.TOPIC_INPUT_ID
    submitted = {"state": {"values": {sgp.TOPIC_BLOCK_ID: {sgp.TOPIC_INPUT_ID: {"value": "  portfolio "}}}}}
    assert sgp.topic_from_view(submitted) == "portfolio"
    assert sgp.topic_from_view({}) == ""


def test_slack_and_discord_ids_do_not_collide():
    discord_ids = {chan.MY, gp.MY, gp.ASK, gp.ASK_MODAL}
    slack_ids = {schan.MY_ACTION_ID, schan.LINK_ACTION_ID, sgp.MY_ACTION_ID,
                 sgp.ASK_ACTION_ID, sgp.OPEN_ACTION_ID, sgp.ASK_MODAL_ID}
    assert not (discord_ids & slack_ids)
