# Outreach Find → Review → Edit → Send (Discord) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Discord `#recruiting` "Find Engineers" find + draft only, then let the user select / edit / add-email and send manually — no auto-email.

**Architecture:** Add a `mode="manual"` path to the existing `tasks` outreach flow that stores drafted candidates instead of posting to n8n. The Discord bot renders an interactive overview message (embed + multi-select + edit dropdown + Send button); selecting/editing PATCHes the stored candidates; Send pushes only the selected ones to the unchanged n8n webhook. Slack and n8n are untouched.

**Tech Stack:** Python, FastAPI, SQLAlchemy (tasks); FastAPI + Discord interactions (webhook-handler); pytest. Spec: `docs/superpowers/specs/2026-06-10-outreach-review-send-design.md`.

**Test runners (from the audit — obey exactly):**
- webhook-handler: `cd webhook-handler && ./.venv/Scripts/python.exe -m pytest <file> -v`
- tasks **pure** modules: run with the **webhook venv** — `cd mcp-servers/tasks && "../../webhook-handler/.venv/Scripts/python.exe" -m pytest <file> -v`. **NEVER run the full tasks suite** (its conftest TRUNCATEs the prod DB).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `mcp-servers/tasks/outreach.py` | modify | Pure review helpers: build review candidates, apply edit, set selection, sendable filter, summary |
| `mcp-servers/tasks/routes_outreach.py` | modify | `mode` flag; manual find stores candidates; `GET/PATCH /candidates`, `POST /send` |
| `webhook-handler/handlers/recruiting_review.py` | create | Pure builders: overview message, edit modal, `custom_id` schemes + parsers |
| `webhook-handler/handlers/recruiting_panel.py` | modify | Relabel count field → "How many to find" |
| `webhook-handler/clients/tasks.py` | modify | `get_outreach_candidates`, `patch_outreach_candidate`, `send_outreach` |
| `webhook-handler/handlers/commands.py` | modify | `run_panel_outreach` manual mode; render review; select/edit/send handlers |
| `webhook-handler/handlers/discord_commands.py` | modify | Route `aiuiout:sel|edit|editmodal|send|refresh` |
| `webhook-handler/tests/test_recruiting_review.py` | create | Unit tests for the pure builders |
| `mcp-servers/tasks/tests/test_outreach_review_logic.py` | create | Unit tests for the pure review helpers |

---

## Task 1: Backend pure review helpers (`outreach.py`)

**Files:**
- Modify: `mcp-servers/tasks/outreach.py` (append after `cap_and_dedupe`)
- Test: `mcp-servers/tasks/tests/test_outreach_review_logic.py`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_outreach_review_logic.py`:

```python
import outreach
from outreach import Candidate


def _found():
    return [
        Candidate(name="A", github_url="gh/a", email="a@x.com", subject="S", body="B"),
        Candidate(name="B", github_url="gh/b", email=None, subject="", body=""),
    ]


def test_build_review_candidates_ids_and_defaults():
    rc = outreach.build_review_candidates(_found())
    assert [c["id"] for c in rc] == ["c0", "c1"]
    assert rc[0]["selected"] is True and rc[0]["status"] == "draft"
    assert rc[1]["selected"] is False and rc[1]["status"] == "no_email"
    assert rc[1]["email"] == ""


def test_apply_edit_add_email_makes_sendable():
    rc = outreach.build_review_candidates(_found())
    rc = outreach.apply_candidate_edit(rc, "c1", email="b@x.com")
    assert rc[1]["status"] == "draft" and rc[1]["email"] == "b@x.com"
    rc = outreach.apply_candidate_edit(rc, "c1", selected=True)
    assert rc[1]["selected"] is True


def test_apply_edit_clearing_email_deselects():
    rc = outreach.build_review_candidates(_found())
    rc = outreach.apply_candidate_edit(rc, "c0", email="")
    assert rc[0]["status"] == "no_email" and rc[0]["selected"] is False


def test_set_selection_only_emailable():
    rc = outreach.build_review_candidates(_found())
    rc = outreach.set_selection(rc, ["c0", "c1"])  # c1 has no email
    assert rc[0]["selected"] is True and rc[1]["selected"] is False


def test_sendable_candidates_and_summary():
    rc = outreach.build_review_candidates(_found())
    send = outreach.sendable_candidates(rc)
    assert [c.name for c in send] == ["A"]
    assert outreach.review_summary(rc) == {"total": 2, "emailable": 1, "selected": 1}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd mcp-servers/tasks && "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_review_logic.py -v`
Expected: FAIL — `AttributeError: module 'outreach' has no attribute 'build_review_candidates'`.

- [ ] **Step 3: Implement the helpers**

Append to `mcp-servers/tasks/outreach.py`:

