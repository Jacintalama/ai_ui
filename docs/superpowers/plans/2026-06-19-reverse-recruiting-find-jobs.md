# Reverse Recruiting ("Find Jobs") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Find Jobs" button to the `#recruiting` panel (Discord + Slack) that runs *reverse recruiting* — find companies hiring for a job-seeker's target role and email a tailored application to each on their behalf, with review-before-send on both platforms.

**Architecture:** Reuse the existing `task_id`-keyed find → review → edit → send → n8n → Google-Sheet outreach pipeline by adding a `direction` flag to the backend; the `Candidate` model and all selection/edit/send logic are reused unchanged. New work is narrow: a reverse prompt branch, a new entry button/modal/router method per platform, making the shared re-render handlers **platform- and direction-aware**, and a brand-new **Slack Block Kit review layer** (Slack has none today and currently auto-sends).

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy (tasks service, Python, async); httpx; anthropic SDK; Discord interactions (components + modals) and Slack Block Kit; pytest (run via the webhook-handler venv); n8n (live Hostinger instance).

**Spec:** `docs/superpowers/specs/2026-06-19-reverse-recruiting-find-jobs-design.md`

**Branch:** `feat/reverse-recruiting`

---

## File Structure

**Backend — `mcp-servers/tasks/`**
- Modify `outreach.py` — `direction` kwarg + reverse branch in `build_outreach_prompt`; direction-aware `format_outreach_summary`; `reply_to` in `post_outreach_to_n8n`.
- Modify `routes_outreach.py` — `OutreachRequest.direction`; `OutreachStatusResponse.direction/role/location` (populated by status, `/candidates`, **PATCH `/candidates/{cid}`**, `/send`); thread `direction`+`location` through `start_outreach` → `_run_outreach` → `_process_outreach_find`/`_process_outreach_result`; persist them in `result`; direction-aware not-found + 0-selected text; pass `reply_to` on send.
- Modify `tests/test_outreach_logic.py`, `tests/test_outreach_n8n.py`, `tests/test_routes_outreach.py` — pure tests only (no DB).

**Webhook handler — `webhook-handler/handlers/`**
- **Create** `recruiting_labels.py` — `labels_for(kind)` shared copy used by Discord review, Slack review, and `commands.py` fallback text.
- Modify `recruiting_panel.py` — `REV_FIND_ID`/`REV_MODAL_ID`, `is_rev_find`/`is_rev_modal`, `build_reverse_modal`, plain-text "Find Jobs" button.
- Modify `recruiting_review.py` — `kind`-aware copy in `build_review_message`.
- Modify `discord_commands.py` — route `aiuiout:revfind`/`aiuiout:revmodal`.
- Modify `commands.py` — `run_panel_reverse`; `_watch_outreach_review` builder-by-platform; `run_outreach_select/edit_submit/send` platform- + direction-aware; Slack → `mode="manual"`.
- Modify `slack_recruiting_panel.py` — reverse button + modal + field extraction.
- **Create** `slack_recruiting_review.py` — Block Kit review builders (mirror of `recruiting_review.py`).
- Modify `slack_interactions.py` — reverse entry + review block actions + edit `view_submission` + review-capable Slack `ctx`.

**Webhook handler — `webhook-handler/clients/`**
- Modify `tasks.py` — `start_outreach` sends `direction`.
- `slack.py` — **no change** (`post_message(blocks=...)` and `post_to_response_url(replace_original=True, blocks=...)` already exist).

**Tests — `webhook-handler/tests/`**
- Modify `test_recruiting_panel.py`, `test_recruiting_review.py`, `test_slack_recruiting.py`.
- **Create** `test_recruiting_labels.py`, `test_slack_recruiting_review.py`, and a re-render direction-regression test.

**n8n (live Hostinger instance — UI, not repo)**
- Modify the `recruiting-outreach` workflow to set `Reply-To` from the payload's `reply_to`. The repo `n8n-workflows/recruiting-outreach.json` is a `CONFIGURE_IN_UI` template — documentation only.

---

## Phase 1 — Backend (tasks service)

All paths are under repo root `C:\Users\alama\Desktop\Lukas Work\IO`. Pure-logic tests run via the documented harness from `mcp-servers/tasks`:
`"../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/<file>.py -v`
Never run the full tasks suite (its conftest TRUNCATEs the prod DB). Only the three named files (`test_outreach_logic.py`, `test_outreach_n8n.py`, `test_routes_outreach.py`) — none of them request the `db_session` fixture, so no DB is touched.

Current line numbers (verified):
- `mcp-servers/tasks/outreach.py`: `build_outreach_prompt` 65–91, `post_outreach_to_n8n` 94–105, `format_outreach_summary` 108–114.
- `mcp-servers/tasks/routes_outreach.py`: `OutreachRequest` 22–27, `OutreachStatusResponse` 34–42, `_process_outreach_result` 45–68, `_process_outreach_find` 71–84, `start_outreach` 108–126 (prompt call line 111, `create_task` 123–125), `get_outreach_status` 129–145, `get_outreach_candidates` 148–156, `patch_outreach_candidate` 167–180, `send_outreach` 183–220, `_run_outreach` 223–246.

---

### Task 1.1 — `build_outreach_prompt`: add `direction` kwarg + reverse branch (hire byte-identical)

- [ ] Step: write the failing test. Append to `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\tests\test_outreach_logic.py` (after line 53, the existing `test_build_outreach_prompt_contains_contract`):

````python
def test_build_outreach_prompt_hire_unchanged_by_direction_default():
    # Positional call and explicit direction="hire" must be byte-identical.
    p_default = outreach.build_outreach_prompt("Python", "Berlin", "Hiring a dev", 8)
    p_hire = outreach.build_outreach_prompt("Python", "Berlin", "Hiring a dev", 8,
                                            direction="hire")
    assert p_default == p_hire
    assert "recruiting research assistant" in p_hire
    assert "api.github.com/search/users" in p_hire


def test_build_outreach_prompt_reverse_branch():
    p = outreach.build_outreach_prompt("Senior Python backend", "Berlin",
                                       "10y Python, FastAPI, AWS", 5,
                                       direction="reverse")
    assert "on behalf of" in p.lower()            # acts for the seeker
    assert "companies hiring for" in p.lower()    # company-oriented search
    assert "WebSearch" in p and "WebFetch" in p   # web-search tools, not GitHub API
    assert "first person" in p.lower() or "first-person" in p.lower()
    assert "10y Python, FastAPI, AWS" in p        # seeker background grounded
    assert "5" in p                               # count threaded
    assert "```json" in p and "COMPLETED" in p    # SAME machine contract reused
    assert "github.com/search/users" not in p     # NOT the hire/GitHub flow
````

- [ ] Step: run it, expect FAIL. From `mcp-servers/tasks`:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_logic.py -k "reverse_branch or hire_unchanged" -v
  ```
  Expected failure: `TypeError: build_outreach_prompt() got an unexpected keyword argument 'direction'` on both new tests.

- [ ] Step: implement. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\outreach.py`, replace the function header + first body line (lines 65–66) — leaving the entire hire `return f"""..."""` block (lines 67–91) untouched:

  Replace:
  ```python
  def build_outreach_prompt(role: str, location: str, jobdesc: str, count: int) -> str:
      loc = f" located in {location}" if location.strip() else ""
  ```
  with:
````python
def build_outreach_prompt(role: str, location: str, jobdesc: str, count: int,
                          *, direction: str = "hire") -> str:
    if direction == "reverse":
        rloc = f" in {location}" if location.strip() else ""
        return f"""You are a job-search assistant working ON BEHALF OF a job seeker. \
Find up to {count} companies hiring for: {role}{rloc}, then draft a tailored \
application email to each — written in the FIRST PERSON as the seeker.

The seeker's background / skills (use this to tailor every application):
---
{jobdesc}
---

STEPS:
1. Use the WebSearch and WebFetch tools to find companies plausibly hiring for \
"{role}"{rloc}. For each company, find a REAL careers/jobs/hiring-contact email \
(careers@, jobs@, or a named recruiter). Never guess or fabricate an email — use \
null if you cannot find a real one.
2. Draft a SHORT, tailored, first-person application email per company (subject + \
body), grounded in the seeker's background above and signed as the seeker.
3. Output EXACTLY ONE fenced json block (no prose after it), then a new line with \
the single word COMPLETED. Use name = the company, github_url = the company \
careers/jobs URL, email = the contact email (or null), and subject/body = the \
application:
```json
{{"candidates":[{{"name":"...","github_url":"...","email":"... or null","subject":"...","body":"..."}}]}}
```
If you cannot find any companies, output a candidates list of [] then COMPLETED. \
On a hard error, output a line starting with FAILED: and the reason."""
    loc = f" located in {location}" if location.strip() else ""
````
  (The hire `return f"""You are a recruiting research assistant. ...` at lines 67–91 stays exactly as-is.)

- [ ] Step: run test, expect PASS:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_logic.py -v
  ```

- [ ] Step: commit (from repo root):
  ```bash
  git add mcp-servers/tasks/outreach.py mcp-servers/tasks/tests/test_outreach_logic.py
  git commit -m "feat(outreach): reverse-direction branch in build_outreach_prompt" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 1.2 — `format_outreach_summary`: direction-aware noun

- [ ] Step: write the failing test. Append to `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\tests\test_outreach_logic.py`:

```python
def test_format_outreach_summary_hire_default_unchanged():
    s = outreach.format_outreach_summary(found=12, sent=8, saved=4, sheet_url="http://s")
    assert "found 12 engineer(s)" in s
    assert "Emailed 8" in s and "Saved 4 to your sheet" in s


def test_format_outreach_summary_reverse_company_noun():
    s = outreach.format_outreach_summary(found=12, sent=8, saved=4, sheet_url="http://s",
                                         direction="reverse")
    assert "found 12 compan(y/ies)" in s
    assert "engineer" not in s
```

- [ ] Step: run it, expect FAIL:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_logic.py -k "summary_reverse_company" -v
  ```
  Expected failure: `TypeError: format_outreach_summary() got an unexpected keyword argument 'direction'`. (The new hire-default test already passes; the reverse test is the red one.)

- [ ] Step: implement. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\outreach.py`, replace `format_outreach_summary` (lines 108–114):

```python
def format_outreach_summary(found: int, sent: int, saved: int, sheet_url: str = "",
                            *, direction: str = "hire") -> str:
    # `saved` is the total written to the sheet this run (emailed + collected),
    # per the n8n Respond node — so phrase it as total-saved, not "no-email only".
    noun = "compan(y/ies)" if direction == "reverse" else "engineer(s)"
    parts = [f"Outreach complete — found {found} {noun}.",
             f"Emailed {sent}.",
             f"Saved {saved} to your sheet."]
    return " ".join(parts)
```

- [ ] Step: run test, expect PASS:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_logic.py -v
  ```

- [ ] Step: commit:
  ```bash
  git add mcp-servers/tasks/outreach.py mcp-servers/tasks/tests/test_outreach_logic.py
  git commit -m "feat(outreach): direction-aware noun in format_outreach_summary" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 1.3 — `post_outreach_to_n8n`: add `reply_to` to payload (backward compatible)

- [ ] Step: write the failing test. Append to `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\tests\test_outreach_n8n.py` (after the existing test at line 36):

```python
@pytest.mark.asyncio
async def test_post_outreach_includes_reply_to(monkeypatch):
    monkeypatch.setattr(outreach.httpx, "AsyncClient", _Client)
    await outreach.post_outreach_to_n8n("Python role", [
        Candidate(name="A", email="a@x.com", subject="s", body="b")],
        reply_to="seeker@x.com")
    assert _Client.last["json"]["reply_to"] == "seeker@x.com"


@pytest.mark.asyncio
async def test_post_outreach_reply_to_defaults_empty(monkeypatch):
    monkeypatch.setattr(outreach.httpx, "AsyncClient", _Client)
    await outreach.post_outreach_to_n8n("Python role", [
        Candidate(name="A", email="a@x.com", subject="s", body="b")])
    assert _Client.last["json"]["reply_to"] == ""
```

- [ ] Step: run it, expect FAIL:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_n8n.py -k "reply_to" -v
  ```
  Expected failure: first test → `TypeError: post_outreach_to_n8n() got an unexpected keyword argument 'reply_to'`; second test → `KeyError: 'reply_to'` on the payload.

- [ ] Step: implement. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\outreach.py`, replace `post_outreach_to_n8n`'s header + docstring + payload (lines 94–100):

```python
async def post_outreach_to_n8n(job_title: str, candidates: list[Candidate],
                               *, reply_to: str = "", timeout: float = 90.0) -> dict:
    """POST the batch to the n8n recruiting-outreach webhook (mirror routes_cron).
    `reply_to` (optional) becomes the Gmail Reply-To so company/recruiter replies
    route to the seeker (reverse) or recruiter (hire). Returns parsed JSON
    ({sent, saved, sheet_url}) or raises on non-2xx."""
    url = f"{N8N_BASE.rstrip('/')}/webhook/{OUTREACH_WEBHOOK_PATH}"
    payload = {"job_title": job_title,
               "reply_to": reply_to,
               "candidates": [c.model_dump() for c in candidates]}
```
  (Lines 101–105 — the `async with httpx.AsyncClient(...)` block — stay as-is.)

- [ ] Step: run test, expect PASS:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_n8n.py -v
  ```

- [ ] Step: commit:
  ```bash
  git add mcp-servers/tasks/outreach.py mcp-servers/tasks/tests/test_outreach_n8n.py
  git commit -m "feat(outreach): add reply_to to n8n outreach payload" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 1.4 — `_process_outreach_find`: direction/role/location in dict + direction-aware not-found (pure)

- [ ] Step: write the failing test. Append to `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\tests\test_routes_outreach.py` (after line 38). `routes_outreach` and `json` are already imported at the top of this file:

````python
def _find_log(cands):
    body = json.dumps({"candidates": cands})
    return json.dumps({"type": "result",
                       "result": f"```json\n{body}\n```\nCOMPLETED"}) + "\n"


def test_process_find_reverse_includes_meta_and_company_copy():
    log = _find_log([{"name": "Acme", "github_url": "https://acme.com/careers",
                      "email": "jobs@acme.com", "subject": "s", "body": "b"}])
    out = routes_outreach._process_outreach_find(
        log, job_title="Senior Python", count=10, direction="reverse",
        location="Berlin")
    assert out["status"] == "review"
    assert out["direction"] == "reverse"
    assert out["role"] == "Senior Python"
    assert out["location"] == "Berlin"
    assert out["found"] == 1


def test_process_find_reverse_not_found_company_copy():
    out = routes_outreach._process_outreach_find(
        _find_log([]), job_title="x", count=10, direction="reverse")
    assert out["status"] == "failed"
    assert "companies" in out["text"]
    assert out["direction"] == "reverse"


def test_process_find_hire_default_unchanged():
    out = routes_outreach._process_outreach_find(_find_log([]), job_title="x", count=10)
    assert out["status"] == "failed"
    assert "engineers" in out["text"]
    assert out["direction"] == "hire" and out["role"] == "x" and out["location"] == ""
````

- [ ] Step: run it, expect FAIL:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -k "process_find" -v
  ```
  Expected failure: reverse tests → `TypeError: _process_outreach_find() got an unexpected keyword argument 'direction'`; hire test → `KeyError: 'direction'`.

- [ ] Step: implement. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\routes_outreach.py`, replace `_process_outreach_find` (lines 71–84):

```python
def _process_outreach_find(raw_log: str, *, job_title: str, count: int,
                           direction: str = "hire", location: str = "") -> dict:
    """Manual mode: parse candidates, DON'T send. Store a review state."""
    meta = {"direction": direction, "role": job_title, "location": location}
    outcome = parse_outcome(raw_log)
    if outcome.kind == "failed":
        return {"status": "failed", "found": 0, "job_title": job_title,
                "text": (outcome.payload or "The search failed.").strip()[:500],
                **meta}
    cand = outreach.extract_candidates(raw_log)
    if not cand.candidates:
        nf = ("I couldn't find companies hiring for that — try a broader role."
              if direction == "reverse"
              else "I couldn't find engineers matching that — try a broader role.")
        return {"status": "failed", "found": 0, "job_title": job_title,
                "text": nf, **meta}
    batch = outreach.cap_and_dedupe(cand.candidates, count)
    return {"status": "review", "phase": "review", "job_title": job_title,
            "found": len(batch),
            "candidates": outreach.build_review_candidates(batch), **meta}
```

- [ ] Step: run test, expect PASS:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -v
  ```

- [ ] Step: commit:
  ```bash
  git add mcp-servers/tasks/routes_outreach.py mcp-servers/tasks/tests/test_routes_outreach.py
  git commit -m "feat(outreach): thread direction/role/location into _process_outreach_find" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 1.5 — `_process_outreach_result`: direction/role/location in dict + direction-aware copy (pure, monkeypatched n8n)

- [ ] Step: write the failing test. Append to `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\tests\test_routes_outreach.py`:

