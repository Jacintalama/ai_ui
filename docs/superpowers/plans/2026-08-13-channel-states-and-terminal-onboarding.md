# Channel States and Terminal Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Terminal channel usable by someone who does not have the repository, and make every channel row say which bot carries their messages before they connect, not only after.

**Architecture:** The terminal client moves into `mcp-servers/tasks/static/`, which Caddy already proxies, so it is served with no new route and is baked into the image rather than read from a bind mount that is currently stale. The server-side `via` rule gains one state, `offer`, so unconnected rows answer the same whose-bot question. The page's expanded row becomes numbered steps with copyable commands.

**Tech Stack:** FastAPI, vanilla JS in a single static page, pytest, Playwright for the render check.

**Spec:** `docs/superpowers/specs/2026-08-13-channel-states-and-terminal-onboarding-design.md`

## Global Constraints

- Branch: `feat/multi-platform-gateway`. Do not create a new branch.
- **The page builds DOM with `document.createElement` and `textContent`, never `innerHTML`.** These rows render remote strings (a bot username, Telegram error text), so this rule is load-bearing.
- **Never log a bot token and never put one in a URL path.**
- **`crypto_utils` must never be imported at module scope** in the tasks service.
- **Do not modify the existing Discord or Slack integrations**, or their catalogue entries.
- The command shown to a user is built from `window.location.origin`. Never hardcode a domain.
- The badge for an unconnected row stays `READY TO CONNECT`. Not `NOT CONNECTED`.
- A channel with `can_bring_bot` false must never produce a bot label. You connect a *device* to the terminal, not a bot.
- Commit messages carry NO Claude or AI co-author trailer and no "Generated with" line. Attribution is Ralph Benitez only.
- Baseline before any work: tasks `gateway and not db` subset is **109 passed** with 3 pre-existing warnings from `mcp-servers/tasks/schemas.py:27` and `main.py:154`. Do not chase those warnings.
- Do NOT run the full tasks `tests/` suite; it has ~130 pre-existing `ERROR at setup` failures because there is no local Postgres.
- `mcp-servers/tasks/pytest.ini` sets `asyncio_mode = auto`.

## File Structure

| File | Responsibility |
|---|---|
| `mcp-servers/tasks/static/io.py` | create | The canonical terminal client. Lives here because Caddy already proxies `/tasks/static/*` and the tasks build context is `./mcp-servers/tasks`, so it ships inside the image. |
| `mcp-servers/tasks/tests/test_io_client_copies.py` | create | Proves the served copy and `scripts/io.py` cannot drift, and that the Cloudflare fix survives. |
| `mcp-servers/tasks/routes_gateway.py` | modify | `_route_for` gains the `offer` state; the CLI note becomes short. |
| `mcp-servers/tasks/tests/test_gateway_route_label.py` | modify | Cases for `offer`. |
| `mcp-servers/tasks/static/gateway-link.html` | modify | Numbered steps, copyable commands, clipboard fallback. |
| `mcp-servers/tasks/tests/test_gateway_page_steps.py` | create | Page copy assertions for the new structure. |

---

### Task 1: Serve the terminal client

**Files:**
- Create: `mcp-servers/tasks/static/io.py` (copy of `scripts/io.py`)
- Test: `mcp-servers/tasks/tests/test_io_client_copies.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the client at `mcp-servers/tasks/static/io.py`, publicly served at `<origin>/tasks/static/io.py`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_io_client_copies.py`:

```python
"""The terminal client a user actually downloads.

The row tells people to fetch this file, so it must ship inside the image
rather than be read from the bind mount. The mount was stale in production on
2026-08-13: 3279 bytes from before the Cloudflare User-Agent fix against 3907
in the repository, so serving from it would have handed every user a client
that 403s before reaching IO.

Two copies exist on purpose: repository users expect scripts/io.py, and the
served copy must live under static/ for Caddy to proxy it. This file is what
stops them drifting apart.
"""
import pathlib

TASKS = pathlib.Path(__file__).resolve().parents[1]
REPO = TASKS.parents[1]

SERVED = TASKS / "static" / "io.py"
MIRROR = REPO / "scripts" / "io.py"


def test_the_served_client_exists_where_caddy_proxies_it():
    assert SERVED.is_file(), (
        "Caddy proxies /tasks/static/*, so the client must be here to be "
        "downloadable at all")


def test_the_two_copies_are_byte_identical():
    # Drift here means a user downloads a different program than a developer
    # runs, and nothing else would report it.
    assert SERVED.read_bytes() == MIRROR.read_bytes()


def test_the_client_still_sets_its_own_user_agent():
    # Cloudflare answers 1010 to urllib's default Python-urllib/3.x agent, so
    # without this the download works and then every request 403s.
    source = SERVED.read_text(encoding="utf-8")
    assert "User-Agent" in source
    assert "USER_AGENT" in source


def test_the_client_is_runnable_as_a_script():
    assert SERVED.read_text(encoding="utf-8").startswith("#!")


def test_the_client_needs_nothing_installed():
    # "single dependency-free script" is the promise the channel row makes.
    source = SERVED.read_text(encoding="utf-8")
    for banned in ("import requests", "import httpx", "from requests", "from httpx"):
        assert banned not in source
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_io_client_copies.py -q
```

Expected: FAIL. `test_the_served_client_exists_where_caddy_proxies_it` fails because the file does not exist yet; the others error on the missing file.

- [ ] **Step 3: Copy the client into the served location**

```bash
cd "C:/All/Work - Code/ai_ui" && cp scripts/io.py mcp-servers/tasks/static/io.py
```

Do not edit either copy in this task. They must stay identical.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_io_client_copies.py -q
```

Expected: PASS, 5 passed.

- [ ] **Step 5: Confirm the tasks image will carry it**

The tasks build context is `./mcp-servers/tasks` (see `docker-compose.unified.yml`). Confirm the Dockerfile copies the static directory:

```bash
cd "C:/All/Work - Code/ai_ui" && grep -n "COPY" mcp-servers/tasks/Dockerfile
```

If `static/` is not covered by an existing `COPY . .` or equivalent, add a line that copies it, and say so in your report. If it is already covered, change nothing.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/static/io.py mcp-servers/tasks/tests/test_io_client_copies.py
git commit -m "feat(gateway): serve the terminal client where a user can actually get it"
```

---

### Task 2: An unconnected row names the path in

**Files:**
- Modify: `mcp-servers/tasks/routes_gateway.py` (`_route_for`, and the `cli` branch of `_channel_status`)
- Modify: `mcp-servers/tasks/tests/test_gateway_route_label.py`

**Interfaces:**
- Consumes: `_route_for(row: dict, shared: str) -> dict[str, str]` as it exists today, returning `{"via", "via_label"}`.
- Produces: `via` gains the value `"offer"`. Full set is now `"own"`, `"shared"`, `"offer"`, `""`.

- [ ] **Step 1: Write the failing test**

Append to `mcp-servers/tasks/tests/test_gateway_route_label.py`:

```python
def test_an_unconnected_bot_channel_offers_both_ways_in():
    # Before this, the row said only "ready to connect", so nothing on the page
    # revealed that bringing your own bot was even possible.
    out = rg._route_for(row(status="available", bot=None), SHARED)
    assert out["via"] == "offer"
    assert SHARED in out["via_label"]
    assert "your own" in out["via_label"].lower()


def test_the_offer_drops_the_handle_when_no_shared_bot_exists():
    out = rg._route_for(row(status="available", bot=None), "")
    assert out["via"] == "offer"
    assert "@" not in out["via_label"], "must not print a bare @ with no handle"
    assert out["via_label"].strip()


def test_a_channel_that_cannot_carry_a_bot_offers_nothing():
    # The terminal connects a DEVICE. An offer line naming a Telegram bot here
    # would be false, which is exactly what shipped once already.
    out = rg._route_for(row(status="available", bot=None, can_bring_bot=False),
                        SHARED)
    assert out["via"] == ""
    assert out["via_label"] == ""


def test_a_saved_bot_still_wins_over_the_offer():
    out = rg._route_for(row(status="available", bot=enabled_bot()), SHARED)
    assert out["via"] == "own"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_gateway_route_label.py -q
```

Expected: FAIL. `test_an_unconnected_bot_channel_offers_both_ways_in` gets `via == ""` because the function falls through to the empty return.

- [ ] **Step 3: Add the offer state**

In `mcp-servers/tasks/routes_gateway.py`, replace the final `return` of `_route_for`:

```python
    return {"via": "", "via_label": ""}
```

with:

```python
    # Not connected, but this channel CAN carry a personal bot, so the row can
    # still answer the whose-bot question instead of saying only "ready".
    # Without this, nothing on the page reveals that bringing your own bot is
    # possible until after someone has already paired the other way.
    if shared:
        return {"via": "offer",
                "via_label": f"via IO's bot {shared}, or bring your own"}
    return {"via": "offer", "via_label": "bring your own bot"}
```

Leave the three branches above it exactly as they are: the `can_bring_bot` guard still returns early, so a terminal row never reaches this.

- [ ] **Step 4: Shorten the CLI note**

The step list on the page now carries the instructions, so the note is a summary rather than a command. In the `cli` branch of `_channel_status`, replace:

```python
                    "note": "Run python scripts/io.py and it will print a code."}
```

with:

```python
                    "note": "Download the one-file client and it will print a code."}
```

The old text named a path that only exists in a checkout, which is the whole reason nobody could use this channel.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_gateway_route_label.py -q
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/ -q -k "gateway and not db"
```

Expected: the label file passes; the subset is 113 passed or more, never fewer than the 109 baseline.

If `tests/test_gateway_catalogue.py` asserts on the old CLI note text, update that assertion to the new sentence. That is a real copy change, not a workaround.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_gateway.py mcp-servers/tasks/tests/test_gateway_route_label.py mcp-servers/tasks/tests/test_gateway_catalogue.py
git commit -m "feat(gateway): an unconnected row says which bot would carry you"
```

---

### Task 3: Numbered steps and copyable commands

**Files:**
- Modify: `mcp-servers/tasks/static/gateway-link.html`
- Test: `mcp-servers/tasks/tests/test_gateway_page_steps.py`

**Interfaces:**
- Consumes: `buildExpand(c)`, `buildConnectFields(c)`, `botSection(c, refresh)`, `setMsg(el, text, cls)` as they exist today; `c.via` and `c.via_label` from Task 2.
- Produces: `steps(items)` and `commandLine(text)` helpers used by both paths.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_page_steps.py`:

```python
"""The page has to tell someone what to DO, in order.

The terminal row previously said "Run python scripts/io.py", naming a path that
only exists in a checkout. Nobody without the repository could use the channel.
"""
import pathlib

PAGE = (pathlib.Path(__file__).resolve().parents[1] / "static" / "gateway-link.html")
HTML = PAGE.read_text(encoding="utf-8")


def test_the_page_offers_a_downloadable_client():
    assert "/tasks/static/io.py" in HTML


def test_the_command_is_built_from_the_current_origin():
    # A hardcoded domain silently breaks every other host, including local
    # development and any future domain.
    assert "location.origin" in HTML


def test_the_page_never_hardcodes_the_production_domain_in_the_command():
    assert "https://ai-ui.coolestdomain.win/tasks/static/io.py" not in HTML


def test_the_old_checkout_only_instruction_is_gone():
    assert "python scripts/io.py" not in HTML


def test_copying_falls_back_when_the_clipboard_is_denied():
    # This page runs inside an iframe, where clipboard-write can be refused.
    # Asserting on selectNodeContents specifically, not on "select": the page
    # is full of querySelector calls, so a looser check would pass with no
    # fallback present at all.
    assert "navigator.clipboard" in HTML
    assert "selectNodeContents" in HTML


def test_both_paths_render_as_steps():
    assert "steps(" in HTML


def test_the_windows_alternative_is_offered():
    assert "iwr" in HTML


def test_the_warning_sits_with_the_code_box():
    assert "Only paste a code you asked for yourself" in HTML


def test_the_page_still_builds_dom_safely():
    # These rows render remote strings: a bot username and Telegram error text.
    assert "innerHTML" not in HTML
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_gateway_page_steps.py -q
```

Expected: FAIL on `test_the_page_offers_a_downloadable_client`, `test_the_command_is_built_from_the_current_origin`, `test_the_old_checkout_only_instruction_is_gone`, `test_both_paths_render_as_steps`, `test_the_windows_alternative_is_offered`.

- [ ] **Step 3: Add the two helpers**

In `mcp-servers/tasks/static/gateway-link.html`, above `buildExpand`, add:

```javascript
// One renderer for both paths, so a channel that gains a second way in later
// gets the same shape without new code.
function steps(items) {
  const list = document.createElement("ol");
  list.className = "steps";
  for (const item of items) {
    const li = document.createElement("li");
    if (typeof item === "string") {
      li.textContent = item;
    } else {
      li.append(...item);
    }
    list.append(li);
  }
  return list;
}

