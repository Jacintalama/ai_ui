# Needed, then pick one: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under a recommendation, the app the person named reads as needed, and n8n, Zapier and Automations read as one pick.

**Architecture:** `app_triage.plan` marks a choice (`p["choice"]`) and adds Automations to it; `with_buttons` lays out a needed line per app and one pick-one line with its own row of buttons; `brief` tells the model the same; the build-a-workflow skill lets them choose before its n8n steps.

**Tech Stack:** Python 3.12, pytest (`asyncio_mode = auto`), all in `mcp-servers/tasks/`.

**Spec:** `docs/superpowers/specs/2026-11-24-needed-and-pick-one-design.md`

## Global Constraints

- Exact copy: `You need {label}, because you asked for it.` and `To do it automatically, pick one: {a}, {b} or {c}.`
- With no choice in the plan, `with_buttons` and `brief` output is byte for byte what it is on `main` today.
- A connected n8n or Zapier settles the choice: no pick-one line, no Automations added.
- A timer job (tool `schedules`) is unchanged.
- No page-script change. Run tests with `.venv/Scripts/python.exe -m pytest` from `mcp-servers/tasks/`.

## Review Focus

1. The answer already wrote a member's Connect link: that button must not appear twice.
2. Zapier (not n8n) connected: the choice is settled the same way.
3. Two named apps (Airtable and Gmail): two needed lines, each with its own button.
4. Publish picked beside the choice: its button must not land in the pick-one row.
5. Automations picked by Jev AND added by the choice: it appears once.

---

### Task 1: The plan marks the choice

**Files:**
- Modify: `mcp-servers/tasks/app_triage.py` (`plan`, about lines 487-565)
- Test: `mcp-servers/tasks/tests/test_triage_needed_and_pick_one.py` (create)

**Interfaces:**
- Produces: `p["choice"]: list[str]`, ids in order: the unconnected automation-group members as `plan` already orders them, then `"automations"`; `[]` when there is no choice. Each `p["apps"]` entry gains `"named": bool` (`_named(app, text)`). When there is a choice, `p["platform"]` holds exactly one `automations` entry.

- [ ] **Step 1: Write the failing tests**

```python
import app_triage
MSG = "I want people to fill the form from my website to be saved into Airtable automatically"

def _p(picks=(("airtable", .97), ("n8n", .95)), connected=(), tools=(), text=MSG):
    return app_triage.plan(list(picks), set(connected), list(tools), text=text)

def test_automations_joins_the_choice_even_if_jev_did_not_pick_it():
    p = _p()
    assert p["choice"] == ["n8n", "zapier", "automations"]
    assert [x["id"] for x in p["platform"]].count("automations") == 1

def test_automations_picked_by_jev_is_not_added_twice():
    p = _p(picks=(("airtable", .97), ("n8n", .95), ("automations", .8)))
    assert [x["id"] for x in p["platform"]].count("automations") == 1

def test_a_connected_n8n_or_zapier_settles_it():
    for have in ({"n8n"}, {"zapier"}):
        p = _p(connected=have)
        assert p["choice"] == []
        assert "automations" not in [x["id"] for x in p["platform"]]

def test_a_timer_job_has_no_choice():
    assert _p(tools=["schedules"], text="every 8am save my email to Airtable")["choice"] == []

def test_the_named_app_is_marked_named():
    assert {a["id"]: a["named"] for a in _p()["apps"]}["airtable"] is True
```

- [ ] **Step 2: Run, expect FAIL** (`KeyError: 'choice'`)

Run: `.venv/Scripts/python.exe -m pytest tests/test_triage_needed_and_pick_one.py -q`

- [ ] **Step 3: Implement in `plan()`**

After `chosen` is final: choice = members of `AUTOMATION_GROUP` in `chosen`, only if none of the group is in `have`; if non-empty, append `"automations"` and, when `automations` is not already in `platform`, append the same dict `plan` builds for it today (`acting` computed the same way). Add `"named"` to each app dict. Put `"choice"` in `out`.

