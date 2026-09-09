---
name: meeting-scheduler
description: Find a free slot in the user's calendar and draft the invitation. Use when asked to schedule, book, set up a meeting or a call, or find a time.
allowed-tools: calendar gmail
metadata:
  tags: calendar, planning
---

# Schedule a meeting

## Steps

1. `list_calendar_events` for the days in question. Their real calendar,
   never an assumed working week.
2. Offer two or three slots that are genuinely free, in their own timezone.
3. When they pick one, `create_calendar_event`, and draft the invitation
   with `draft_email` if other people need telling.

## Rules

- **Never book or invite anyone without being asked.** Offer the times, wait.
- Say the timezone every time. A meeting at the wrong hour is the whole
  failure mode of this job.
- Leave a gap either side of an existing event rather than butting a call
  straight onto another one.
- If the calendar cannot be read, say so and say the times are unverified.
  Never guess at somebody's availability.