// A command someone has to type. Copy is a convenience, never the only way to
// get the text: this page runs inside an iframe, where clipboard-write can be
// refused, so the fallback selects the command for a manual copy.
function commandLine(text) {
  const wrap = document.createElement("div");
  wrap.className = "cmd";

  const code = document.createElement("code");
  code.textContent = text;

  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = "Copy";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      copy.textContent = "Copied";
      setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    } catch (err) {
      const range = document.createRange();
      range.selectNodeContents(code);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      copy.textContent = "Press Ctrl+C";
    }
  });

  wrap.append(code, copy);
  return wrap;
}
```

- [ ] **Step 4: Build the terminal path**

Still above `buildExpand`, add:

```javascript
// The terminal is the one channel where the first step is "get the program".
// Built from location.origin so it stays correct on any host.
function terminalSteps() {
  const url = window.location.origin + "/tasks/static/io.py";

  const download = document.createElement("div");
  download.append(document.createTextNode("Download the client"),
                  commandLine("curl -fsSL " + url + " -o io.py"));

  const windows = document.createElement("div");
  windows.className = "why";
  windows.textContent = "On older Windows: iwr " + url + " -OutFile io.py";
  download.append(windows);

  const run = document.createElement("div");
  run.append(document.createTextNode("Run it"), commandLine("python io.py"));

  return steps([[download], [run], [document.createTextNode("Paste the code it prints below")]]);
}
```

- [ ] **Step 5: Use the steps in `buildExpand`**

Replace the `c.status === "available"` block inside `buildExpand`:

```javascript
  if (c.status === "available") {
    const quick = document.createElement("div");
    quick.className = "botheadline";
    quick.textContent = "Quick connect";
    panel.append(quick, buildConnectFields(c));
  }
```

with:

```javascript
  if (c.status === "available") {
    const quick = document.createElement("div");
    quick.className = "botheadline";
    quick.textContent = c.can_bring_bot
      ? "Quick connect \u00b7 use IO's bot"
      : "Quick connect \u00b7 from your shell";
    panel.append(quick);

    if (c.platform === "cli") {
      panel.append(terminalSteps());
    } else if (c.note) {
      panel.append(steps([c.note, "It replies with a code",
                          "Paste it below"]));
    }

    panel.append(buildConnectFields(c));
  }
```

- [ ] **Step 6: Add the styles**

Next to the existing `.step` rule:

```css
  .steps { margin: .2rem 0 .8rem; padding-left: 1.3rem; font-size: .875rem; }
  .steps li { margin-bottom: .5rem; }
  .cmd {
    display: flex; gap: .5rem; align-items: center; flex-wrap: wrap;
    margin: .35rem 0;
  }
  .cmd code {
    flex: 1; min-width: 0; overflow-x: auto; white-space: pre;
    background: #0d141b; border: 1px solid #1e2b36; border-radius: 4px;
    padding: .35rem .5rem; font-size: .8125rem;
  }
