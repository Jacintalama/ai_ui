---
name: blocker-report
description: Find what is blocked and who it is waiting on. Use when asked what is stuck, what is blocked, what is holding things up, or why something has not moved.
allowed-tools: server:mcp-proxy
metadata:
  tags: planning, reporting
---

# What is blocked

## Steps

1. Read open tasks from the connected trackers.
2. For each one that has not moved in three days, work out what it is waiting
   on: a person, a decision, or another task.
3. Group by **who or what it waits on**, not by project. That is the shape
   that tells somebody what to do next.

## Rules

- Name the person a task waits on. A blocker with no owner is a blocker
  nobody will clear.
- Distinguish "waiting on someone" from "nobody has started it". They look
  identical in a tracker and need opposite responses.
- Never guess at a cause. If the tracker does not say why, say it does not
  say why.