````python
@pytest.mark.asyncio
async def test_process_result_reverse_meta_and_summary(monkeypatch):
    cand = json.dumps({"candidates": [
        {"name": "Acme", "github_url": "https://acme.com", "email": "jobs@acme.com",
         "subject": "s", "body": "b"}]})
    log = json.dumps({"type": "result",
                      "result": f"```json\n{cand}\n```\nCOMPLETED"}) + "\n"

    async def fake_post(job_title, candidates, **kw):
        return {"sent": 1, "saved": 1, "sheet_url": "http://sheet"}
    monkeypatch.setattr(routes_outreach.outreach, "post_outreach_to_n8n", fake_post)

    out = await routes_outreach._process_outreach_result(
        log, job_title="Senior Python", count=10, direction="reverse",
        location="Berlin")
    assert out["status"] == "completed"
    assert out["direction"] == "reverse"
    assert out["role"] == "Senior Python" and out["location"] == "Berlin"
    assert "compan(y/ies)" in out["text"]


@pytest.mark.asyncio
async def test_process_result_reverse_not_found_company_copy():
    log = json.dumps({"type": "result",
                      "result": "```json\n{\"candidates\":[]}\n```\nCOMPLETED"}) + "\n"
    out = await routes_outreach._process_outreach_result(
        log, job_title="x", count=10, direction="reverse")
    assert out["status"] == "failed" and out["found"] == 0
    assert "companies" in out["text"]
    assert out["direction"] == "reverse"
````

- [ ] Step: run it, expect FAIL:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -k "process_result_reverse" -v
  ```
  Expected failure: `TypeError: _process_outreach_result() got an unexpected keyword argument 'direction'`.

- [ ] Step: implement. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\routes_outreach.py`, replace `_process_outreach_result` (lines 45–68):

```python
async def _process_outreach_result(raw_log: str, *, job_title: str, count: int,
                                   direction: str = "hire", location: str = "") -> dict:
    """Pure: agent log -> summary dict."""
    meta = {"direction": direction, "role": job_title, "location": location}
    noun = "compan(y/ies)" if direction == "reverse" else "engineer(s)"
    outcome = parse_outcome(raw_log)
    if outcome.kind == "failed":
        return {"status": "failed", "found": 0, "sent": 0, "saved": 0,
                "sheet_url": "", "text": (outcome.payload or "The search failed.").strip()[:500],
                **meta}
    cand = outreach.extract_candidates(raw_log)
    found = len(cand.candidates)
    if found == 0:
        nf = ("I couldn't find companies hiring for that — try a broader role or drop the location."
              if direction == "reverse"
              else "I couldn't find engineers matching that — try a broader role or remove the location.")
        return {"status": "failed", "found": 0, "sent": 0, "saved": 0, "sheet_url": "",
                "text": nf, **meta}
    batch = outreach.cap_and_dedupe(cand.candidates, count)
    try:
        res = await outreach.post_outreach_to_n8n(job_title, batch)
    except Exception as exc:  # noqa: BLE001
        logger.error("outreach n8n POST failed: %s", exc)
        return {"status": "completed", "found": found, "sent": 0, "saved": len(batch),
                "sheet_url": "",
                "text": f"Found {found} {noun} but sending failed — they're saved; I'll retry sends.",
                **meta}
    sent = int(res.get("sent", 0)); saved = int(res.get("saved", len(batch)))
    sheet_url = res.get("sheet_url", "")
    return {"status": "completed", "found": found, "sent": sent, "saved": saved,
            "sheet_url": sheet_url,
            "text": outreach.format_outreach_summary(found, sent, saved, sheet_url,
                                                     direction=direction),
            **meta}
```

- [ ] Step: run test, expect PASS (also re-runs the three existing `test_process_*` cases — still green):
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -v
  ```

- [ ] Step: commit:
  ```bash
  git add mcp-servers/tasks/routes_outreach.py mcp-servers/tasks/tests/test_routes_outreach.py
  git commit -m "feat(outreach): thread direction/role/location into _process_outreach_result" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 1.6 — Model fields: `OutreachRequest.direction` + `OutreachStatusResponse.direction/role/location`

- [ ] Step: write the failing test. Append to `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\tests\test_routes_outreach.py`:

```python
def test_outreach_request_direction_default_hire():
    assert routes_outreach.OutreachRequest(jobdesc="hiring a dev").direction == "hire"
    assert routes_outreach.OutreachRequest(jobdesc="x", direction="reverse").direction == "reverse"


def test_outreach_status_response_has_direction_role_location():
    r = routes_outreach.OutreachStatusResponse(status="review")
    assert r.direction == "hire"
    assert r.role == "" and r.location == ""
```

- [ ] Step: run it, expect FAIL:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -k "outreach_request_direction or status_response_has" -v
  ```
  Expected failure: pydantic v2 ignores the unknown `direction`/`role`/`location`, so `AttributeError: 'OutreachRequest' object has no attribute 'direction'` (and likewise for the status response).

- [ ] Step: implement. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\routes_outreach.py`:

  (a) Add one line to `OutreachRequest` (after line 27, the `mode:` line):
  ```python
      direction: str = "hire"   # "hire" = company->engineer; "reverse" = seeker->company
  ```

  (b) Add three lines to `OutreachStatusResponse` (after line 42, the `job_title:` line):
  ```python
      direction: str = "hire"
      role: str = ""
      location: str = ""
  ```

- [ ] Step: run test, expect PASS:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -v
  ```

- [ ] Step: commit:
  ```bash
  git add mcp-servers/tasks/routes_outreach.py mcp-servers/tasks/tests/test_routes_outreach.py
  git commit -m "feat(outreach): add direction to request + direction/role/location to status model" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 1.7 — Thread `direction`+`location`: `start_outreach` → `_run_outreach` → `_process_*`

`_run_outreach`'s signature is unit-testable via `inspect` (does not run the body, no DB). The `start_outreach` body and the `_run_outreach` internals touch the DB / spawn the agent, so they are code-edits with a manual verification note.

- [ ] Step: write the failing test. Append to `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\tests\test_routes_outreach.py` (add `import inspect` at the top of the file alongside the existing `import json, os, sys, pytest`):

```python
def test_run_outreach_signature_accepts_direction_and_location():
    sig = inspect.signature(routes_outreach._run_outreach)
    assert sig.parameters["direction"].default == "hire"
    assert sig.parameters["location"].default == ""
    assert sig.parameters["mode"].default == "auto"   # unchanged
```

- [ ] Step: run it, expect FAIL:
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -k "run_outreach_signature" -v
  ```
  Expected failure: `KeyError: 'direction'`.

- [ ] Step: implement `_run_outreach`. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\routes_outreach.py`, replace lines 223–231 (header through the `_process_*` calls):

  Replace:
  ```python
  async def _run_outreach(task_id, execution_id, prompt, *, job_title: str,
                          count: int, mode: str = "auto"):
      from routes_execution import _stream_claude  # LOCAL import (keep here, not module-top)
      try:
          raw_log = await _stream_claude(prompt, execution_id, task_id)
          if mode == "manual":
              summary = _process_outreach_find(raw_log, job_title=job_title, count=count)
          else:
              summary = await _process_outreach_result(raw_log, job_title=job_title, count=count)
  ```
  with:
  ```python
  async def _run_outreach(task_id, execution_id, prompt, *, job_title: str,
                          count: int, mode: str = "auto", direction: str = "hire",
                          location: str = ""):
      from routes_execution import _stream_claude  # LOCAL import (keep here, not module-top)
      try:
          raw_log = await _stream_claude(prompt, execution_id, task_id)
          if mode == "manual":
              summary = _process_outreach_find(raw_log, job_title=job_title, count=count,
                                               direction=direction, location=location)
          else:
              summary = await _process_outreach_result(raw_log, job_title=job_title,
                                                       count=count, direction=direction,
                                                       location=location)
  ```
  (Lines 232–246 — status write-back + exception handler — unchanged.)

- [ ] Step: implement `start_outreach` (DB-touching — no pytest). In the same file, edit two spots inside `start_outreach`:

  (a) Prompt build (line 111). Replace:
  ```python
      prompt = outreach.build_outreach_prompt(body.role, body.location, body.jobdesc, body.count)
  ```
  with:
  ```python
      prompt = outreach.build_outreach_prompt(body.role, body.location, body.jobdesc,
                                              body.count, direction=body.direction)
  ```

  (b) Agent spawn (lines 123–125). Replace:
  ```python
      asyncio.create_task(_run_outreach(task_id, exec_id, prompt,
                                        job_title=body.role, count=body.count,
                                        mode=body.mode))
  ```
  with:
  ```python
      asyncio.create_task(_run_outreach(task_id, exec_id, prompt,
                                        job_title=body.role, count=body.count,
                                        mode=body.mode, direction=body.direction,
                                        location=body.location))
  ```

- [ ] Step: run test, expect PASS (signature test + full pure file stays green):
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -v
  ```

- [ ] Step: manual/integration verification (NOT a pytest — `start_outreach` opens a DB session and spawns the agent). After deploy, run a reverse search end-to-end (spec §10) and confirm the stored `TaskItem.result` JSON contains `"direction":"reverse"`, `"role"`, and `"location"`; and that a hire run still stores `"direction":"hire"`. Do NOT add a test that opens a DB session.

- [ ] Step: commit:
  ```bash
  git add mcp-servers/tasks/routes_outreach.py mcp-servers/tasks/tests/test_routes_outreach.py
  git commit -m "feat(outreach): thread direction/location through start_outreach -> _run_outreach" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 1.8 — Populate `direction`/`role`/`location` on GET status, GET candidates, PATCH candidate (DB-touching)

These three handlers read `data` from the DB (`_load_review` / direct select), so they are code-edits with a manual verification note. The model defaults are already covered by Task 1.6's pure test; this task wires the stored `result` JSON into the response. The PATCH one is load-bearing (select/edit re-render reads it).

- [ ] Step: edit `get_outreach_status` return. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\routes_outreach.py`, replace the return at lines 141–145:

  Replace:
  ```python
      return OutreachStatusResponse(
          status=data.get("status", "failed"), found=data.get("found", 0),
          sent=data.get("sent", 0), saved=data.get("saved", 0),
          sheet_url=data.get("sheet_url", ""), text=data.get("text", ""),
          candidates=data.get("candidates", []), job_title=data.get("job_title", ""))
  ```
  with:
  ```python
      return OutreachStatusResponse(
          status=data.get("status", "failed"), found=data.get("found", 0),
          sent=data.get("sent", 0), saved=data.get("saved", 0),
          sheet_url=data.get("sheet_url", ""), text=data.get("text", ""),
          candidates=data.get("candidates", []),
          job_title=data.get("job_title", "") or data.get("role", ""),
          direction=data.get("direction", "hire"),
          role=data.get("role", "") or data.get("job_title", ""),
          location=data.get("location", ""))
  ```

- [ ] Step: edit `get_outreach_candidates` return. Replace lines 153–156:

  Replace:
  ```python
      return OutreachStatusResponse(
          status=data.get("status", "failed"), found=data.get("found", 0),
          text=data.get("text", ""), candidates=data.get("candidates", []),
          job_title=data.get("job_title", ""))
  ```
  with:
  ```python
      return OutreachStatusResponse(
          status=data.get("status", "failed"), found=data.get("found", 0),
          text=data.get("text", ""), candidates=data.get("candidates", []),
          job_title=data.get("job_title", "") or data.get("role", ""),
          direction=data.get("direction", "hire"),
          role=data.get("role", "") or data.get("job_title", ""),
          location=data.get("location", ""))
  ```

- [ ] Step: edit `patch_outreach_candidate` return (LOAD-BEARING). Replace lines 179–180:

  Replace:
  ```python
      return OutreachStatusResponse(status="review", candidates=candidates,
                                    found=len(candidates), job_title=data.get("job_title", ""))
  ```
  with:
  ```python
      return OutreachStatusResponse(status="review", candidates=candidates,
                                    found=len(candidates),
                                    job_title=data.get("job_title", "") or data.get("role", ""),
                                    direction=data.get("direction", "hire"),
                                    role=data.get("role", "") or data.get("job_title", ""),
                                    location=data.get("location", ""))
  ```

- [ ] Step: import-sanity check (no DB, just confirms the file still imports and the existing pure tests are unaffected):
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -v
  ```

- [ ] Step: manual/integration verification (NOT a pytest — handlers open DB sessions). After deploy, against a reverse task: `GET /outreach/{id}`, `GET /outreach/{id}/candidates`, and a `PATCH /outreach/{id}/candidates/{cid}` must each return `direction:"reverse"`, the `role`, and `location`. Confirm a hire task still returns `direction:"hire"`. (This is what lets the §6 re-render handlers pick company copy on every interaction.)

