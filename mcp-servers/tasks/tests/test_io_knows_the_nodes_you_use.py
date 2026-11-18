# -*- coding: utf-8 -*-
"""IO can build the nodes people actually use, not just two of them.

Measured on the real instance 2026-11-18, across 33 workflows and 27
distinct node types:

    httpRequest  51 uses   typeVersions 4, 4.2, 4.4
    code         25        2
    set          13        2, 3.4
    webhook      12        2, 2.1
    if            7        2, 2.3
    googleSheets  6        4.5, 4.7
    scheduleTrigger 4      1.1, 1.2

IO knew exactly two of those: manualTrigger and set. Asked for anything
real, a workflow that calls an API on a schedule, it had no shape to
build from and would invent one.

Every shape here was READ OUT OF HIS OWN WORKFLOWS rather than copied
from a changelog. A changelog says what the newest n8n supports; it does
not say what this instance writes, and a typeVersion an instance does
not know renders as a broken node in the editor.
"""
import n8n_nodes


# What the survey found in use, with the newest typeVersion each.
MEASURED = {
    "httpRequest": 4.4,
    "code": 2,
    "set": 3.4,
    "webhook": 2.1,
    "scheduleTrigger": 1.2,
    "if": 2.3,
    "respondToWebhook": 1.5,
    "merge": 3.2,
    "switch": 3.4,
}


def test_the_nodes_people_actually_use_are_all_known():
    missing = sorted(set(MEASURED) - set(n8n_nodes.NODES))
    assert missing == [], (
        "IO cannot build these, and they are in real use: %s" % missing)


def test_every_shape_carries_the_version_that_was_measured():
    """Not the newest n8n has ever shipped: the newest THIS instance
    writes. A node tagged with a typeVersion the instance does not know
    loads broken in the editor, which is worse than an older shape that
    works."""
    for name, want in MEASURED.items():
        got = n8n_nodes.NODES[name].type_version
        assert got == want, (
            "%s: catalogue says typeVersion %s, the instance writes %s"
            % (name, got, want))


def test_every_shape_is_complete_enough_to_build_with():
    for name, node in n8n_nodes.NODES.items():
        assert node.type.startswith("n8n-nodes-base."), name
        assert isinstance(node.parameters, dict), name
        assert node.summary.strip(), name


def test_a_trigger_is_marked_as_one():
    """A workflow with no trigger cannot be switched on, and n8n answers
    400 rather than explaining why. Knowing which nodes are triggers is
    what lets the refusal say so before the request is sent."""
    assert n8n_nodes.NODES["scheduleTrigger"].is_trigger is True
    assert n8n_nodes.NODES["webhook"].is_trigger is True
    assert n8n_nodes.NODES["httpRequest"].is_trigger is False
    assert n8n_nodes.NODES["set"].is_trigger is False


def test_the_manual_trigger_is_known_but_marked_as_not_enough():
    """Measured live: a workflow whose only trigger is a manual trigger
    is refused activation by n8n with "no trigger node". The catalogue
    has to carry that, or IO will build one and then be unable to switch
    it on."""
    man = n8n_nodes.NODES["manualTrigger"]
    assert man.is_trigger is True
    assert man.activates is False
    assert n8n_nodes.NODES["scheduleTrigger"].activates is True


def test_a_node_can_be_rendered_ready_to_send():
    node = n8n_nodes.build("set", "Set message", [220, 0])
    assert node["type"] == "n8n-nodes-base.set"
    assert node["typeVersion"] == 3.4
    assert node["name"] == "Set message"
    assert node["position"] == [220, 0]
    assert isinstance(node["parameters"], dict)
    assert node["id"]


def test_building_twice_does_not_share_one_parameters_dict():
    """A shared dict would mean editing one node's parameters silently
    edited the catalogue, and every node built after it."""
    a = n8n_nodes.build("set", "A", [0, 0])
    b = n8n_nodes.build("set", "B", [0, 0])
    a["parameters"]["mode"] = "changed"
    assert "mode" not in b["parameters"] or b["parameters"]["mode"] != "changed"
    assert a["id"] != b["id"]


def test_an_unknown_node_is_refused_by_name():
    try:
        n8n_nodes.build("slackulator", "X", [0, 0])
    except ValueError as e:
        assert "slackulator" in str(e)
    else:
        raise AssertionError("an unknown node should not build")


def test_the_catalogue_can_be_described_for_a_model():
    text = n8n_nodes.describe()
    assert "httpRequest" in text
    assert "scheduleTrigger" in text
    # The shapes are the point: a list of names tells a model nothing it
    # could build from.
    assert "typeVersion" in text
