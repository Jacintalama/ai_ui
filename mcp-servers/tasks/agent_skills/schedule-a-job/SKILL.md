---
name: schedule-a-job
description: Set up a recurring job that runs as this agent on a schedule. Use when asked to do something every day, every week, at a certain time, on a schedule, or as a recurring reminder.
allowed-tools: schedules
---

# Schedule a recurring job

## Steps

1. Work out the cron expression from what they said. "Every morning" is not a
   time; ask for one if they did not give it.
2. `create_schedule` with a name they will recognise in a month, the cron
   expression, and the prompt the run should carry out.
3. Say back in plain words what will happen and when. "Every weekday at
   9:15am", not "15 9 * * 1-5".

## Rules

- The prompt is what a future run receives with no conversation around it, so
  it has to stand alone. "Do that" will do nothing in a week.
- Their timezone, not the server's. Check before assuming.
- Before making a second schedule that sounds like an existing one,
  `list_schedules` and ask whether they meant to replace it.
- Describe what you asked for, never what a create response echoed back.
