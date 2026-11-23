---
name: build-a-workflow
description: Build an n8n workflow for someone who describes, in their own words, a job they want done automatically between their apps. Use when asked to automate something, make a workflow, connect two apps so one updates the other, or have something happen on its own every time.
allowed-tools: server:mcp-proxy schedules
metadata:
  tags: automation, n8n
---

# Build a workflow from plain words

The person may never have automated anything. Never say trigger, node,
webhook, endpoint, POST, API, cron, credential or JSON to them,
not even in brackets, unless they said it first. Say "a web address" and "sends".
You work out those parts yourself from their answers.

First, look at n8n in the list of apps. If it is not connected (or you
have no n8n tools), say so in your first sentence: their n8n is not
connected yet, and they connect it from Connections with their n8n
address and an API key (in n8n: Settings, n8n API, Create an API key).
You can still ask the questions below, but do not say you will build it
until it is connected.

## Steps

1. Ask what should happen, in their words: "What would you like done for
   you?" Get the result they want, and which of their apps it touches.
2. Ask "When should this happen?" and offer plain choices:
   - when you press a button,
   - every day or every week at a time you pick (ask the time and their
     timezone),
   - when another app or website sends something to a web address you
     give them once it is on.
   One question at a time. If their first answer already says when, do
   not ask again.
3. `list_my_workflows`: is there one like this already? If so, ask
   whether to change it rather than make a second.
4. Use the apps they connected in AIUI, never ask them for an app's key.
   Call `link_aiui` once for the credential id, then each step that reads
   or writes an app is an aiuiTool step naming that app and tool.
5. Say the plan back in one or two plain sentences, e.g. "Every Monday at
   9am I will read last week's GitHub issues and post a summary to your
   team channel." Build it only after they say yes.
6. `create_workflow`. It is made switched off. Tell them what it is called,
   then offer to switch it on (`activate_workflow`), and for a web-address
   start, give them the address to paste into the other app.
7. If the build is refused, read the reason, fix that step and try again.
   Do not tell them about the refusal unless you cannot fix it.

## When n8n is not the right place

- When an email arrives: their n8n cannot start from an email through
  AIUI yet. Offer Automations instead (Agents page, Automation): a rule
  that starts on an email matching a search and has an agent do the job.
- A job that is only "every morning, tell me X" or "every Friday,
  summarise Y" needs no workflow: make it in Schedules with
  `create_schedule`.
- An app they have not connected in AIUI: say which one, and that it is
  connected from Connections.

## Rules

- Describe what you built from what you asked for, never from what a
  create response echoed back.
- Never delete or change a workflow they did not name.
- Plain words about time: "every weekday at 9:15am", not "15 9 * * 1-5".
