---
name: metric-definition
description: Pin down exactly what a number means before anybody reports it. Use when asked to define a metric, what counts as something, or why two reports disagree.
metadata:
  tags: data, reporting
---

# Define the metric

## Steps

1. Write the definition as a sentence somebody could compute from: what is
   counted, over what period, excluding what.
2. Name the edge cases and decide each one explicitly.
3. Give the definition back and ask them to confirm it before it is used.

## Rules

- Exclusions are the definition. "Active users" without saying what inactive
  means is not a definition.
- If two reports disagree, the answer is almost always two definitions. Find
  both before proposing a fix.
- Never invent a threshold. Ask for it.
