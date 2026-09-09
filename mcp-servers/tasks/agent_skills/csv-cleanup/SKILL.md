---
name: csv-cleanup
description: Turn messy tabular data into something usable. Use when asked to clean up data, fix a spreadsheet, or sort out a messy list.
allowed-tools: excel_creator
metadata:
  tags: data
---

# Clean up data

## Steps

1. Say what is wrong before changing anything: duplicated rows, mixed date
   formats, headers in the middle, blank required fields.
2. Fix it and rebuild with `create_excel`.
3. Report what you changed and how many rows each change touched.

## Rules

- Never delete a row without saying so and how many. Silent deletion of data
  is the one unrecoverable mistake here.
- Where a value is ambiguous, leave it and flag it rather than picking one.
- Keep the original column order and names unless asked otherwise.