- [ ] Step: commit:
  ```bash
  git add mcp-servers/tasks/routes_outreach.py
  git commit -m "feat(outreach): populate direction/role/location on status, candidates, PATCH" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 1.9 — `send_outreach`: pass `reply_to`+role to n8n, direction-aware 0-selected/summary, persist direction/role/location (DB-touching)

`send_outreach` reads/writes the DB, so this is a code-edit with manual verification. The `reply_to` payload key was unit-proven in Task 1.3 and the direction-aware summary in Task 1.2; this task wires them into the handler.

- [ ] Step: edit `send_outreach`. In `C:\Users\alama\Desktop\Lukas Work\IO\mcp-servers\tasks\routes_outreach.py`, replace the whole handler (lines 183–220) with:

```python
@router.post("/outreach/{task_id}/send", response_model=OutreachStatusResponse)
async def send_outreach(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    item, data = await _load_review(task_id, user)
    direction = data.get("direction", "hire")
    role = data.get("role", "") or data.get("job_title", "")
    location = data.get("location", "")
    candidates = data.get("candidates", [])
    batch = outreach.sendable_candidates(candidates)
    if not batch:
        none_sel = ("Pick at least one company with an email first."
                    if direction == "reverse"
                    else "Pick at least one engineer with an email first.")
        return OutreachStatusResponse(status="review", candidates=candidates,
                                      text=none_sel, job_title=role,
                                      direction=direction, role=role, location=location)
    try:
        res = await outreach.post_outreach_to_n8n(role, batch,
                                                  reply_to=item.assignee_email)
    except Exception as exc:  # noqa: BLE001
        logger.error("manual outreach send failed: %s", exc)
        return OutreachStatusResponse(status="review", candidates=candidates,
                                      text="Sending failed — try again.", job_title=role,
                                      direction=direction, role=role, location=location)
    sent_emails = {c.email.strip().lower() for c in batch}
    for c in candidates:
        if (c.get("email") or "").strip().lower() in sent_emails:
            c["status"] = "sent"
            c["selected"] = False
    new_data = {**data, "phase": "sent", "candidates": candidates,
                "status": "completed",
                "direction": direction, "role": role, "location": location,
                "sent": int(res.get("sent", len(batch))),
                "saved": int(res.get("saved", len(batch))),
                "sheet_url": res.get("sheet_url", ""),
                "text": outreach.format_outreach_summary(
                    data.get("found", len(candidates)),
                    int(res.get("sent", len(batch))),
                    int(res.get("saved", len(batch))), res.get("sheet_url", ""),
                    direction=direction)}
    async with session() as s:
        await s.execute(update(TaskItem).where(TaskItem.id == task_id)
                        .values(result=json.dumps(new_data)))
        await s.commit()
    return OutreachStatusResponse(
        status="sent", candidates=candidates, sent=new_data["sent"],
        saved=new_data["saved"], sheet_url=new_data["sheet_url"], text=new_data["text"],
        job_title=role, direction=direction, role=role, location=location)
```

  Notes: `role` replaces the old `data.get("job_title", "")` as the n8n `job_title` (falls back to stored `job_title`, so hire is unchanged); `reply_to=item.assignee_email` is the seeker (reverse) or recruiter (hire) per spec §5; the 0-selected text and the summary are direction-aware; `new_data` now persists `direction`/`role`/`location` so the post-send re-render keeps company copy.

- [ ] Step: import-sanity check (no DB):
  ```bash
  "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_routes_outreach.py -v
  ```

- [ ] Step: manual/integration verification (NOT a pytest — opens a DB session + POSTs to n8n). After deploy, in a reverse review: send with 0 selected → "Pick at least one company with an email first."; send with 1 selected → the n8n execution payload shows `reply_to` = the seeker's `assignee_email`, the sent summary reads "found N compan(y/ies)", and the received email's `Reply-To` is the seeker. Confirm a hire send still says "engineer(s)" and `reply_to` = the recruiter.

- [ ] Step: commit:
  ```bash
  git add mcp-servers/tasks/routes_outreach.py
  git commit -m "feat(outreach): send passes reply_to+role, direction-aware copy, persists meta" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

## Phase 2 — Discord

This phase ships the Discord vertical slice for reverse recruiting ("Find Jobs"): a new entry button + modal, a direction-aware review builder, the shared `recruiting_labels` copy module, and the load-bearing change that makes the re-render handlers (`run_outreach_select`/`edit_submit`/`send`) platform- AND direction-aware so company-oriented copy survives every interaction — not just the first watcher post.

**Dependency note:** Phase 2 assumes Phase 1 (backend) is landing in parallel and that `GET /outreach/{id}/candidates`, `PATCH /outreach/{id}/candidates/{cid}`, and `POST /outreach/{id}/send` will return `direction`/`role`/`location` (default `"hire"`/`""`/`""`). The webhook-handler code degrades safely if those keys are absent (`st.get("direction","hire")`), so Phase 2 tests pass regardless of Phase 1 timing.

**Files touched:** `webhook-handler/handlers/recruiting_labels.py` (new), `recruiting_panel.py`, `recruiting_review.py`, `commands.py`, `discord_commands.py`, `clients/tasks.py`, plus tests.

All pytest commands run from the repo root `C:\Users\alama\Desktop\Lukas Work\IO` exactly as: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/<file>.py -v`.

---

### Task 2.1 — `recruiting_labels.py`: direction-aware copy module (shared by Discord + Slack + commands)

This module is the single source of truth for every user-facing string that differs between the `hire` ("Find Engineers") and `reverse` ("Find Jobs") flows. `hire` keeps today's EXACT strings (so the existing hire UX is byte-for-byte unchanged); `reverse` uses company-oriented copy. Imported by `recruiting_review.py` (Phase 2), `slack_recruiting_review.py` (Phase 3), and `commands.py` for fallback/watcher text.

- [ ] **Step — write the failing test.** Create `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\tests\test_recruiting_labels.py`:

```python
from handlers import recruiting_labels as rl

KEYS = {"found_prefix", "select_placeholder", "edit_placeholder", "send_button",
        "footer", "none_found", "ready", "pick_one"}


def test_hire_has_all_keys_and_engineer_copy():
    lab = rl.labels_for("hire")
    assert set(lab) == KEYS
    assert lab["select_placeholder"] == "Select who to email…"
    assert lab["footer"] == "Pick who to email · ✏️ edit/add-email · then Send"
    assert lab["none_found"] == "No engineers found."
    assert lab["ready"] == "Engineers ready to review."
    assert lab["pick_one"] == "Pick at least one engineer first."
    assert lab["send_button"] == "\U0001f4e7 Send to selected"
    assert lab["found_prefix"] == "\U0001f50d Found"


def test_reverse_has_all_keys_and_company_copy():
    lab = rl.labels_for("reverse")
    assert set(lab) == KEYS
    assert "apply" in lab["select_placeholder"].lower()
    assert "apply" in lab["footer"].lower()
    assert "compan" in lab["none_found"].lower()
    assert "compan" in lab["ready"].lower()
    assert "compan" in lab["pick_one"].lower()
    assert "application" in lab["send_button"].lower()
    assert lab["found_prefix"] == "Found"


def test_unknown_and_empty_kind_fall_back_to_hire():
    assert rl.labels_for("") == rl.labels_for("hire")
    assert rl.labels_for("bogus") == rl.labels_for("hire")


def test_returns_independent_copy():
    a = rl.labels_for("hire")
    a["footer"] = "MUTATED"
    assert rl.labels_for("hire")["footer"] != "MUTATED"
```

- [ ] **Step — run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_labels.py -v` → fails with `ModuleNotFoundError: No module named 'handlers.recruiting_labels'`.

- [ ] **Step — implement.** Create `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\handlers\recruiting_labels.py`:

```python
"""Direction-aware copy for the recruiting review UI.

Pure, no I/O. labels_for(kind) returns the user-facing strings for either the
"hire" (Find Engineers) or "reverse" (Find Jobs / companies) flow. The "hire"
strings are byte-for-byte the ones hard-coded today, so the existing flow is
unchanged. Imported by handlers/recruiting_review.py (Discord),
handlers/slack_recruiting_review.py (Slack, Phase 3), and used by
handlers/commands.py for fallback/watcher text. Unit-tested in
tests/test_recruiting_labels.py.
"""
from __future__ import annotations

_HIRE = {
    "found_prefix": "\U0001f50d Found",
    "select_placeholder": "Select who to email…",
    "edit_placeholder": "Edit / add email for one…",
    "send_button": "\U0001f4e7 Send to selected",
    "footer": "Pick who to email · ✏️ edit/add-email · then Send",
    "none_found": "No engineers found.",
    "ready": "Engineers ready to review.",
    "pick_one": "Pick at least one engineer first.",
}

_REVERSE = {
    "found_prefix": "Found",
    "select_placeholder": "Select who to apply to…",
    "edit_placeholder": "Edit / add email for one…",
    "send_button": "\U0001f4e7 Send applications",
    "footer": "Pick who to apply to · ✏️ edit/add-email · then Send",
    "none_found": "No companies found.",
    "ready": "Companies ready to review.",
    "pick_one": "Pick at least one company first.",
}


def labels_for(kind: str) -> dict:
    """Copy dict for ``kind`` ∈ {"hire","reverse"}. Unknown/empty kinds fall
    back to hire so callers can pass a raw ``direction`` value safely. Returns a
    fresh dict each call so callers may mutate the result without side effects."""
    return dict(_REVERSE if kind == "reverse" else _HIRE)
```

- [ ] **Step — run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_labels.py -v` → 4 passed.

- [ ] **Step — commit.**
```bash
git add webhook-handler/handlers/recruiting_labels.py webhook-handler/tests/test_recruiting_labels.py
git commit -m "feat(recruiting): add direction-aware labels module (hire/reverse copy)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.2 — `recruiting_panel.py`: REV_FIND_ID/REV_MODAL_ID, predicates, reverse modal, "Find Jobs" button

The reverse modal REUSES the exact input custom_ids `role`/`location`/`jobdesc`/`count` so the existing `parse_outreach_modal` works on it unchanged — only the labels/placeholders differ. The entry button uses the PLAIN TEXT label `"Find Jobs"` (no emoji), per the standing no-emoji preference, even though the existing "Find Engineers" button keeps its emoji.

- [ ] **Step — write the failing test.** Append to `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\tests\test_recruiting_panel.py`:

```python
def test_panel_has_find_jobs_plain_text_button():
    payload = rp.build_recruiting_panel()
    buttons = [c for row in payload["components"] for c in row["components"]
               if "custom_id" in c]
    ids = [c["custom_id"] for c in buttons]
    assert rp.REV_FIND_ID in ids
    label = next(c["label"] for c in buttons if c["custom_id"] == rp.REV_FIND_ID)
    assert label == "Find Jobs"  # plain text, no emoji


def test_reverse_modal_reuses_outreach_input_ids():
    modal = rp.build_reverse_modal()
    assert modal["custom_id"] == rp.REV_MODAL_ID
    assert modal["title"] == "Find Jobs"
    input_ids = [row["components"][0]["custom_id"] for row in modal["components"]]
    assert input_ids == [rp.OUT_ROLE_INPUT, rp.OUT_LOCATION_INPUT,
                         rp.OUT_JOBDESC_INPUT, rp.OUT_COUNT_INPUT]
    styles = {row["components"][0]["custom_id"]: row["components"][0]["style"]
              for row in modal["components"]}
    assert styles[rp.OUT_JOBDESC_INPUT] == 2   # paragraph (background/skills)
    assert styles[rp.OUT_ROLE_INPUT] == 1      # short


def test_parse_outreach_modal_works_on_reverse_modal_values():
    role, location, jobdesc, count = rp.parse_outreach_modal({
        rp.OUT_ROLE_INPUT: "Senior Python backend", rp.OUT_LOCATION_INPUT: "Berlin",
        rp.OUT_JOBDESC_INPUT: "6 yrs Python/Django", rp.OUT_COUNT_INPUT: "12"})
    assert (role, location, jobdesc, count) == (
        "Senior Python backend", "Berlin", "6 yrs Python/Django", 12)


def test_reverse_is_predicates():
    assert rp.is_rev_find(rp.REV_FIND_ID)
    assert not rp.is_rev_find(rp.OUT_FIND_ID)
    assert rp.is_rev_modal(rp.REV_MODAL_ID)
    assert not rp.is_rev_modal(rp.OUT_MODAL_ID)
```

- [ ] **Step — run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_panel.py -v` → fails with `AttributeError: module 'handlers.recruiting_panel' has no attribute 'REV_FIND_ID'`.

- [ ] **Step — implement (constants + `__all__`).** In `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\handlers\recruiting_panel.py`, replace the `__all__` block (lines 13-18) with:

```python
__all__ = [
    "OUT_FIND_ID", "OUT_MODAL_ID", "OUT_ROLE_INPUT", "OUT_LOCATION_INPUT",
    "OUT_JOBDESC_INPUT", "OUT_COUNT_INPUT", "REV_FIND_ID", "REV_MODAL_ID",
    "build_recruiting_panel", "build_recruiting_embed", "build_outreach_modal",
    "build_reverse_modal", "is_out_find", "is_out_modal", "is_rev_find",
    "is_rev_modal", "parse_outreach_modal",
]
```

  Then add the two id constants immediately after line 25 (`OUT_COUNT_INPUT = "count"`):

```python
REV_FIND_ID = "aiuiout:revfind"
REV_MODAL_ID = "aiuiout:revmodal"
```

- [ ] **Step — implement (button).** In the same file, replace the `row = {...}` block inside `build_recruiting_panel` (lines 40-43) with:

```python
    row = {"type": ACTION_ROW, "components": [
        _button("\U0001f50d Find Engineers", OUT_FIND_ID, STYLE_SUCCESS),
        _button("Find Jobs", REV_FIND_ID, STYLE_PRIMARY),
        _button("\U0001f517 Link my account", LINK_START_ID, STYLE_PRIMARY),
    ]}
```

- [ ] **Step — implement (reverse modal + predicates).** In the same file, immediately after `build_outreach_modal` (after line 84) and before `def is_out_find` (line 87), insert:

```python
def build_reverse_modal() -> dict:
    """Type-9 MODAL data for reverse recruiting ('Find Jobs'): target role,
    location, the seeker's background/skills, how many companies. Reuses the
    SAME input custom_ids as build_outreach_modal (role/location/jobdesc/count)
    so parse_outreach_modal works unchanged — only the labels differ."""
    def _ti(cid, label, style, required, maxlen, placeholder):
        return {"type": ACTION_ROW, "components": [{
            "type": TEXT_INPUT, "custom_id": cid, "label": label, "style": style,
            "required": required, "max_length": maxlen, "placeholder": placeholder,
        }]}
    return {
        "title": "Find Jobs"[:45],
        "custom_id": REV_MODAL_ID,
        "components": [
            _ti(OUT_ROLE_INPUT, "Target role", TEXT_SHORT, True, 100,
                "e.g. Senior Python backend"),
            _ti(OUT_LOCATION_INPUT, "Location (optional)", TEXT_SHORT, False, 100,
                "e.g. Berlin"),
            _ti(OUT_JOBDESC_INPUT, "Your background / skills", TEXT_PARAGRAPH, True,
                4000, "6 yrs Python/Django, led payments team, ..."),
            _ti(OUT_COUNT_INPUT, "How many companies (max 25)", TEXT_SHORT, False, 3,
                "10"),
        ],
    }
```

  And add the two predicates immediately after `def is_out_modal` (after line 92):

```python
def is_rev_find(custom_id: str) -> bool:
    return custom_id == REV_FIND_ID


def is_rev_modal(custom_id: str) -> bool:
    return custom_id == REV_MODAL_ID
```

- [ ] **Step — run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_panel.py -v` → all pass (existing + 4 new).

- [ ] **Step — commit.**
```bash
git add webhook-handler/handlers/recruiting_panel.py webhook-handler/tests/test_recruiting_panel.py
git commit -m "feat(recruiting): add Find Jobs button + reverse modal (reuses outreach input ids)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.3 — `recruiting_review.py`: `kind`-aware review/sent builders

`build_review_message` gains `kind="hire"` and pulls title/footer/select-placeholder/edit-placeholder/send-button copy from `recruiting_labels.labels_for(kind)`. Reverse renders `"Found N companies for {role}"`, `"Pick who to apply to…"`, `"📧 Send applications (n)"`; hire is byte-for-byte identical to today. `build_sent_message` gains a reserved `kind="hire"` (the `text` is already direction-aware from the backend summary, so `kind` is currently unused on Discord — kept for signature parity with the Slack builder in Phase 3).

- [ ] **Step — write the failing test.** Append to `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\tests\test_recruiting_review.py`:

```python
def test_hire_kind_default_is_unchanged():
    msg = rr.build_review_message("t1", CANDS, role="Python", location="Manila")
    title = msg["embeds"][0]["title"]
    assert title == "\U0001f50d Found 2 · Python · Manila"
    assert msg["embeds"][0]["footer"]["text"] == (
        "Pick who to email · ✏️ edit/add-email · then Send")
    sel = msg["components"][0]["components"][0]
    assert sel["placeholder"] == "Select who to email…"
    send = msg["components"][2]["components"][0]
    assert send["label"] == "\U0001f4e7 Send to selected (1)"


def test_reverse_kind_renders_company_copy():
    msg = rr.build_review_message("t1", CANDS, role="Backend", location="Berlin",
                                  kind="reverse")
    title = msg["embeds"][0]["title"]
    assert title == "Found 2 companies for Backend"   # no location, "companies for"
    assert "apply" in msg["embeds"][0]["footer"]["text"].lower()
    sel = msg["components"][0]["components"][0]
    assert "apply" in sel["placeholder"].lower()
    send = msg["components"][2]["components"][0]
    assert send["label"] == "\U0001f4e7 Send applications (1)"


def test_reverse_empty_list_uses_no_companies_copy():
    msg = rr.build_review_message("t1", [], role="Backend", kind="reverse")
    assert msg["embeds"][0]["description"] == "No companies found."


def test_build_sent_message_accepts_kind_kwarg():
    out = rr.build_sent_message("Emailed 3 companies, saved 5", kind="reverse")
    assert "Emailed 3 companies" in out["content"]
    assert out["components"] == []
```

- [ ] **Step — run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_review.py -v` → fails with `TypeError: build_review_message() got an unexpected keyword argument 'kind'`.

- [ ] **Step — implement (import).** In `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\handlers\recruiting_review.py`, after the import block (after line 12, the `_button,` import line closing paren on line 12) add:

```python
from handlers.recruiting_labels import labels_for
```

- [ ] **Step — implement (`build_review_message`).** Replace the entire `build_review_message` function (lines 26-68) with:

```python
def build_review_message(task_id: str, candidates: list[dict], *,
                         role: str = "", location: str = "",
                         kind: str = "hire") -> dict:
    """Overview message: embed list + recipient multi-select (emailable only) +
    edit dropdown (all) + Send/Refresh buttons. ``kind`` ∈ {"hire","reverse"}
    selects engineer- vs company-oriented copy (recruiting_labels.labels_for)."""
    lab = labels_for(kind)
    lines = []
    for c in candidates:
        email = (c.get("email") or "").strip()
        icon = "✅" if (c.get("selected") and email) else ("⚠️" if not email else "⬜")
        lines.append(f"{icon} **{c.get('name', '?')}** — {email or '(no email)'}")
    if kind == "reverse":
        title = f"{lab['found_prefix']} {len(candidates)} companies for {role}"
    else:
        where = role + (f" · {location}" if location else "")
        title = f"{lab['found_prefix']} {len(candidates)} · {where}"
    embed = {
        "title": title[:256],
        "color": ROBOTIC_CYAN,
        "description": ("\n".join(lines) or lab["none_found"])[:4000],
        "footer": {"text": lab["footer"]},
    }
    rows: list[dict] = []
    emailable = _emailable(candidates)[:_MAX]
    if emailable:
        rows.append({"type": ACTION_ROW, "components": [{
            "type": SELECT_MENU, "custom_id": f"{SEL_PREFIX}{task_id}",
            "placeholder": lab["select_placeholder"],
            "min_values": 0, "max_values": len(emailable),
            "options": [{
                "label": (c.get("name") or c["id"])[:100], "value": c["id"],
                "description": c["email"][:100], "default": bool(c.get("selected")),
            } for c in emailable],
        }]})
    rows.append({"type": ACTION_ROW, "components": [{
        "type": SELECT_MENU, "custom_id": f"{EDIT_PREFIX}{task_id}",
        "placeholder": lab["edit_placeholder"],
        "min_values": 1, "max_values": 1,
        "options": [{
            "label": (c.get("name") or c["id"])[:100], "value": c["id"],
            "description": ((c.get("email") or "").strip() or "no email")[:100],
        } for c in candidates[:_MAX]],
    }]})
    selected = sum(1 for c in candidates if c.get("selected") and (c.get("email") or "").strip())
    rows.append({"type": ACTION_ROW, "components": [
        _button(f"{lab['send_button']} ({selected})", f"{SEND_PREFIX}{task_id}", STYLE_SUCCESS),
        _button("♻ Refresh", f"{REFRESH_PREFIX}{task_id}", STYLE_SECONDARY),
    ]})
    return {"embeds": [embed], "components": rows}
```

- [ ] **Step — implement (`build_sent_message`).** Replace the `build_sent_message` signature line (line 71, `def build_sent_message(text: str, sheet_url: str = "") -> dict:`) with:

```python
def build_sent_message(text: str, sheet_url: str = "", *, kind: str = "hire") -> dict:
```

  (Body unchanged. `kind` is reserved for parity with the Slack builder and is unused on Discord because `text` is already direction-aware from the backend summary.)

- [ ] **Step — run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_review.py -v` → all pass (existing hire tests still green + 4 new).

- [ ] **Step — commit.**
```bash
git add webhook-handler/handlers/recruiting_review.py webhook-handler/tests/test_recruiting_review.py
git commit -m "feat(recruiting): make Discord review builder kind-aware (company copy for reverse)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.4 — `clients/tasks.py`: `start_outreach` sends `direction` in the POST body

The client forwards a free-form payload, so we inject a `direction="hire"` default into the POST body. A caller passing `direction="reverse"` (Task 2.5) overrides it. Backward-compatible: existing callers that omit `direction` now send `"hire"` explicitly, which is the backend default anyway.

- [ ] **Step — write the failing test.** Append to `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\tests\test_tasks_client_outreach.py`:

```python
@pytest.mark.asyncio
async def test_start_outreach_defaults_direction_hire():
    tc = _client({"task_id": "abc"})
    await tc.start_outreach("u@x.com", {"role": "Python", "count": 8})
    assert tc._request.call_args.kwargs["json"]["direction"] == "hire"


@pytest.mark.asyncio
async def test_start_outreach_passes_reverse_direction():
    tc = _client({"task_id": "abc"})
    await tc.start_outreach("u@x.com", {
        "role": "Python", "count": 8, "mode": "manual", "direction": "reverse"})
    assert tc._request.call_args.kwargs["json"]["direction"] == "reverse"
```

- [ ] **Step — run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_tasks_client_outreach.py -v` → `test_start_outreach_defaults_direction_hire` fails with `KeyError: 'direction'`.

- [ ] **Step — implement.** In `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\clients\tasks.py`, replace the `start_outreach` body (lines 237-241) with:

```python
    async def start_outreach(
        self, user_email: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        # Always include a direction so the backend can label the run; callers
        # override via payload["direction"] ("hire" | "reverse").
        body = {"direction": "hire", **payload}
        resp = await self._request("POST", "/outreach", user_email, json=body)
        return resp.json()
```

- [ ] **Step — run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_tasks_client_outreach.py -v` → all pass (incl. existing `test_start_outreach_posts_payload`, which only asserts `role`).

- [ ] **Step — commit.**
```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client_outreach.py
git commit -m "feat(recruiting): start_outreach sends direction (default hire) in POST body

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.5 — `commands.py`: `run_panel_reverse` + `_review_builder` helper + direction-aware `_watch_outreach_review`

`run_panel_reverse` mirrors `run_panel_outreach` (lines 2336-2370) but sends `direction="reverse"` and is ALWAYS `mode="manual"` (review-before-send) on every platform.

**CALLOUT (per spec §7 and the prompt):** in the original `run_panel_outreach` the line is `manual = ctx.platform == "discord"`. In `run_panel_reverse` that becomes unconditional `manual` — we set `mode="manual"` directly and always run `_watch_outreach_review`. This means Slack reverse is ALSO manual. We do NOT touch `run_panel_outreach` here, so Slack **hire** keeps its current auto-send behavior; flipping hire to manual on Slack is deferred to Phase 3, where the Slack review-capable ctx (`notify_channel_msg`/`edit_message`) is built — flipping it now would degrade Slack hire to a text-only post. (Slack reverse never executes in Phase 2 anyway: the Slack entry button is added in Phase 3, so `run_panel_reverse` is unreachable on Slack until then.)

`_review_builder(ctx)` implements the contract's builder-by-platform resolution (`handlers.recruiting_review` for Discord, `handlers.slack_recruiting_review` for Slack) via a lazy import so Phase 2 doesn't require the Phase 3 Slack module to exist.

- [ ] **Step — write the failing test.** Append to `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\tests\test_run_panel_outreach.py` (reuses the `_router`/`_ctx` helpers already at the top of that file):

```python
@pytest.mark.asyncio
async def test_run_panel_reverse_sends_direction_reverse_and_manual():
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock())
    await r.run_panel_reverse(ctx, "Backend", "Berlin", "6 yrs Python", 8)
    tc.start_outreach.assert_awaited_once()
    _email, payload = tc.start_outreach.await_args.args
    assert payload["direction"] == "reverse"
    assert payload["mode"] == "manual"
    ctx.respond.assert_awaited()  # the "Searching…" ack


@pytest.mark.asyncio
async def test_run_panel_reverse_is_manual_even_on_slack():
    # Reverse is review-before-send on ALL platforms (NOT auto like Slack hire).
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock(), platform="slack")
    await r.run_panel_reverse(ctx, "Backend", "", "skills", 8)
    _email, payload = tc.start_outreach.await_args.args
    assert payload["mode"] == "manual"
    assert payload["direction"] == "reverse"


