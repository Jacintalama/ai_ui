# Custom "build from prompt" template card — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "Custom" card as the last entry in the templates gallery so users can opt out of templates and build from their own description with a generic file-layout / scope-rules baseline.

**Architecture:** Synthetic `"custom"` template_key in `templates.py`. The card sends `template_key="custom"` like any other; backend's existing `build_rules_for` machinery returns just `_BASE_RULES + _GENERATION_LAYOUT` (because the template's `rules` field is `""`). No new code paths — just data + UI.

**Tech Stack:** Python (dataclass + pytest) for backend; vanilla JS + CSS in static/projects.html for frontend.

**Design doc:** `docs/plans/2026-05-04-custom-template-card-design.md` (read first if anything is unclear).

---

## Task 1: Backend — add `"custom"` Template entry + tests

**Files:**
- Modify: `mcp-servers/tasks/templates.py` (insert new `Template(...)` at the END of the `TEMPLATES: list[Template] = [...]` literal, currently starting at line 460).
- Create: `mcp-servers/tasks/tests/test_custom_template.py`

**Context the implementer needs:**
- The `Template` dataclass (templates.py:12-39) requires `key, label, emoji, description, placeholder, rules`. Other fields default — leave `feature_bullets=()`, `svg_mockup=""`.
- `build_rules_for(key, storage)` (templates.py:686-709) computes `_BASE_RULES + _GENERATION_LAYOUT + t.rules.strip()`. With `t.rules=""`, the strip produces `""`, joined with `\n\n` it's a trailing blank section — harmless. The agent receives the universal layout + scope rules, no template-specific guidance. That's exactly what the design wants.
- `_has_template_app("custom")` will return False (no `template_apps/custom/index.html`), so `routes_tasks.py:362` falls into `_ensure_app_skeleton(slug, "none")`. Empty skeleton path runs.
- `_is_generic_description("...")` heuristic at routes_tasks.py:402 is irrelevant here because the instant-build branch (routes_tasks.py:374) requires `template_app_used=True`. Custom never sets that flag — agent always runs.

### Step 1: Write the failing test

Create `mcp-servers/tasks/tests/test_custom_template.py`:

```python
"""Tests for the synthetic 'custom' template key — escape hatch from
template selection that lets the agent build from the user's description
alone with the universal layout/scope baseline."""
from templates import (
    is_valid_key,
    build_rules_for,
    storage_for,
    requires_supabase,
    _has_template_app,
    get_template,
)


def test_custom_is_a_valid_key():
    assert is_valid_key("custom") is True


def test_custom_template_metadata():
    t = get_template("custom")
    assert t is not None
    assert t.key == "custom"
    assert t.label == "Custom"
    assert "description" in t.description.lower() or "prompt" in t.description.lower()


def test_custom_storage_is_none():
    assert storage_for("custom") == "none"


def test_custom_does_not_trigger_supabase_gate():
    assert requires_supabase("custom", "none") is False
    assert requires_supabase("custom", "supabase") is False


def test_custom_has_no_template_app_folder():
    assert _has_template_app("custom") is False


def test_custom_rules_block_contains_baseline_layout_and_scope():
    block = build_rules_for("custom", "none")
    assert "FILE LAYOUT" in block
    assert "apps/<slug>/" in block
    assert "RULES (strict)" in block
    # Make sure no template-specific guidance leaked in.
    assert "PURPOSE: Marketing" not in block  # would be from landing
    assert "PURPOSE: Operational analytics" not in block  # dashboard
    assert "PURPOSE: Manage one main entity" not in block  # crud


def test_custom_rules_block_is_non_empty():
    block = build_rules_for("custom", "none")
    assert len(block) > 500  # baseline alone is several hundred chars


def test_custom_appears_last_in_templates_list():
    """Brainstorm Q3=B: the Custom card sits at the end of the gallery.
    Order is determined by the TEMPLATES list order in templates.py."""
    from templates import TEMPLATES
    assert TEMPLATES[-1].key == "custom"
```

### Step 2: Run the test to verify it fails

```bash
cd mcp-servers/tasks
DATABASE_URL=postgresql://dummy:dummy@localhost/dummy AIUI_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") python -m pytest tests/test_custom_template.py -v
```

Expected: 8 failures, all on `is_valid_key("custom") is False` or `get_template("custom") is None`. The Custom entry doesn't exist yet.

### Step 3: Add the Custom Template entry

Find the closing `]` of `TEMPLATES: list[Template] = [...]` in `templates.py` (currently around line 658, the line right before `_BY_KEY = {t.key: t for t in TEMPLATES}`). Insert this entry as the **last** template, BEFORE the closing `]`:

```python
    Template(
        key="custom",
        label="Custom",
        emoji="✨",
        description="Build from your description — no template",
        placeholder="Describe your app: what it does, who it's for, the look and feel, any specific sections or features.",
        rules="",  # No template-specific guidance — baseline (BASE_RULES + GENERATION_LAYOUT) is enough.
        storage="none",
        role_tag="From scratch",
        feature_bullets=(
            "Skip the template gallery — describe what you want",
            "Static HTML + Tailwind + Alpine baseline still applied",
            "Agent builds the file layout for you",
        ),
        svg_mockup="",  # Frontend renders a dashed-border + glyph card instead of an SVG mockup.
    ),
```

### Step 4: Run the test to verify it passes

```bash
DATABASE_URL=postgresql://dummy:dummy@localhost/dummy AIUI_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") python -m pytest tests/test_custom_template.py -v
```

Expected: 8 PASS.

### Step 5: Run the broader templates test suite to confirm no regressions

```bash
DATABASE_URL=postgresql://dummy:dummy@localhost/dummy AIUI_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") python -m pytest tests/test_templates.py tests/test_template_app_copy.py tests/test_custom_template.py
```

Expected: all PASS. (Pre-existing `test_build_enhance_prompt_forbids_stack_pivot` may still fail in a separate file; that's an out-of-scope known issue.)

### Step 6: Commit

```bash
git add mcp-servers/tasks/templates.py mcp-servers/tasks/tests/test_custom_template.py
git commit -m "feat(templates): add synthetic 'custom' template_key

The Custom entry is the escape hatch from template selection: rules='',
storage='none', no template_app folder. build_rules_for('custom','none')
returns just _BASE_RULES + _GENERATION_LAYOUT — the agent gets the
universal file-layout + scope-rules baseline plus the user's
description. No new code paths; the existing template_key machinery
treats it like any other entry.

Frontend hookup lands in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Frontend — render Custom card + wire click handler

**Files:**
- Modify: `mcp-servers/tasks/static/projects.html`
  - CSS: add a `#templates-modal .tcard.custom { ... }` rule near the existing `.tcard` styles (around line 414).
  - JS: in the gallery rendering loop (currently around line 1496-1511), append a Custom card element after the loop completes.

**Context the implementer needs:**
- `_renderTgGrid()` (search the file — it's the function that renders the gallery; the loop ends just before the iframe-health-check block at projects.html:1514).
- Existing template cards have markup `<div class="tcard featured kind-<X>" data-key="<key>">…</div>` with a "Use this template" button having `data-action="use"`. The click handler at projects.html:1543-1551 sets `npTemplate.value = key` and closes the modal — same logic the Custom card needs.
- `_templatesCache` already includes the Custom entry from Task 1 (because the backend's `GET /api/templates` returns the full list). So you have **two options**:
  - (a) Render Custom from the existing data loop with conditional CSS based on `data-key="custom"`. Simpler.
  - (b) Skip Custom inside the data loop and append it manually as the last card. More control over visual.
- **Pick option (a).** It reuses the loop, keeps the data flow uniform, and the CSS selector `.tcard[data-key="custom"]` handles the visual difference cleanly. Filter pills (All/Featured/Static/Dynamic) need to keep Custom always visible — handle that in the filter function (see Step 3).

### Step 1: Add CSS for the Custom card visual

Find the existing `#templates-modal .tcard.featured { ... }` rule (around line 424). After the `.tcard:hover` rule and before the `.tcard .visual` rules, insert:

```css
    /* Custom card — escape hatch from template selection. Visually distinct
       from real templates: dashed border, transparent visual area, + glyph. */
    #templates-modal .tcard[data-key="custom"] {
      border: 1px dashed var(--border-2);
      background: transparent;
    }
    #templates-modal .tcard[data-key="custom"]:hover {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    #templates-modal .tcard[data-key="custom"] .visual {
      background: transparent;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    #templates-modal .tcard[data-key="custom"] .visual::after {
      content: "+";
      font-size: 64px;
      font-weight: 200;
      color: var(--muted);
      line-height: 1;
    }
    #templates-modal .tcard[data-key="custom"]:hover .visual::after {
      color: var(--accent);
    }
```

### Step 2: Verify the existing render loop already picks up `key="custom"`

Open `_renderTgGrid()` and confirm the loop iterates `_templatesCache`. The Custom entry comes from the backend list (Task 1), so it'll already render. The CSS from Step 1 makes it look right.

If the loop has a guard like `if (t.svg_mockup === "" && !t.preview_url) skip` — remove the skip (or pass through). Search for `skip` / `continue` inside the render function. If you find one, the implementer should report what it does before changing it.

### Step 3: Make the Custom card immune to filter pills

Find the filter logic (`tgActiveFilter` is referenced around line 1558). Inside the render loop, when computing whether a card should be shown for the current filter, force `key === "custom"` to always pass.

Concrete change: locate the line that filters by `tgActiveFilter` (likely a `.filter()` call on `_templatesCache`). Wrap the predicate so `t.key === "custom"` short-circuits to `true`. Example:

```js
// Existing pattern (illustrative — adapt to actual code):
const visible = _templatesCache.filter((t) => {
  if (t.key === "custom") return true;  // always show Custom
  if (tgActiveFilter === "all") return true;
  if (tgActiveFilter === "featured") return !!t.featured;
  if (tgActiveFilter === "static") return t.storage === "none";
  if (tgActiveFilter === "dynamic") return t.storage === "supabase";
  return true;
});
```

If the existing filter logic is structured differently, the spirit is the same: Custom shows for every filter.

### Step 4: Verify Custom is the last visible card

Because backend Task 1 puts Custom at the END of `TEMPLATES` and the frontend renders in the order `_templatesCache` provides, no extra sort is needed. But add a defensive comment near the loop:

```js
// Order is server-provided. The "custom" entry is intentionally last in
// templates.py so it lands at the end of the grid as the escape hatch.
```

### Step 5: Manual smoke test (best done after Task 3 deploy)

Skip ahead to Task 3 if no local dev environment.

If you have one:
1. Open `/tasks/static/projects.html`.
2. Click "+ New project". The modal opens.
3. Click "Select template". Gallery opens.
4. Confirm Custom card is visible at the bottom with dashed border + `+` glyph.
5. Click each filter pill (All / Featured / Static / Dynamic) — Custom remains visible in every case.
6. Click "Use custom" on the Custom card. Modal closes.
7. The status pill in the form shows "Custom — Build from your description — no template".
8. Type a real description ("Make me a portfolio Jacint A. Alama minimalist website").
9. Click "Create project". Task creates without error.

### Step 6: Commit

```bash
git add mcp-servers/tasks/static/projects.html
git commit -m "feat(projects): render Custom card in templates gallery

Custom card is the last entry in the gallery, dashed-border + glyph
visual, always visible regardless of active filter. Click sends
template_key='custom' just like any template; no special-case JS for
the submit path.

Closes the 'kapoyan ko pindot' UX gap — users no longer need to pick a
template they don't want before they can describe their own app.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Deploy to Hetzner

**Step 1: SCP the modified files**

From `mcp-servers/tasks/`:

```bash
scp templates.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/templates.py
scp static/projects.html root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/projects.html
```

Expected: silent success on both.

**Step 2: Rebuild + restart the tasks container**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks 2>&1 | tail -8"
```

Expected: ends with `Container tasks  Started`.

**Step 3: Verify the new code is in the running container**

```bash
ssh root@46.224.193.25 "docker exec tasks python -c 'from templates import is_valid_key, build_rules_for; print(\"valid:\", is_valid_key(\"custom\")); print(\"rules len:\", len(build_rules_for(\"custom\", \"none\")))'"
```

Expected: `valid: True`, `rules len: <several thousand>`.

```bash
ssh root@46.224.193.25 "docker exec tasks grep -nE 'tcard\\[data-key=.custom.\\]|key === .custom.' static/projects.html | head -5"
```

Expected: matches in both CSS and JS.

---

## Task 4: Smoke test on live deployment

**Step 1: Hard-refresh** the App Builder page (Ctrl+Shift+R / Cmd+Shift+R).

**Step 2: Open `+ New project` → `Select template`.**

**Step 3: Confirm Custom card appears at the bottom** with the dashed border + `+` glyph. Try every filter pill — Custom remains visible.

**Step 4: Click "Use custom".** Modal closes; status pill in the form updates.

**Step 5: Type a real description** ("Make me a portfolio Jacint A. Alama minimalist website") + a slug ("portfolio-2"), submit.

**Step 6: Confirm:**
- Task creates (no 500, no stuck "Building").
- Agent runs — logs appear in the Logs tab.
- After build, files appear under `apps/portfolio-2/` with the standard layout (`index.html`, `styles/`, `src/`).
- Auto-start kicks in (from earlier auto-run feature) — preview iframe goes live without Run click.

**Step 7: Regression check** — pick a real template (e.g. Portfolio), submit. Existing flow still works.

---

## Acceptance checklist (from design doc §Acceptance)

- [ ] Custom card visible as the last card in the gallery, regardless of active filter.
- [ ] Clicking Custom sets `template_key="custom"` and closes the modal.
- [ ] Submitting with Custom + a real description creates a task whose stored `description` includes the generic baseline prefix.
- [ ] The agent run completes without a `ValueError` from `build_prompt`.
- [ ] Existing template flow unaffected.
- [ ] `tests/test_custom_template.py` covers the new `"custom"` entry (8 tests).
