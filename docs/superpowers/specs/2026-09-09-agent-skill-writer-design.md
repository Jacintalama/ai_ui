# Agents write their own skills

**Status:** design, awaiting review
**Date:** 2026-09-09

## Why

Skills shipped on 2026-09-08: ten SKILL.md files in the image, ticked on the
agent form, injected into the agent's brief. Proven on production, where
giving Mia `inbox-triage` changed her answer from a fifteen-message dump with
internal ids and a trailing "let me know if you'd like" into one line per
message with the empty group written out as "None".

Ten is not a library. The obvious next move was to import from GitHub, so
that was measured rather than assumed. 1,225 SKILL.md files across five public
repositories:

| verdict | count | share |
|---|---|---|
| usable | 35 | 2.9% |
| needs a filesystem, shell or scripts | 514 | 42.0% |
| body too large to put in a prompt | 209 | 17.1% |
| frontmatter did not parse | 459 | 37.5% |
| proprietary or unlicensed | 8 | 0.7% |

Of the 35 that passed, roughly nine are things a project manager or a
receptionist would ever use; the rest are for coding or robotics agents.
Anthropic's own repository carries no licence file, and its `docx`, `pdf`,
`pptx` and `xlsx` skills are marked `Proprietary`.

So importing is not the answer, and the reason is form rather than content:
public skills are written for an agent with a filesystem that loads them on
demand. The agents here are Open WebUI model rows on a small model with eleven
REST tools, and a skill arrives pasted into the prompt.

The answer is to generate skills that fit this platform, and to let the people
using it do that for themselves.

## What this builds

Someone describes a job in a sentence. A model writes a SKILL.md fitted to
this platform's real tools and size limits. They read it, edit it if they
want, and save it. It then appears in the same list they already tick skills
from, and works exactly like a built-in one.

Two front doors, one engine:

- a **+ New skill** button on the Skills list in the agent form
- a **`write_skill`** tool, so "Ada, write me a skill for chasing invoices"
  works too

Both call the same endpoint and both end in a draft the person approves.
Nothing is ever saved without that approval.

## What this does not build

- **Editing a built-in skill.** Copy-then-edit is the same feature without the
  question of what happens to your edits on the next deploy.
- **Sharing.** A skill is private to whoever wrote it. This platform has
  already had one wildcard-share incident, and a skill is text injected into
  an agent's brief, so "everyone can write instructions that run inside your
  agent" is not a default anyone chose.
- **Importing from GitHub.** The measurement above is the argument. The nine
  usable ones are worth rewriting by hand, separately, as ordinary content
  work.

## The constraint everything else follows from

A ticked skill's whole body goes into the agent's brief, every turn. Measured
on Mia's real brief:

```
Mia's brief, no skills            1,876 chars
              1 skill             2,825   (+949)
              5 skills            5,754   (+3,878)
             10 skills            9,478   (+7,602)
```

`MAX_TOTAL_CHARS` is 8,000 and the conversation budget for a round is 24,000,
and the conversation is the thing being answered.

So the ceiling is on **how many skills one agent can hold**, roughly ten, not
on how large the library may be. Tick more than that and `brief_for` already
cuts to fit and names what it left out.

The library itself is limited by the picker, not the prompt. A list of four
hundred checkboxes is unusable long before it is expensive, which is why
search and grouping belong in this work once the library outgrows one screen.

This matters for a later decision and is recorded here so it is not
rediscovered: if skills are ever chosen by the agent rather than ticked by
hand, every description would have to sit in the brief instead. All ten
descriptions together cost 1,859 characters, about what one body costs, so
that design would trade a per-agent ceiling of ten for a platform-wide
ceiling of roughly forty. That is a different spec.

## Storage

Built-in skills stay files in the image, read from `agent_skills/`. They ship,
they are the same for everybody, and they need no database.

A person's own skills go in a new table:

```sql
-- migrations/049_user_skill.sql
CREATE TABLE IF NOT EXISTS tasks.user_skill (
    id           uuid PRIMARY KEY,
    user_email   text NOT NULL,
    name         text NOT NULL,
    description  text NOT NULL,
    tools        text[] NOT NULL DEFAULT '{}',
    body         text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS user_skill_owner_name
    ON tasks.user_skill (user_email, name);
```

Additive and idempotent, like every migration in this repo.

The unique index is on `(user_email, name)`, not on `name`. Two people may
each have a skill called `inbox-triage`; they are different skills and neither
can see the other's.

**A name may collide with a built-in one.** When it does, the person's own
skill wins for that person. Anything else means a deploy that adds a built-in
skill silently replaces one somebody wrote, which is the worse failure.

## The interface change, and why it is the risky part

Today:

```python
agent_skills.brief_for(meta) -> str
```

It resolves names against a module-level dict of files. A private skill cannot
be resolved that way: it needs to know *whose* agent this is.

```python
async def brief_for(meta, user_email) -> str
```

That turns a synchronous pure function into an async one that touches the
database, and it runs inside `_identity_line`, which runs inside `_turn_for`,
which every surface goes through: the chat panel, Discord, Telegram, the
terminal channel, and every scheduled run.

This is the single most dangerous change in the work, so it is treated that
way:

- `_identity_line` becomes async, and every caller is updated in the same
  task. There are tests asserting on its output today and they stay green.
- A database failure returns the built-in skills alone, never an exception.
  The rule this codebase already follows is that bookkeeping must never cost
  somebody their turn.
- The ordinary case, an agent with no skills, must not query the database at
  all. Most agents have none, and a per-turn round trip for nothing is a cost
  paid by every user on the platform for a feature few of them use.

