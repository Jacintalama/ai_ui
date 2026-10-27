"""The agent's face: the office robot as a picture, the same one the floor
draws, so the chat and the office agree about who is who."""
import base64
import xml.etree.ElementTree as ET

import agent_avatar as av


def _js_hue(name):
    # agent.js nameHue, written out again here rather than imported, so a
    # drift in either copy fails this test.
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) % 360
    return h


def test_the_hue_is_the_floors_hue():
    for name in ("Ada", "Mia", "Iris", "Research Assistant", ""):
        assert av.hue_of(name) == _js_hue(name)
    assert av.hue_of("Ada") != av.hue_of("Mia")


def test_the_same_name_always_gives_the_same_picture():
    assert av.svg("agent-a", "Ada") == av.svg("agent-a", "Ada")
    assert av.svg("agent-a", "Ada") != av.svg("agent-m", "Mia")


def test_the_picture_is_well_formed_svg_in_the_agents_colour():
    root = ET.fromstring(av.svg("agent-ada-1", "Ada", size=28))
    assert root.tag.endswith("svg")
    assert root.get("width") == "28" and root.get("height") == "28"
    assert root.get("viewBox") == "22 0 96 96"
    assert f"hsl({av.hue_of('Ada')}, 70%, 66%)" in ET.tostring(root, encoding="unicode")
    # No size asked: fills its frame, which is what a profile picture wants.
    assert ET.fromstring(av.svg("agent-ada-1", "Ada")).get("width") is None


def test_an_odd_id_or_name_cannot_break_the_markup():
    text = av.svg('agent-"x"<y>', 'Ada "the" <Great> & co', size=28)
    root = ET.fromstring(text)
    assert root.get("aria-label") == 'Ada "the" <Great> & co'


def test_the_data_uri_is_the_svg_base64():
    uri = av.data_uri("agent-a", "Ada")
    assert uri.startswith("data:image/svg+xml;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]).decode("utf-8") == av.svg("agent-a", "Ada")


def test_a_reply_opens_with_the_small_robot_and_the_name():
    line = av.reply_face("agent-a", "Ada")
    assert line.startswith("![Ada](data:image/svg+xml;base64,")
    assert line.endswith(") **Ada**")
    assert 'width="28"' in base64.b64decode(line.split("(", 1)[1].split(")", 1)[0].split(",", 1)[1]).decode()
    # Square brackets in a name would end the alt text early.
    assert av.reply_face("agent-x", "A[d]a").startswith("![Ada](")
