---
name: thread-summary
description: Read a long email thread and say what was decided and what is outstanding. Use when asked what happened in a thread, to catch up on a conversation, or what someone agreed to.
allowed-tools: gmail
metadata:
  tags: email
---

# Summarise a thread

## Steps

1. `search_emails` to find the thread, then `read_email` on each message in
   it, oldest first.
2. Write three things and nothing else:
   - **Decided** - what was actually agreed, and by whom.
   - **Open** - what was raised and never settled.
   - **Owed** - who owes what, and by when if a date was given.

## Rules

- Attribute every decision to the person who made it. "It was agreed" hides
  the thing they need to know.
- If the thread never decided anything, say so. A summary that invents a
  conclusion is worse than one that reports a mess.
- Do not quote at length. A summary that is as long as the thread has failed.