@pytest.mark.asyncio
async def test_run_panel_reverse_unlinked_prompts_link():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    r._respond_not_linked = AsyncMock()
    ctx = _ctx(AsyncMock())
    await r.run_panel_reverse(ctx, "Backend", "", "skills", 8)
    r._respond_not_linked.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_panel_reverse_empty_background_does_not_start():
    r = _router(MagicMock())
    ctx = _ctx(AsyncMock())
    await r.run_panel_reverse(ctx, "Backend", "", "   ", 8)
    ctx.respond.assert_awaited()  # asks for background; no task started
    r._tasks_client.start_outreach.assert_not_called()
```

- [ ] **Step — run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_run_panel_outreach.py -v` → new tests fail with `AttributeError: 'CommandRouter' object has no attribute 'run_panel_reverse'`.

- [ ] **Step — implement (`_review_builder` + `run_panel_reverse`).** In `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\handlers\commands.py`, immediately AFTER the end of `run_panel_outreach` (after line 2370, the `w.add_done_callback(...)` line) and BEFORE `async def _watch_outreach` (line 2372), insert:

```python
    @staticmethod
    def _review_builder(ctx: CommandContext):
        """Resolve the review-message builder module for ``ctx.platform``:
        Discord embeds (handlers.recruiting_review) vs Slack Block Kit
        (handlers.slack_recruiting_review, added in Phase 3). Lazy-imported so
        Phase 2 (Discord) does not require the Slack module to exist yet."""
        if ctx.platform == "discord":
            from handlers import recruiting_review as rr
        else:
            from handlers import slack_recruiting_review as rr
        return rr

    async def run_panel_reverse(
        self, ctx: CommandContext, role: str, location: str,
        jobdesc: str, count: int,
    ) -> None:
        """Reverse recruiting ('Find Jobs'): find COMPANIES hiring for the
        seeker's target role and draft a tailored application to each, for review
        before send. Mirrors run_panel_outreach but sends direction='reverse' and
        is ALWAYS manual (review-before-send) on every platform — unlike
        run_panel_outreach, whose ``manual`` is Discord-only today."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        if not (jobdesc or "").strip():
            await ctx.respond(
                "Please paste your background / skills so I can tailor each application.")
            return
        try:
            result = await self._tasks_client.start_outreach(email, {
                "role": role, "location": location, "jobdesc": jobdesc,
                "count": count, "mode": "manual", "direction": "reverse"})
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        task_id = result["task_id"]
        where = f"{role}" + (f" · {location}" if location else "")
        await ctx.respond(
            f"\U0001f50e Searching for companies hiring for **{where}** … I'll post "
            "the list here to review when it's ready (usually a minute or two).")
        if ctx.notify_channel is not None:
            w = asyncio.create_task(self._watch_outreach_review(
                ctx, email, task_id, role, location, direction="reverse"))
            self._background_tasks.add(w)
            w.add_done_callback(self._background_tasks.discard)
```

- [ ] **Step — implement (direction-aware `_watch_outreach_review`).** Replace the entire `_watch_outreach_review` method (lines 2413-2461) with:

```python
    async def _watch_outreach_review(
        self, ctx: CommandContext, email: str, task_id: str,
        role: str, location: str, *, direction: str = "hire",
    ) -> None:
        """Manual mode: poll the find until it reaches ``review``, then post the
        interactive overview to the channel as a fresh message that outlives the
        interaction window. The builder is chosen by ``ctx.platform`` (Discord
        embeds vs Slack Block Kit, Phase 3) and copy by ``direction`` (hire vs
        reverse). Slack hire keeps the auto-send path via ``_watch_outreach``."""
        from handlers import recruiting_labels
        rr = self._review_builder(ctx)
        lab = recruiting_labels.labels_for(direction)
        if ctx.notify_channel is None:
            return

        async def _notify_text(msg: str) -> None:
            try:
                await ctx.notify_channel(msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("watch_outreach_review notify failed task=%s: %s", task_id, exc)

        async def _notify_msg(msg: dict) -> None:
            try:
                if ctx.notify_channel_msg is not None:
                    await ctx.notify_channel_msg(msg)
                else:
                    # No rich poster wired — degrade to the embed's text summary
                    # so the result still lands somewhere.
                    embeds = msg.get("embeds") or []
                    desc = embeds[0].get("description", "") if embeds else ""
                    await ctx.notify_channel(desc or lab["ready"])
            except Exception as exc:  # noqa: BLE001
                logger.error("watch_outreach_review rich notify failed task=%s: %s", task_id, exc)

        for _ in range(OUTREACH_MAX_POLLS):
            await asyncio.sleep(OUTREACH_POLL_SECONDS)
            try:
                st = await self._tasks_client.get_outreach_candidates(email, task_id)
            except TasksAPIError as e:
                logger.warning("watch_outreach_review status error (%s) task=%s", e.status, task_id)
                continue
            status = st.get("status")
            if status == "running":
                continue
            if status == "review":
                msg = rr.build_review_message(
                    task_id, st.get("candidates", []),
                    role=st.get("role", role), location=st.get("location", location),
                    kind=st.get("direction", direction))
                await _notify_msg(msg)
                return
            await _notify_text((st.get("text") or "").strip() or lab["none_found"])
            return
        await _notify_text("Outreach search timed out — try again.")
```

- [ ] **Step — run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_run_panel_outreach.py -v` → all pass (existing hire tests + 4 new reverse tests). The spawned watcher coroutine sleeps on `OUTREACH_POLL_SECONDS` before any client call and is discarded at loop teardown, so the MagicMock `get_outreach_candidates` is never actually awaited during the test — identical to the existing `test_run_panel_outreach_starts_and_acks` pattern.

- [ ] **Step — commit.**
```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_run_panel_outreach.py
git commit -m "feat(recruiting): add run_panel_reverse + builder-by-platform watcher (always manual)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.6 — `commands.py`: platform- + direction-aware re-render (`run_outreach_select`/`edit_submit`/`send`) — the key regression

