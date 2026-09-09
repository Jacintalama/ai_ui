---
name: protect-focus-time
description: Find the unbroken stretches in the week and offer to block them. Use when asked about focus time, deep work, when there is time to think, or a quiet block.
allowed-tools: calendar
metadata:
  tags: calendar, planning
---

# Protect focus time

## Steps

1. `list_calendar_events` for the week ahead.
2. Find every unbroken stretch of two hours or more inside working hours.
3. List them, longest first, and offer to block one.

## Rules

- Only block with `create_calendar_event` when they say to. Offering is the
  job; booking is their decision.
- A stretch broken by a fifteen minute call is two stretches, not one. Say so
  rather than rounding it away.
- If there are none, say there are none and name the busiest day. That is the
  useful finding.
