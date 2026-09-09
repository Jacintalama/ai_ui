---
name: review-my-app
description: Read one of the user's built apps and say what is wrong with it. Use when asked to review an app, look at code, find bugs, or check a site.
allowed-tools: code
metadata:
  tags: apps, code
---

# Review an app

## Steps

1. `list_my_apps` to find it, then `read_app_file` on the parts that matter,
   or `search_my_app` when looking for something specific.
2. Report in order of what would hurt: broken behaviour first, then security,
   then things that are merely untidy.
3. For each, say the file and what is wrong, not just that something is.

## Rules

- Read before judging. A review written from the app's name is worthless.
- Change nothing. `propose_app_change` exists for that and it is a separate
  request.
- Say what you did not read. A review of three files out of thirty is a
  review of three files, and saying so is the difference between useful and
  misleading.
