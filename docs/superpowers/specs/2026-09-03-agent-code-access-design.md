# Agents that can read your code, and change it with your say-so

Date: 2026-09-03
Status: approved, not yet implemented

## The problem

An agent can read your inbox and your calendar, and knows nothing about the
24 apps you built on this platform. "Why is the checkout page blank" is a
question about a file the agent cannot open, so it answers from imagination
or not at all.

The apps are right there. They live at `apps/<slug>/` in this repo, bind
mounted into the tasks container at `/workspace/ai_ui`, and
`tasks.project_members` already records who owns which one. Nothing needs
inventing for the agent to see them, only wiring.

Changing them is a different matter, and the interesting design work is in
making that safe rather than making it possible.

## What we are building

One native tool, `code`, on the same path as `agents` and `account`: the
tool holds no logic, the tasks service decides everything, so the web chat,
Discord and Telegram all behave identically and an agent's access level
applies here too.

Five functions. Three read, two write.

### Reading

- `list_my_apps()` gives the apps this person is a member of, with each
  one's slug, whether it is published, and when it last changed.
- `read_app_file(slug, path)` returns one file.
- `search_my_app(slug, query)` returns matching lines with their file and
  line number, so the agent can find the checkout page without being told
  where it is.

Every call re-checks membership against `tasks.project_members` for the
calling user. Membership is not cached between calls and is never taken
from the tool's arguments: the caller supplies a slug, and the service
decides whether that slug is theirs.

### Writing, in two steps

`propose_app_change(slug, description)` writes a row and returns a token.
It changes nothing. The description is what the agent intends, in plain
language, and it is shown to the person as-is.

`apply_app_change(token)` is the only function that can change anything. It
looks the token up, checks it belongs to this user, is unused, and is less
than 30 minutes old, marks it used, and calls
`_create_and_spawn_enhance(email, slug, description)`.

The slug comes from the stored proposal, never from the apply call, so a
token cannot be redirected at a different app after the fact. That helper
already requires the editor or owner role, so applying needs more than the
membership that reading needs, and a viewer on a project can propose a
change and not apply it.

Single use is enforced by the row, not by the model. A second
`apply_app_change` with the same token finds `used_at` set and refuses.

Tokens live in a new table, `tasks.agent_proposals`: token, user_email,
slug, description, created_at, used_at. A table rather than process memory
because the tasks service is not guaranteed to be one worker, and a
proposal made on one and confirmed on another must not silently vanish.

## Why the enhance pipeline, and not writing the file

`apply_app_change` deliberately does not write anything itself. It queues a
normal App Builder enhance, which is the path that already:

1. captures a regression baseline and smokes the app **before** the agent
   runs (`app_regression.capture_baseline`),
2. runs the change,
3. drives headless Playwright and catches `pageerror`, `console.error`,
   `requestfailed` and the main response status, running narrow fix passes
   when it finds them (`app_smoke.smoke_app`),
4. sweeps the README and commits `apps/<slug>/`,
5. and rolls the app back if it was clean before and is broken now.

Writing the file directly would bypass all five. Every one of them would
have to be rebuilt on the new path before it was safe to ship, and two of
them exist because this project shipped a feature without them and broke 43
of 47 real apps.

`_create_and_spawn_enhance` also already takes an advisory lock per slug and
returns 409 when an enhancement is in flight, so two agents cannot edit one
app at once.

**The honest cost:** the agent describes the change and the builder decides
the final code, so what lands may not be character for character what the
agent described. The description is a brief, not a diff. In exchange the
change is smoke tested and reversible, which a diff applied straight to disk
would not be.

## What it deliberately cannot do

- **Reach anything but the caller's own apps.** Not the platform repo, which
  holds other people's work and the credential handling. The path is
  resolved and then required to sit inside the resolved `apps/<slug>/`, so
  `../`, an absolute path, and a symlink pointing outward are all rejected
  by the same check. Rejecting the string `..` is not sufficient and is not
  the mechanism.
- **Delete.** No file removal, no app deletion. Deleting is one click in the
  UI, and this project has an incident where a bad delete path wiped 9
  production projects and all chat history.
- **Create an app.** That is App Builder's job and it already has an entry
  point.
- **Read a file it has no business reading.** Dotfiles, anything matching
  `*.pem`, `*.key`, `id_rsa*`, and any path segment named `.git`,
  `node_modules`, `.venv` or `dist` are refused. Supabase keys are injected
  at request time and are not in an app's files, so this is defence rather
  than a known leak, but a tool that prints file contents into a chat log is
  exactly where that assumption should not be trusted.
- **Return something enormous.** Files are capped (64KB, truncated with a
  clear marker) and search returns at most 50 matches. A binary is detected
  by a null byte in the first 8KB and refused rather than printed.

## Access levels

`propose_app_change` is a read-level action: it writes a proposal row and
touches no app. `apply_app_change` is a write.

Under the existing ceiling in `agent_access.py`, an agent set to **Read
only** can list, read, search and propose, and cannot apply. **With access**
and **All access** can apply. This falls out of the existing rules rather
than adding new ones, and it means "read only" is true in the strong sense:
such an agent can tell you exactly what it would change and still cannot
change it.

Two-phase confirmation is enforced by the token regardless of access level,
so it holds on every surface, including any that does not run our tool loop.

## Testing

The rule this project keeps relearning: every real defect here was found by
running code, and every check that missed one was reasoning about code.

- A member reads their own app. A non-member gets 403 for the same slug.
- Path containment: `../../etc/passwd`, an absolute path, and a symlink
  inside the app pointing outside it are each refused. The symlink case is
  the one a string check passes and the real check catches, so it is the one
  that must exist as a test.
- A denied filename is refused even for the owner.
- A binary file is refused rather than printed.
- `apply_app_change` with no token, a stranger's token, an expired token and
  a used token each refuse, and none of them queue a task.
- A used token cannot be replayed: the second call finds `used_at` set.
- A successful apply produces a real task row whose slug matches the
  proposal's, and does not trust any slug sent by the caller at apply time.
- An agent at Read only can propose and cannot apply.
- Two applies for one slug at once: the second gets 409, not a second run.

On the server, with a real app and a real browser, because wiring inside a
function body is not caught by an import or a unit test and this pipeline
has been bitten by exactly that twice.

## Deploy

`tasks` changes (new routes and the proposals table, so a migration), and
the tool is installed with `scripts/insert_owui_tool.py` and granted with
`scripts/grant_tools_public.py`, then attached to the chat models with
`TOOL_IDS=code scripts/enable_gmail_tool_on_models.py`.

Order is tasks first: the tool has nothing to call until the endpoints
exist.