- [ ] **Step 4: Run, expect PASS**, then the whole triage set: `.venv/Scripts/python.exe -m pytest tests/test_triage_*.py tests/test_it_recommends_what_you_already_have.py -q`. Expected: all pass.

- [ ] **Step 5: Commit** `git commit -m "The plan marks a choice of n8n, Zapier or Automations"`

### Task 2: The buttons say needed, then pick one

**Files:**
- Modify: `mcp-servers/tasks/app_triage.py` (`with_buttons`, about lines 743-850)
- Test: `mcp-servers/tasks/tests/test_triage_needed_and_pick_one.py`

**Interfaces:**
- Consumes: `p["choice"]`, `a["named"]` from Task 1.

- [ ] **Step 1: Capture today's output for the no-choice test.** On `main`, before any change to `with_buttons`, print `app_triage.with_buttons("Here is how.", app_triage.plan([("airtable", .97)], set(), []))` and paste it as the literal `BEFORE`.

- [ ] **Step 2: Write the failing tests**

```python
def _out(answer="Here is how.", **kw):
    return app_triage.with_buttons(answer, _p(**kw))

def _line(out, text):
    return next(l for l in out.splitlines() if text in l)

def test_the_named_app_reads_as_needed_with_its_own_button():
    out = _out()
    assert "#aiui-connect:airtable" in _line(out, "You need Airtable, because you asked for it.")
    assert "#aiui-connect:airtable" not in out.rstrip().splitlines()[-1]

def test_the_three_are_one_pick_with_their_own_row():
    lines = _out().rstrip().splitlines()
    assert lines[-2] == "To do it automatically, pick one: n8n, Zapier or Automations."
    assert all(h in lines[-1] for h in ("#aiui-connect:n8n", "#aiui-connect:zapier", "#aiui-open:ai-agents"))

def test_a_choice_has_no_recommended_zapier_and_no_webhook():
    out = _out()
    assert "Recommended: Zapier" not in out and "webhook" not in out.lower()

def test_an_app_not_named_keeps_the_recommended_line():
    out = _out(text="save every form entry from my site automatically")
    assert "#aiui-connect:airtable" in _line(out, "Recommended: Airtable")

def test_two_named_apps_are_two_needed_lines():
    out = _out(picks=(("airtable", .97), ("gmail", .96), ("n8n", .95)),
               text="save my Gmail attachments into Airtable automatically")
    assert "#aiui-connect:gmail" in _line(out, "You need Gmail")
    assert "#aiui-connect:airtable" in _line(out, "You need Airtable")

def test_a_button_the_answer_already_wrote_is_not_repeated():
    out = _out(answer="Connect it: [Connect n8n](#aiui-connect:n8n)")
    assert out.count("#aiui-connect:n8n") == 1

def test_publish_beside_the_choice_is_not_in_the_pick_row():
    out = _out(picks=(("airtable", .97), ("n8n", .95), ("publish", .8)))
    assert "#aiui-open:app-builder" not in out.rstrip().splitlines()[-1]

def test_without_a_choice_the_output_is_unchanged():
    assert app_triage.with_buttons("Here is how.", app_triage.plan([("airtable", .97)], set(), [])) == BEFORE
```

Check the Gmail one first: if `APPS["gmail"].label` is not `Gmail`, use its label in the assertion.

- [ ] **Step 3: Run, expect FAIL** on the first six.

- [ ] **Step 4: Implement.** When `p.get("choice")`: for apps in the choice, skip today's "Recommended" line and its button (the limit line for an app the answer named stays); for `automations` in the choice, skip its how-line and its button. For each unconnected app outside the group: `You need {label}, because you asked for it.` if `named`, else today's `Recommended: ...` line, with its button at the end of that same line, and if `named` and `cannot` then today's `{label} cannot yet {cannot}.` on the next line. Layout: `lines`, then the needed lines, then any other buttons on their own row, then the pick line, then the choice buttons (skipping any whose href the answer already holds) on the last row. Labels in the pick line come from `APPS[id].label` / `PLATFORM["automations"].label`, joined `a, b or c`. With no choice, take the existing code path untouched.

