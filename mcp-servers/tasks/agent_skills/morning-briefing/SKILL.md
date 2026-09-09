---
name: morning-briefing
description: Set up a briefing that arrives every morning with what matters that day. Use when asked for a morning summary, a daily briefing, or to be told what is happening each day.
allowed-tools: schedules
metadata:
  tags: automation, reporting
---

# Morning briefing

## Steps

1. Agree what goes in it: calendar, mail needing a reply, tasks due.
2. Write the prompt so it stands alone, because a scheduled run has no
   conversation around it.
3. `create_schedule` on a weekday cron at a time before their first meeting.

## Rules

- Ask what time they start. A briefing that arrives after the first meeting
  has missed the point of being a briefing.
- Weekdays unless they say otherwise.
- `list_my_schedules` first, in case one already exists.