This is the load-bearing change both reviews flagged: the re-render handlers must read `direction`/`role`/`location` from the tasks-client response (now populated by Phase 1's PATCH/candidates/send endpoints) and pass `kind`/`role`/`location` to `build_review_message`, resolving the builder by `ctx.platform`. Today they hardcode `recruiting_review` and pass `role=""`/`location=""`, so reverse company-copy (and even the hire title) is lost on every re-render after the first watcher post. The regression test calls `run_outreach_select` with a FAKE tasks_client returning `direction="reverse"` and a fake ctx capturing the `edit_message` payload, asserting company-oriented copy renders. Fallback texts are templated via `recruiting_labels.labels_for(kind)`.

- [ ] **Step — write the failing test.** Append to `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\tests\test_run_panel_outreach.py` (uses `_router` from that file; builds the review-capable ctx inline from the `CommandContext` dataclass — required fields `user_id/user_name/channel_id/raw_text/subcommand/arguments/platform/respond`, plus the `edit_message` callback that the re-render handlers invoke):

```python
def _review_ctx(captured: dict, platform="discord"):
    """A review-capable CommandContext whose edit_message captures the rendered
    payload (mirrors discord_commands._out_ctx: edit the component's own message
    in place)."""
    async def edit_message(msg: dict) -> None:
        captured.clear()
        captured.update(msg)
    return CommandContext(
        user_id="100", user_name="alice", channel_id="c", raw_text="outreach",
        subcommand="outreach", arguments="", platform=platform,
        respond=AsyncMock(), edit_message=edit_message)


@pytest.mark.asyncio
async def test_run_outreach_select_reverse_renders_company_copy():
    # REGRESSION (review-demanded): on RE-RENDER the builder must read
    # direction/role/location FROM the tasks-client response and produce
    # company-oriented copy — not the hire defaults baked into the (empty) args.
    tc = MagicMock()
    tc.patch_outreach_candidate = AsyncMock(return_value={
        "status": "review", "direction": "reverse",
        "role": "Senior Python backend", "location": "Berlin",
        "candidates": [{
            "id": "c0", "name": "Acme Corp", "github_url": "acme.com/careers",
            "email": "jobs@acme.com", "subject": "S", "body": "B",
            "selected": True, "status": "draft"}]})
    r = _router(tc)
    captured: dict = {}
    ctx = _review_ctx(captured)
    # NB: discord_commands still passes role=""/location="" — the handler must
    # IGNORE those and read from the response instead.
    await r.run_outreach_select(ctx, "task-1", ["c0"], "", "")
    tc.patch_outreach_candidate.assert_awaited_once()
    title = captured["embeds"][0]["title"]
    assert title == "Found 1 companies for Senior Python backend"
    assert "apply" in captured["embeds"][0]["footer"]["text"].lower()
    sel = captured["components"][0]["components"][0]
    assert "apply" in sel["placeholder"].lower()
    send = captured["components"][2]["components"][0]
    assert send["label"] == "\U0001f4e7 Send applications (1)"


@pytest.mark.asyncio
async def test_run_outreach_select_hire_still_renders_engineer_copy():
    tc = MagicMock()
    tc.patch_outreach_candidate = AsyncMock(return_value={
        "status": "review", "direction": "hire", "role": "Python", "location": "Manila",
        "candidates": [{
            "id": "c0", "name": "Alice", "github_url": "gh/a", "email": "a@x.com",
            "subject": "S", "body": "B", "selected": True, "status": "draft"}]})
    r = _router(tc)
    captured: dict = {}
    await r.run_outreach_select(_review_ctx(captured), "task-1", ["c0"], "", "")
    assert captured["embeds"][0]["title"] == "\U0001f50d Found 1 · Python · Manila"
    assert "email" in captured["embeds"][0]["footer"]["text"].lower()


@pytest.mark.asyncio
async def test_run_outreach_send_zero_selected_uses_company_pick_one():
    tc = MagicMock()
    tc.send_outreach = AsyncMock(return_value={
        "status": "review", "direction": "reverse", "role": "Backend", "location": "",
        "text": "", "candidates": []})
    r = _router(tc)
    captured: dict = {}
    await r.run_outreach_send(_review_ctx(captured), "task-1")
    assert "Pick at least one company first." in captured["content"]


@pytest.mark.asyncio
async def test_run_outreach_send_sent_locks_with_backend_text():
    tc = MagicMock()
    tc.send_outreach = AsyncMock(return_value={
        "status": "sent", "direction": "reverse",
        "text": "Emailed 2 companies, saved 3", "sheet_url": "http://sheet"})
    r = _router(tc)
    captured: dict = {}
    await r.run_outreach_send(_review_ctx(captured), "task-1")
    assert "Emailed 2 companies" in captured["content"]
    assert captured["components"] == []   # locked, no components
```

- [ ] **Step — run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_run_panel_outreach.py -v -k "reverse or hire_still or zero_selected or sent_locks"` → `test_run_outreach_select_reverse_renders_company_copy` fails (`AssertionError`: title is `🔍 Found 1 · ` — hire copy with empty role — because the current handler passes `role=""`/`kind` defaults), and the zero-selected test fails (`"Pick at least one engineer first."` instead of company copy).

- [ ] **Step — implement (`run_outreach_select`).** In `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\handlers\commands.py`, replace the entire `run_outreach_select` method (lines 2463-2486) with:

```python
    async def run_outreach_select(
        self, ctx: CommandContext, task_id: str,
        selected_ids: Optional[list[str]], role: str = "", location: str = "",
    ) -> None:
        """Apply a recipient selection (``selected_ids``) or just refresh
        (``selected_ids is None``), then re-render the overview in place. Builder
        is resolved by ``ctx.platform`` and copy by the ``direction`` returned in
        the response (the ``role``/``location`` args are legacy and ignored —
        labels/title are restored from backend state, §5)."""
        rr = self._review_builder(ctx)
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            if selected_ids is None:
                st = await self._tasks_client.get_outreach_candidates(email, task_id)
            else:
                st = await self._tasks_client.patch_outreach_candidate(
                    email, task_id, "_", {"selected_ids": selected_ids})
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        msg = rr.build_review_message(
            task_id, st.get("candidates", []), role=st.get("role", ""),
            location=st.get("location", ""), kind=st.get("direction", "hire"))
        if ctx.edit_message is not None:
            await ctx.edit_message(msg)
```

- [ ] **Step — implement (`run_outreach_edit_submit`).** Replace the entire `run_outreach_edit_submit` method (lines 2488-2522) with:

```python
    async def run_outreach_edit_submit(
        self, ctx: CommandContext, task_id: str, cid: str, email_val: str,
        subject: str, body: str, role: str = "", location: str = "",
    ) -> None:
        """Save an edited candidate (email/subject/body) then re-render the
        overview in place. Platform-/direction-aware (see run_outreach_select)."""
        rr = self._review_builder(ctx)
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        from handlers.discord_commands import _valid_email
        ev = (email_val or "").strip()
        if ev and not _valid_email(ev):
            # bounce invalid email without mutating the candidate
            try:
                st = await self._tasks_client.get_outreach_candidates(email, task_id)
            except TasksAPIError:
                return
            if ctx.edit_message is not None:
                msg = rr.build_review_message(
                    task_id, st.get("candidates", []), role=st.get("role", ""),
                    location=st.get("location", ""), kind=st.get("direction", "hire"))
                msg = {**msg, "content": f"⚠️ `{ev}` doesn't look like a valid email — not saved."}
                await ctx.edit_message(msg)
            return
        try:
            st = await self._tasks_client.patch_outreach_candidate(
                email, task_id, cid,
                {"email": email_val, "subject": subject, "body": body})
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        msg = rr.build_review_message(
            task_id, st.get("candidates", []), role=st.get("role", ""),
            location=st.get("location", ""), kind=st.get("direction", "hire"))
        if ctx.edit_message is not None:
            await ctx.edit_message(msg)
```

- [ ] **Step — implement (`run_outreach_send`).** Replace the entire `run_outreach_send` method (lines 2524-2549) with:

```python
    async def run_outreach_send(self, ctx: CommandContext, task_id: str) -> None:
        """Send to the selected candidates. On success, lock the message with the
        backend's (already direction-aware) sent summary; otherwise surface why
        nothing went out. Platform-/direction-aware (see run_outreach_select)."""
        from handlers import recruiting_labels
        rr = self._review_builder(ctx)
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            st = await self._tasks_client.send_outreach(email, task_id)
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        kind = st.get("direction", "hire")
        if st.get("status") == "sent":
            msg = rr.build_sent_message(
                st.get("text", "Sent."), st.get("sheet_url", ""), kind=kind)
            if ctx.edit_message is not None:
                await ctx.edit_message(msg)
            else:
                await ctx.respond(msg.get("content", "✅ Sent."))
            return
        # not sent (e.g. nothing selected / transient send error): keep the
        # interactive overview intact and show the reason as a content line.
        lab = recruiting_labels.labels_for(kind)
        if ctx.edit_message is not None:
            msg = rr.build_review_message(
                task_id, st.get("candidates", []), role=st.get("role", ""),
                location=st.get("location", ""), kind=kind)
            msg = {**msg, "content": "⚠️ " + (st.get("text") or lab["pick_one"])}
            await ctx.edit_message(msg)
        else:
            await ctx.respond(st.get("text") or lab["pick_one"])
```

- [ ] **Step — run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_run_panel_outreach.py -v` → all pass (the reverse re-render regression now renders `"Found 1 companies for Senior Python backend"`, the hire path stays `"🔍 Found 1 · Python · Manila"`, and the zero-selected fallback reads `"Pick at least one company first."`).

- [ ] **Step — commit.**
```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_run_panel_outreach.py
git commit -m "fix(recruiting): make re-render handlers platform/direction-aware (reverse copy survives)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.7 — `discord_commands.py`: route `aiuiout:revfind` (component → reverse modal) + `aiuiout:revmodal` (submit → `run_panel_reverse`)

The component router (`_handle_message_component`, recruiting section lines 369-383) returns the reverse modal for `is_rev_find`. The modal-submit router (`_handle_modal_submit`, after the `is_out_modal` block at lines 782-823) parses the reverse modal with the shared `parse_outreach_modal` and spawns `router.run_panel_reverse`, building the same review-capable ctx (`notify_channel`/`notify_channel_rich`/`notify_channel_msg`) the hire path uses. Both new custom_ids are exact-match and disjoint from every earlier predicate, so insertion order is safe.

- [ ] **Step — write the failing test.** Create `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\tests\test_discord_reverse_routing.py` (modeled on `test_discord_commands_appselect.py`; the repo runs pytest in asyncio auto mode, so bare `async def` tests need no marker):

```python
import asyncio
from handlers.discord_commands import (
    DiscordCommandHandler, DEFERRED_CHANNEL_MESSAGE, MODAL)


class FakeDiscord:
    async def edit_original(self, **kwargs): pass
    async def post_channel_message(self, *a, **k): pass


class FakeRouter:
    def __init__(self):
        self.reverse_calls = []
    async def run_panel_reverse(self, ctx, role, location, jobdesc, count):
        self.reverse_calls.append((role, location, jobdesc, count))


def _component(custom_id):
    return {"type": 3, "data": {"custom_id": custom_id, "component_type": 2},
            "token": "tok", "channel_id": "c1",
            "member": {"user": {"id": "u1", "username": "ralph"}}}


def _modal(custom_id, values):
    comps = [{"type": 1, "components": [{"type": 4, "custom_id": k, "value": v}]}
             for k, v in values.items()]
    return {"type": 5, "data": {"custom_id": custom_id, "components": comps},
            "token": "tok", "channel_id": "c1",
            "member": {"user": {"id": "u1", "username": "ralph"}}}


async def test_rev_find_button_returns_reverse_modal():
    h = DiscordCommandHandler(FakeDiscord(), FakeRouter())
    resp = await h.handle_interaction(_component("aiuiout:revfind"))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == "aiuiout:revmodal"
    assert resp["data"]["title"] == "Find Jobs"


async def test_rev_modal_submit_spawns_run_panel_reverse():
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(_modal("aiuiout:revmodal", {
        "role": "Backend", "location": "Berlin", "jobdesc": "6 yrs Python",
        "count": "8"}))
    assert resp == {"type": DEFERRED_CHANNEL_MESSAGE}
    await asyncio.sleep(0)  # let the spawned task run
    assert router.reverse_calls == [("Backend", "Berlin", "6 yrs Python", 8)]
```

- [ ] **Step — run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_discord_reverse_routing.py -v` → `test_rev_find_button_returns_reverse_modal` fails (unknown component → `{"type": DEFERRED_UPDATE_MESSAGE}`, not `MODAL`); the modal test fails (`router.reverse_calls == []`).

- [ ] **Step — implement (component route).** In `C:\Users\alama\Desktop\Lukas Work\IO\webhook-handler\handlers\discord_commands.py`, in `_handle_message_component`, immediately after the `is_out_find` branch (after line 371, the `return {"type": MODAL, "data": recruiting_panel.build_outreach_modal()}` line) insert:

```python
        if recruiting_panel.is_rev_find(custom_id):
            return {"type": MODAL, "data": recruiting_panel.build_reverse_modal()}
```

- [ ] **Step — implement (modal-submit route).** In the same file, in `_handle_modal_submit`, immediately after the `is_out_modal` block (after line 823, the `return {"type": DEFERRED_CHANNEL_MESSAGE}` that ends that block) and before the `if rr.is_out_editmodal(custom_id):` line (824), insert:

```python
        if recruiting_panel.is_rev_modal(custom_id):
            values = {c["custom_id"]: c.get("value", "")
                      for row in data.get("components", [])
                      for c in row.get("components", [])}
            role, location, jobdesc, count = recruiting_panel.parse_outreach_modal(values)
            interaction_token = payload.get("token", "")
            member = payload.get("member", {})
            user = member.get("user", payload.get("user", {}))
            channel_id = payload.get("channel_id", "")
            notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)

            async def respond(msg: str) -> None:
                await self.discord.edit_original(
                    interaction_token=interaction_token, content=msg,
                )

            async def notify_channel_msg(msg: dict) -> None:
                await self.discord.post_channel_message(
                    channel_id, content=msg.get("content", ""),
                    embeds=msg.get("embeds"), components=msg.get("components"),
                )

            ctx = CommandContext(
                user_id=user.get("id", ""),
                user_name=user.get("username", "unknown"),
                channel_id=channel_id,
                raw_text="reverse find",
                subcommand="outreach",
                arguments="",
                platform="discord",
                respond=respond,
                metadata={
                    "interaction_id": payload.get("id", ""),
                    "interaction_token": interaction_token,
                    "guild_id": payload.get("guild_id", ""),
                },
                notify_channel=notify_channel if channel_id else None,
                notify_channel_rich=notify_channel_rich if channel_id else None,
                notify_channel_msg=notify_channel_msg if channel_id else None,
            )
            self._spawn(self.router.run_panel_reverse(ctx, role, location, jobdesc, count))
            return {"type": DEFERRED_CHANNEL_MESSAGE}
```

  (The `respond`/`notify_channel_msg` closure names are re-bound within `_handle_modal_submit`, matching the existing pattern in the `is_out_modal` block above — Python rebinds them per branch with no conflict.)

- [ ] **Step — run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_discord_reverse_routing.py -v` → 2 passed.

- [ ] **Step — regression sweep (all Phase 2 pure builders + routing).** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_labels.py tests/test_recruiting_panel.py tests/test_recruiting_review.py tests/test_tasks_client_outreach.py tests/test_run_panel_outreach.py tests/test_discord_reverse_routing.py tests/test_discord_commands_appselect.py -v` → all pass (confirms the new branches did not disturb the existing App Builder / hire routing).

- [ ] **Step — commit.**
```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_discord_reverse_routing.py
git commit -m "feat(recruiting): route Discord Find Jobs button + reverse modal to run_panel_reverse

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Phase 2 completion notes

- **Out of Phase 2 (deferred to Phase 1 / Phase 3):** the backend `direction`/`role`/`location` plumbing + reverse prompt + `reply_to` (Phase 1, `mcp-servers/tasks`); the Slack review layer — `slack_recruiting_review.py`, the Slack reverse entry button, the review-capable Slack ctx, and flipping `run_panel_outreach` to manual on Slack (Phase 3). `_review_builder` already imports `handlers.slack_recruiting_review` on the Slack branch, so Phase 3 just needs to add that module — no further change to `commands.py`'s re-render handlers.
- **Manual e2e (after Phase 1 lands):** one live Discord run in `#recruiting` — click **Find Jobs** → fill the reverse modal → confirm the watcher posts company-oriented copy (`"Found N companies for {role}"`, `"Select who to apply to…"`, `"📧 Send applications (n)"`) → select 1 → edit one application → **Send** → verify the n8n execution, the Google Sheet row, and `Reply-To = seeker` on the received email.
- **Deploy (webhook-handler is NOT covered by the orchestrator script):** per `CLAUDE.md`, scp each changed file individually (never `scp -r`), then `ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"`; confirm `docker compose ... ps webhook-handler` shows `Up`. Do this only after Phase 1's tasks service is deployed, or reverse runs will 422 on the unknown `direction` field.

## Phase 3 — Slack review layer

**Prerequisite (Phase 2 deliverables this phase imports):** `handlers/recruiting_labels.py` exposing `labels_for(kind)` with keys `found_prefix, select_placeholder, edit_placeholder, send_button, footer, none_found, ready, pick_one`; `commands.py:run_panel_reverse(self, ctx, role, location, jobdesc, count)`; and the platform/direction-aware `run_outreach_select` / `run_outreach_edit_submit` / `run_outreach_send` that resolve `kind`/`role`/`location` from the tasks-client response and pick the builder by `ctx.platform`. Phase 3 calls these by name; do not re-implement them here.

**Test harness (Windows, from repo root):**
`cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/<file>.py -v`

**Files touched:** `webhook-handler/handlers/slack_recruiting_panel.py` (edit), `webhook-handler/handlers/slack_recruiting_review.py` (new), `webhook-handler/handlers/slack_interactions.py` (edit), `webhook-handler/tests/test_slack_recruiting.py` (edit — panel + routing), `webhook-handler/tests/test_slack_recruiting_review.py` (new — pure builders).

---

### Task 3.1 — slack_recruiting_panel: `OUT_REV_*` constants, `build_reverse_view`, `reverse_fields_from_view`, "Find Jobs" button

The reverse modal is a **relabeled** copy of `build_outreach_view` that reuses the exact `_ROLE_BLOCK_ID`/`_LOCATION_BLOCK_ID`/`_JOBDESC_BLOCK_ID`/`_COUNT_BLOCK_ID` ids, so `reverse_fields_from_view` is just `outreach_fields_from_view` (→ `parse_outreach_modal`). The new entry button is **plain text "Find Jobs"** (no emoji) per the standing preference.

- [ ] **Step: write the failing test.** Append to `webhook-handler/tests/test_slack_recruiting.py`:
```python
# --- Phase 3.1: reverse entry (Find Jobs) panel builders ---

def test_find_jobs_button_present_plain_text():
    blocks = srp.build_recruiting_blocks()
    actions = [b for b in blocks if b["type"] == "actions"][0]
    labels = {e["text"]["text"]: e["action_id"] for e in actions["elements"]}
    # NEW button is plain text "Find Jobs" (no emoji); Find Engineers stays as-is.
    assert labels.get("Find Jobs") == srp.OUT_REV_ACTION_ID
    assert any(v == srp.OUT_FIND_ACTION_ID for v in labels.values())


def test_build_reverse_view_reuses_ids_and_callback():
    v = srp.build_reverse_view("C123")
    assert v["type"] == "modal"
    assert v["callback_id"] == srp.OUT_REV_CALLBACK
    assert v["private_metadata"] == "C123"
    assert v["title"]["text"] == "Find Jobs"
    # MUST reuse build_outreach_view's block ids so reverse_fields_from_view parses it.
    out = srp.build_outreach_view("C123")
    assert [b["block_id"] for b in v["blocks"]] == [b["block_id"] for b in out["blocks"]]


def test_reverse_fields_round_trip_and_clamp():
    view = {"state": {"values": srp.sample_state("Backend", "Remote", "Skills here", "30")}}
    # delegates to outreach_fields_from_view -> parse_outreach_modal (count clamps 30->25)
    assert srp.reverse_fields_from_view(view) == ("Backend", "Remote", "Skills here", 25)
```

- [ ] **Step: run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py -v` → `AttributeError: module 'handlers.slack_recruiting_panel' has no attribute 'OUT_REV_ACTION_ID'` (and `build_reverse_view`, `reverse_fields_from_view`).

- [ ] **Step: implement.** In `webhook-handler/handlers/slack_recruiting_panel.py`, extend `__all__` (lines 15–22) to include the new names:
```python
__all__ = [
    "OUT_FIND_ACTION_ID",
    "OUT_MODAL_CALLBACK",
    "OUT_REV_ACTION_ID",
    "OUT_REV_CALLBACK",
    "build_recruiting_blocks",
    "build_outreach_view",
    "build_reverse_view",
    "outreach_fields_from_view",
    "reverse_fields_from_view",
    "sample_state",
]
```
Add the two constants immediately after line 26 (`OUT_MODAL_CALLBACK = "aiuiout:modal"`):
```python
# Reverse-recruiting ("Find Jobs") entry button + modal ids.
OUT_REV_ACTION_ID = "aiuiout:revfind"
OUT_REV_CALLBACK = "aiuiout:revmodal"
```
Replace the `actions` block inside `build_recruiting_blocks` (lines 58–63) with one that adds the plain-text Find Jobs button:
```python
        {
            "type": "actions",
            "elements": [
                _button("\U0001f50d Find Engineers", OUT_FIND_ACTION_ID, primary=True),
                _button("Find Jobs", OUT_REV_ACTION_ID),
            ],
        },
```
Append `build_reverse_view` and `reverse_fields_from_view` at the end of the file (after `sample_state`, line 181):
```python
def build_reverse_view(channel_id: str) -> dict:
    """Slack modal for reverse recruiting ("Find Jobs"). Relabeled for a
    job-seeker but REUSES the exact role/location/jobdesc/count block & input
    ids of build_outreach_view, so reverse_fields_from_view (-> parse_outreach_modal)
    parses it unchanged. callback_id == OUT_REV_CALLBACK; the originating channel
    is stashed in private_metadata so the submit handler knows where to post."""
    return {
        "type": "modal",
        "callback_id": OUT_REV_CALLBACK,
        "private_metadata": channel_id or "",
        "title": {"type": "plain_text", "text": "Find Jobs"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Search"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": _ROLE_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Target role"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": _ROLE_INPUT_ID,
                    "multiline": False,
                    "max_length": 100,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. Senior Python backend",
                    },
                },
            },
            {
                "type": "input",
                "block_id": _LOCATION_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Location (optional)"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": _LOCATION_INPUT_ID,
                    "multiline": False,
                    "max_length": 100,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. Berlin or Remote",
                    },
                },
            },
            {
                "type": "input",
                "block_id": _JOBDESC_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Your background / skills"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": _JOBDESC_INPUT_ID,
                    "multiline": True,
                    "max_length": 4000,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Your experience, key skills, and what you're looking for...",
                    },
                },
            },
            {
                "type": "input",
                "block_id": _COUNT_BLOCK_ID,
                "label": {"type": "plain_text", "text": "How many companies (max 25)"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": _COUNT_INPUT_ID,
                    "multiline": False,
                    "max_length": 3,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "10",
                    },
                },
            },
        ],
    }