- [ ] **Step 5: Run, expect PASS**, then the triage set as in Task 1. Expected: all pass (`test_ios_own_automations_sit_beside_n8n_and_zapier` still holds: the last row has all three).

- [ ] **Step 6: Commit** `git commit -m "Needed apps on their own line, the pick-one row under them"`

### Task 3: The brief and the skill offer the choice

**Files:**
- Modify: `mcp-servers/tasks/app_triage.py` (`brief`, about lines 631-708)
- Modify: `mcp-servers/tasks/agent_skills/build-a-workflow/SKILL.md`
- Test: `mcp-servers/tasks/tests/test_triage_needed_and_pick_one.py`, `mcp-servers/tasks/tests/test_build_a_workflow_skill.py`

- [ ] **Step 1: Write the failing tests**

```python
import agent_skills

def _with_skill():
    pool = agent_skills.load_all(refresh=True)
    return app_triage.plan([("airtable", .97), ("n8n", .95)], set(), [], text=MSG,
                           skills=[("build-a-workflow", .95)], pool=pool)

def test_the_brief_offers_the_choice_before_the_skill():
    b = app_triage.brief(_with_skill())
    assert "Needed for this: Airtable." in b
    assert "choice of three" in b and "Do not pick one for them" in b
    assert b.index("choice of three") < b.index("Follow the ready-made skill")
    assert "webhook" not in b.split("Follow the ready-made skill")[0].lower()

def test_the_brief_without_a_choice_says_nothing_of_one():
    assert "choice of three" not in app_triage.brief(app_triage.plan([("airtable", .97)], set(), []))
```

In `test_build_a_workflow_skill.py`:

```python
def test_it_lets_them_choose_before_the_n8n_steps():
    body = _skill()["body"]
    assert "let them choose first" in body
    assert body.index("let them choose first") < body.index("## Steps")
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement.** In `brief`, when `p.get("choice")`: leave `automations` out of the platform "advise" list, and before the skill block add (needed sentence only when there are apps outside the group):
  `Needed for this: {labels joined with and}. To do it automatically there is a choice of three, and the person picks: {n8n}, {Zapier}, or Automations (the platform's own: it runs one of their agents when something arrives at a web address or by email). Give the case for each in a sentence and let them choose. Do not pick one for them, and do not say it cannot be done because one of them is not connected.`
  In SKILL.md, at the end of the "First, look at n8n" paragraph add: `If you were told they have a choice between n8n and other ways, such as Zapier or Automations, let them choose first, and follow these steps once they choose n8n.`

- [ ] **Step 4: Run, expect PASS**: both test files, then the triage set and `tests/test_build_a_workflow_skill.py`. Expected: all pass, and `len(body) <= MAX_SKILL_CHARS`.

- [ ] **Step 5: Commit** `git commit -m "The brief and build-a-workflow let the person pick"`

### Task 4: Ship and check live

- [ ] Full unit suite: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_agent_chat_endpoint.py`. Expected: only `ERROR at setup` DB-tier errors, no new failure.
- [ ] Push a branch, open a PR, wait for CI: unit and browser green; database tier no worse than its baseline (15 failed).
- [ ] Merge; wait for `deploy.yml`; `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz` and `.deploy-state` sha = merge commit.
- [ ] Live: the `MSG` above in a fresh chat (minted token, `scratchpad/live/chat.py`). Expected: the needed line with Connect Airtable, the pick-one line, the three buttons on the row under it, no "Recommended: Zapier", the answer giving a case for each. Then delete the test chat, any memory it made, and the token.
