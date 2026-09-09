---
name: spreadsheet
description: Build a real spreadsheet file when the deliverable is a spreadsheet. Use when asked for a spreadsheet, an xlsx, a table to download, a budget or a tracker.
allowed-tools: excel_creator
metadata:
  tags: data, documents
---

# Spreadsheet work

Use when the thing they want to end up with is a file, not numbers in a chat
answer.

## Steps

1. Get the shape straight first: what the columns are, what one row means.
   Ask only if that is genuinely unclear.
2. Build it with `create_excel`, or `create_simple_excel` for a plain table.
3. Say what you made, what is in it, and hand back the download.

## Rules

- Use formulas, not answers you worked out and typed in. The sheet has to
  recalculate when its inputs change.
- A header on every column, and a sheet name that says what the sheet is.
- If you assumed a number, mark it where the reader will see it, not in a
  chat message they will lose.
- Follow the columns they asked for exactly. A better design that is not what
  they asked for is a failure.
