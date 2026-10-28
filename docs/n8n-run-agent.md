# Run an agent from n8n

Since 2026-10-27 anything outside the platform can run one of your agents
and get its answer, with the same brief, skills, memory and tools the agent
has in the office and on Discord. n8n is the first caller; a script or a
cron job works the same way.

## 1. Make a key

Agents page → **Automation** → give the key a label → **New key**. Copy
it: it is shown once. The key starts with `iok_`. Revoke it from the same
panel when a workflow is retired. You can hold ten live keys.

## 2. Call the route

```
POST https://ai-ui.coolestdomain.win/api/tasks/agents/run
Authorization: Bearer iok_...
Content-Type: application/json

{"agent": "Ada", "message": "What is due this week?"}
```

`agent` is the agent's name or its id. `message` is what you would have
typed to it. The reply:

```json
{"id": "6f1c...", "status": "done",
 "agent": {"id": "agent-ada-1a2b", "name": "Ada"},
 "answer": "Two invoices are due Friday...", "notes": []}
```

`status` is `done` or `failed`. `notes` carries what the agent refused to
do and why. An unknown agent is a 404 that lists the agents you have; a
missing or revoked key is a 401.

### Long runs

A turn with tools can take a minute or two. Send `callback_url` and the
call returns at once with `"status": "accepted"` and an `id`; the same
result shape is POSTed to that URL when the agent finishes, with the `id`
in it. The URL must be public: anything on the platform's own box or a
private network is refused.

In n8n: a **Webhook** node gives you the callback URL; put it in the
request, then let the workflow continue from the webhook.

## 3. What the agent may do

Nobody is watching an automated run, so there is nobody to ask. An agent
set to **All** on the Agents page acts; one set to **Ask** or **Read**
reads and answers, and says in `notes` what it did not do. Set the agent
to All on purpose for the workflows that should send, write or change
things.

Runs are capped at two at a time per tasks process
(`AUTOMATION_CONCURRENCY`); more queue. A message is at most 20,000
characters.

## 4. The sample workflow

`docs/n8n/run-agent.workflow.json` imports into n8n as is: a webhook in,
an HTTP Request to the route, and the answer back out. Open the HTTP
Request node and paste your key into the Authorization header.

Every run shows on the office floor and in the activity log as an
automation run.