def reverse_fields_from_view(view: dict) -> tuple[str, str, str, int]:
    """Extract (role, location, jobdesc, count) from a reverse modal submit.
    The reverse modal reuses build_outreach_view's block/input ids, so this
    delegates to outreach_fields_from_view (kept as a named function for routing
    clarity / symmetry with the Discord side)."""
    return outreach_fields_from_view(view)
```

- [ ] **Step: run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py -v`

- [ ] **Step: commit.**
```bash
git add webhook-handler/handlers/slack_recruiting_panel.py webhook-handler/tests/test_slack_recruiting.py
git commit -m "feat(slack-recruiting): Find Jobs button + reverse modal builders

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.2 — NEW `slack_recruiting_review.py`: `build_review_message` (Block Kit mirror)

Block Kit mirror of `recruiting_review.build_review_message`. **Same signature** `(task_id, candidates, *, role="", location="", kind="hire")`; only the return shape differs (`{"text", "blocks"}`). Section list + a `multi_static_select` of **emailable-only** candidates (`aiuiout:sel:{task_id}`) + a single `static_select` to edit one (`aiuiout:edit:{task_id}`) + Send/Refresh buttons (`aiuiout:send|refresh:{task_id}`). All company-vs-engineer copy comes from `recruiting_labels.labels_for(kind)`. The header is built the same way as Discord's `recruiting_review.build_review_message` — `found_prefix` + role/location with company phrasing for reverse (header parity with Discord; honors the no-emoji preference for reverse).

- [ ] **Step: write the failing test.** Create `webhook-handler/tests/test_slack_recruiting_review.py`:
```python
from handlers import slack_recruiting_review as srr
from handlers import recruiting_labels

CANDS = [
    {"id": "c0", "name": "Alice", "github_url": "gh/a", "email": "a@x.com",
     "subject": "S0", "body": "B0", "selected": True, "status": "draft"},
    {"id": "c1", "name": "Bob", "github_url": "gh/b", "email": "",
     "subject": "", "body": "", "selected": False, "status": "no_email"},
]


def _by_action_prefix(blocks, prefix):
    """First Block Kit element across all actions blocks whose action_id starts with prefix."""
    for b in blocks:
        if b.get("type") != "actions":
            continue
        for el in b["elements"]:
            if el.get("action_id", "").startswith(prefix):
                return el
    return None


def test_review_message_shape_and_ids_hire():
    msg = srr.build_review_message("t1", CANDS, role="Python", location="Manila")
    assert set(msg) == {"text", "blocks"}
    lbl = recruiting_labels.labels_for("hire")
    header = msg["blocks"][0]["text"]["text"]
    assert lbl["found_prefix"] in header and "2" in header and "Python" in header

    sel = _by_action_prefix(msg["blocks"], srr.SEL_PREFIX)
    assert sel["action_id"] == "aiuiout:sel:t1"
    assert sel["type"] == "multi_static_select"
    assert [o["value"] for o in sel["options"]] == ["c0"]  # emailable only
    assert [o["value"] for o in sel["initial_options"]] == ["c0"]  # pre-selected
    assert sel["placeholder"]["text"] == lbl["select_placeholder"]

    edit = _by_action_prefix(msg["blocks"], srr.EDIT_PREFIX)
    assert edit["action_id"] == "aiuiout:edit:t1"
    assert [o["value"] for o in edit["options"]] == ["c0", "c1"]  # all candidates
    assert edit["placeholder"]["text"] == lbl["edit_placeholder"]

    send = _by_action_prefix(msg["blocks"], srr.SEND_PREFIX)
    assert send["action_id"] == "aiuiout:send:t1"
    assert lbl["send_button"] in send["text"]["text"] and "(1)" in send["text"]["text"]
    assert _by_action_prefix(msg["blocks"], srr.REFRESH_PREFIX)["action_id"] == "aiuiout:refresh:t1"


def test_review_message_no_emailable_omits_multiselect():
    msg = srr.build_review_message("t1", [CANDS[1]], role="X", location="")
    assert _by_action_prefix(msg["blocks"], srr.SEL_PREFIX) is None
    # edit select + send/refresh still render
    assert _by_action_prefix(msg["blocks"], srr.EDIT_PREFIX) is not None
    assert _by_action_prefix(msg["blocks"], srr.SEND_PREFIX) is not None


def test_review_message_reverse_uses_company_copy():
    rev = recruiting_labels.labels_for("reverse")
    msg = srr.build_review_message("t1", CANDS, role="Backend", location="", kind="reverse")
    header = msg["blocks"][0]["text"]["text"]
    assert rev["found_prefix"] in header
    assert "companies for Backend" in header   # company phrasing, parity with Discord
    assert "\U0001f50d" not in header          # no magnifying-glass emoji for reverse
    assert _by_action_prefix(msg["blocks"], srr.SEL_PREFIX)["placeholder"]["text"] == rev["select_placeholder"]
    assert rev["send_button"] in _by_action_prefix(msg["blocks"], srr.SEND_PREFIX)["text"]["text"]
```

- [ ] **Step: run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting_review.py -v` → `ModuleNotFoundError: No module named 'handlers.slack_recruiting_review'`.

- [ ] **Step: implement.** Create `webhook-handler/handlers/slack_recruiting_review.py` (full module — later tasks append `build_edit_modal_view`, `build_sent_message`, parsers):
```python
"""Pure Block Kit builders for the Slack recruiting review/select/edit/send UI.

Block Kit analog of handlers/recruiting_review.py (Discord). No I/O. The
custom-id scheme is identical (aiuiout:sel|edit|send|refresh|editmodal:<task_id>
[:<cid>]) so the Slack interaction router and the platform/direction-aware
command router methods key off the same ids as Discord. Direction-aware copy
comes from recruiting_labels.labels_for(kind). Unit-tested in
tests/test_slack_recruiting_review.py.
"""
from __future__ import annotations

import json

from handlers.slack_app_builder_panel import _button
from handlers.recruiting_labels import labels_for

__all__ = [
    "SEL_PREFIX", "EDIT_PREFIX", "SEND_PREFIX", "REFRESH_PREFIX", "EDITMODAL_PREFIX",
    "build_review_message", "build_edit_modal_view", "build_sent_message",
    "edit_fields_from_view", "ids_from_editmodal", "response_url_from_meta",
    "sample_edit_state",
]

SEL_PREFIX = "aiuiout:sel:"
EDIT_PREFIX = "aiuiout:edit:"
SEND_PREFIX = "aiuiout:send:"
REFRESH_PREFIX = "aiuiout:refresh:"
EDITMODAL_PREFIX = "aiuiout:editmodal:"

_MAX = 25
_OPT_TEXT_MAX = 75      # Slack select-option text hard limit
_PLACEHOLDER_MAX = 150  # Slack placeholder hard limit
_SECTION_MAX = 2900     # keep section text under Slack's 3000-char cap
_TITLE_MAX = 24         # Slack modal title hard limit

# Edit-modal input block/action ids.
_EMAIL_BLOCK_ID = "edit_email"
_EMAIL_INPUT_ID = "edit_email_input"
_SUBJECT_BLOCK_ID = "edit_subject"
_SUBJECT_INPUT_ID = "edit_subject_input"
_BODY_BLOCK_ID = "edit_body"
_BODY_INPUT_ID = "edit_body_input"


def _emailable(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if (c.get("email") or "").strip()]


def _opt(c: dict) -> dict:
    """A select option for one candidate (value = candidate id)."""
    label = (c.get("name") or c.get("id") or "?")[:_OPT_TEXT_MAX]
    return {"text": {"type": "plain_text", "text": label}, "value": c["id"]}


def build_review_message(task_id: str, candidates: list[dict], *,
                         role: str = "", location: str = "",
                         kind: str = "hire") -> dict:
    """Block Kit review overview. Returns {"text", "blocks"}.

    Mirrors recruiting_review.build_review_message (same signature, same id
    scheme) but renders Block Kit instead of an embed + components:
      - a header section ("<found_prefix> N · role · location"),
      - a section listing every candidate (status icon + name + email),
      - a multi_static_select of EMAILABLE candidates only (aiuiout:sel:<task_id>),
      - a static_select to edit/add-email for ONE candidate (aiuiout:edit:<task_id>),
      - Send / Refresh buttons (aiuiout:send|refresh:<task_id>),
      - a context footer.
    Company-oriented copy for kind="reverse" comes from labels_for(kind)."""
    lbl = labels_for(kind)
    n = len(candidates)
    # Header parity with Discord recruiting_review.build_review_message: derive the
    # title from labels_for(kind)["found_prefix"] + role/location. found_prefix carries
    # the emoji policy (no leading magnifying-glass for the reverse kind).
    if kind == "reverse":
        header = f"{lbl['found_prefix']} {n} companies for {role}"
    else:
        where = role + (f" · {location}" if location else "")
        header = f"{lbl['found_prefix']} {n} · {where}"

    lines = []
    for c in candidates:
        email = (c.get("email") or "").strip()
        icon = "✅" if (c.get("selected") and email) else ("⚠️" if not email else "⬜")
        lines.append(f"{icon} *{c.get('name', '?')}* — {email or '(no email)'}")
    body = ("\n".join(lines) or lbl["none_found"])[:_SECTION_MAX]

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header[:_SECTION_MAX]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
    ]

    emailable = _emailable(candidates)[:_MAX]
    if emailable:
        options = [_opt(c) for c in emailable]
        initial = [o for o, c in zip(options, emailable) if c.get("selected")]
        sel: dict = {
            "type": "multi_static_select",
            "action_id": f"{SEL_PREFIX}{task_id}",
            "placeholder": {"type": "plain_text",
                            "text": lbl["select_placeholder"][:_PLACEHOLDER_MAX]},
            "options": options,
        }
        if initial:
            sel["initial_options"] = initial
        blocks.append({"type": "actions", "elements": [sel]})

    if candidates:
        blocks.append({"type": "actions", "elements": [{
            "type": "static_select",
            "action_id": f"{EDIT_PREFIX}{task_id}",
            "placeholder": {"type": "plain_text",
                            "text": lbl["edit_placeholder"][:_PLACEHOLDER_MAX]},
            "options": [_opt(c) for c in candidates[:_MAX]],
        }]})

    selected = sum(1 for c in candidates
                   if c.get("selected") and (c.get("email") or "").strip())
    blocks.append({"type": "actions", "elements": [
        _button(f"{lbl['send_button']} ({selected})", f"{SEND_PREFIX}{task_id}", primary=True),
        _button("Refresh", f"{REFRESH_PREFIX}{task_id}"),
    ]})
    blocks.append({"type": "context",
                   "elements": [{"type": "mrkdwn", "text": lbl["footer"]}]})

    return {"text": header[:_SECTION_MAX], "blocks": blocks}
```

- [ ] **Step: run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting_review.py -v`

- [ ] **Step: commit.**
```bash
git add webhook-handler/handlers/slack_recruiting_review.py webhook-handler/tests/test_slack_recruiting_review.py
git commit -m "feat(slack-recruiting): Block Kit review-message builder

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.3 — `slack_recruiting_review`: `build_edit_modal_view` + `edit_fields_from_view` + `ids_from_editmodal` + `response_url_from_meta`

The edit modal `callback_id` is `aiuiout:editmodal:{task_id}:{cid}`; its `private_metadata` carries the block action's `response_url` (+ task_id/cid) as JSON, because the `view_submission` payload carries **no** `response_url`. `edit_fields_from_view` reads the three inputs back; `ids_from_editmodal` and `response_url_from_meta` are the parse helpers the router uses on submit.

- [ ] **Step: write the failing test.** Append to `webhook-handler/tests/test_slack_recruiting_review.py`:
```python
import json


def test_build_edit_modal_view_prefilled_and_meta():
    v = srr.build_edit_modal_view("t1", CANDS[0], "https://hook")
    assert v["type"] == "modal"
    assert v["callback_id"] == "aiuiout:editmodal:t1:c0"
    meta = json.loads(v["private_metadata"])
    assert meta == {"response_url": "https://hook", "task_id": "t1", "cid": "c0"}
    inits = {b["block_id"]: b["element"].get("initial_value") for b in v["blocks"]}
    assert inits["edit_email"] == "a@x.com"
    assert inits["edit_subject"] == "S0"
    assert inits["edit_body"] == "B0"


def test_edit_modal_omits_empty_initial_value():
    # Slack rejects initial_value="" — a blank-email candidate must omit the key.
    v = srr.build_edit_modal_view("t1", CANDS[1], "")
    email_el = [b for b in v["blocks"] if b["block_id"] == "edit_email"][0]["element"]
    assert "initial_value" not in email_el
    assert json.loads(v["private_metadata"])["response_url"] == ""


def test_edit_fields_and_parsers_round_trip():
    view = {"state": {"values": srr.sample_edit_state("z@x.com", "Hi", "Body!")}}
    assert srr.edit_fields_from_view(view) == ("z@x.com", "Hi", "Body!")
    assert srr.ids_from_editmodal("aiuiout:editmodal:t1:c0") == ("t1", "c0")
    meta = json.dumps({"response_url": "https://hook", "task_id": "t1", "cid": "c0"})
    assert srr.response_url_from_meta(meta) == "https://hook"
    assert srr.response_url_from_meta("not json") == ""
```

- [ ] **Step: run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting_review.py -v` → `AttributeError: module 'handlers.slack_recruiting_review' has no attribute 'build_edit_modal_view'`.

- [ ] **Step: implement.** Append to `webhook-handler/handlers/slack_recruiting_review.py`:
```python
def build_edit_modal_view(task_id: str, candidate: dict,
                          response_url: str = "") -> dict:
    """Slack modal to edit one candidate's email/subject/body.

    callback_id = aiuiout:editmodal:<task_id>:<cid>. Block actions carry a
    response_url but view_submission does NOT, so we stash the block action's
    response_url (alongside task_id/cid) in private_metadata as JSON. On submit
    the router reads it back to replace the review message in place. Empty values
    omit initial_value (Slack rejects initial_value="")."""
    cid = candidate.get("id", "")
    name = candidate.get("name", "")
    meta = json.dumps({"response_url": response_url or "",
                       "task_id": task_id, "cid": cid})

    def _input(block_id: str, input_id: str, label: str, value, *,
               multiline: bool, maxlen: int) -> dict:
        element: dict = {
            "type": "plain_text_input",
            "action_id": input_id,
            "multiline": multiline,
            "max_length": maxlen,
        }
        v = (value or "")[:maxlen]
        if v:
            element["initial_value"] = v
        return {
            "type": "input",
            "block_id": block_id,
            "optional": True,
            "label": {"type": "plain_text", "text": label},
            "element": element,
        }

    return {
        "type": "modal",
        "callback_id": f"{EDITMODAL_PREFIX}{task_id}:{cid}",
        "private_metadata": meta,
        "title": {"type": "plain_text", "text": f"Edit: {name}"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _input(_EMAIL_BLOCK_ID, _EMAIL_INPUT_ID, "Email (blank = don't email)",
                   candidate.get("email"), multiline=False, maxlen=200),
            _input(_SUBJECT_BLOCK_ID, _SUBJECT_INPUT_ID, "Subject",
                   candidate.get("subject"), multiline=False, maxlen=200),
            _input(_BODY_BLOCK_ID, _BODY_INPUT_ID, "Message",
                   candidate.get("body"), multiline=True, maxlen=_SECTION_MAX),
        ],
    }


def edit_fields_from_view(view: dict) -> tuple[str, str, str]:
    """(email, subject, body) from an editmodal view_submission's state."""
    values = (view or {}).get("state", {}).get("values", {})

    def _val(block_id: str, input_id: str) -> str:
        return (
            ((values.get(block_id) or {}).get(input_id) or {}).get("value") or ""
        ).strip()

    return (
        _val(_EMAIL_BLOCK_ID, _EMAIL_INPUT_ID),
        _val(_SUBJECT_BLOCK_ID, _SUBJECT_INPUT_ID),
        _val(_BODY_BLOCK_ID, _BODY_INPUT_ID),
    )


def ids_from_editmodal(callback_id: str) -> tuple[str, str]:
    """aiuiout:editmodal:<task_id>:<cid> -> (task_id, cid). task_id is a UUID
    (no colons) so the final ':' splits cleanly."""
    rest = callback_id[len(EDITMODAL_PREFIX):]
    task_id, _, cid = rest.rpartition(":")
    return task_id, cid


