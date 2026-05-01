# Tasks Panel Launcher (FAB) — Design

**Date:** 2026-05-01
**Branch:** `feat/gdrive-gmail-connectors`
**File primarily affected:** `mcp-servers/tasks/static/task-panel.js`

## Problem

The admin tasks panel auto-pops in the center of the page (520px card) on every fresh page load when there are pending or done tasks. This is fine for developers but disruptive for everyday users — the panel obstructs the chat input on first paint, has no obvious "where did this come from" affordance, and is easy to dismiss accidentally with no clear way to bring it back.

## Goal

Replace the auto-popup with a small persistent floating launcher icon that lives near the temp-chat icon at the bottom-right of the viewport. Click the icon to open the panel; close the panel and it collapses back to the icon. Mobile gets a bottom-sheet layout.

## Approach

Fixed-position floating action button (FAB) anchored to the viewport — not DOM-injected into Open WebUI's chat toolbar. Robust against Open WebUI DOM changes; matches the visual position of the temp-chat icon without depending on its markup.

## Components

### 1. Launcher button (FAB)

- Position: `position: fixed; bottom: 24px; right: 24px;` (desktop) — visually adjacent to the temp-chat icon
- Size: 44×44 px desktop, 48×48 px mobile (tap-friendly)
- Style: dark circle (`#1a1a1a` background, `#2a2a2a` border), matches existing panel chrome
- Icon: clipboard / checklist glyph
- Count badge: red circle in upper-right of FAB showing pending count; hidden when count is 0
- Subtle pulse animation when pending count increases (auto-fades after ~3 s)
- Visible only when signed in as admin
- Hidden while the panel is open

### 2. Panel (open state)

**Desktop (> 640 px width):**
- Keep existing 520 px card with tabs, task list, all current actions
- Anchor: `bottom: 80px; right: 24px` (slides up from FAB position, replaces current `top: 24px; right: 24px`)
- `max-height: 78vh`
- Existing `X` close button collapses back to FAB
- Existing minimize button removed (FAB replaces that role)

**Mobile (≤ 640 px width):**
- Bottom sheet: full width, slides up from bottom edge
- `max-height: 85vh`
- Drag handle bar across the top
- Tap outside / close button collapses back to FAB
- Same content (tabs, task cards) laid edge-to-edge

### 3. Removed / changed

| Item | Change |
|---|---|
| Auto-popup on first load (`init()` showing panel when tasks exist) | **Removed** — FAB is the only auto-visible affordance |
| `DISMISS_KEY` 4-hour TTL | **Removed** (no longer needed) |
| Minimize button in panel header | **Removed** |
| `AUTOSHOW_KEY` toggle in `+` integrations menu | **Removed** — FAB makes it redundant |
| `+` integrations menu "Tasks" entry | **Kept** — secondary entry point |
| `window.aiuiTaskPanel.open()` API | **Kept** for any external callers |

## Behavior summary

- On first paint (admin signed in): FAB renders bottom-right with badge count.
- User clicks FAB → panel slides up from FAB position; FAB hides.
- User clicks `X` (or taps outside on mobile) → panel slides back down; FAB reappears with current count.
- New pending task arrives via SSE / refresh: badge count updates; FAB pulses briefly.
- Sign-out / on auth route: FAB and panel hidden.

## What stays the same

- All existing task rendering logic (`renderPending`, `renderProgress`, `renderDone`)
- SSE streaming during running/planning states
- The `+` integrations menu entry as an alternate way to open the panel
- The left-sidebar "App Builder" injection (unrelated)
- Plan / Approve / Cancel / Manual / AI buttons inside task cards

## Out of scope

- Animation polish beyond the simple slide-up + pulse
- Keyboard shortcut to open the panel
- Persisting "panel was open" state across page reloads (deliberately simpler — always starts collapsed)
- Reskinning the panel cards themselves

## Files touched

- `mcp-servers/tasks/static/task-panel.js` (CSS + DOM + behavior changes)

No other files affected. Image cache-bust query string in `openwebui-overrides/index.html` (`?v=20260425-oi`) will be bumped on deploy.