## Generating a draft

```
POST /tasks/agents/skills/draft   { "job": "chase unpaid invoices" }
  -> { "name": ..., "description": ..., "tools": [...], "body": ... }
```

Answered with the caller's own minted Open WebUI token, the same way
`_answer_as_io` already answers for IO, so the request is attributed to the
right person and their own model access applies.

The prompt carries three things the public skills lacked:

1. **The tools this person actually has**, by id and label, read from
   `tools_for_email`. A skill that names Gmail for somebody who has not
   connected Gmail is the silent-failure case.
2. **The format**, with the size ceiling stated as a number.
3. **The house rules that made the first ten work**: steps then rules, one
   job per skill, never invent a fact, say when something could not be
   checked, answer and stop.

The endpoint **saves nothing**. It returns a draft.

## Saving

```
POST   /tasks/agents/skills/mine    create
PATCH  /tasks/agents/skills/mine/{name}   edit
DELETE /tasks/agents/skills/mine/{name}   remove
```

Validated on save, not on draft, because a draft is allowed to be wrong and a
saved skill is not:

- `name` matches the Agent Skills spec: 1-64 characters, lowercase letters,
  digits and hyphens, no leading, trailing or doubled hyphen.
- `description` is 1-1024 characters. A description that never says *when* to
  use the skill is warned about, not refused: the built-in ten are held to
  that by a test because I wrote them, but "Use this whenever an invoice is
  late" and "Use when an invoice is late" both say it, and no string check
  tells those apart from a bad description. Refusing on a guess would block
  people from saving perfectly good skills.
- `body` is non-empty and within `MAX_SKILL_CHARS`.
- every tool named is one that exists on this platform. Naming a tool the
  person has not connected is a **warning at save time**, not a refusal:
  people do connect things later, and refusing would be wrong the moment they
  did.

Deleting a skill leaves the agents that referenced it alone. `selected()`
already drops unknown names, and there is already a test proving a missing
skill degrades to being left out rather than to a turn that fails.

## The agent tool

`write_skill(job)` is a native tool that calls the same draft endpoint and
returns the draft as text for the person to read.

It creates nothing. The chat is where the draft is shown; saving is a separate
deliberate act.

Under the existing classifier this falls out correctly without new machinery:
`write_skill` contains the write verb `write`, so `is_write_tool` returns
True, so an agent on **Read only** is refused and one on **Ask** stops and
asks first. That is the behaviour we want and it needs no special case.

## A skill grants nothing

Stated explicitly because it is the question a reader will have.

A skill is instructions. It is not permission.

- It cannot add a tool to an agent. The tool list comes from `_resolve_agent`,
  which reads the agent's own `meta.toolIds` unioned with what its owner can
  reach, and never looks at skills.
- It cannot widen the access level. `effective_mode` reads `meta.access`, and
  every write the agent then attempts goes through `is_write_tool` and the
  same gate as before.
- It is private, so the text can only ever reach its own author's agents.

The worst a bad skill can do is waste a turn giving bad advice, which is the
same thing a bad instruction in the Instructions box already does.

## Failure behaviour

| what fails | what happens |
|---|---|
| the database is unreachable | built-in skills only, turn proceeds |
| the draft model call fails | the modal says so; nothing is saved |
| a saved skill names a missing tool | saved, with a warning shown at save |
| a skill is deleted while an agent holds it | quietly dropped from that brief |
| PyYAML is missing | no built-in skills; user skills still work, since they come from the database, not from parsed files |

## Testing

The pattern that has found every real defect on this project is running code
against reality, so:

- **Unit**: name and description validation against the spec's own rules; the
  size cap; a private skill resolving for its owner and not for anybody else;
  a user skill shadowing a built-in one of the same name; junk in the stored
  list surviving.
- **Interface**: `_identity_line` still produces its current output for an
  agent with no skills, character for character. This is the regression that
  matters most, because most agents have none.
- **No-query proof**: an agent with no skills makes no database call. Asserted
  with a counting stub, not by reading the code.
- **Browser**: the New skill modal draws a draft, edits survive, save posts
  the right body, cancel saves nothing, and a user's own skills appear in the
  same list as the built-in ones and are marked as theirs.
- **Live, on the server, before it is called done**: write a skill through the
  modal, tick it on an agent, ask that agent something the skill covers, and
  read the answer. The first ten skills were only proven this way, by asking
  Mia the same question twice and comparing.

## Build order

The pieces are separable, and the order matters because the risk is not
evenly spread.

1. **The table, and user skills in the picker.** Storage, the three
   endpoints, and the list showing your own skills alongside the built-in
   ones. This is where the async `brief_for` change lands, which is the
   riskiest edit in the work because it runs on every surface.
2. **Duplicate a built-in skill.** One button. It proves the whole save and
   load path end to end with no model involved, so a failure at this point is
   unambiguous.
3. **The generator.** The draft endpoint and the New skill modal.
4. **The `write_skill` tool.** Smallest piece, and it depends on 3.

Stopping after 2 would leave something useful rather than something half
built, which is the test of whether the split is honest.

## Open question for review

The draft is generated by a model, and the person may never read it carefully.
A skill that says "always tell the user everything looks fine" would be
followed. Since skills are private this is self-inflicted rather than an
attack, and the same is true of the Instructions box today, so this design
does not attempt to police the content.

If that judgement is wrong, the alternative is a review pass on save that
refuses a skill instructing an agent to conceal, fabricate, or bypass its
approval flow. That is a real feature and would be its own work.
