# Agents in channels: the bot picks the right agent for you

Date: 2026-08-24
Status: design, awaiting review
Depends on: the AI Agents feature shipped 2026-08-24 (`feat/ai-agents`)

## What we are building

Today every message to the bot, on Discord, Telegram, Slack, Mattermost, the
CLI or Buzz, is answered by one fixed model. An agent you built is only usable
on the web.

After this, you message the bot the way you always have, and it works out which
of your agents fits and answers as that agent, with that agent's instructions
and that agent's tools, acting as your account. The reply says which agent
answered. If it picked wrong you say so in a sentence and it switches for the
rest of the conversation.

There is no syntax to learn and nothing to set up. That is the point: the whole
platform is aimed at "just ask", so an agent feature that needs you to remember
a command would be a step backwards.

## Why it is small

An agent is an Open WebUI model row. The gateway already sends a model id to
`chat_completion`. So routing to an agent is choosing a different string:

| What an agent needs | Where it already comes from |
|---|---|
| its instructions | `params.system` on the row, applied by Open WebUI |
| its tools | `meta.toolIds` on the row |
| acting as the caller | the existing pairing, which resolves the user's own token |
| appearing in chat at all | it is a model, so `chat_completion` accepts it |

Nothing about instructions, tools or identity is built here. The only new
behaviour is deciding which id to send.

## The privacy wall this does not touch

`pipeline.py` refuses group chats before identity is even resolved:

```python
if src.chat_type != "dm":
    return await _say(adapter, src.chat_id, GROUP_REFUSAL)
```

The reason is that the Brain, each user's private knowledge graph, is injected
into every model call, so answering in a group would print one person's private
memory into a shared room. Refusing before identity exists means no code path
can do it.

This feature is **direct messages only** and leaves that check untouched. Agents
make the leak worse rather than better: an agent can also read your email and
your files, so a group answer could print those too. Opening groups is a
separate decision with its own design, and it is not this one.

## Architecture

The pick happens after identity and after commands, so `/help` and `/resume`
keep working when models are down, which is exactly when someone needs them.

```
DM arrives
   |
   v
identity resolved (existing pairing)
   |
   v
commands handled (existing, never reaches a model)
   |
   v
PICK AN AGENT  <- new
   |  returns an agent id, or nothing
   v
chat_completion(messages, <agent id or the default model>)
   |
   v
reply, with a line naming the agent when one was used
```

The chosen id also goes to `get_or_create_chat` and `append_turn`, which
already take a model, so the transcript records what actually answered.

## Choosing the agent

### Candidates

Candidates come from `GET /api/v1/models/list` called with **the user's own
token**, so the router can only ever see agents that user is allowed to see. A
private agent belonging to somebody else is not returned at all.

That endpoint returns only derived models, not the 130 base models, so the list
is small. It is filtered to the `agent-` prefix, the same test the Agents page
uses.

The gateway's Open WebUI client has no model-listing method today. Adding one is
part of this work.

### The router

The router is given the message and one line per candidate: the agent's name and
the short description already stored on every agent. It answers with a single
agent id or `NONE`.

Full instructions are deliberately not sent. They run to 4000 characters each,
and this call happens on messages from every user, so the prompt has to stay
small. The description exists for exactly this.

**The answer is validated against the candidate list.** A model that returns an
id it invented, or one belonging to someone else, must not be able to route a
real request. Anything not in the candidates is treated as `NONE`.

An LLM call is used rather than embedding similarity because the thing being
matched is intent against behaviour: "check my mail" against "you read the
user's unread email and tell them what actually needs them". Those two embed to
very different places, so a similarity match would misfire on precisely the
short messages people actually send.

### When the router is skipped

Three cases, and they matter because this call would otherwise run on every
message from every user:

1. The message is a command. Commands never reach a model at all today.
2. The conversation has a pinned agent. The pin is the answer.
3. The user has no candidates. Nothing to choose between.

