# App Builder Multi-User Roles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `tasks.project_members.role` actually mean something — owners can do everything, editors can build/enhance but not invite, viewers can read but not write.

**Architecture:** A new helper `_require_role(slug, user, *roles)` in `routes_projects.py` runs before mutations. Existing endpoints now call it with the minimum role they require. Read endpoints stay open to all members.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.x async / pytest-asyncio.

---

## Role matrix

| Action | Owner | Editor | Viewer |
|---|---|---|---|
| List members, list versions, see preview | ✅ | ✅ | ✅ |
| Run AI build / enhance / chat | ✅ | ✅ | ❌ |
| Rollback to a version | ✅ | ✅ | ❌ |
| Publish / unpublish | ✅ | ❌ | ❌ |
| Attach / detach / verify custom domain | ✅ | ❌ | ❌ |
| Invite / remove members | ✅ | ❌ | ❌ |
| Rename project | ✅ | ❌ | ❌ |
| Leave project | ✅ (if not last owner) | ✅ | ✅ |

---

## File Structure

**Will modify:**
- `mcp-servers/tasks/routes_projects.py` — `_require_role` helper + replace existing per-endpoint owner checks with calls to it
- `mcp-servers/tasks/routes_tasks.py` — `/enhance` + `/{id}/execute` + `/{id}/cancel` must be callable only by editor+ on the project

**Will create:**
- `mcp-servers/tasks/tests/test_role_enforcement.py` — verify each endpoint enforces the right role

---

### Task 1: Add `_require_role` helper

**Files:**
- Modify: `mcp-servers/tasks/routes_projects.py` (insert near `_user_can_see_project`)

- [ ] **Step 1: Add the helper function**

Insert after `_user_can_see_project` (around line 65):

```python
ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}


async def _require_role(s, slug: str, email: str, min_role: str) -> str:
    """Raise 403 unless the user has at least `min_role` on the project.

    Admins (X-User-Admin: true → user.is_admin) bypass to "owner".
    Returns the user's effective role (for callers that want to log it).
    """
    member = (
        await s.execute(
            select(ProjectMember).where(
                and_(
                    ProjectMember.slug == slug,
                    ProjectMember.user_email == email,
                )
            ).limit(1)
        )
    ).scalar_one_or_none()
    if member is None:
        # Fall back to "creator implicitly owns it" if there's a TaskItem.
        task = (
            await s.execute(
                select(TaskItem).where(
                    and_(
                        TaskItem.built_app_slug == slug,
                        TaskItem.assignee_email == email,
                    )
                ).limit(1)
            )
        ).scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=403, detail="Not a member of this project")
        role = "owner"
    else:
        role = member.role

    if ROLE_RANK.get(role, -1) < ROLE_RANK[min_role]:
        raise HTTPException(
            status_code=403,
            detail=f"This action needs role '{min_role}' — you have '{role}'.",
        )
    return role
```

- [ ] **Step 2: Run existing tests, expect PASS (added function, no callers yet)**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/ -q"
```

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/routes_projects.py
git commit -m "feat(projects): add _require_role helper"
```

---

### Task 2: Replace owner checks with `_require_role` (publish, unpublish, custom domain, rename)

**Files:**
- Modify: `mcp-servers/tasks/routes_projects.py`

Find every block that currently looks like:

```python
        is_owner = (
            await s.execute(
                select(ProjectMember).where(
                    ProjectMember.slug == slug,
                    ProjectMember.user_email == user.email,
                    ProjectMember.role == "owner",
                ).limit(1)
            )
        ).scalar_one_or_none() is not None
        if not is_owner and not user.is_admin:
            raise HTTPException(status_code=403, detail="Only project owners can ...")
```

…in `publish_app`, `unpublish_app`, `set_custom_domain`, `remove_custom_domain`, `rename_project`, and `rollback_project`.

- [ ] **Step 1: Replace each with a single call**

For example, in `publish_app`:

```python
        await _require_role(s, slug, user.email, "owner")
```

Do the same for `unpublish_app`, `set_custom_domain`, `remove_custom_domain`, `rename_project`. **Rollback** stays at owner-level for now — even though editors can run builds, only owners can rewrite history.

For `invite_member` and `remove_member`, also use `_require_role(..., "owner")` since membership management is owner-only.

- [ ] **Step 2: Run existing tests, expect PASS**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_routes_projects.py -v"
```

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/routes_projects.py
git commit -m "refactor(projects): use _require_role helper across mutating endpoints"
```

---

### Task 3: Gate `/enhance` and `/execute` and `/cancel` to editor+

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py`

Today these endpoints check `assignee_email == user.email or TEAM_EMAIL`. We want collaborators with `editor` role to be able to run builds too.

- [ ] **Step 1: Add the new check at the top of each endpoint body**

In `enhance` (around line 355) — after fetching the source task and confirming it has a `built_app_slug`:

```python
        # Editors and owners on the project can enhance.
        from routes_projects import _require_role
        await _require_role(s, source.built_app_slug, user.email, "editor")
```

In `execute` (around line 226) — after fetching the item and confirming it has a `built_app_slug`:

```python
        if item.built_app_slug:
            from routes_projects import _require_role
            await _require_role(s, item.built_app_slug, user.email, "editor")
        elif item.assignee_email not in (user.email, TEAM_EMAIL):
            raise HTTPException(status_code=403, detail="Not your task")