```python
def build_review_candidates(candidates: list[Candidate]) -> list[dict]:
    """Manual-review rows with stable ids. Selected defaults ON for emailable
    candidates, OFF for no-email ones."""
    rows = []
    for i, c in enumerate(candidates):
        email = (c.email or "").strip()
        rows.append({
            "id": f"c{i}", "name": c.name, "github_url": c.github_url,
            "email": email, "subject": c.subject, "body": c.body,
            "selected": bool(email),
            "status": "draft" if email else "no_email",
        })
    return rows


def apply_candidate_edit(candidates: list[dict], cid: str, *, email=None,
                         subject=None, body=None, selected=None) -> list[dict]:
    """Return a new list with row `cid` updated. Unknown cid -> unchanged.
    Email drives status: an email makes it draft/selectable; no email forces
    status=no_email and selected=False."""
    out = []
    for c in candidates:
        if c["id"] != cid:
            out.append(c)
            continue
        c = dict(c)
        if email is not None:
            c["email"] = email.strip()
        if subject is not None:
            c["subject"] = subject
        if body is not None:
            c["body"] = body
        has_email = bool(c["email"])
        c["status"] = "draft" if has_email else "no_email"
        if not has_email:
            c["selected"] = False
        elif selected is not None:
            c["selected"] = bool(selected)
        out.append(c)
    return out


def set_selection(candidates: list[dict], selected_ids: list[str]) -> list[dict]:
    """Overwrite selection with exactly `selected_ids` (only emailable rows can
    end up selected). Mirrors a Discord multi-select reporting the full set."""
    chosen = set(selected_ids)
    out = []
    for c in candidates:
        c = dict(c)
        c["selected"] = (c["id"] in chosen) and bool(c["email"])
        out.append(c)
    return out


def sendable_candidates(candidates: list[dict]) -> list[Candidate]:
    """Selected + has-email rows -> Candidate objects for n8n."""
    return [Candidate(name=c["name"], github_url=c["github_url"], email=c["email"],
                      subject=c["subject"], body=c["body"])
            for c in candidates if c.get("selected") and (c.get("email") or "").strip()]


def review_summary(candidates: list[dict]) -> dict:
    emailable = sum(1 for c in candidates if (c.get("email") or "").strip())
    selected = sum(1 for c in candidates
                   if c.get("selected") and (c.get("email") or "").strip())
    return {"total": len(candidates), "emailable": emailable, "selected": selected}
```

- [ ] **Step 4: Run the tests — verify pass**

Run: `cd mcp-servers/tasks && "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_review_logic.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/outreach.py mcp-servers/tasks/tests/test_outreach_review_logic.py
git commit -m "feat(outreach): pure review-state helpers (build/edit/select/sendable)"
```

---

## Task 2: Backend — `mode` flag + manual find storage (`routes_outreach.py`)

**Files:**
- Modify: `mcp-servers/tasks/routes_outreach.py`

No unit test (touches the agent + DB). Verified manually in Task 9.

- [ ] **Step 1: Add `mode` to the request model**

In `OutreachRequest` add the field:

```python
class OutreachRequest(BaseModel):
    role: str = ""
    location: str = ""
    jobdesc: str
    count: int = 10
    mode: str = "auto"   # "auto" = find+send (Slack/legacy); "manual" = find+store
```

- [ ] **Step 2: Thread `mode` into the run**

In `start_outreach`, pass `mode` to the background run:

```python
    asyncio.create_task(_run_outreach(task_id, exec_id, prompt,
                                      job_title=body.role, count=body.count,
                                      mode=body.mode))
```

- [ ] **Step 3: Branch `_run_outreach` on mode**

Replace the body of `_run_outreach` so manual mode stores candidates and skips n8n:

```python
async def _run_outreach(task_id, execution_id, prompt, *, job_title: str,
                        count: int, mode: str = "auto"):
    from routes_execution import _stream_claude  # LOCAL import
    try:
        raw_log = await _stream_claude(prompt, execution_id, task_id)
        if mode == "manual":
            summary = _process_outreach_find(raw_log, job_title=job_title, count=count)
        else:
            summary = await _process_outreach_result(raw_log, job_title=job_title, count=count)
        final_status = "completed" if summary["status"] in ("completed", "review") else "failed"
        async with session() as s:
            await s.execute(update(TaskExecution).where(TaskExecution.id == execution_id)
                            .values(status="succeeded" if final_status == "completed" else "failed"))
            await s.execute(update(TaskItem).where(TaskItem.id == task_id)
                            .values(status=final_status, result=json.dumps(summary)))
            await s.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("outreach run failed: %s", exc)
        async with session() as s:
            await s.execute(update(TaskItem).where(TaskItem.id == task_id).values(
                status="failed",
                result=json.dumps({"status": "failed", "text": f"Run error: {exc}"[:300]})))
            await s.commit()
```

- [ ] **Step 4: Add the manual find processor (pure-ish, no n8n)**

Add next to `_process_outreach_result`:

```python
def _process_outreach_find(raw_log: str, *, job_title: str, count: int) -> dict:
    """Manual mode: parse candidates, DON'T send. Store a review state."""
    outcome = parse_outcome(raw_log)
    if outcome.kind == "failed":
        return {"status": "failed", "found": 0, "text":
                (outcome.payload or "The search failed.").strip()[:500]}
    cand = outreach.extract_candidates(raw_log)
    if not cand.candidates:
        return {"status": "failed", "found": 0,
                "text": "I couldn't find engineers matching that — try a broader role."}
    batch = outreach.cap_and_dedupe(cand.candidates, count)
    return {"status": "review", "phase": "review", "job_title": job_title,
            "found": len(batch),
            "candidates": outreach.build_review_candidates(batch)}
```

