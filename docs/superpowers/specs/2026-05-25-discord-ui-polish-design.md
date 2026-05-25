# Discord UI Polish — Design Spec

**Date:** 2026-05-25
**Status:** Approved (brainstorm) → implementing
**Builds on:** `feat/discord-schedules-ux`

## Goal
Polish every button/panel/card across the bot — both the #app-builder channel
and the per-user private threads. "Nicer look + less clutter." Reliable classic
primitives (string-selects + embeds), since we send raw JSON (no library). We
researched Components V2 but chose embeds/selects for ~90% of the look at far
less risk (V2 disables content/embeds and reworks every message).

## Phases

### Phase 1 — App Builder template grid → dropdown (this commit)
Today: 25 template buttons in a grid. After: a header + a single **"▼ Pick a
template…"** string-select (one option per template, emoji + 1-line description)
+ a **⬜ Blank** button.
- `app_builder_panel.build_panel_payload(templates)` → header content + a
  `TEMPLATE_SELECT_ID = "aiuibuild:tplselect"` dropdown (value = template key,
  label = "emoji label", description = template description, ≤25 options) +
  the existing Blank button.
- `is_template_select(custom_id)` predicate.
- Routing: selecting a template → respond with the build **MODAL** for that key
  (a select interaction may return a type-9 modal), same private-thread build
  flow afterward. The Blank button keeps its existing button→modal route.

### Phase 2 — Colored embed cards (next)
`DiscordClient` gains `embeds` support on post/edit/followup. Schedule card,
build-ready, and published messages become embeds with a status/context color:
schedule 🟢 active / ⏸ paused / ⚠️ failed; build-ready blue; published green.

### Phase 3 — Consistency sweep (next)
Standardize button colors/emojis/labels/order across all remaining surfaces.

## Testing
Phase 1: `build_panel_payload` now yields a template select + Blank (pure test);
template-select routing → build modal (interaction test); existing
`build_panel_payload` button-grid tests updated to the dropdown shape. All in
the webhook-handler venv (currently 277 green).

## Honest scope
Phase 1 is self-contained and fully TDD'd. Phases 2–3 are follow-ups (Phase 2
touches DiscordClient + several card builders). No tasks-service change in
Phase 1. Live Discord smoke (open panel → pick template from dropdown → build)
needs a deploy.