def response_url_from_meta(private_metadata: str) -> str:
    """Pull the stashed response_url out of an edit modal's private_metadata JSON.
    Returns "" on any parse failure (router then posts a fresh review message)."""
    try:
        return (json.loads(private_metadata or "{}") or {}).get("response_url", "") or ""
    except (ValueError, TypeError):
        return ""


def sample_edit_state(email: str, subject: str, body: str) -> dict:
    """A view.state.values dict shaped exactly as Slack sends an edit-modal
    submit. Used in tests so edit_fields_from_view and the test agree on the
    structure without duplicating the block/input id constants."""
    def _e(v: str) -> dict:
        return {"type": "plain_text_input", "value": v}

    return {
        _EMAIL_BLOCK_ID: {_EMAIL_INPUT_ID: _e(email)},
        _SUBJECT_BLOCK_ID: {_SUBJECT_INPUT_ID: _e(subject)},
        _BODY_BLOCK_ID: {_BODY_INPUT_ID: _e(body)},
    }
```

- [ ] **Step: run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting_review.py -v`

- [ ] **Step: commit.**
```bash
git add webhook-handler/handlers/slack_recruiting_review.py webhook-handler/tests/test_slack_recruiting_review.py
git commit -m "feat(slack-recruiting): edit-modal view builder + field/id parsers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.4 — `slack_recruiting_review`: `build_sent_message`

Final locked Block Kit message after Send (no action elements). **Same signature** as Discord `build_sent_message(text, sheet_url="", *, kind="hire")`; `text` is already direction-aware from the backend; `kind` is reserved/unused.

- [ ] **Step: write the failing test.** Append to `webhook-handler/tests/test_slack_recruiting_review.py`:
```python
def test_build_sent_message():
    msg = srr.build_sent_message("Emailed 3, saved 5.", "https://sheet")
    assert set(msg) == {"text", "blocks"}
    body = msg["blocks"][0]["text"]["text"]
    assert "Emailed 3, saved 5." in body and "https://sheet" in body
    # locked: no actions blocks
    assert all(b["type"] != "actions" for b in msg["blocks"])


def test_build_sent_message_no_sheet():
    msg = srr.build_sent_message("Done.")
    assert "Done." in msg["blocks"][0]["text"]["text"]
    assert "http" not in msg["text"]
```

- [ ] **Step: run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting_review.py -v` → `AttributeError: ... has no attribute 'build_sent_message'`.

- [ ] **Step: implement.** Append to `webhook-handler/handlers/slack_recruiting_review.py`:
```python
def build_sent_message(text: str, sheet_url: str = "", *,
                       kind: str = "hire") -> dict:
    """Final locked Block Kit message after Send (no action elements). `text` is
    already direction-aware from the backend; `kind` is reserved (unused)."""
    body = (f"✅ {text}" + (f"\n{sheet_url}" if sheet_url else ""))[:_SECTION_MAX]
    return {"text": body, "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": body}}]}
```

- [ ] **Step: run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting_review.py -v`

- [ ] **Step: commit.**
```bash
git add webhook-handler/handlers/slack_recruiting_review.py webhook-handler/tests/test_slack_recruiting_review.py
git commit -m "feat(slack-recruiting): locked sent-summary Block Kit message

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.5 — `slack_interactions`: route the reverse entry button + reverse modal submit (→ `run_panel_reverse`), and wire `notify_channel_msg` on both outreach modal ctxs

Block action `OUT_REV_ACTION_ID` opens `build_reverse_view`; `view_submission` with `OUT_REV_CALLBACK` parses via `reverse_fields_from_view` and dispatches `router.run_panel_reverse`. Both the existing hire ctx (lines 773–784) and the new reverse ctx get `notify_channel_msg`, because Phase 2 makes Slack `run_panel_outreach`/`run_panel_reverse` **manual**, and `_watch_outreach_review` posts the Block Kit review via `ctx.notify_channel_msg`.

> **Manual integration note:** the unit tests below assert dispatch + ctx wiring with a mocked router/Slack client (mirroring `test_slack_recruiting.py`). The live modal render and the actual review post are verified manually e2e in `#recruiting` (§10 of the spec).

- [ ] **Step: write the failing test.** Append to `webhook-handler/tests/test_slack_recruiting.py`:
```python
# --- Phase 3.5: reverse entry routing ---

@pytest.mark.asyncio
async def test_reverse_button_opens_modal():
    h = _handler(MagicMock())
    payload = {"type": "block_actions", "trigger_id": "tg",
               "channel": {"id": "c"}, "user": {"id": "u"},
               "actions": [{"action_id": srp.OUT_REV_ACTION_ID}]}
    await h.handle_interaction(payload)
    h.slack.open_modal.assert_awaited_once()
    _, view = h.slack.open_modal.await_args.args
    assert view["callback_id"] == srp.OUT_REV_CALLBACK


@pytest.mark.asyncio
async def test_reverse_modal_dispatches_run_panel_reverse():
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count):
        calls.append((role, location, jobdesc, count,
                      ctx.notify_channel, ctx.notify_channel_msg))
    router.run_panel_reverse = fake
    h = _handler(router)
    view = {"callback_id": srp.OUT_REV_CALLBACK, "private_metadata": "c",
            "state": {"values": srp.sample_state("Backend dev", "Remote", "10y Python", "5")}}
    payload = {"type": "view_submission", "user": {"id": "u"}, "view": view}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls, "run_panel_reverse was not dispatched"
    role, location, jobdesc, count, notify, ncm = calls[0]
    assert (role, location, jobdesc, count) == ("Backend dev", "Remote", "10y Python", 5)
    assert notify is not None      # text fallbacks
    assert ncm is not None         # Block Kit review poster for the manual watcher


@pytest.mark.asyncio
async def test_hire_modal_ctx_has_review_poster():
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count):
        calls.append(ctx.notify_channel_msg)
    router.run_panel_outreach = fake
    h = _handler(router)
    view = {"callback_id": srp.OUT_MODAL_CALLBACK, "private_metadata": "c",
            "state": {"values": srp.sample_state("Python", "Berlin", "Hiring", "8")}}
    payload = {"type": "view_submission", "user": {"id": "u"}, "view": view}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls and calls[0] is not None  # manual review needs notify_channel_msg
```

- [ ] **Step: run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py -v` → `test_reverse_button_opens_modal` fails (open_modal not awaited; unknown action no-ops), `test_reverse_modal_dispatches_run_panel_reverse` fails (`assert calls`), `test_hire_modal_ctx_has_review_poster` fails (`ctx.notify_channel_msg` is None).

- [ ] **Step: implement (block action route).** In `webhook-handler/handlers/slack_interactions.py`, add the review-review import after line 71 (`from handlers import slack_recruiting_panel as srp`):
```python
from handlers import slack_recruiting_review as srr
```
Replace the existing OUT_FIND block (lines 345–348) so the reverse button is routed alongside it:
```python
        # ----- Recruiting outreach panel (aiuiout:*) -----
        if action_id == srp.OUT_FIND_ACTION_ID:
            await self.slack.open_modal(trigger_id, srp.build_outreach_view(channel_id))
            return {}
        if action_id == srp.OUT_REV_ACTION_ID:
            await self.slack.open_modal(trigger_id, srp.build_reverse_view(channel_id))
            return {}
```

- [ ] **Step: implement (reverse modal submit).** In `_handle_view_submission`, insert this block immediately after the existing outreach-modal block (after line 797, before the final `logger.info(... unknown callback_id ...)` at line 799). It reuses `callback_id` (already set at line 543) and adds `notify_channel_msg`:
```python
        # ----- Reverse recruiting modal (Find Jobs) -----
        if callback_id == srp.OUT_REV_CALLBACK:
            role, location, jobdesc, count = srp.reverse_fields_from_view(view)
            target_channel = view.get("private_metadata") or ""

            async def _start_reverse() -> None:
                try:
                    async def respond(msg: str) -> None:
                        await self.slack.post_message(channel=target_channel, text=msg)

                    async def notify_channel(msg: str) -> None:
                        await respond(msg)

                    async def notify_channel_msg(msg: dict) -> None:
                        await self.slack.post_message(
                            channel=target_channel, blocks=msg["blocks"],
                            text=msg.get("text", ""))

                    ctx = CommandContext(
                        user_id=user_id,
                        user_name=user_name,
                        channel_id=target_channel,
                        raw_text="",
                        subcommand="outreach",
                        arguments="",
                        platform="slack",
                        respond=respond,
                        metadata={},
                        notify_channel=notify_channel,
                        notify_channel_msg=notify_channel_msg,
                    )
                    await self.router.run_panel_reverse(
                        ctx, role, location, jobdesc, count)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Slack reverse _start_reverse failed user=%s: %s",
                        user_id, exc,
                    )

            task = asyncio.create_task(_start_reverse())
            self.router._background_tasks.add(task)
            task.add_done_callback(self.router._background_tasks.discard)
            return {}
```

- [ ] **Step: implement (hire modal gets the review poster).** In the existing outreach-modal block, add a `notify_channel_msg` closure and pass it on the ctx. Replace lines 765–784 (the `_start_outreach` body up to and including the `ctx = CommandContext(...)`) with:
```python
            async def _start_outreach() -> None:
                try:
                    async def notify_channel(msg: str) -> None:
                        await self.slack.post_message(channel=target_channel, text=msg)

                    async def respond(msg: str) -> None:
                        await self.slack.post_message(channel=target_channel, text=msg)

                    async def notify_channel_msg(msg: dict) -> None:
                        await self.slack.post_message(
                            channel=target_channel, blocks=msg["blocks"],
                            text=msg.get("text", ""))

                    ctx = CommandContext(
                        user_id=user_id,
                        user_name=user_name,
                        channel_id=target_channel,
                        raw_text="",
                        subcommand="outreach",
                        arguments="",
                        platform="slack",
                        respond=respond,
                        metadata={},
                        notify_channel=notify_channel,
                        notify_channel_msg=notify_channel_msg,
                    )
```
(Leave the `await self.router.run_panel_outreach(...)` call and the surrounding task-spawn lines 785–797 unchanged.)

- [ ] **Step: run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py -v`

- [ ] **Step: commit.**
```bash
git add webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_slack_recruiting.py
git commit -m "feat(slack-recruiting): route Find Jobs entry + wire review poster on outreach ctx

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.6 — `slack_interactions`: route the review block actions `aiuiout:sel|send|refresh:*` (review-capable ctx)

`sel` parses `selected_options` → `run_outreach_select(ctx, task_id, selected_ids)`; `refresh` → `run_outreach_select(ctx, task_id, None)`; `send` → `run_outreach_send(ctx, task_id)`. The ctx exposes `notify_channel_msg` (Block Kit post) + `edit_message` (replace-in-place via the block action's `response_url`). Role/location/direction are resolved inside the router methods from the tasks response (Phase 2), so routing passes none.

> **Manual integration note:** mocks below verify dispatch + ctx shape. The actual `post_to_response_url(replace_original=True, blocks=...)` re-render and the ~30-min/5-use response_url TTL are verified manually e2e.

- [ ] **Step: write the failing test.** Append to `webhook-handler/tests/test_slack_recruiting.py`:
```python
# --- Phase 3.6: review block-action routing ---

@pytest.mark.asyncio
async def test_review_select_dispatches_and_wires_ctx():
    calls = []
    router = MagicMock()
    async def fake(ctx, task_id, selected_ids):
        calls.append((task_id, selected_ids, ctx.platform,
                      ctx.notify_channel_msg, ctx.edit_message))
    router.run_outreach_select = fake
    h = _handler(router)
    payload = {"type": "block_actions", "user": {"id": "u"},
               "channel": {"id": "c"}, "response_url": "https://hook",
               "actions": [{"action_id": "aiuiout:sel:t1",
                            "selected_options": [{"value": "c0"}, {"value": "c1"}]}]}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls, "run_outreach_select not dispatched"
    task_id, selected_ids, platform, ncm, em = calls[0]
    assert task_id == "t1" and selected_ids == ["c0", "c1"]
    assert platform == "slack" and ncm is not None and em is not None


@pytest.mark.asyncio
async def test_review_refresh_passes_none():
    calls = []
    router = MagicMock()
    async def fake(ctx, task_id, selected_ids):
        calls.append((task_id, selected_ids))
    router.run_outreach_select = fake
    h = _handler(router)
    payload = {"type": "block_actions", "user": {"id": "u"},
               "channel": {"id": "c"}, "response_url": "https://hook",
               "actions": [{"action_id": "aiuiout:refresh:t1"}]}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls == [("t1", None)]


@pytest.mark.asyncio
async def test_review_send_dispatches():
    calls = []
    router = MagicMock()
    async def fake(ctx, task_id):
        calls.append((task_id, ctx.edit_message))
    router.run_outreach_send = fake
    h = _handler(router)
    payload = {"type": "block_actions", "user": {"id": "u"},
               "channel": {"id": "c"}, "response_url": "https://hook",
               "actions": [{"action_id": "aiuiout:send:t1"}]}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls and calls[0][0] == "t1" and calls[0][1] is not None
```

- [ ] **Step: run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py -v` → the three new tests fail (`assert calls` — actions fall through to the unknown-action no-op).

- [ ] **Step: implement (routing + ctx helpers).** In `webhook-handler/handlers/slack_interactions.py`, insert the review block-action routes right after the reverse-button block added in Task 3.5 (before the final `logger.info(f"Ignoring unknown Slack action_id: {action_id}")` at line 350):
```python
        # ----- Recruiting review interactions (aiuiout:sel|send|refresh:<task_id>) -----
        if action_id.startswith(srr.SEL_PREFIX):
            task_id = action_id[len(srr.SEL_PREFIX):]
            selected = [o.get("value")
                        for o in (actions[0].get("selected_options") or [])]
            self._spawn_review(payload, "run_outreach_select", task_id, selected)
            return {}
        if action_id.startswith(srr.REFRESH_PREFIX):
            task_id = action_id[len(srr.REFRESH_PREFIX):]
            self._spawn_review(payload, "run_outreach_select", task_id, None)
            return {}
        if action_id.startswith(srr.SEND_PREFIX):
            task_id = action_id[len(srr.SEND_PREFIX):]
            self._spawn_review(payload, "run_outreach_send", task_id)
            return {}
```
Add the ctx + spawn helpers next to `_slack_ctx` (after line 462, before `_email_for`):
```python
    def _review_ctx(
        self, *, user_id: str, user_name: str, channel_id: str, response_url: str,
    ) -> CommandContext:
        """A CommandContext wired for Slack outreach-review interactions:
          - notify_channel_msg posts the Block Kit review message (bot token),
          - edit_message replaces the review message in place via response_url
            (block actions carry one; the editmodal path passes the stashed one),
          - respond posts the reason/error privately via the response_url.
        Email resolves from the Slack user id inside the router methods
        (run_outreach_* call _resolve_email_for_ctx)."""

        async def respond(msg: str) -> None:
            if response_url:
                await self.slack.post_to_response_url(response_url, msg)
            elif channel_id:
                await self.slack.post_message(channel=channel_id, text=msg)

        async def notify_channel(msg: str) -> None:
            await respond(msg)

        async def notify_channel_msg(msg: dict) -> None:
            await self.slack.post_message(
                channel=channel_id, blocks=msg["blocks"], text=msg.get("text", ""))

        async def edit_message(msg: dict) -> None:
            if response_url:
                # Router warning nudges (e.g. "Pick at least one company first.",
                # invalid-email notice) arrive as msg["content"]; Slack only renders
                # text/blocks, so surface content into the message text or the nudge
                # is lost (parity with Discord, which shows it as the content).
                text = msg.get("content") or msg.get("text", "")
                await self.slack.post_to_response_url(
                    response_url, text,
                    response_type="in_channel", replace_original=True,
                    blocks=msg["blocks"])

        return CommandContext(
            user_id=user_id, user_name=user_name, channel_id=channel_id,
            raw_text="outreach", subcommand="outreach", arguments="",
            platform="slack", respond=respond, metadata={},
            notify_channel=notify_channel,
            notify_channel_msg=notify_channel_msg,
            edit_message=edit_message,
        )

    def _spawn_review(
        self, payload: dict[str, Any], method_name: str, *args: Any,
    ) -> None:
        """Build a review ctx from a block-action payload and run the named
        router method (run_outreach_select / run_outreach_send) in the
        background. response_url comes from the block action."""
        user = payload.get("user", {})
        ctx = self._review_ctx(
            user_id=user.get("id", ""),
            user_name=user.get("username") or user.get("name", "user"),
            channel_id=(payload.get("channel") or {}).get("id", ""),
            response_url=payload.get("response_url", ""),
        )
        method = getattr(self.router, method_name)
        task = asyncio.create_task(method(ctx, *args))
        self.router._background_tasks.add(task)
        task.add_done_callback(self.router._background_tasks.discard)
```