- [ ] **Step 5: Make the status endpoint expose `review`**

In `get_outreach_status`, after loading `data`, return review state through the existing model by adding fields. Change `OutreachStatusResponse` to include candidates, and the return:

```python
class OutreachStatusResponse(BaseModel):
    status: str
    found: int = 0
    sent: int = 0
    saved: int = 0
    sheet_url: str = ""
    text: str = ""
    candidates: list[dict] = []
    job_title: str = ""
```

and at the end of `get_outreach_status`:

```python
    return OutreachStatusResponse(
        status=data.get("status", "failed"), found=data.get("found", 0),
        sent=data.get("sent", 0), saved=data.get("saved", 0),
        sheet_url=data.get("sheet_url", ""), text=data.get("text", ""),
        candidates=data.get("candidates", []), job_title=data.get("job_title", ""))
```

- [ ] **Step 6: Sanity-import check (no full suite)**

Run: `cd mcp-servers/tasks && "../../webhook-handler/.venv/Scripts/python.exe" -c "import ast; ast.parse(open('routes_outreach.py').read()); print('parse ok')"`
Expected: `parse ok`.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_outreach.py
git commit -m "feat(outreach): manual mode finds + stores candidates (no auto-send)"
```

---

## Task 3: Backend — review endpoints (`routes_outreach.py`)

**Files:**
- Modify: `mcp-servers/tasks/routes_outreach.py`

- [ ] **Step 1: Add a helper to load+save the review state**

```python
async def _load_review(task_id, user) -> tuple[object, dict]:
    """Return (item, data dict) for an OUTREACH task owned by user, else 404."""
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
    if item is None or item.assignee_email != user.email:
        raise HTTPException(status_code=404, detail="not found")
    try:
        data = json.loads(item.result or "{}")
    except ValueError:
        data = {}
    return item, data


async def _save_candidates(task_id, data: dict, candidates: list[dict]) -> None:
    data = {**data, "candidates": candidates}
    async with session() as s:
        await s.execute(update(TaskItem).where(TaskItem.id == task_id)
                        .values(result=json.dumps(data)))
        await s.commit()
