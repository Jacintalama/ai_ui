---
name: draft-reply
description: Write a reply to an email in the user's own voice and show it before anything is sent. Use when asked to reply, respond, answer someone, or draft a message.
allowed-tools: gmail
metadata:
  tags: email, writing
---

# Draft a reply

## Steps

1. `read_email` on the message being replied to. Never write a reply from a
   subject line alone.
2. Draft it. Match how they write: if their other mail is short, yours is
   short.
3. Show the draft in full and stop. Use `draft_email` if they want it saved
   in Gmail; use `send_email` or `reply_to_email` only when told to send.

## Rules

- **Never send without being asked to send.** "Reply to Sam" means write it.
  Only "send it" means send it.
- Answer every question the original asked. A reply that addresses one of
  three is worse than none, because they will think it is handled.
- Do not invent facts to fill a gap. Leave a marked blank and say what is
  missing.
- No "I hope this email finds you well".
