# Custom "build from prompt" card in the templates gallery — design

**Date:** 2026-05-04
**Branch:** `feat/gdrive-gmail-connectors`
**Status:** Approved, ready for implementation plan.

## Problem

The new-project flow forces the user to pick a template before they can submit (`projects.html:1782` toasts "Click Select template at the top to pick one" otherwise). Some prompts don't match any of the 5+ existing templates — e.g. "Make me a portfolio Jacint A. Alama minimalist website" doesn't fit the "portfolio" template's defaults. Today the user has to either pick a template they don't want or give up.

User feedback: *"if user is not agree with the template so user can choose base on prompt something like that"* — they want an escape hatch from the template gallery into a "build from my own description" mode.

## Goal

Add a "Custom" card to the templates gallery as the last card. Clicking it opts out of any template; the user's description goes to the agent with a generic file-layout / scope-rules baseline (so the build still lands in `apps/<slug>/` with the expected structure) but no template-specific guidance.

## Non-goals

- Removing the existing templates. They stay, untouched.
- Letting the user save a description as a reusable "custom template". Real-templates concern.
- Description-prefilling tips ("include brand, colors, sections..."). YAGNI until asked.
- Per-user history of Custom prompts. Existing chat history already covers refinement.
- A backend SSE/WebSocket layer for "preview ready" events. Out of scope.

## Approach (chosen: synthetic `"custom"` template_key)

Add a `"custom"` entry to `templates.py`. The card sends `template_key="custom"` like any other template. Backend treats it identically to existing entries — `is_valid_key("custom")` returns True, `build_rules_for("custom", "none")` returns a generic baseline prefix, `_has_template_app("custom")` returns False so the empty-skeleton path runs.

### Why this approach

- Reuses the existing `template_key` → prefix machinery. No new backend code paths.
- The new entry is just data. Existing tests that iterate `TEMPLATES` see it for free.
- Keeps the "Phase D" security boundary intact: rules text stays server-side; the browser never embeds prompt content in the request body.

### Why not the alternatives

- **Null `template_key` + special branch in `routes_tasks.py`:** works but adds a parallel code path that diverges from the unified template machinery.
- **Frontend embeds the baseline rules in `description`:** Phase D explicitly moved rules text server-side to close a prompt-injection hole. Don't reverse it.

## Sections

### 1. UX + UI (frontend)

- **Card position:** Last in the templates grid, after the loop over `_templatesCache`. Always visible regardless of which filter pill (All/Featured/Static/Dynamic) is active.
- **Visual:** Same card dimensions as templates so the grid stays clean, but visually distinct:
  - Dashed border, transparent background.
  - A simple `+` glyph in the visual area (no gradient, no preview iframe).
  - Title "Custom", subtitle "Build from your description".
  - Single primary button "Use custom".
- **Click handler:** Identical to template cards' "Use this template" — sets `npTemplate.value = "custom"`, closes the modal, refreshes the status pill to "Custom — build from your description". The "Change" link still re-opens the gallery.
- **Validation:** Description stays required (existing toast handles the empty case).
- **Submit:** Identical to existing templates — the "must pick" guard at `projects.html:1782` is satisfied because `npTemplate.value === "custom"` is truthy. POST `/api/tasks` with `{"template_key": "custom", "storage": "none", "description": "...", "slug": "..."}`.

### 2. Backend

One change in `templates.py`: add a `"custom"` entry to the registry.

| Field | Value |
|---|---|
| `key` | `"custom"` |
| `label` | `"Custom"` |
| `description` | `"Build from your description — no template."` |
| `storage` | `"none"` |
| `featured` | `False` |
| `kind` | `"custom"` (new value; no gradient — the visual is the dashed-border `+` card) |
| `prefix` | Generic baseline (see below) |
| `requires_supabase` | `False` |

**Generic baseline content for `prefix`:**
- The existing FILE LAYOUT block (`apps/<slug>/`, `index.html`, `styles/main.css`, `src/main.js`, `src/components/`, `public/`).
- The existing SCOPE RULES (build only what's described; simplest solution; no Docker/auth/backend unless explicitly requested).
- The existing CDN + ALPINE.JS USAGE notes for default static stack.
- Omitted: any template-specific guidance ("this is a portfolio", "this is a CRUD list"). Description is the only voice on what the app *is*.

**Re-used machinery (no new code paths):**
- `is_valid_key("custom")` → True automatically.
- `build_rules_for("custom", "none")` → returns the new prefix.
- `_has_template_app("custom")` → False (no base app folder), so `routes_tasks.py:362` runs `_ensure_app_skeleton(slug, "none")` — the same path the 13 template-less templates already use.
- `requires_supabase("custom", "none")` → False, so the Supabase gate doesn't fire.
- `_is_generic_description` heuristic: irrelevant. The instant-build branch at `routes_tasks.py:374` requires `template_app_used=True`; Custom never sets that flag, so the agent always runs.

### 3. Edge cases + testing

| Case | Handling |
|---|---|
| User picks Custom + leaves description empty | Existing toast: "Either drop project files OR describe what you want to build." No change. |
| User picks Custom + uploads files | Dropzone path takes over (`stagedOk.length > 0`) and skips the AI build. `template_key` is ignored. No change. |
| User picks Custom + filters "Dynamic" | Custom card stays visible (rendered after the loop, not subject to filter). |
| User clicks "Use custom" then "Change" | Gallery re-opens; user picks again. |
| Slug already exists | Existing 409 handling. No change. |
| Description "build me a Python Flask app" | Baseline prefix says "default static unless explicitly asked"; the description wins. Agent builds Flask. |
| Generic description "build me an app" with no template_app folder | Instant-build requires `template_app_used=True`. Custom never sets that, so agent always runs. |
| Future template additions | Custom stays at the bottom (rendered after the data loop). |

**Testing**

| Layer | Test | Tool |
|---|---|---|
| Backend unit | `tests/test_templates.py`: `is_valid_key("custom")`; `build_rules_for("custom", "none")` returns non-empty string containing the layout + scope rules; `_has_template_app("custom")` is False; `requires_supabase("custom", "none")` is False. | pytest |
| Backend smoke | POST `/api/tasks` with `{"template_key": "custom", "description": "x", "action_type": "BUILD"}` creates a task with the prefix prepended. | pytest + httpx ASGI |
| Frontend manual | New-project modal → Select template → last card shows Custom with dashed border + `+` glyph → click "Use custom" → modal closes → pill shows "Custom" → submit with a real description → task created, agent runs, no 500. | Browser |
| Frontend regression | Pick a real template, submit — still works. "Must pick a template" guard still fires when no card is selected. | Browser |

## Acceptance

- [ ] Custom card visible as the last card in the gallery, regardless of active filter.
- [ ] Clicking Custom sets `template_key="custom"` and closes the modal.
- [ ] Submitting with Custom + a real description creates a task whose stored `description` includes the generic baseline prefix.
- [ ] The agent run completes without a `ValueError` from `build_prompt` (the prompt-template fix from `93550e7a0` already covers this).
- [ ] Existing template flow unaffected.
- [ ] `tests/test_templates.py` covers the new `"custom"` entry.
