# Channel states and terminal onboarding

Date: 2026-08-13
Branch: `feat/multi-platform-gateway`
Status: designed, not implemented

## The problems

**1. The Terminal channel cannot be used by anyone.**
The row tells a user to "Run python scripts/io.py and it will print a code."
Nothing serves that file. There is no route for it, so the instruction only
works for someone who already has the repository checked out. Pairing a
terminal was possible during verification only because the verifier had the
source.

**2. A status never says which bot carries your messages until after you pair.**
`READY TO CONNECT` is all a user sees, so nothing on the page reveals that
bringing your own bot is even possible.

**3. The expanded row reads as prose, not as something to follow.**
Two stacked blocks and a floating paragraph of security warning.

## Decisions taken

- Unconnected rows name the path you would take, not just "ready".
- The app serves the terminal client, and the row shows a copy-paste command.
- Each path becomes short numbered steps.
- The badge stays `READY TO CONNECT` rather than `NOT CONNECTED`: equally
  accurate, less discouraging, and the useful part is the line beneath it.

## Where the client lives

The canonical copy moves to `mcp-servers/tasks/static/io.py`.

This needs no new route and no proxy change: Caddy already proxies
`/tasks/static/*`, so the file is immediately public at
`https://<host>/tasks/static/io.py`.

It is baked into the tasks image, because the build context is
`./mcp-servers/tasks`. That is the point, not an accident. The alternative,
reading `/workspace/ai_ui/scripts/io.py` through the bind mount, is stale in
production **right now**: 3,279 bytes from before the Cloudflare User-Agent fix,
against 3,907 bytes in the repository. Serving from the mount would hand every
user the client that 403s. A baked copy cannot be older than the code running
beside it.

`scripts/io.py` stays where repository users expect it. A test compares the two
files byte for byte, so they cannot drift apart.

## What every state shows

The server already computes `via` per row. This extends it to unconnected rows,
so one rule covers every channel and Slack or Discord inherit it the moment they
become bot-capable.

| State | Badge | Line beneath |
|---|---|---|
| Telegram, not connected | `READY TO CONNECT` | via IO's bot @aiuiteam_bot, or bring your own |
| Telegram, via IO's bot | `CONNECTED · IO'S BOT` | IO's bot @aiuiteam_bot, connected as @ralph |
| Telegram, via own bot | `CONNECTED · YOUR BOT` | Your bot @ralphs_io_bot, connected as @ralph |
| Terminal, not connected | `READY TO CONNECT` | no bot line: you connect a device, not a bot |
| Terminal, connected | `CONNECTED` | Connected as ralph-laptop |
| Not built yet | `COMING LATER` | the existing reason |

`via` values: `"own"`, `"shared"`, `"offer"` (can bring a bot, not connected
yet), `""` (no whose-bot question exists here).

A channel with `can_bring_bot` false never claims a bot. The terminal is the
case that makes this obvious, and an earlier build printed "IO's bot
@aiuiteam_bot" on the Terminal row, which was simply false.

## The expanded row

One renderer for both paths, so a channel that gains a second way in later gets
the same shape without new code.

Telegram:

```
Quick connect · use IO's bot
  1  Message @aiuiteam_bot on Telegram
  2  It replies with a code
  3  Paste it here   [ ABCD2345 ]  [ Connect ]
     Only paste a code you asked for yourself.

Use your own bot                          optional
  1  Create a bot with @BotFather
  2  Paste its token          [ ......................... ]
  3  Who may use it           [ leave empty for just you  ]
  4  [ SAVE & ENABLE ]
```

Terminal:

```
Quick connect · from your shell
  1  Download the client
     curl -fsSL .../tasks/static/io.py -o io.py        [copy]
  2  Run it
     python io.py                                      [copy]
  3  Paste the code it prints  [ ABCD2345 ]  [ Connect ]
     Only paste a code you asked for yourself.
```

The security warning moves from a floating paragraph to directly beneath the
code box, which is the moment it matters.

Two details decide whether this works in practice:

- The command is built from `window.location.origin`, never a hardcoded
  domain, so it stays correct on any host.
- **Copy** falls back to selecting the command text when the clipboard API is
  unavailable. This page runs inside an iframe, where `clipboard-write` can be
  denied.

The page keeps building DOM with `createElement` and `textContent`. No
`innerHTML`, because these rows render remote strings such as a bot username and
Telegram error text.

## Failure handling

| Case | Behavior |
|---|---|
| Clipboard blocked in the iframe | Button selects the command so it stays copyable by hand |
| Windows without curl | Works on Windows 10+, which ships curl. Underneath, one PowerShell line for older machines: `iwr <origin>/tasks/static/io.py -OutFile io.py` |
| Served file drifts from `scripts/io.py` | A test compares them byte for byte and fails |
| Served file is stale | Impossible by construction: baked into the image, not read from the bind mount |
| Terminal flag set on one service only | Already fixed; a test asserts both services read the same variable |
| No shared bot configured | The offer line drops the handle rather than printing a bare `@` |

## Testing

- `scripts/io.py` and `mcp-servers/tasks/static/io.py` are byte-identical.
- The served URL returns 200, the shebang survives, and the source still sets a
  custom `User-Agent`, so the Cloudflare fix cannot silently regress into a
  client that 403s before reaching IO.
- `via` produces the right value for every row in the state table, including
  the `offer` state and the no-shared-handle case.
- A channel with `can_bring_bot` false never produces a bot label.
- Page copy assertions for the step text and the command.
- A rendered screenshot of both expanded rows before shipping. That is what
  caught the last three UI defects, none of which any test or review saw.

## Out of scope

- Splitting `gateway-link.html`. It is about 650 lines of HTML, CSS and JS in
  one file. Several existing tests assert on that file's source text and would
  all need rewiring, so it is churn without user-visible gain. Worth doing when
  the page next changes shape.
- A prettier `/io.py` URL. That needs an edit to the host systemd Caddyfile,
  which is riskier than the gain; `/tasks/static/io.py` already works.
- Making Slack, Discord or any other channel connectable.
