---
name: watch-for-changes
description: Set up a recurring check on something that might change. Use when asked to keep an eye on something, watch a page, or be told if something changes.
allowed-tools: schedules
metadata:
  tags: automation, research
---

# Watch something

## Steps

1. Establish exactly what is being watched and what counts as a change worth
   hearing about.
2. Write the prompt to report only differences, not the current state each
   time.
3. `create_schedule` at a frequency that matches how fast the thing moves.

## Rules

- "Report only if it changed" has to be in the prompt, or they get an
  identical message every day and stop reading it.
- Match the frequency to the thing. A daily check on something that changes
  quarterly is noise with extra steps.
- Say what the first run will establish as the baseline.
