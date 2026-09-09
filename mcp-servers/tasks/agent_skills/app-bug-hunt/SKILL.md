---
name: app-bug-hunt
description: Look for the specific things most likely to be broken in one of the user's apps. Use when asked to find bugs, why something is not working, or to check an app for problems.
allowed-tools: code
metadata:
  tags: apps, code
---

# Hunt for bugs

## Steps

1. `list_my_apps`, then `search_my_app` for the usual failure points: form
   submission, error handling, empty states, anything fetching data.
2. `read_app_file` on what looks suspicious.
3. Report each with the file, what breaks it, and what a user would see.

## Rules

- "What a user would see" is what makes this worth reading. A finding
  without it is a code comment.
- Read before reporting. A bug guessed from a file name is not a bug.
- Do not fix anything. `propose_app_change` is a separate request.
