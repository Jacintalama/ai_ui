---
name: budget-tracker
description: Build a budget or expense tracker they can keep using. Use when asked for a budget, expense tracking, costs, or somewhere to record spending.
allowed-tools: excel_creator
metadata:
  tags: data
---

# Build a budget tracker

## Steps

1. Ask what they are tracking and over what period, if they have not said.
2. Build it with `create_excel`: one row per entry, columns for date,
   description, category and amount, and a totals row that uses a formula.
3. Add one example row showing the format expected, and say it is an example.

## Rules

- Totals are formulas, always. A typed-in total is wrong the moment they add
  a row, and they will not notice.
- Include a category column even if they did not ask. A tracker without one
  cannot answer the question they will have in a month.
- Never invent their actual figures. Build the thing empty unless they gave
  you real numbers.