```

- [ ] **Step 2: `GET /outreach/{id}/candidates`**

```python
@router.get("/outreach/{task_id}/candidates", response_model=OutreachStatusResponse)
async def get_outreach_candidates(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    item, data = await _load_review(task_id, user)
    if item.status == "running":
        return OutreachStatusResponse(status="running")
    return OutreachStatusResponse(
        status=data.get("status", "failed"), found=data.get("found", 0),
        text=data.get("text", ""), candidates=data.get("candidates", []),
        job_title=data.get("job_title", ""))
```

- [ ] **Step 3: `PATCH /outreach/{id}/candidates/{cid}`**

```python
class CandidatePatch(BaseModel):
    email: str | None = None
    subject: str | None = None
    body: str | None = None
    selected: bool | None = None
    selected_ids: list[str] | None = None   # set the whole selection at once


@router.patch("/outreach/{task_id}/candidates/{cid}", response_model=OutreachStatusResponse)
async def patch_outreach_candidate(task_id: uuid.UUID, cid: str, body: CandidatePatch,
                                   user: CurrentUser = Depends(current_user)):
    item, data = await _load_review(task_id, user)
    candidates = data.get("candidates", [])
    if body.selected_ids is not None:
        candidates = outreach.set_selection(candidates, body.selected_ids)
    else:
        candidates = outreach.apply_candidate_edit(
            candidates, cid, email=body.email, subject=body.subject,
            body=body.body, selected=body.selected)
    await _save_candidates(task_id, data, candidates)
    return OutreachStatusResponse(status="review", candidates=candidates,
                                  found=len(candidates), job_title=data.get("job_title", ""))
```

(For a whole-selection update the caller may use `cid="_"`.)

- [ ] **Step 4: `POST /outreach/{id}/send`**

```python
@router.post("/outreach/{task_id}/send", response_model=OutreachStatusResponse)
async def send_outreach(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    item, data = await _load_review(task_id, user)
    candidates = data.get("candidates", [])
    batch = outreach.sendable_candidates(candidates)
    if not batch:
        return OutreachStatusResponse(status="review", candidates=candidates,
                                      text="Pick at least one engineer with an email first.",
                                      job_title=data.get("job_title", ""))
    try:
        res = await outreach.post_outreach_to_n8n(data.get("job_title", ""), batch)
    except Exception as exc:  # noqa: BLE001
        logger.error("manual outreach send failed: %s", exc)
        return OutreachStatusResponse(status="review", candidates=candidates,
                                      text="Sending failed — try again.",
                                      job_title=data.get("job_title", ""))
    sent_emails = {c.email.strip().lower() for c in batch}
    for c in candidates:
        if (c.get("email") or "").strip().lower() in sent_emails:
            c["status"] = "sent"
            c["selected"] = False
    new_data = {**data, "phase": "sent", "candidates": candidates,
                "status": "completed",
                "sent": int(res.get("sent", len(batch))),
                "saved": int(res.get("saved", len(batch))),
                "sheet_url": res.get("sheet_url", ""),
                "text": outreach.format_outreach_summary(
                    data.get("found", len(candidates)),
                    int(res.get("sent", len(batch))),
                    int(res.get("saved", len(batch))), res.get("sheet_url", ""))}
    async with session() as s:
        await s.execute(update(TaskItem).where(TaskItem.id == task_id)
                        .values(result=json.dumps(new_data)))
        await s.commit()
    return OutreachStatusResponse(
        status="sent", candidates=candidates, sent=new_data["sent"],
        saved=new_data["saved"], sheet_url=new_data["sheet_url"], text=new_data["text"],
        job_title=data.get("job_title", ""))
```

- [ ] **Step 5: Parse check + commit**

Run: `cd mcp-servers/tasks && "../../webhook-handler/.venv/Scripts/python.exe" -c "import ast; ast.parse(open('routes_outreach.py').read()); print('parse ok')"`
Expected: `parse ok`.

```bash
git add mcp-servers/tasks/routes_outreach.py
git commit -m "feat(outreach): GET candidates, PATCH candidate, POST send endpoints"
```

---

## Task 4: webhook-handler pure builders (`recruiting_review.py`)

**Files:**
- Create: `webhook-handler/handlers/recruiting_review.py`
- Test: `webhook-handler/tests/test_recruiting_review.py`

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_recruiting_review.py`:

```python
from handlers import recruiting_review as rr

CANDS = [
    {"id": "c0", "name": "Alice", "github_url": "gh/a", "email": "a@x.com",
     "subject": "S0", "body": "B0", "selected": True, "status": "draft"},
    {"id": "c1", "name": "Bob", "github_url": "gh/b", "email": "",
     "subject": "", "body": "", "selected": False, "status": "no_email"},
]


def test_message_has_embed_and_three_rows():
    msg = rr.build_review_message("t1", CANDS, role="Python", location="Manila")
    assert "Found 2" in msg["embeds"][0]["title"]
    rows = msg["components"]
    assert len(rows) == 3
    # row0 = recipient multi-select with only emailable options
    sel = rows[0]["components"][0]
    assert sel["custom_id"] == "aiuiout:sel:t1"
    assert [o["value"] for o in sel["options"]] == ["c0"]
    assert sel["options"][0]["default"] is True
    # row1 = edit dropdown over ALL candidates
    edit = rows[1]["components"][0]
    assert edit["custom_id"] == "aiuiout:edit:t1"
    assert [o["value"] for o in edit["options"]] == ["c0", "c1"]
    # row2 = send + refresh, send shows selected count
    send = rows[2]["components"][0]
    assert send["custom_id"] == "aiuiout:send:t1"
    assert "(1)" in send["label"]


def test_message_with_no_emailable_omits_recipient_select():
    msg = rr.build_review_message("t1", [CANDS[1]], role="X", location="")
    sel_ids = [c["components"][0].get("custom_id", "") for c in msg["components"]]
    assert "aiuiout:sel:t1" not in sel_ids  # no recipient select when nobody emailable


def test_edit_modal_prefilled_and_parse():
    modal = rr.build_edit_modal("t1", CANDS[0])
    assert modal["custom_id"] == "aiuiout:editmodal:t1:c0"
    vals = {r["components"][0]["custom_id"]: r["components"][0].get("value")
            for r in modal["components"]}
    assert vals["email"] == "a@x.com" and vals["subject"] == "S0" and vals["body"] == "B0"
    assert rr.ids_from_editmodal("aiuiout:editmodal:t1:c0") == ("t1", "c0")


def test_id_parsers():
    assert rr.is_out_sel("aiuiout:sel:t1") and rr.task_id_from_sel("aiuiout:sel:t1") == "t1"
    assert rr.is_out_edit("aiuiout:edit:t1") and rr.task_id_from_edit("aiuiout:edit:t1") == "t1"
    assert rr.is_out_send("aiuiout:send:t1") and rr.task_id_from_send("aiuiout:send:t1") == "t1"
    assert rr.is_out_refresh("aiuiout:refresh:t1")
    assert rr.is_out_editmodal("aiuiout:editmodal:t1:c0")
```

- [ ] **Step 2: Run it — verify fail**

Run: `cd webhook-handler && ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_review.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handlers.recruiting_review'`.

- [ ] **Step 3: Implement the builders**

Create `webhook-handler/handlers/recruiting_review.py`:

```python
"""Pure builders for the Discord recruiting review/select/edit/send UI.

No I/O. custom_id scheme: aiuiout:<action>:<task_id>[:<cid>]. task_id is a UUID
(no colons) so editmodal ids rsplit cleanly into (task_id, cid). Unit-tested in
tests/test_recruiting_review.py.
"""
from __future__ import annotations

from handlers.app_builder_panel import (
    ACTION_ROW, BUTTON, SELECT_MENU, TEXT_INPUT, TEXT_SHORT, TEXT_PARAGRAPH,
    STYLE_SUCCESS, STYLE_SECONDARY, ROBOTIC_CYAN, _button,
)

SEL_PREFIX = "aiuiout:sel:"
EDIT_PREFIX = "aiuiout:edit:"
SEND_PREFIX = "aiuiout:send:"
REFRESH_PREFIX = "aiuiout:refresh:"
EDITMODAL_PREFIX = "aiuiout:editmodal:"
_MAX = 25


def _emailable(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if (c.get("email") or "").strip()]


def build_review_message(task_id: str, candidates: list[dict], *,
                         role: str = "", location: str = "") -> dict:
    """Overview message: embed list + recipient multi-select (emailable only) +
    edit dropdown (all) + Send/Refresh buttons."""
    lines = []
    for c in candidates:
        email = (c.get("email") or "").strip()
        icon = "✅" if (c.get("selected") and email) else ("⚠️" if not email else "⬜")
        lines.append(f"{icon} **{c.get('name', '?')}** — {email or '(no email)'}")
    where = role + (f" · {location}" if location else "")
    embed = {
        "title": f"🔍 Found {len(candidates)} · {where}"[:256],
        "color": ROBOTIC_CYAN,
        "description": ("\n".join(lines) or "No engineers found.")[:4000],
        "footer": {"text": "Pick who to email · ✏️ edit/add-email · then Send"},
    }
    rows: list[dict] = []
    emailable = _emailable(candidates)[:_MAX]
    if emailable:
        rows.append({"type": ACTION_ROW, "components": [{
            "type": SELECT_MENU, "custom_id": f"{SEL_PREFIX}{task_id}",
            "placeholder": "Select who to email…",
            "min_values": 0, "max_values": len(emailable),
            "options": [{
                "label": (c.get("name") or c["id"])[:100], "value": c["id"],
                "description": c["email"][:100], "default": bool(c.get("selected")),
            } for c in emailable],
        }]})
    rows.append({"type": ACTION_ROW, "components": [{
        "type": SELECT_MENU, "custom_id": f"{EDIT_PREFIX}{task_id}",
        "placeholder": "Edit / add email for one…",
        "min_values": 1, "max_values": 1,
        "options": [{
            "label": (c.get("name") or c["id"])[:100], "value": c["id"],
            "description": ((c.get("email") or "").strip() or "no email")[:100],
        } for c in candidates[:_MAX]],
    }]})
    selected = sum(1 for c in candidates if c.get("selected") and (c.get("email") or "").strip())
    rows.append({"type": ACTION_ROW, "components": [
        _button(f"📧 Send to selected ({selected})", f"{SEND_PREFIX}{task_id}", STYLE_SUCCESS),
        _button("♻ Refresh", f"{REFRESH_PREFIX}{task_id}", STYLE_SECONDARY),
    ]})
    return {"embeds": [embed], "components": rows}


def build_sent_message(text: str, sheet_url: str = "") -> dict:
    """Final locked message after Send (no components)."""
    body = f"✅ {text}" + (f"\n👉 {sheet_url}" if sheet_url else "")
    return {"content": body[:2000], "embeds": [], "components": []}


def build_edit_modal(task_id: str, candidate: dict) -> dict:
    """Edit popup prefilled with email/subject/body for one candidate."""
    def _ti(cid, label, style, maxlen, value):
        return {"type": ACTION_ROW, "components": [{
            "type": TEXT_INPUT, "custom_id": cid, "label": label, "style": style,
            "required": False, "max_length": maxlen, "value": (value or "")[:maxlen],
        }]}
    return {
        "title": f"Edit: {candidate.get('name', '')}"[:45],
        "custom_id": f"{EDITMODAL_PREFIX}{task_id}:{candidate['id']}",
        "components": [
            _ti("email", "Email (blank = don't email)", TEXT_SHORT, 200, candidate.get("email")),
            _ti("subject", "Subject", TEXT_SHORT, 200, candidate.get("subject")),
            _ti("body", "Message", TEXT_PARAGRAPH, 4000, candidate.get("body")),
        ],
    }


def is_out_sel(cid: str) -> bool: return cid.startswith(SEL_PREFIX)
def is_out_edit(cid: str) -> bool: return cid.startswith(EDIT_PREFIX)
def is_out_send(cid: str) -> bool: return cid.startswith(SEND_PREFIX)
def is_out_refresh(cid: str) -> bool: return cid.startswith(REFRESH_PREFIX)
def is_out_editmodal(cid: str) -> bool: return cid.startswith(EDITMODAL_PREFIX)
def task_id_from_sel(cid: str) -> str: return cid[len(SEL_PREFIX):]
def task_id_from_edit(cid: str) -> str: return cid[len(EDIT_PREFIX):]
def task_id_from_send(cid: str) -> str: return cid[len(SEND_PREFIX):]
def task_id_from_refresh(cid: str) -> str: return cid[len(REFRESH_PREFIX):]


def ids_from_editmodal(cid: str) -> tuple[str, str]:
    """aiuiout:editmodal:<task_id>:<cid> -> (task_id, cid)."""
    rest = cid[len(EDITMODAL_PREFIX):]
    task_id, _, candidate_id = rest.rpartition(":")
    return task_id, candidate_id
```

- [ ] **Step 4: Run the tests — verify pass**

Run: `cd webhook-handler && ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_review.py -v`
Expected: PASS (4 passed). If `_button`/`SELECT_MENU` import fails, confirm names against `handlers/app_builder_panel.py` (they exist there).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/recruiting_review.py webhook-handler/tests/test_recruiting_review.py
git commit -m "feat(recruiting): pure builders for review/select/edit/send UI"
```

---

## Task 5: Relabel the modal count field (`recruiting_panel.py`)

**Files:**
- Modify: `webhook-handler/handlers/recruiting_panel.py:81-82`
- Test: `webhook-handler/tests/test_recruiting_panel.py` (if it asserts the label)

- [ ] **Step 1: Change the label + placeholder**

In `build_outreach_modal`, replace the count field line:

```python
            _ti(OUT_COUNT_INPUT, "How many to find (max 25)", TEXT_SHORT, False, 3,
                "10"),
```

- [ ] **Step 2: Update the panel copy (no longer "email in one click")**

Replace `PANEL_CONTENT` body sentence:

```python
PANEL_CONTENT = (
    "\U0001f3af **Recruiting Outreach**\n"
    "Find software engineers, then review the list and choose who to email. Hit "
    "**\U0001f50d Find Engineers**, describe the role, and I'll search GitHub and "
    "show you everyone I find — you pick who gets a message."
)
```

- [ ] **Step 3: Run the panel tests**

Run: `cd webhook-handler && ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_panel.py -v`
Expected: PASS. If a test asserts the old label/copy, update that test to the new text.

- [ ] **Step 4: Commit**

```bash
git add webhook-handler/handlers/recruiting_panel.py webhook-handler/tests/test_recruiting_panel.py
git commit -m "feat(recruiting): modal/panel copy for find-then-choose flow"
```

---

## Task 6: Tasks client methods (`clients/tasks.py`)

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (after `get_outreach_status`, ~line 240)

No unit test (HTTP client). Verified in Task 9. Mirror the existing `start_outreach`/`get_outreach_status` which call `self._request(METHOD, PATH, user_email, json=...)`.

- [ ] **Step 1: Add the three methods**

```python
    async def get_outreach_candidates(self, user_email: str, task_id) -> dict:
        resp = await self._request("GET", f"/outreach/{task_id}/candidates", user_email)
        return resp

    async def patch_outreach_candidate(self, user_email: str, task_id, cid: str,
                                       payload: dict) -> dict:
        resp = await self._request("PATCH", f"/outreach/{task_id}/candidates/{cid}",
                                   user_email, json=payload)
        return resp

    async def send_outreach(self, user_email: str, task_id) -> dict:
        resp = await self._request("POST", f"/outreach/{task_id}/send", user_email, json={})
        return resp
```

- [ ] **Step 2: Confirm `start_outreach` passes `mode`**

`run_panel_outreach` (Task 7) sends `mode` inside the payload dict, so no change here is needed — verify `start_outreach` forwards the whole dict as JSON (it does: `json=payload`).

- [ ] **Step 3: Parse check + commit**

Run: `cd webhook-handler && ./.venv/Scripts/python.exe -c "import ast; ast.parse(open('clients/tasks.py').read()); print('ok')"`
Expected: `ok`.

```bash
git add webhook-handler/clients/tasks.py
git commit -m "feat(recruiting): tasks-client methods for candidates/patch/send"
```

---

## Task 7: Discord handlers — manual run, render, select/edit/send (`commands.py`)

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (`run_panel_outreach` ~2157; add new methods after `_watch_outreach`)

No unit test (orchestration/HTTP). Verified in Task 9.

- [ ] **Step 1: Switch `run_panel_outreach` to manual + render review**

Replace the `start_outreach` call args and the watcher in `run_panel_outreach`:

```python
        try:
            result = await self._tasks_client.start_outreach(email, {
                "role": role, "location": location, "jobdesc": jobdesc,
                "count": count, "mode": "manual"})
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        task_id = result["task_id"]
        where = f"{role}" + (f" · {location}" if location else "")
        await ctx.respond(
            f"\U0001f50e Searching GitHub for **{where}** … I'll post the list "
            "here to review when it's ready (usually a minute or two).")
        if ctx.notify_channel is not None:
            w = asyncio.create_task(self._watch_outreach_review(ctx, email, task_id, role, location))
            self._background_tasks.add(w)
            w.add_done_callback(self._background_tasks.discard)
```

- [ ] **Step 2: Add the review watcher (poll until ready → post overview)**

Add after `_watch_outreach`:

```python
    async def _watch_outreach_review(self, ctx, email: str, task_id: str,
                                     role: str, location: str) -> None:
        from handlers import recruiting_review as rr
        if ctx.notify_channel is None:
            return
        for _ in range(OUTREACH_MAX_POLLS):
            await asyncio.sleep(OUTREACH_POLL_SECONDS)
            try:
                st = await self._tasks_client.get_outreach_candidates(email, task_id)
            except TasksAPIError:
                continue
            status = st.get("status")
            if status == "running":
                continue
            if status == "review":
                msg = rr.build_review_message(task_id, st.get("candidates", []),
                                              role=role, location=location)
                await ctx.notify_channel(msg)
                return
            await ctx.notify_channel(st.get("text") or "No engineers found.")
            return
        await ctx.notify_channel("Outreach search timed out — try again.")
```

NOTE: `ctx.notify_channel` must accept a full message dict (content/embeds/components). Confirm the Discord `notify_channel` used for outreach posts rich messages; if it only accepts a string, post via `self.discord.create_message(channel_id, **msg)` using `ctx.channel_id` instead. Check `_watch_outreach`'s `_notify`/`notify_channel` wiring at call time and match it.

- [ ] **Step 3: Add the selection handler**

```python
    async def run_outreach_select(self, ctx, task_id: str, selected_ids: list[str],
                                  role: str, location: str) -> None:
        from handlers import recruiting_review as rr
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        st = await self._tasks_client.patch_outreach_candidate(
            email, task_id, "_", {"selected_ids": selected_ids})
        msg = rr.build_review_message(task_id, st.get("candidates", []),
                                      role=role, location=location)
        await ctx.edit_message(msg)
```

- [ ] **Step 4: Add the edit-submit handler**

```python
    async def run_outreach_edit_submit(self, ctx, task_id: str, cid: str,
                                       email_val: str, subject: str, body: str,
                                       role: str, location: str) -> None:
        from handlers import recruiting_review as rr
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        st = await self._tasks_client.patch_outreach_candidate(
            email, task_id, cid,
            {"email": email_val, "subject": subject, "body": body})
        msg = rr.build_review_message(task_id, st.get("candidates", []),
                                      role=role, location=location)
        await ctx.edit_message(msg)
```

- [ ] **Step 5: Add the send handler**

```python
    async def run_outreach_send(self, ctx, task_id: str) -> None:
        from handlers import recruiting_review as rr
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        st = await self._tasks_client.send_outreach(email, task_id)
        if st.get("status") == "sent":
            await ctx.edit_message(rr.build_sent_message(st.get("text", "Sent."),
                                                         st.get("sheet_url", "")))
        else:
            await ctx.respond(st.get("text") or "Pick at least one engineer first.")
```

`ctx.edit_message(msg_dict)` edits the component message in place; if `CommandContext` has no such helper, the Discord handlers in Task 8 pass an `edit_message` closure built on `self.discord.edit_original(interaction_token, **msg)` (the deferred-update pattern from `_handle_publish_component`).

- [ ] **Step 6: Parse check + commit**

Run: `cd webhook-handler && ./.venv/Scripts/python.exe -c "import ast; ast.parse(open('handlers/commands.py').read()); print('ok')"`
Expected: `ok`.

```bash
git add webhook-handler/handlers/commands.py
git commit -m "feat(recruiting): manual review watcher + select/edit/send handlers"
```

---

## Task 8: Route the new interactions (`discord_commands.py`)

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` — the component dispatch (~line 346) and the modal-submit dispatch (~line 677)

No unit test. Verified in Task 9. Follow the `_handle_publish_component` pattern (deferred ACK + background task + `edit_original` closure).

- [ ] **Step 1: Import the helpers**

At the top with the other handler imports, add:

```python
from handlers import recruiting_review as rr
```

- [ ] **Step 2: Route the component interactions**

In the component dispatch, right after the `is_out_find` block (line ~348), add:

```python
        if rr.is_out_send(custom_id):
            return await self._handle_outreach_send(payload, custom_id)
        if rr.is_out_refresh(custom_id):
            return await self._handle_outreach_refresh(payload, custom_id)
        if rr.is_out_sel(custom_id):
            return await self._handle_outreach_select(payload, custom_id, data)
        if rr.is_out_edit(custom_id):
            values = data.get("values") or []
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_outreach_edit_open(payload, custom_id, values[0])
```

- [ ] **Step 3: Route the edit-modal submit**

In the modal-submit dispatch (where `is_out_modal` is handled, ~line 670), add a branch:

```python
        if rr.is_out_editmodal(custom_id):
            return await self._handle_outreach_editmodal(payload, custom_id, values)
```

- [ ] **Step 4: Add the component handlers**

Add these methods to the handler class (mirror `_handle_publish_component`). Each builds a `CommandContext` whose `edit_message`/`respond` use `self.discord.edit_original`. Role/location aren't in the interaction, so re-fetch them from the task's stored `job_title` (role) via the candidates call; for location, pass "" (the embed title still shows the role).

```python
    def _out_ctx(self, payload, *, raw="outreach"):
        token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))

        async def edit_message(msg: dict) -> None:
            await self.discord.edit_original(
                interaction_token=token, content=msg.get("content", ""),
                embeds=msg.get("embeds", []), components=msg.get("components", []))

        async def respond(text: str) -> None:
            await self.discord.edit_original(interaction_token=token, content=text)

        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text=raw,
            subcommand="outreach", arguments="", platform="discord",
            respond=respond,
            metadata={"interaction_id": payload.get("id", ""), "interaction_token": token,
                      "guild_id": payload.get("guild_id", "")})
        ctx.edit_message = edit_message  # attach closure
        return ctx

    async def _handle_outreach_select(self, payload, custom_id, data):
        task_id = rr.task_id_from_sel(custom_id)
        selected = data.get("values") or []
        ctx = self._out_ctx(payload)
        asyncio.create_task(self.router.run_outreach_select(ctx, task_id, selected, "", ""))
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_outreach_edit_open(self, payload, custom_id, cid):
        task_id = rr.task_id_from_edit(custom_id)
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        email = await self.router._resolve_email_auto(user.get("id", ""))
        st = await self.router._tasks_client.get_outreach_candidates(email, task_id)
        cand = next((c for c in st.get("candidates", []) if c["id"] == cid), None)
        if cand is None:
            return {"type": DEFERRED_UPDATE_MESSAGE}
        return {"type": MODAL, "data": rr.build_edit_modal(task_id, cand)}

    async def _handle_outreach_editmodal(self, payload, custom_id, values):
        task_id, cid = rr.ids_from_editmodal(custom_id)
        ctx = self._out_ctx(payload)
        asyncio.create_task(self.router.run_outreach_edit_submit(
            ctx, task_id, cid, values.get("email", ""), values.get("subject", ""),
            values.get("body", ""), "", ""))
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_outreach_send(self, payload, custom_id):
        task_id = rr.task_id_from_send(custom_id)
        ctx = self._out_ctx(payload)
        asyncio.create_task(self.router.run_outreach_send(ctx, task_id))
        return {"type": DEFERRED_UPDATE_MESSAGE}

    async def _handle_outreach_refresh(self, payload, custom_id):
        task_id = rr.task_id_from_refresh(custom_id)
        ctx = self._out_ctx(payload)
        asyncio.create_task(self.router.run_outreach_select(ctx, task_id, None, "", ""))
        return {"type": DEFERRED_UPDATE_MESSAGE}
```

NOTE on refresh: `run_outreach_select` with `selected_ids=None` must re-render WITHOUT changing selection. Adjust `run_outreach_select` (Task 7 step 3) to skip the PATCH when `selected_ids is None` and just GET + re-render:

```python
        if selected_ids is None:
            st = await self._tasks_client.get_outreach_candidates(email, task_id)
        else:
            st = await self._tasks_client.patch_outreach_candidate(
                email, task_id, "_", {"selected_ids": selected_ids})
```

- [ ] **Step 5: Confirm modal-submit value flattening**

The modal handler passes `values` as `{custom_id: value}` (same shape `parse_outreach_modal` consumes). Confirm the existing modal dispatch builds `values` that way before calling `_handle_outreach_editmodal` (it does for `is_out_modal`). Reuse that flattening.

- [ ] **Step 6: Parse check + commit**

Run: `cd webhook-handler && ./.venv/Scripts/python.exe -c "import ast; ast.parse(open('handlers/discord_commands.py').read()); print('ok')"`
Expected: `ok`.

```bash
git add webhook-handler/handlers/discord_commands.py
git commit -m "feat(recruiting): route select/edit/editmodal/send/refresh interactions"
```

---

## Task 9: Deploy + live end-to-end verification

**Files:** none (deploy + manual test)

- [ ] **Step 1: Run the full unit suites that exist for these files**

```bash
cd webhook-handler && ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_review.py tests/test_recruiting_panel.py -v
cd mcp-servers/tasks && "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_outreach_review_logic.py tests/test_outreach_logic.py -v
```
Expected: all PASS.

- [ ] **Step 2: Deploy tasks (orchestrator) + webhook-handler (manual scp)**

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh   # ships mcp-servers/tasks
# webhook-handler is NOT covered by the orchestrator — scp each changed file:
for f in handlers/recruiting_review.py handlers/recruiting_panel.py handlers/commands.py handlers/discord_commands.py clients/tasks.py; do
  tr -d '\r' < "webhook-handler/$f" | ssh root@46.224.193.25 "cat > /root/proxy-server/webhook-handler/$f"
done
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler tasks"
```

- [ ] **Step 3: Verify health**

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
ssh root@46.224.193.25 "docker compose -f /root/proxy-server/docker-compose.unified.yml ps webhook-handler tasks"
```
Expected: `{"status":"ok"}` and both `Up`.

- [ ] **Step 4: Live test in `#recruiting` (Discord)**

In `#recruiting`: **Find Engineers** → role e.g. "React", count 3 → wait for the overview message → confirm: list shows, recipient multi-select lists only emailable, **✏️ edit** one (change subject) → re-render shows it, **✚ add email** to a no-email one → it becomes selectable, select 1 → **Send** → message locks to the sent summary.

- [ ] **Step 5: Confirm from the n8n side (independent evidence)**

Use the audit technique: the only n8n execution should be the one fired by **Send** (not at Find). Confirm `Gmail Send` ran only for the selected candidate(s) and the sheet row matches the edited subject. (Find must produce **zero** n8n executions.)

- [ ] **Step 6: Final commit / PR**

```bash
git push -u origin feat/outreach-review-send
gh pr create --title "Outreach: find → review → edit → send (Discord)" --body "Implements docs/superpowers/specs/2026-06-10-outreach-review-send-design.md"
```

---

## Notes for the implementer

- **Slack is intentionally untouched** — it keeps auto-send. Don't wire any `aiuiout:*` review routing into `slack_interactions.py`.
- **Initiator-only** (spec §4) is enforced naturally: handlers resolve the *interacting* user's email and the tasks endpoints are `assignee_email`-owner-checked, so a different user's PATCH/Send 404s. No extra check needed, but a friendlier ephemeral "not your session" can be added if 404s feel abrupt.
- **No DB migration** — everything lives in `TaskItem.result` JSON.
- **`ctx.edit_message`** is attached as a closure in Task 8's `_out_ctx`; if `CommandContext` is a frozen dataclass that rejects attribute assignment, add an optional `edit_message` field to it (mirror the existing optional `on_published` callback) instead of monkey-patching.