```

In `cancel` — same pattern as `execute`.

- [ ] **Step 2: Run existing tests, expect PASS**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_enhance_endpoint.py tests/test_routes_tasks.py -v"
```

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py
git commit -m "feat(tasks): editor+ can run /enhance + /execute + /cancel on shared projects"
```

---

### Task 4: Add `POST /api/projects/{slug}/leave` for self-removal

**Files:**
- Modify: `mcp-servers/tasks/routes_projects.py`

Members should be able to remove themselves without going through the owner.

- [ ] **Step 1: Append the endpoint near the other members endpoints**

```python
@router.post("/{slug}/leave", status_code=204)
async def leave_project(slug: str, user: AdminUser = Depends(current_admin)):
    """Self-remove from a project. Refused if you're the last owner."""
    _validate_slug(slug)
    async with session() as s:
        row = (
            await s.execute(
                select(ProjectMember).where(
                    and_(
                        ProjectMember.slug == slug,
                        ProjectMember.user_email == user.email,
                    )
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Not a member of this project")
        if row.role == "owner":
            owner_count = len((
                await s.execute(
                    select(ProjectMember).where(
                        and_(ProjectMember.slug == slug, ProjectMember.role == "owner")
                    )
                )
            ).scalars().all())
            if owner_count <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="You're the last owner — promote someone else first or unpublish the project.",
                )
        await s.delete(row)
        await s.commit()
    return None
```

- [ ] **Step 2: Test the endpoint**

Add to `tests/test_routes_projects.py`:

```python
async def test_member_can_leave_project(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    db_session.add(ProjectMember(slug="alpha", user_email="bob@aiui.com",
                                  role="editor", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/leave",
                         headers={"X-User-Email": "bob@aiui.com",
                                  "X-User-Admin": "true"})
    assert r.status_code == 204

    rows = (await db_session.execute(
        select(ProjectMember).where(ProjectMember.slug == "alpha")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_email == "ralph@aiui.com"


async def test_last_owner_cannot_leave(db_session, transport):
    db_session.add(ProjectMember(slug="alpha", user_email="ralph@aiui.com",
                                  role="owner", added_by="ralph@aiui.com"))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/projects/alpha/leave", headers=OWNER_HDR)
    assert r.status_code == 409
```

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/test_routes_projects.py::test_member_can_leave_project tests/test_routes_projects.py::test_last_owner_cannot_leave -v"
```

Expected: both PASS.

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/routes_projects.py mcp-servers/tasks/tests/test_routes_projects.py
git commit -m "feat(projects): POST /leave for self-removal (last-owner protected)"
```

---

### Task 5: Frontend — show role on each member row + add "Leave project"

**Files:**
- Modify: `mcp-servers/tasks/static/projects.html` — the existing members modal

- [ ] **Step 1: Add a "Leave" button in the modal footer**

Find the members modal markup (search for `id="members-modal"`) and replace its footer:

```html
      <div class="modal-footer">
        <button type="button" class="btn" id="mm-leave" hidden>Leave project</button>
        <span style="flex:1;"></span>
        <button type="button" class="btn" data-close>Close</button>
      </div>
```

- [ ] **Step 2: Wire it up in the JS**

Find `mmInvite.addEventListener("click", async () => {` and add right after the members render block, inside `refreshMembers`:

```javascript
        // Show "Leave project" button if the current user is in the list.
        const myEmail = (typeof userEmail !== "undefined" && userEmail) || null;
        const $mmLeave = document.getElementById("mm-leave");
        if ($mmLeave) {
          const meIn = rows.some((r) => r.user_email === myEmail);
          $mmLeave.hidden = !meIn;
        }
```

- [ ] **Step 3: Wire the click handler near the other members JS**

```javascript
    const $mmLeave = document.getElementById("mm-leave");
    if ($mmLeave) {
      $mmLeave.addEventListener("click", async () => {
        if (!confirm(`Leave the project "${mmCurrentSlug}"? You'll lose access immediately.`)) return;
        try {
          const r = await fetch(`/api/projects/${encodeURIComponent(mmCurrentSlug)}/leave`, {
            method: "POST",
            headers: authHeaders(),
            credentials: "include",
          });
          if (!r.ok && r.status !== 204) {
            const t = await r.text();
            showToast("Couldn't leave: " + t.slice(0, 200), true);
            return;
          }
          mmModal.hidden = true;
          showToast(`Left ${mmCurrentSlug}.`);
          load();  // refresh card list — leaving may remove this project from view
        } catch (err) {
          showToast("Network error: " + err.message, true);
        }
      });
    }
```

- [ ] **Step 4: Manual test in browser**

1. Open `/tasks/app-builder`
2. Click 👥 Members on a project where you're an editor (not owner) — Leave button should appear
3. Click Leave → confirm → toast → project disappears from your card list

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/projects.html
git commit -m "feat(projects): self-leave button in members modal"
```

---

### Task 6: Self-review

- [ ] **Step 1: Run full test suite**

```bash
ssh -i ~/.ssh/aiui_safe root@46.224.193.25 "docker exec tasks pytest tests/ -q"
```

Expected: all green.

- [ ] **Step 2: End-to-end role test (manual)**

1. As Ralph (owner): open a project, click 👥 Members, invite `bob@example.com` as `editor`
2. As Bob (editor — would need a real Bob account; can simulate with X-User-Email header in curl):
   - Should be able to enhance the app
   - Should NOT be able to publish, unpublish, set custom domain, or rename
3. As Bob (after demoted to viewer):
   - Can open preview, see code
   - Cannot click "Build" sidebar (server returns 403)

- [ ] **Step 3: Final commit if needed**

```bash
git add -A && git commit -m "chore(plan-multiuser): manual e2e pass" || true
```
