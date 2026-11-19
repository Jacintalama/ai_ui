# n8n steps that use your AIUI connections

Since 2026-11-19 an n8n workflow can use the apps you connected in AIUI
(Trello, Airtable, GitHub, HubSpot, Google Drive and the rest) without
connecting them again in n8n. Your app keys stay in AIUI. The only thing
stored in n8n is an AIUI key, which only AIUI accepts and which you can
revoke in one place.

To run a whole agent from n8n instead, see `n8n-run-agent.md`.

## The easy way: ask in the chat

Connect n8n in AIUI first (Connections, n8n, your n8n URL and an API key
that may create credentials). Then ask, for example:

> Every morning at 8, read my Leads sheet and approve any open pull
> request on my-org/my-repo that has "ready" in the title.

AIUI will:

1. Ask to **link AIUI to your n8n** (first time only). This makes an AIUI
   key and saves it in your n8n as a credential called **AIUI**.
2. Ask to **create the workflow**: a schedule, then AIUI steps (Drive
   read, GitHub list pull requests, GitHub review).
3. Create it switched off, like every workflow it builds. Switch it on
   from the chat or in n8n.

Saying yes to the workflow is what lets its writing steps (here, the
approve) run. A writing step you add by hand in n8n later is refused
until you ask AIUI to add it, and AIUI asks you first.

## What a step is

An ordinary n8n **HTTP Request** node:

- Method `POST`, URL `https://ai-ui.coolestdomain.win/api/tasks/tools/run`
- Authentication: Generic Credential Type, Header Auth, credential **AIUI**
- JSON body:

```json
{"app": "github", "tool": "list_repo_pull_requests",
 "args": {"owner": "my-org", "repo": "my-repo"}}
```

## The route

```
POST /api/tasks/tools/run
Authorization: Bearer iok_...        (a key with the tools scope)
{"app": "...", "tool": "...", "args": {...}}
```

| Status | Means |
|---|---|
| 200 | The tool's own result, the same as the chat gets |
| 401 | No key, or the key is unknown or revoked |
| 403 | The key cannot run tools (a key made on the Agents page runs agents only); or the step writes and was never approved in AIUI; or it is an n8n tool or `link_aiui`, which never run from a key |
| 404 | Unknown app or tool; the message lists what exists |
| 409 | You have not connected that app in AIUI |
| 422 | `args` is not an object, a required argument is missing, or the app refused (its reason is in the message) |
| 502 | A Google service did not answer |

Apps: every app in AIUI's per-user tool list, plus Google reads only:
`gdrive_search_files`, `gdrive_list_files`, `gdrive_read_file` (a Sheet
comes back as CSV), `gmail_search_emails`, `gmail_read_email`,
`calendar_list_events`.

## Turning it off

Agents page, Automation: the key labelled **n8n (made by AIUI)** says
"Runs tools (n8n)". Revoke it and every AIUI step in your n8n stops at
once (401). Asking AIUI to link again makes a new one; approvals carry
over.
