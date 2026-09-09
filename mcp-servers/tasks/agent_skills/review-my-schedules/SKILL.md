---
name: review-my-schedules
description: Show what is set to run automatically and whether it should still be. Use when asked about schedules, automations, what runs automatically, or to tidy up recurring jobs.
allowed-tools: schedules
metadata:
  tags: automation
---

# Review the schedules

## Steps

1. `list_my_schedules`.
2. Report each one in plain words: what it does, when it runs, whether it is
   on, and when it last ran.
3. Flag the two kinds worth attention: enabled but failing, and enabled but
   plainly superseded.

## Rules

- Translate the cron. Nobody reads "0 6 * * 1" and thinks "Monday at 6am".
- Change nothing. `disable_schedule` and `delete_schedule` are theirs to ask
  for; a tidy-up that removes something silently is unrecoverable.
- If there are none, say so in one line.
