---
name: build-an-app
description: Build a new app, site or landing page for this person, then change it after they approve. Use when asked to build, create or make an app, a website, a landing page or a page that does not exist yet.
allowed-tools: code
metadata:
  tags: apps, code
---

# Build an app

## Steps

1. If what they want does not exist yet, `create_app` with their own words as
   the description. Do not ask them to pick an existing app first.
2. Give them the link from the result, exactly as it is written, and say it
   takes a few minutes.
3. `build_status` with the id from `create_app` when they ask how it is
   going, and before you ever say an app is ready.
4. To change an app that already exists, `list_my_apps`, read the file you
   would change, then `propose_app_change` and wait for their yes before
   `apply_app_change`.

## Rules

- Creating and changing are different jobs. A new app starts from nothing, so
  there is nothing to approve first; a change can destroy work, so it is
  always propose, then their yes, then apply.
- Never answer a request to build something by listing apps that are not it.
  Asked for a camera landing page, an agent once offered three unrelated slugs
  and asked which to put it in. Build the thing.
- One build runs at a time on this platform. If the builder refuses because
  another is running, say exactly that and offer to start it when that one
  finishes, rather than reporting a failure.
- The description is the brief the builder works from, so pass on what they
  asked for rather than your summary of it.
- Say what the app is called once it exists. A slug is how they will find it
  again.
