---
name: invoice-tracker
description: Build something to track invoices and what is unpaid. Use when asked about invoices, receivables, who owes money, or chasing payment.
allowed-tools: excel_creator
metadata:
  tags: data
---

# Track invoices

## Steps

1. Build with `create_excel`: invoice number, client, amount, sent date, due
   date, paid date, and a status column driven by a formula.
2. Make the status compute itself from the dates rather than being typed.
3. Add a total outstanding, also a formula.

## Rules

- Status is derived, never typed. A typed status is wrong the day after it
  is typed and nobody notices.
- Overdue must be visibly different from unpaid but not yet due. They are
  different problems.
- Never enter real invoice figures you were not given.
