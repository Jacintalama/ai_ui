---
name: find-my-file
description: Find a file in Drive by what the user remembers about it. Use when asked to find a file, where a document is, or what happened to something.
allowed-tools: gdrive
metadata:
  tags: documents
---

# Find a file in Drive

## Steps

1. `search_drive` for the words they gave you.
2. If nothing matches, try the obvious variations before giving up: the
   client's name, the month, the project.
3. Report matches with enough to tell them apart: name, folder, last changed.

## Rules

- Say what you searched for. A search that failed on one word is fixed by
  them giving you a better word, and they cannot do that if you do not say.
- More than five matches means say how many and show the five most recent.
- Never open or change a file you were only asked to find.
