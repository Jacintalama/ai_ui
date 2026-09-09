---
name: recurring-digest
description: Set up a summary that arrives on its own every day or week. Use when asked for a daily summary, a weekly report, to be kept updated, or to be told something regularly.
allowed-tools: schedules
metadata:
  tags: automation, reporting
---

# Set up a recurring digest

## Steps

1. Establish three things: what goes in it, how often, and at what time.
2. Write the prompt the run will receive. It must stand alone: a future run
   has no conversation, so it needs to say what to gather and how to present
   it.
3. `create_schedule` with that prompt, then say what will arrive and when.

## Rules

- Write the prompt as instructions to somebody who was not here, because that
  is exactly what a scheduled run is.
- Pick a time that is useful, not the current time. A daily digest at 3pm is
  a digest of a day that is half over.
- `list_my_schedules` first and say if one like it already exists.
