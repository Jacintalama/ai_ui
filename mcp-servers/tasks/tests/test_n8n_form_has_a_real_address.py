# -*- coding: utf-8 -*-
"""A form the platform built must say its real address, or say it has none.

WHAT HAPPENED, read off the live chat record on 2026-11-19 (the chat "n8n
Workflow Test" of 2026-11-18, workflow HRZmilFlvXXehRXa):

Ralph asked "give me the url of the form". The assistant answered

    https://n8n.srv1041674.hstgr.io/form/HRZmilFlvXXehRXa

and that address is wrong twice over. The host is `.cloud`, not `.io`:
nothing in this repo has ever said `.io`, so the domain was invented. And
the path is the WORKFLOW id, while an n8n form is served at the trigger
node's `path` or its `webhookId`, never the workflow id.

Then it got worse in the way that costs an afternoon. The browser said
DNS_PROBE_FINISHED_NXDOMAIN, which is exactly what a made-up hostname
produces, and the assistant diagnosed the person's machine: flush DNS,
disable the VPN, try another browser, check the router. Twice. It never
re-read its own answer.

The workflow itself was built correctly, which is the part worth keeping in
view. Read back today it really is Form Trigger -> Set message -> Save to
Data Table, exactly as claimed. The tools did their job. The one fact with
no tool behind it is the one that was invented.

SO THE FIX IS NOT AN INSTRUCTION. The address is knowable from the
connection the call already used, and when it is not knowable the honest
answer is that the form has no address yet. That node carries no `path` and
no `webhookId`, because n8n assigns one in the editor and not over the API,
so this particular form was never reachable at any URL.
"""
import mytools


def _wf(nodes):
    return {"id": "W1", "name": "x", "nodes": nodes}


def _form(name="Form Trigger", params=None, webhook=None):
    node = {"name": name, "type": "n8n-nodes-base.formTrigger",
            "parameters": params or {}}
    if webhook:
        node["webhookId"] = webhook
    return node


BASE = "https://n8n.srv1041674.hstgr.cloud"


def test_the_url_is_built_from_the_connection_not_from_memory():
    forms = mytools._n8n_forms(_wf([_form(params={"path": "intake"})]), BASE)
    assert forms == [{"node": "Form Trigger",
                      "url": BASE + "/form/intake"}], forms


def test_a_trailing_slash_on_the_host_does_not_double_up():
    forms = mytools._n8n_forms(_wf([_form(params={"path": "intake"})]),
                               BASE + "/")
    assert forms[0]["url"] == BASE + "/form/intake"


def test_the_webhook_id_is_used_when_there_is_no_path():
    forms = mytools._n8n_forms(_wf([_form(webhook="abc-123")]), BASE)
    assert forms[0]["url"] == BASE + "/form/abc-123"


def test_a_form_with_no_path_and_no_webhook_id_says_it_has_no_address():
    """The real case. Inventing one here is what cost an afternoon."""
    forms = mytools._n8n_forms(_wf([_form()]), BASE)
    assert forms[0]["url"] is None
    assert "no address" in forms[0]["why"]
    assert "n8n" in forms[0]["why"]


def test_the_workflow_id_is_never_used_as_the_path():
    """What the model reached for, and it is not how n8n serves a form."""
    item = _wf([_form()])
    forms = mytools._n8n_forms(item, BASE)
    assert all(item["id"] not in str(f.get("url") or "") for f in forms)


def test_a_workflow_with_no_form_gets_nothing():
    assert mytools._n8n_forms(
        _wf([{"name": "Set", "type": "n8n-nodes-base.set",
              "parameters": {}}]), BASE) == []


def test_every_form_in_the_workflow_is_listed():
    forms = mytools._n8n_forms(
        _wf([_form("A", {"path": "one"}), _form("B", {"path": "two"})]), BASE)
    assert [f["node"] for f in forms] == ["A", "B"]


def test_no_host_is_hardcoded_in_the_helper_code():
    """One instance's host in the code would be the same bug, shipped.

    The docstring is excluded deliberately: it quotes the invented address
    so the next reader knows what this guards against, and a test that
    forbade the explanation would push the explanation out of the file.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(mytools._n8n_forms).lstrip())
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.unparse(fn)
    for bad in ("hstgr", "http://", "https://"):
        assert bad not in code, "a host is baked into _n8n_forms: %r" % bad
