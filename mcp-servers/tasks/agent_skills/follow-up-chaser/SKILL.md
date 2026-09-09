---
name: follow-up-chaser
description: Find messages the user sent that nobody answered, so nothing goes quiet unnoticed. Use when asked what is waiting, what has gone quiet, who has not replied, or what needs chasing.
allowed-tools: gmail
metadata:
  tags: email, triage
---

# Chase what went quiet

## Steps

1. `search_emails` for mail they sent in the last 30 days.
2. For each, check whether a later message in the same thread came back.
3. Report only the ones with no answer, longest silence first.

## Rules

- One line each: who, what it was about, how many days of silence.
- Say what you searched. "In the last 30 days" is part of the answer, not a
  caveat on it.
- Do not chase anything yourself. Report, and let them decide.
- Automated mail and no-reply addresses never count as waiting.