```

- [ ] **Step 7: Show the offer line on unconnected rows**

Task 2 computes `via_label` for an unconnected bot-capable row, but the page
only renders that field inside the `connected` branch, so today it would be
computed and never seen. Find this block in the row loop:

```javascript
    if (c.status === "connected" && c.name) {
```

and add a branch for the offer, immediately after that block's `}` and before
the existing `else if (c.status !== "available" && c.note)`:

```javascript
    } else if (c.via === "offer" && c.via_label) {
      // Says which bot would carry you BEFORE you connect. Without this the
      // row reads only "ready to connect" and nothing on the page reveals
      // that bringing your own bot is possible at all.
      const offer = document.createElement("div");
      offer.className = "why";
      offer.textContent = c.via_label;
      naming.append(offer);
```

Add the matching test to `mcp-servers/tasks/tests/test_gateway_page_steps.py`:

```python
def test_an_unconnected_row_renders_its_offer_line():
    # The server computes via_label for these rows; without this branch the
    # page computes it and shows nobody.
    assert 'c.via === "offer"' in HTML
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/test_gateway_page_steps.py -q
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && python -m pytest tests/ -q -k "gateway and not db"
```

Expected: the steps file passes; the subset never drops below its previous count.

If an older page-copy test asserted on wording you replaced, update that assertion to the new copy. Do not weaken an assertion into checking nothing.

- [ ] **Step 9: Check the JavaScript actually parses**

Source-text tests cannot catch a syntax error. Extract and check:

```bash
cd "C:/All/Work - Code/ai_ui" && python -c "
import re, pathlib
src = pathlib.Path('mcp-servers/tasks/static/gateway-link.html').read_text(encoding='utf-8')
m = re.search(r'<script>(.*?)</script>', src, re.S)
pathlib.Path('/tmp/page.js').write_text(m.group(1), encoding='utf-8')
" && node --check /tmp/page.js && echo "JS SYNTAX OK"
```

Expected: `JS SYNTAX OK`.

- [ ] **Step 10: Commit**

```bash
git add mcp-servers/tasks/static/gateway-link.html mcp-servers/tasks/tests/test_gateway_page_steps.py
git commit -m "feat(gateway): tell people what to do, in order, with commands they can copy"
```

---

### Task 4: Look at it, then ship it

**Files:**
- No source changes unless the render shows a defect.

**Interfaces:**
- Consumes: everything above.
- Produces: two screenshots and a deployed, verified page.

- [ ] **Step 1: Render both expanded rows**

Every UI defect in this feature so far was invisible to tests and reviews and obvious in a screenshot. Write a throwaway script in the scratchpad (not the repo) that calls `routes_gateway.link_page()`, injects a realistic `window.__CHANNELS__`, stubs `fetch` so it never resolves, expands the Telegram row and then the Terminal row, and saves two PNGs to:

`C:\Users\RYZENmsiPROddr4\AppData\Local\Temp\claude\C--All-Work---Code-ai-ui\82825e98-a66d-4fe2-98d4-bc2284cf3049\scratchpad\`

Use `chromium.launch()` with `color_scheme="dark"`. Playwright and Chromium both work on this machine.

Name them `steps-telegram.png` and `steps-terminal.png`.

- [ ] **Step 2: Actually look at them**

Check each one and report what you saw:
- Are the steps numbered and in order?
- Is the command readable and not overflowing its box?
- Does the Terminal row show the download command, and NOT any mention of a bot?
- Does the unconnected Telegram row's line beneath the badge name both ways in?
- Does the badge read `READY TO CONNECT`?

If any answer is no, fix it and re-render before continuing.

- [ ] **Step 3: Verify the served client is reachable in the built image**

```bash
cd "C:/All/Work - Code/ai_ui" && ls -l mcp-servers/tasks/static/io.py
```

Expected: present, same byte count as `scripts/io.py`.

- [ ] **Step 4: Commit any fixes from the render**

```bash
git add -A mcp-servers/tasks
git commit -m "fix(gateway): correct what the rendered page showed"
```

Skip this step if the render was clean; say so in your report.

---

## Deployment (do not run without asking Ralph)

This ships the tasks service only. The runbook is
`docs/runbooks/deploy-bring-your-own-bot.md`; its traps still apply. In short:

1. Ship the changed files by tar over ssh, never `scp -r`, then `sed -i 's/\r$//'`.
2. Rebuild with `docker compose -f docker-compose.unified.yml up -d --build tasks`, detached via `systemd-run`, because SSH drops mid-build.
3. Verify: `curl -fsS https://ai-ui.coolestdomain.win/tasks/static/io.py | head -1` returns the shebang, and the page's Terminal row shows the download command.
4. Confirm `docker exec tasks printenv GATEWAY_CLI_ENABLED` is still `1`, and that `WEBUI_SECRET_KEY` is still set. Both have been silently dropped by a rebuild before.

## What this plan does not do

- Split `gateway-link.html`. Several existing tests assert on that file's source text and would all need rewiring, so it is churn without user-visible gain.
- Serve the client at a prettier `/io.py`. That needs an edit to the host systemd Caddyfile, which is riskier than the gain.
- Make Slack, Discord or any other channel connectable.