- [ ] **Step: run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py -v`

- [ ] **Step: commit.**
```bash
git add webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_slack_recruiting.py
git commit -m "feat(slack-recruiting): route select/send/refresh review block actions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.7 — `slack_interactions`: edit-select opens the prefilled edit modal (stash `response_url`) + `aiuiout:editmodal:*` submit → `run_outreach_edit_submit`

The `aiuiout:edit:*` block action carries the chosen candidate id in `selected_option.value` and a `response_url`. We fetch the candidate, open `build_edit_modal_view(task_id, cand, response_url)` with the block action's `trigger_id`, stashing `response_url` in `private_metadata`. On `view_submission` we read it back (`response_url_from_meta`), build a `_review_ctx` whose `edit_message` uses it, and dispatch `run_outreach_edit_submit`.

> **Manual integration note:** there is **one** await (the candidate fetch) before `views.open`, which risks the ~3s `trigger_id` TTL under prod latency — acceptable and called out in the spec; verified manually e2e. The unit tests mock the fetch and `open_modal`.

- [ ] **Step: write the failing test.** Append to `webhook-handler/tests/test_slack_recruiting.py`:
```python
# --- Phase 3.7: edit-modal open + submit routing ---

@pytest.mark.asyncio
async def test_edit_select_opens_modal_with_response_url():
    import json
    router = MagicMock()
    router._tasks_client = MagicMock()
    router._tasks_client.get_outreach_candidates = AsyncMock(return_value={
        "candidates": [{"id": "c0", "name": "Alice", "email": "a@x.com",
                        "subject": "S", "body": "B"}]})
    h = _handler(router)
    # _open_outreach_edit calls self._email_for(user_id) (slack_interactions.py:464),
    # NOT router._resolve_email_for_ctx — stub the method actually invoked.
    h._email_for = AsyncMock(return_value="e@x.com")
    payload = {"type": "block_actions", "trigger_id": "tg",
               "user": {"id": "u"}, "channel": {"id": "c"},
               "response_url": "https://hook",
               "actions": [{"action_id": "aiuiout:edit:t1",
                            "selected_option": {"value": "c0"}}]}
    await h.handle_interaction(payload)
    for _ in range(8):
        await asyncio.sleep(0)
    h.slack.open_modal.assert_awaited_once()
    _, view = h.slack.open_modal.await_args.args
    assert view["callback_id"] == "aiuiout:editmodal:t1:c0"
    assert json.loads(view["private_metadata"])["response_url"] == "https://hook"


@pytest.mark.asyncio
async def test_editmodal_submit_dispatches_with_response_url():
    import json
    calls = []
    router = MagicMock()
    async def fake(ctx, task_id, cid, email_val, subject, body):
        calls.append((task_id, cid, email_val, subject, body, ctx.edit_message))
    router.run_outreach_edit_submit = fake
    h = _handler(router)
    meta = json.dumps({"response_url": "https://hook", "task_id": "t1", "cid": "c0"})
    view = {"callback_id": "aiuiout:editmodal:t1:c0", "private_metadata": meta,
            "state": {"values": srr.sample_edit_state("a@x.com", "S2", "B2")}}
    payload = {"type": "view_submission", "user": {"id": "u"}, "view": view}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls, "run_outreach_edit_submit not dispatched"
    task_id, cid, email_val, subject, body, em = calls[0]
    assert (task_id, cid, email_val, subject, body) == ("t1", "c0", "a@x.com", "S2", "B2")
    assert em is not None
```
At the top of `webhook-handler/tests/test_slack_recruiting.py`, make sure the review module is imported (add if missing, next to the existing `from handlers import slack_recruiting_panel as srp`):
```python
from handlers import slack_recruiting_review as srr
```

- [ ] **Step: run it, expect FAIL.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py -v` → both new tests fail (edit action no-ops; editmodal callback unknown).

- [ ] **Step: implement (edit-open block action).** In `_handle_block_actions`, add the edit-select route right after the `SEND_PREFIX` block from Task 3.6 (still before the final unknown-action log at line 350):
```python
        if action_id.startswith(srr.EDIT_PREFIX):
            task_id = action_id[len(srr.EDIT_PREFIX):]
            cid = (actions[0].get("selected_option") or {}).get("value", "")
            response_url = payload.get("response_url", "")
            task = asyncio.create_task(
                self._open_outreach_edit(
                    trigger_id, payload, task_id, cid, response_url))
            self.router._background_tasks.add(task)
            task.add_done_callback(self.router._background_tasks.discard)
            return {}
```
Add the opener method next to `_review_ctx`/`_spawn_review` (Task 3.6):
```python
    async def _open_outreach_edit(
        self, trigger_id: str, payload: dict[str, Any],
        task_id: str, cid: str, response_url: str,
    ) -> None:
        """Edit dropdown picked a candidate → fetch it and open the prefilled
        edit modal, stashing the block action's response_url in private_metadata
        so the view_submission can re-render the review message in place.

        NOTE: one await (the candidate fetch) precedes views.open — under prod
        latency the ~3s trigger_id TTL can lapse; acceptable per the spec and
        verified manually e2e."""
        user_id = (payload.get("user") or {}).get("id", "")
        try:
            email = await self._email_for(user_id)
            if not email:
                return
            st = await self.router._tasks_client.get_outreach_candidates(email, task_id)
            cand = next(
                (c for c in st.get("candidates", []) if c.get("id") == cid), None)
            if cand is None:
                return
            await self.slack.open_modal(
                trigger_id, srr.build_edit_modal_view(task_id, cand, response_url))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Slack outreach edit-open failed task=%s cid=%s: %s",
                task_id, cid, exc,
            )
```

- [ ] **Step: implement (editmodal submit).** In `_handle_view_submission`, insert this block after the reverse-modal block from Task 3.5 (still before the final `logger.info(... unknown callback_id ...)` at line 799). It reuses `user_id`/`user_name`/`callback_id` already in scope and the `_review_ctx` helper:
```python
        # ----- Recruiting edit modal submit (aiuiout:editmodal:<task_id>:<cid>) -----
        if callback_id.startswith(srr.EDITMODAL_PREFIX):
            task_id, cid = srr.ids_from_editmodal(callback_id)
            email_val, subject, body = srr.edit_fields_from_view(view)
            response_url = srr.response_url_from_meta(
                view.get("private_metadata", ""))
            ctx = self._review_ctx(
                user_id=user_id, user_name=user_name,
                channel_id="", response_url=response_url)
            task = asyncio.create_task(
                self.router.run_outreach_edit_submit(
                    ctx, task_id, cid, email_val, subject, body))
            self.router._background_tasks.add(task)
            task.add_done_callback(self.router._background_tasks.discard)
            return {}
```

- [ ] **Step: run test, expect PASS.** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py tests/test_slack_recruiting_review.py -v`

- [ ] **Step: commit.**
```bash
git add webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_slack_recruiting.py
git commit -m "feat(slack-recruiting): edit-modal open (stash response_url) + submit routing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.8 — Flip Slack hire (`run_panel_outreach`) to review-before-send

Today `run_panel_outreach` is manual only on Discord (`commands.py:2347` `manual = ctx.platform == "discord"`), so Slack "Find Engineers" auto-sends. Spec §7 and the Definition of Done require Slack hire to review-before-send now that the Slack review layer exists. The Slack hire entry ctx already carries `notify_channel_msg` (Task 3.5), and `_watch_outreach_review` is builder-by-platform and defaults to `direction="hire"` (Task 2.5), so this is a one-line behavior flip plus a guard test.

**Files:**
- Modify: `webhook-handler/handlers/commands.py:2347`
- Test: `webhook-handler/tests/test_run_panel_outreach.py`

- [ ] **Step 1: write the failing test** — assert a Slack ctx routes hire through manual review (`mode="manual"`), not auto-send. Read `tests/test_run_panel_outreach.py` first and match its actual `_ctx`/`_router`/email-mock helpers (adapt names if they differ).

```python
def test_slack_hire_uses_manual_review(monkeypatch):
    # Slack "Find Engineers" must now post a review (mode="manual"), not auto-send.
    router = _router()
    captured = {}

    async def fake_start_outreach(email, payload):
        captured["mode"] = payload["mode"]
        return {"task_id": "t-slack-hire"}

    router._tasks_client.start_outreach = fake_start_outreach
    monkeypatch.setattr(router, "_resolve_email_for_ctx",
                        _async_return("seeker@example.com"))

    ctx = _ctx(platform="slack")           # notify_channel set; edit_message None
    asyncio.run(router.run_panel_outreach(ctx, "Python", "Berlin", "Hiring a dev", 5))

    assert captured["mode"] == "manual"
```

- [ ] **Step 2: run it, expect FAIL.**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_run_panel_outreach.py::test_slack_hire_uses_manual_review -v`
Expected: FAIL — Slack currently sends `mode="auto"`.

- [ ] **Step 3: implement the flip.** In `webhook-handler/handlers/commands.py`, in `run_panel_outreach`, replace line 2347:

```python
        manual = ctx.platform == "discord"
```
with:
```python
        # Both Discord and Slack now review-before-send (the Slack review layer
        # exists as of this feature). Reverse always uses run_panel_reverse.
        manual = True
```
No other change is needed: the existing `"mode": "manual" if manual else "auto"`, the ACK-text branch, and the `_watch_outreach_review` vs `_watch_outreach` spawn all key off `manual`, so Slack now posts the review. (`_watch_outreach` stays defined but is no longer reached from the panel.)

- [ ] **Step 4: run tests, expect PASS.**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_run_panel_outreach.py -v`
Expected: PASS. Adjust any existing test that asserted Slack auto-send.

- [ ] **Step 5: commit.**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_run_panel_outreach.py
git commit -m "feat(recruiting): Slack hire also reviews before send" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.9 — Full Slack recruiting test sweep + manual e2e checklist

- [ ] **Step: run the full Slack recruiting suite, expect PASS.**
```bash
cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_panel.py tests/test_recruiting_review.py tests/test_slack_recruiting.py tests/test_slack_recruiting_review.py -v
```
Expected: all green (Discord builders + Slack panel/routing + Slack review builders).

- [ ] **Step: manual integration checklist (not automatable — call out in the PR).** In a live Slack `#recruiting`:
  - Find Jobs (plain-text button) → reverse modal opens with seeker-oriented labels.
  - Submit → review message posts as Block Kit with company copy (`labels_for("reverse")`), multi-select shows only emailable companies.
  - Change the multi-select → message replaces in place (response_url edit).
  - Edit one → modal prefilled; Save → review replaces in place.
  - Send 1 → locked sent-summary; confirm the n8n execution, the Google Sheet row, and `Reply-To = seeker` on the received email.
  - Repeat once on the **hire** path (Find Engineers) to confirm Slack now reviews before sending (the intended §7 behavior change) and uses the unchanged hire copy.

- [ ] **Step: commit (if the run surfaced any fixes; otherwise skip).**
```bash
git add -A
git commit -m "test(slack-recruiting): full review-layer suite green

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

**Cross-references / load-bearing facts verified against current code:**
- `slack_recruiting_panel.py:25-26` constants, `:41-64` `build_recruiting_blocks`, `:67-145` `build_outreach_view` (block ids `out_role`/`out_location`/`out_jobdesc`/`out_count`), `:148-165` `outreach_fields_from_view`, `:168-181` `sample_state`.
- `slack_interactions.py:71` `import srp`, `:128-351` `_handle_block_actions` (OUT_FIND at `:346-348`, response_url usage at `:303`/`:338`), `:447-462` `_slack_ctx`, `:538-800` `_handle_view_submission` (hire outreach modal ctx at `:760-797`).
- `clients/slack.py:58-111` `post_message(..., blocks=)`, `:140-163` `open_modal`, `:232-275` `post_to_response_url(replace_original, blocks)` — confirmed **no** `chat.update` (edit is response_url-based).
- `commands.py:43-78` `CommandContext` (has `notify_channel_msg`, `edit_message`, `platform`), `:1927-1942` `_resolve_email_for_ctx` (Slack reads profile email), `:2413-2461` `_watch_outreach_review` (posts via `notify_channel_msg`), `:2463-2549` the three router methods.
- `recruiting_review.py:26-110` Discord builders being mirrored (signature, id scheme, status icons, `ids_from_editmodal` rpartition).
- `discord_commands.py:464-512` confirms the edit-open pattern (fetch candidates → find by id → open modal) and that the router methods are called with trailing `"",""` (Phase 2 makes role/location/direction resolve from the response instead).
- Slack Block Kit constraints honored: `multi_static_select`/`static_select` require ≥1 option (guarded), `initial_value=""` is rejected (omitted), placeholder ≤150, option text ≤75, section text <3000.

---

## Phase 4 — n8n `Reply-To` (manual, live Hostinger UI — NOT a code task)

> The production workflow lives in the **Hostinger** n8n (`https://n8n.srv1041674.hstgr.cloud`), not in this repo. Editing `n8n-workflows/recruiting-outreach.json` changes nothing in production — treat it as docs only.

- [ ] **Step: open the workflow.** Log into the Hostinger n8n and open **Recruiting Outreach** (`recruiting-outreach` webhook).
- [ ] **Step: make `reply_to` reach the Gmail node.** The webhook payload now carries a top-level `reply_to`. The per-item "Dedupe and Prepare" Code node today maps only `date,name,github_url,email,subject,body,status,job_title` — so either (a) add `reply_to: items[0].json.body.reply_to` (or the equivalent per-item) to that node's output, **or** (b) in the Gmail node reference `{{ $('Webhook').first().json.body.reply_to }}` directly (simplest, since `reply_to` is one batch-level value).
- [ ] **Step: set Reply-To on the Gmail node.** In the Gmail "Send" node → **Options → Reply To**, set it to the `reply_to` value from the step above. Leave it blank-safe: if `reply_to` is empty (legacy hire callers that don't send it), the node must still send (no Reply-To header).
- [ ] **Step: save / activate** the workflow.
- [ ] **Step (optional, docs):** mirror the change into `n8n-workflows/recruiting-outreach.json` for documentation and commit it, clearly noting it is not the deployed copy.
- [ ] **Step: verify** during the Phase 5 e2e that the received application email has `Reply-To` = the seeker's address.

---

## Phase 5 — Deploy & verify

> Per `CLAUDE.md`: no git on the server; deploy by scp + `docker compose ... up -d --build <svc>`. **Before overwriting any server file, drift-check** (CRLF-normalized sha256 vs the known git ancestor) so VPS-only work isn't clobbered. **Never** touch/commit `.env`. **Never** deploy local `mcp-servers/tasks/templates.py` (server copy is ahead — not touched by this feature anyway).

### 5a. Backend (tasks service)
- [ ] **Step: deploy changed tasks files.** Changed: `mcp-servers/tasks/outreach.py`, `mcp-servers/tasks/routes_outreach.py`. The orchestrator (`ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh`) watches `mcp-servers/` — use it if rsync is available; otherwise scp each changed file individually (`scp -r` silently skips files — never use it) and rebuild:
  ```bash
  scp mcp-servers/tasks/outreach.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/outreach.py
  scp mcp-servers/tasks/routes_outreach.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/routes_outreach.py
  ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
  ```
- [ ] **Step: smoke the tasks service.** `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz` → expect 200. Update `.deploy-state` SHA if deployed manually.

### 5b. Discord bot (webhook-handler — NOT covered by the orchestrator)
- [ ] **Step: drift-check then scp each changed/created webhook file individually** to `/root/proxy-server/webhook-handler/...`: `handlers/recruiting_labels.py` (new), `handlers/recruiting_panel.py`, `handlers/recruiting_review.py`, `handlers/discord_commands.py`, `handlers/commands.py`, `handlers/slack_recruiting_panel.py`, `handlers/slack_recruiting_review.py` (new), `handlers/slack_interactions.py`, `clients/tasks.py`.
- [ ] **Step: rebuild.** `ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"`.
- [ ] **Step: verify Up.** `docker compose ... ps webhook-handler` shows `Up`. Tail logs for a clean boot.

### 5c. Live end-to-end (both platforms)
- [ ] **Step: Discord e2e** in `#recruiting`: **Find Jobs** → fill the reverse modal → review list shows **companies** with company copy → edit one application → **Send** 1 → message locks to a sent summary + sheet link.
- [ ] **Step: Slack e2e** in the recruiting channel: same flow through the new Block Kit review layer (select → edit modal → Send).
- [ ] **Step: verify the n8n execution + Google Sheet** recorded the send, and the received email has `Reply-To` = the seeker.

---

## Definition of done

- [ ] All new/changed pure tests pass via the webhook venv (Discord + Slack builders, `recruiting_labels`, reverse prompt/summary, the re-render direction regression on both a Discord and a Slack ctx).
- [ ] Reverse copy is correct on the **initial post and on every re-render** (select/edit/send), on both platforms.
- [ ] Slack review layer works end-to-end (post → select → edit modal via stashed `response_url` → send).
- [ ] Hire flow is unchanged on Discord; Slack hire is now also review-before-send (intended).
- [ ] `Reply-To` confirmed on a received application email.
- [ ] Deployed; `tasks/healthz` 200 and `webhook-handler` Up.
