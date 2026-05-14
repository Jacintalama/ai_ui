# Flight-booking template — light redesign + Saved Trips view

**Date:** 2026-05-14
**Status:** Design approved, ready for implementation planning
**Scope:** One template app — `mcp-servers/tasks/template_apps/flight-booking/`

## Problem

Two issues with the `flight-booking` base template:

1. **"Saved" is a dead end.** The header shows a `Saved (n)` counter, but the
   button does `setView('search')` — there is no Saved Trips screen. A user
   saves a flight, sees the counter increment, clicks "Saved", and lands back
   on the search form. The save *does* persist to `localStorage` (the
   `persistence.js` layer works correctly) — but there is no UI to view or
   manage saved trips, so it appears broken.

2. **The default look is dark and "tech startup", not "professional".** The
   template ships with a dark navy background (`#0a1f3d`) and coral accent
   (`#ff6b5b`). The user wants a lighter, more professional default.

This is the **base template** — every flight-booking app generated from it
inherits these problems, and the agent's "CUSTOMIZE MODE" personalises a copy
rather than fixing the base.

## Goal

Make the `flight-booking` base template ship with:
- A working **Saved Trips** view (the counter leads somewhere real).
- A **light, professional theme** with refined typography.

Approach chosen: **targeted re-skin + add one view**. Keep the existing
layout, structure, animations, and the 4 current views unchanged. Do not
refactor the template architecture.

## Design

### Part 1 — Saved Trips view

Files: `src/main.js`, `index.html`.

`src/main.js`:
- Add `"saved"` to the router's `views` array
  (`["search", "results", "detail", "review", "saved"]`).
- Add method `removeTrip(flightId)`: removes the matching entry from
  `savedTrips`, calls `_save("savedTrips")`, toasts "Trip removed".
- `saveTrip()` and the `createPersistence` layer are **unchanged** — they
  already work correctly.

`index.html`:
- Header "Saved" button: change `@click="setView('search')"` to
  `@click="setView('saved')"`.
- Add `<section x-show="view === 'saved'" x-transition.duration.200ms x-cloak>`:
  - Heading + a "← Back to search" control consistent with the other views.
  - `x-for` over `savedTrips`, each rendered as a card showing route, airline,
    cabin, time labels, duration, stops, price — visually consistent with the
    results-view cards.
  - Clicking a saved card reopens that flight's Detail view via the existing
    `openDetail(f.id)`.
  - A "Remove" button per card calling `removeTrip(f.id)`. The remove button
    must not also trigger the card's open-detail click (stop propagation).
  - Empty state when `savedTrips.length === 0`: "No saved trips yet — save a
    flight from its detail page."

### Part 2 — Light theme re-skin

Files: `styles/main.css`, `index.html`.

`styles/main.css` — replace the palette CSS variables:

| Variable      | New value  | Role                       |
|---------------|------------|----------------------------|
| `--bg`        | `#f4f5f7`  | soft cool-gray page background (not white) |
| `--bg-card`   | `#ffffff`  | white cards that lift off the background |
| `--border`    | `#e5e7eb`  | card / input borders        |
| `--text`      | `#1f2937`  | primary text                |
| `--text-muted`| `#6b7280`  | secondary text              |
| `--accent`    | `#2563eb`  | primary action / price blue |

Keep the `prefers-reduced-motion` guard, the `[x-cloak]` rule, and the
`article` transition. Update the `html { background }` rule to the new `--bg`.

`index.html`:
- Swap the Google Fonts link from Inter to **Plus Jakarta Sans**
  (weights 400/500/600/700/800). Update the `font-family` in `styles/main.css`
  accordingly.
- Rewrite the hardcoded dark Tailwind utilities — they assume a dark
  background and must change for a light one. This spans every section
  (header, search, results, detail, review, the new saved view, toast):
  - `text-white` → `text-[var(--text)]`; `text-white/60`, `text-white/50`,
    `text-white/40` → `text-[var(--text-muted)]`.
  - `bg-white/5`, `bg-white/10` → `bg-[var(--bg-card)]` with
    `border border-[var(--border)]` and `shadow-sm` (cards lift via shadow,
    not translucency).
  - `border-white/10`, `border-white/5` → `border-[var(--border)]`.
  - Header: from the dark translucent bar to a white bar with a bottom
    border (`bg-[var(--bg-card)]` + `border-b border-[var(--border)]`); keep
    the existing scroll-shrink behaviour.
  - Filter pills' selected/unselected states, range slider track colours,
    `<select>`/`<input>` field styling, result cards, detail panels, review
    panels, the seat-map SVG fills, and the toast — all re-skinned to the
    light palette.
- All colour references route through the CSS variables so a future re-skin
  is a variables-only change. This is a light touch toward token-driven
  theming, **not** a full architecture refactor.

The `<title>` stays "Skylane" (the template's placeholder brand).

## Out of scope

- Already-generated apps (`alama-flight`, `pacific-wings`, `tokyo-air`) — this
  changes only the base template; existing apps are untouched.
- The build-prompt rules, the `search_flights` MCP hint, and `src/data.js`
  seed data.
- The `src/lib/` files (`router.js`, `persistence.js`, `skeleton.js`) — used
  by other templates; not modified.
- Layout/spacing overhaul, result-card restructuring, airline logos — the
  approved approach is a re-skin, not a layout redesign.
- Template architecture refactor (token/config-driven theming as a system).
- New dependencies or a build step — stays Tailwind CDN + Alpine + ES modules.

## Testing & verification

Template apps have no unit tests (consistent with the other 14 templates in
`template_apps/`). Verification is manual + the existing static-structure
test:

- Preview the base template directly and click through all **5** views
  (search → results → detail → review, plus saved).
- Save a trip from a Detail view → confirm it appears in the Saved view →
  remove it → confirm it disappears and the counter updates → reload the page
  → confirm a still-saved trip persists.
- Confirm `tests/test_functional_templates_static.py` still passes (it
  validates template structure / that `main.js` imports resolve).
- Generate one fresh `flight-booking` app end-to-end and confirm the agent
  still customises the new light base cleanly (CUSTOMIZE MODE intact).

## Deployment

Template file change. Deploy path matches prior template/source deploys:
- SCP the 3 changed files (`index.html`, `src/main.js`, `styles/main.css`) to
  the server's `mcp-servers/tasks/template_apps/flight-booking/`.
- Rebuild + recreate the `tasks` container
  (`docker compose -f docker-compose.unified.yml up -d --build tasks`).
- Verify the container is healthy and the template preview serves the new
  light look.