## Correcting it

Auto-picking is only safe if a wrong pick is visible and cheap to fix.

**Visible.** When an agent answered, the reply ends with one short line, on its
own, reading `via <agent name>`. When the normal assistant answered there is no
line at all, so nothing changes for someone who has no agents.

**Cheap to fix.** Saying "use Research Assistant" pins that agent for the
conversation. Saying "stop using that" clears it. The pin lives in the existing
`/state` key-value store, keyed by platform and chat, next to the other bot
conversation state.

How a pin phrase is recognised matters, so it is stated rather than left to the
implementer. It is **not** the router's job and **not** a model call. A narrow
matcher runs in the command step, before the router: the message must start with
one of a small set of verbs (`use`, `switch to`, `talk to`), and the remainder
must match the name of one of that user's own candidates. "Use Research
Assistant" pins. "Use my email to find the invoice" does not, because "my email
to find the invoice" is not the name of one of their agents, so it falls through
and is answered as an ordinary message.

That restriction is the point. A looser matcher would swallow real requests that
happen to begin with the word "use", and a message silently turning into a
setting is worse than a router that picks wrong.

The pin also stops a wrong pick from repeating. Without it, a message the router
misreads once it will misread every time you rephrase it.

## Failure and limits

Every failure still answers the message. This follows the rule the rest of this
codebase already applies to post-processing: a step that helps must never be
able to stop the thing it was helping.

| When | What happens |
|---|---|
| Router errors or times out | Answer normally, no tag |
| Router answer cannot be parsed | Answer normally |
| Router returns an id not in the candidates | Treat as `NONE`, answer normally |
| Pinned agent has been deleted | Clear the pin, say so once, answer normally |
| Listing candidates fails | Answer normally |

Limits worth stating plainly:

- **Direct messages only.** See the privacy wall above.
- **One extra model call per message**, for any user who has candidates. Since
  the two ready-made agents are visible to everyone, that is every user. This is
  the real cost of auto-picking and it is why the router prompt is names and
  one-liners rather than instructions.
- **The router can be wrong.** It is a model reading a short message. The tag
  and the pin exist because of this, not in spite of it.
- **A wrong pick can still act.** An agent with write tools can create things in
  a real account. The existing tools are 28 read and 5 create, with no delete
  and no update, so the blast radius today is a stray created item. That changes
  the day write tools grow, and confirmation on destructive tools should land
  before they do.

## Testing

In `webhook-handler/tests/`, beside the existing gateway tests. The router is a
separate module so its choice can be tested without a model.

- the router picks the matching agent from a candidate list
- an id the router invented is rejected and falls back to the normal model
- a router failure still answers the user
- no candidates means the router is never called, which is the cost guard
- a pin is used on the next message without calling the router
- a pin clears on request
- a pin naming a deleted agent clears itself and answers normally
- the reply is tagged only when an agent answered
- commands still bypass the whole path
- **a group message is still refused**, which is a regression test rather than a
  new one, because this change touches the code immediately after that check

## Deliberately not in this spec

- **Group channels.** The Brain injection makes that a data-leak decision, not a
  routing one.
- **`/agent` style commands.** Rejected in favour of the bot deciding, because
  needing a command defeats the purpose. The natural-language pin covers the
  case where you want to be explicit.
- **Agents on a schedule.** The schedules table has no model column at all, so
  cron cannot target an agent. That is a separate, smaller piece of work.
- **Write and delete tools.** Named above as a risk, but adding them is its own
  design, and destructive tools need a confirmation step first.

## Order of work

1. `list_models()` on the gateway's Open WebUI client.
2. The router module: candidates, prompt, call, validation. Testable alone.
3. Wire it into the pipeline, including the tag and the transcript model.
4. The pin: set, use, clear, and self-clear on a deleted agent.
5. Deploy, then verify on a real DM with a real agent that its tools ran.
