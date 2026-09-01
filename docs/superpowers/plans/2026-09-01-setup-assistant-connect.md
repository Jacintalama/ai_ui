# Setup Assistant: Connect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When somebody asks about email, files or any connectable app, the assistant checks what they actually have, says so, and puts one button in front of them that opens the login, so nobody has to find the Connections page.

**Architecture:** One read-only endpoint in the `tasks` service assembles what a person has connected and how to connect what they have not. A native Open WebUI tool exposes that to every model, so the AI decides when to offer rather than a keyword regex guessing. The tool returns a marker link; a frontend script in `integrations-ui.js` turns that link into a button which opens the vendor login in a new tab when the browser allows popups, and otherwise opens the Connections panel scrolled to the right app.

**Tech Stack:** Python 3.11, FastAPI, httpx, pytest (`asyncio_mode = auto`), an Open WebUI Tool function (pydantic `Valves`), vanilla JS in a bind-mounted file, Docker Compose on Hetzner.

**Spec:** `docs/superpowers/specs/2026-09-01-io-gateway-and-setup-assistant-design.md` (the "Phase 2: the setup assistant" section, connect half only. Creating agents and schedules by chat is a separate plan.)

## Global Constraints

- **Commit messages carry no AI attribution.** No `Co-Authored-By`, no "Generated with". Author is Ralph Benitez only. Non-negotiable.
- **No em-dashes or en-dashes in any user-visible copy**, and this plan is almost entirely user-visible copy. In tests asserting their absence use `"\u2014"` / `"\u2013"`, never the literal characters. Two implementers on the previous plan shipped literal dashes in exactly such a test.
- **No UTF-8 BOM on any file.**
- **`git add` named paths only. Never `git add -A` or `git add .`** This repo carries a large untracked `apps/` tree; an implementer once swept 174 unrelated files and 10MB of binaries into a commit.
- **`mcp-servers/gdrive/integrations-ui.js` is BIND-MOUNTED into the open-webui container.** Deploy it by writing in place with `cat >`, never `scp` and never `sed -i`, or the inode changes and the mount silently breaks.
- **The login itself is never automated.** We open the door; the person walks through it. Completing OAuth on somebody's behalf would mean holding their password and second factor, which is the thing OAuth exists to avoid.
- **Never log or store a minted token or an API key**, and never put one in a response body. This project has already leaked a bot token through a client that logged a request URL.
- Only two providers can show a real vendor login: **Google** (Gmail, Calendar, Drive) and **Notion**. Seven others (ClickUp, Trello, Airtable, HubSpot, GitHub, n8n, Zapier) take a pasted API key and must use the panel path. Do not invent OAuth for them.
- Baseline for the tasks suite: **3048 passed, 70 skipped, 147 errors** (the 147 are pre-existing `db_session` setup failures from having no local Postgres). `tests/test_edit_route.py` is known order-dependent flaky and fails on `main` too.
- Repo checks out CRLF on Windows. Preserve each file's existing line endings.

---

### Task 1: What this person has, and how to get the rest

**Files:**
- Create: `mcp-servers/tasks/account_summary.py`
- Test: `mcp-servers/tasks/tests/test_account_summary.py`

**Interfaces:**
- Consumes: `routes_agents.tools_for_email(email) -> dict` (already exists; returns `{"tools": [{"id","label","connected","connect_url"}]}`).
- Produces: `summarise(email: str) -> dict`, `PROVIDERS`, `OAUTH_PROVIDERS`, `connect_hint(provider_id) -> dict`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_account_summary.py`:

```python
"""What somebody has connected, and how to connect what they have not.

Read only by design. This is what lets the assistant say "you have no
ClickUp" instead of guessing, and every other thing it offers depends on
knowing that. Nothing here can change anything.
"""
from unittest.mock import AsyncMock

import pytest

import account_summary as acc


@pytest.fixture
def tools(monkeypatch):
    async def fake(email):
        return {"tools": [
            {"id": "gmail", "label": "Gmail", "connected": True},
            {"id": "gdrive", "label": "Google Drive", "connected": False},
            {"id": "clickup", "label": "ClickUp", "connected": False},
        ]}
    monkeypatch.setattr(acc, "tools_for_email", fake)


async def test_it_says_what_is_connected_and_what_is_not(tools):
    out = await acc.summarise("owner@example.com")
    assert [c["id"] for c in out["connected"]] == ["gmail"]
    assert {c["id"] for c in out["not_connected"]} == {"gdrive", "clickup"}


async def test_google_gets_a_login_link_and_clickup_gets_the_panel(tools):
    """Only Google and Notion have a registered OAuth app. Everything else
    takes a pasted key, so offering it a login tab would be a lie."""
    out = await acc.summarise("owner@example.com")
    by_id = {c["id"]: c for c in out["not_connected"]}
    assert by_id["gdrive"]["how"] == "login"
    assert by_id["clickup"]["how"] == "key"


async def test_every_unconnected_app_carries_a_link_the_model_can_print(tools):
    """The frontend turns this into a button. Without it the assistant can
    only tell somebody to go and find the Connections page themselves, which
    is the thing this feature exists to remove."""
    out = await acc.summarise("owner@example.com")
    for c in out["not_connected"]:
        assert c["connect_url"].startswith("#aiui-connect:")
        assert c["connect_url"].endswith(c["id"])


async def test_a_key_app_says_where_its_key_lives(tools):
    """Somebody who does not know how to connect ClickUp is not helped by
    being told to paste a key with no idea where to find one."""
    out = await acc.summarise("owner@example.com")
    clickup = next(c for c in out["not_connected"] if c["id"] == "clickup")
    assert clickup["where"], "no pointer to where the key comes from"


async def test_it_never_raises_when_the_tools_read_fails(monkeypatch):
    """A broken read must degrade to the emptiest honest answer, not stop
    the assistant answering at all."""
    async def boom(email):
        raise RuntimeError("down")
    monkeypatch.setattr(acc, "tools_for_email", boom)
    out = await acc.summarise("owner@example.com")
    assert out["connected"] == [] and out["not_connected"] == []


@pytest.mark.parametrize("email", ["", None])
async def test_nobody_gets_nothing(email):
    out = await acc.summarise(email)
    assert out["connected"] == [] and out["not_connected"] == []


def test_only_google_and_notion_can_show_a_login():
    """If this set grows, somebody registered a real OAuth app with that
    vendor. It is not a code change on its own."""
    assert acc.OAUTH_PROVIDERS == frozenset({"gmail", "gdrive", "calendar", "notion"})


def test_no_dashes_in_any_hint():
    for pid in acc.PROVIDERS:
        h = acc.connect_hint(pid)
        for value in h.values():
            if isinstance(value, str):
                assert "\u2014" not in value and "\u2013" not in value
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_account_summary.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'account_summary'`

- [ ] **Step 3: Write the implementation**

Create `mcp-servers/tasks/account_summary.py`:

```python
"""What somebody has connected, and how they would connect the rest.

Read only. This is the half that lets the assistant say "you have no
ClickUp" rather than guessing, and it is what every offer it makes depends
on. Nothing here changes anything, which is why it needs no confirmation
step and can be handed to every model.

The split that matters is `how`. Only Google and Notion have a registered
OAuth app, so only they can show a real vendor login. The other seven take
a pasted API key. Telling somebody to "log in to ClickUp" when no such flow
exists would send them looking for a button that is not there.
"""
import logging

from routes_agents import tools_for_email

logger = logging.getLogger(__name__)

#: Providers that can show a real vendor login, because somebody registered
#: an OAuth app with that vendor. Growing this set is paperwork with the
#: vendor first and a code change second.
OAUTH_PROVIDERS = frozenset({"gmail", "gdrive", "calendar", "notion"})

#: Where a person finds the API key for the apps that take one. Without
#: this, "paste your key" is not help, it is a scavenger hunt.
PROVIDERS = {
    "gmail": {"label": "Gmail"},
    "gdrive": {"label": "Google Drive"},
    "calendar": {"label": "Google Calendar"},
    "notion": {"label": "Notion"},
    "clickup": {"label": "ClickUp",
                "where": "ClickUp, under Settings then Apps"},
    "trello": {"label": "Trello",
               "where": "trello.com/power-ups/admin, under API key"},
    "airtable": {"label": "Airtable",
                 "where": "airtable.com/create/tokens"},
    "hubspot": {"label": "HubSpot",
                "where": "HubSpot, under Settings then Integrations then Private Apps"},
    "github": {"label": "GitHub",
               "where": "github.com/settings/tokens"},
    "n8n": {"label": "n8n", "where": "your n8n instance, under Settings then API"},
    "zapier": {"label": "Zapier", "where": "zapier.com, under your account settings"},
}


def connect_hint(provider_id: str) -> dict:
    """How this app connects, and what the model should print to offer it.

    The link is a marker, not a real URL. integrations-ui.js finds it and
    turns it into a button, which is what lets one shape serve both a vendor
    login and a key paste.
    """
    meta = PROVIDERS.get(provider_id, {})
    oauth = provider_id in OAUTH_PROVIDERS
    return {
        "id": provider_id,
        "label": meta.get("label") or provider_id,
        "how": "login" if oauth else "key",
        "connect_url": "#aiui-connect:" + provider_id,
        "where": "" if oauth else (meta.get("where") or "that app's settings"),
    }


async def summarise(email: str) -> dict:
    """What this person has connected, and how to connect what they have not.

    Never raises. A broken read degrades to the emptiest honest answer,
    because an assistant that cannot check is still useful and one that
    crashes is not.
    """
    if not email:
        return {"connected": [], "not_connected": []}
    try:
        data = await tools_for_email(email)
        tools = data.get("tools") or []
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read what is connected", exc_info=True)
        return {"connected": [], "not_connected": []}

    connected, missing = [], []
    for t in tools:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        entry = {"id": t["id"], "label": t.get("label") or t["id"]}
        if t.get("connected"):
            connected.append(entry)
        else:
            missing.append(connect_hint(t["id"]))
    return {"connected": connected, "not_connected": missing}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_account_summary.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Prove the login/key split bites**

That split is the one thing here a user notices when it is wrong. Temporarily add `"clickup"` to `OAUTH_PROVIDERS`, run the suite, confirm `test_google_gets_a_login_link_and_clickup_gets_the_panel` FAILS, then restore and confirm green. Paste both outputs in your report.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/account_summary.py mcp-servers/tasks/tests/test_account_summary.py
git commit -m "feat(setup): know what a person has connected, and how to connect the rest"
```

---

### Task 2: The endpoint and the tool that reach it

**Files:**
- Create: `mcp-servers/tasks/routes_account.py`
- Modify: `mcp-servers/tasks/main.py` (one import, one `include_router`)
- Create: `open-webui-functions/account_tool.py`
- Test: `mcp-servers/tasks/tests/test_account_endpoint.py`

**Interfaces:**
- Consumes: `account_summary.summarise(email)` (Task 1); `routes_gateway._require_internal`.
- Produces: `GET /account/summary?user_email=...` returning `{"connected": [...], "not_connected": [...]}`; an Open WebUI `Tools` class with one method `my_account(__user__) -> str`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_account_endpoint.py`:

```python
"""The endpoint the assistant's tool calls.

Internal only, like every other endpoint that acts for a named user.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import routes_account as ra


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(ra, "_require_internal", lambda s: None)
    monkeypatch.setattr(ra, "summarise", AsyncMock(return_value={
        "connected": [{"id": "gmail", "label": "Gmail"}],
        "not_connected": [{"id": "clickup", "label": "ClickUp", "how": "key",
                           "connect_url": "#aiui-connect:clickup",
                           "where": "ClickUp, under Settings then Apps"}]}))


async def test_it_returns_the_summary_for_the_named_user():
    out = await ra.summary(user_email="owner@example.com", x_internal_secret="s")
    assert out["connected"][0]["id"] == "gmail"
    assert out["not_connected"][0]["id"] == "clickup"
    assert ra.summarise.await_args.args[0] == "owner@example.com"


async def test_the_internal_secret_is_required(monkeypatch):
    def deny(secret):
        raise HTTPException(status_code=403, detail="invalid internal secret")
    monkeypatch.setattr(ra, "_require_internal", deny)
    with pytest.raises(HTTPException) as caught:
        await ra.summary(user_email="o@e.com", x_internal_secret="wrong")
    assert caught.value.status_code == 403


async def test_the_secret_is_checked_before_any_work(monkeypatch):
    """An unauthenticated caller must not be able to make us read a
    database, even if the answer is then thrown away."""
    calls = []
    monkeypatch.setattr(ra, "summarise",
                        AsyncMock(side_effect=lambda e: calls.append(e)))

    def deny(secret):
        raise HTTPException(status_code=403, detail="nope")
    monkeypatch.setattr(ra, "_require_internal", deny)

    with pytest.raises(HTTPException):
        await ra.summary(user_email="o@e.com", x_internal_secret="wrong")
    assert calls == [], "work happened before the secret was checked"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_account_endpoint.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'routes_account'`

- [ ] **Step 3: Write the endpoint**

Create `mcp-servers/tasks/routes_account.py`:

```python
"""What a person has connected, over HTTP, for the assistant's tool.

Internal only and mounted once, like every other endpoint that acts for a
named user. Read only, so there is nothing here to confirm and nothing it
can break.
"""
import logging

from fastapi import APIRouter, Header

from account_summary import summarise
from routes_gateway import _require_internal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account")


@router.get("/summary")
async def summary(user_email: str,
                  x_internal_secret: str = Header(default="")) -> dict:
    """What this person has connected, and how to connect the rest."""
    _require_internal(x_internal_secret)
    return await summarise(user_email)
```

In `mcp-servers/tasks/main.py`, add the import beside the other route imports:

```python
from routes_account import router as account_router
```

and mount it ONCE, near the other internal-only mounts:

```python
app.include_router(account_router)  # /account — internal only (X-Internal-Secret)
```

Do not add a second mount under `/api/tasks`; that prefix is reachable by an ordinary signed-in browser.

- [ ] **Step 4: Write the native tool**

Create `open-webui-functions/account_tool.py`:

```python
"""
title: My Account
author: Ralph Benitez
version: 1.0.0
description: Checks what apps you have connected, so the assistant can offer to connect the ones you do not, with a button instead of instructions.
requirements: httpx
"""
# Read only. This is what lets the assistant say "you have no ClickUp"
# instead of guessing, and it is what replaced a regex that fired on the
# word "email" appearing anywhere in a message.
#
# The connect link it prints is a marker, not a real URL.
# mcp-servers/gdrive/integrations-ui.js finds it in the rendered answer and
# turns it into a button. That is what lets one shape serve both a vendor
# login and an API key paste, and it is why the model does not need to know
# which is which.
import os

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        internal_secret: str = Field(
            default=os.environ.get("INTERNAL_CALLBACK_SECRET", ""))
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    async def my_account(self, __user__: dict = {}) -> str:
        """
        Check which apps the user has connected to this platform, and which
        they have not. Call this whenever the user asks about connecting
        something, asks what they have connected, asks why an agent cannot
        reach their mail or files, or asks for help setting anything up.
        Call it before offering to connect anything, so the answer is about
        what they actually have.
        """
        email = (__user__ or {}).get("email") or ""
        if not email:
            return ("I could not tell whose account this is, so I did not "
                    "check anything.")
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                r = await c.get(
                    self.valves.tasks_url.rstrip("/") + "/account/summary",
                    params={"user_email": email},
                    headers={"X-Internal-Secret": self.valves.internal_secret})
                r.raise_for_status()
                data = r.json()
        except Exception:                                   # noqa: BLE001
            # Never include the exception text: an httpx error carries the
            # request URL, and this project has already leaked a token that way.
            return ("I could not check your connected apps just now. Try "
                    "again in a moment.")

        connected = data.get("connected") or []
        missing = data.get("not_connected") or []

        lines = []
        if connected:
            lines.append("Connected: "
                         + ", ".join(c.get("label", c.get("id", "")) for c in connected))
        else:
            lines.append("Nothing is connected yet.")

        if missing:
            lines.append("")
            lines.append("Not connected yet. To offer one, print its markdown "
                         "link exactly as given and say one short sentence "
                         "about what it would let them do:")
            for m in missing:
                label = m.get("label") or m.get("id")
                link = "[Connect %s](%s)" % (label, m.get("connect_url", ""))
                if m.get("how") == "key":
                    lines.append("  %s  (needs an API key from %s)"
                                 % (link, m.get("where") or "that app's settings"))
                else:
                    lines.append("  %s  (opens a login)" % link)
        return "\n".join(lines)
```

- [ ] **Step 5: Run the tests and the route check**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_account_endpoint.py tests/test_account_summary.py -q -p no:cacheprovider`
Expected: PASS

Then confirm the route is mounted once and internal only:
```bash
cd mcp-servers/tasks && python -c "
from main import app
paths = sorted({getattr(r,'path','') for r in app.routes if 'account' in getattr(r,'path','')})
print(paths)
assert '/account/summary' in paths and '/api/tasks/account/summary' not in paths
print('mounted once, internal path only')
"
```

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_account.py mcp-servers/tasks/main.py open-webui-functions/account_tool.py mcp-servers/tasks/tests/test_account_endpoint.py
git commit -m "feat(setup): the assistant can check what you have connected"
```

---

### Task 3: One button, whichever way the app connects

**Files:**
- Modify: `mcp-servers/gdrive/integrations-ui.js`
- Test: `mcp-servers/tasks/tests/test_connect_button.py`

**Interfaces:**
- Consumes: the `#aiui-connect:<provider>` marker links printed by the tool (Task 2).
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_connect_button.py`:

```python
"""The button the assistant's link becomes.

Structural, because this file is vanilla JS with no test harness. These
check the things that would silently break the flow, and the browser pass
in Task 4 is what actually proves it works.
"""
import os
import re

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def test_the_marker_link_is_recognised():
    assert "#aiui-connect:" in _js()


def test_a_blocked_popup_is_detected_and_explained():
    """Chrome blocks a window.open that no click triggered, and a blocked
    call returns null. Without checking, the user clicks and nothing at all
    happens, which reads as the feature being broken."""
    js = _js()
    assert re.search(r"window\.open\(", js)
    assert re.search(r"aiuiPopupBlocked|popupBlocked", js), (
        "nothing detects a blocked popup")


def test_there_is_a_panel_fallback():
    """Somebody who never allows popups must still be able to connect."""
    assert "aiuiOpenConnections" in _js()


def test_the_login_is_never_completed_for_the_user():
    """We open the door. Automating the login would mean holding somebody's
    password and second factor, which is what OAuth exists to avoid."""
    js = _js()
    for bad in ["password", "autofill", "document.forms[0].submit"]:
        assert bad not in js.lower().split("aiui-connect")[-1][:4000], bad


def test_no_dashes_in_the_new_copy():
    assert "\u2014" not in _js() and "\u2013" not in _js()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_connect_button.py -q -p no:cacheprovider`
Expected: FAIL on the marker-link and popup-detection assertions.

- [ ] **Step 3: Implement**

In `mcp-servers/gdrive/integrations-ui.js`, add this block immediately before the existing `linkifyConnectButtons()` definition (around line 2537), and add `wireAiuiConnectLinks();` beside the existing `linkifyConnectButtons();` call at the bottom of the file:

```javascript
  // ===== The assistant's connect links =====
  // The My Account tool prints [Connect Gmail](#aiui-connect:gmail). This
  // finds those and turns them into buttons.
  //
  // Popup first, because that is the flow somebody actually wants: one
  // click and the vendor's login opens. Chrome blocks a window.open that no
  // click triggered, and a blocked call returns null, so we can tell and
  // say so. Once the person allows popups for this site the block is gone
  // for good and later connects open with no fuss.
  //
  // Panel second, so that somebody who never allows popups is never stuck.
  //
  // The login itself is always theirs. We open the door.
  var AIUI_CONNECT_MARKER = '#aiui-connect:';

  function aiuiConnectUrlFor(provider) {
    var email = getEffectiveEmail();
    if (provider === 'gmail') return GMAIL_API + '/auth/google/start?user_email=' + encodeURIComponent(email);
    if (provider === 'gdrive') return GDRIVE_API + '/auth/google/start?user_email=' + encodeURIComponent(email);
    if (provider === 'calendar') return CALENDAR_API + '/auth/google/start?user_email=' + encodeURIComponent(email);
    return null;  // key-paste apps have no login to open
  }

  function aiuiPopupBlocked(win) {
    // A blocked window.open returns null in Chrome; some browsers return a
    // window that is immediately closed.
    return !win || win.closed || typeof win.closed === 'undefined';
  }

  function aiuiSayBlocked(container) {
    var note = document.createElement('div');
    note.className = 'aiui-connect-note';
    note.style.cssText = 'margin-top:6px;font-size:12.5px;color:#c8c8c8;';
    note.textContent = 'Chrome blocked that window. Click the blocked icon in '
      + 'your address bar and choose Always allow, and I can open these for '
      + 'you from now on. Or use the panel button above.';
    if (!container.querySelector('.aiui-connect-note')) container.appendChild(note);
  }

  function wireAiuiConnectLink(anchor) {
    if (!anchor || anchor.getAttribute('data-aiui-wired')) return;
    var href = anchor.getAttribute('href') || '';
    var i = href.indexOf(AIUI_CONNECT_MARKER);
    if (i === -1) return;
    var provider = href.slice(i + AIUI_CONNECT_MARKER.length).trim();
    if (!provider) return;
    anchor.setAttribute('data-aiui-wired', '1');

    var container = document.createElement('span');
    container.className = 'aiui-connect-inline';
    var btn = document.createElement('button');
    btn.textContent = anchor.textContent || ('Connect ' + provider);
    btn.style.cssText = 'padding:8px 16px;background:#4CAF50;color:#fff;border:none;'
      + 'border-radius:8px;font-size:13.5px;font-weight:600;cursor:pointer;';
    container.appendChild(btn);
    if (anchor.parentNode) anchor.parentNode.replaceChild(container, anchor);

    btn.addEventListener('click', function () {
      var url = aiuiConnectUrlFor(provider);
      if (!url) {
        // A key-paste app. There is no vendor login to open, so the panel
        // is the whole flow rather than a fallback.
        window.aiuiOpenConnections();
        return;
      }
      var win = window.open(url, '_blank');
      if (aiuiPopupBlocked(win)) {
        aiuiSayBlocked(container);
        window.aiuiOpenConnections();
      }
    });
  }

  function wireAiuiConnectLinks() {
    var pending = false;
    function scan() {
      pending = false;
      var anchors = document.querySelectorAll('a[href*="' + AIUI_CONNECT_MARKER + '"]');
      for (var i = 0; i < anchors.length; i++) wireAiuiConnectLink(anchors[i]);
    }
    var obs = new MutationObserver(function () {
      if (pending) return;
      pending = true;
      setTimeout(scan, 200);
    });
    obs.observe(document.body, { childList: true, subtree: true });
    scan();
  }
```

- [ ] **Step 4: Retire the keyword watcher**

`maybePromptConnect` and `detectConnectService` fire on `/(gmail|e-?mail|inbox|...)/` appearing anywhere in a message. That is the same shape as the auto-send watcher already disabled a few hundred lines above in this same file, for popping a modal whenever a message mentioned sending. Now that the model decides deliberately, keyword guessing is a liability rather than a fallback.

Change `setupChatConnectWatcher` to return immediately, in the same style as the disabled watcher above it, with a comment saying the My Account tool replaced it and pointing at `wireAiuiConnectLinks`. Leave the functions in place rather than deleting them, matching how the earlier watcher was retired.

- [ ] **Step 5: Run the tests**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_connect_button.py -q -p no:cacheprovider`
Expected: PASS

Then confirm the file still parses as JavaScript, because a syntax error here takes the whole Open WebUI page down and no Python test would catch it:
```bash
node --check mcp-servers/gdrive/integrations-ui.js && echo "JS parses"
```
If `node` is unavailable, verify by reading that every function you added is closed and the file still ends with `})();`.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/gdrive/integrations-ui.js mcp-servers/tasks/tests/test_connect_button.py
git commit -m "feat(setup): one button connects, whichever way the app connects"
```

---

### Task 4: Deploy and prove it in a browser

**Files:**
- No source changes. This task is deployment and verification.

- [ ] **Step 1: Confirm the tree is clean and the suite passes**

```bash
cd "C:/All/Work - Code/ai_ui"
git status --short | grep -v "^?? apps/" | grep -v "^?? _aiui_demo" | grep -v "^?? .superpowers"
cd mcp-servers/tasks && python -m pytest tests/ -q -p no:cacheprovider 2>&1 | tail -3
```
Expected: no unexpected modified files; at or above **3048 passed, 70 skipped, 147 errors**. `tests/test_edit_route.py` is known order-dependent flaky and fails on `main` too, so one failure there is not yours; anything else is.

- [ ] **Step 2: Deploy the tasks service**

`rsync` is absent from Git Bash on Windows, so the orchestrator will not run. One `scp` per file (`scp -r` silently skips files), then normalise line endings, then verify by hash before rebuilding:

```bash
cd "C:/All/Work - Code/ai_ui"
for f in mcp-servers/tasks/account_summary.py mcp-servers/tasks/routes_account.py mcp-servers/tasks/main.py; do
  scp -o ConnectTimeout=25 "$f" "root@46.224.193.25:/root/proxy-server/$f"
done
ssh root@46.224.193.25 "cd /root/proxy-server/mcp-servers/tasks && sed -i 's/\r\$//' account_summary.py routes_account.py main.py"
```

Compare `sed 's/\r$//' <file> | md5sum` locally against `md5sum <file>` on the server for all three. They must match before rebuilding.

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

- [ ] **Step 3: Deploy the bind-mounted frontend correctly**

`integrations-ui.js` is bind-mounted. Writing it with `scp` changes the inode and silently breaks the mount, so the container keeps serving the old file with no error anywhere.

```bash
cd "C:/All/Work - Code/ai_ui"
ssh root@46.224.193.25 "cp /root/proxy-server/mcp-servers/gdrive/integrations-ui.js /root/integrations-ui.js.bak.\$(date +%s) && stat -c '%i' /root/proxy-server/mcp-servers/gdrive/integrations-ui.js"
sed 's/\r$//' mcp-servers/gdrive/integrations-ui.js | ssh root@46.224.193.25 "cat > /root/proxy-server/mcp-servers/gdrive/integrations-ui.js"
ssh root@46.224.193.25 "stat -c '%i' /root/proxy-server/mcp-servers/gdrive/integrations-ui.js && docker exec open-webui grep -c aiui-connect /app/build/static/integrations-ui.js"
```
The inode must be **unchanged** and the container grep must be non-zero. If either fails, the mount is broken; restore from the backup and investigate before continuing.

- [ ] **Step 4: Verify the service and the endpoint's exposure**

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
for p in "/tasks/account/summary" "/api/tasks/account/summary" "/account/summary"; do
  printf "%s -> " "$p"
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 "https://ai-ui.coolestdomain.win$p?user_email=x@y.com"
done
ssh root@46.224.193.25 "docker exec api-gateway sh -lc 'curl -s -o /dev/null -w \"internal, no secret -> %{http_code}\n\" --max-time 10 \"http://tasks:8210/account/summary?user_email=x@y.com\"'"
```
Expected: healthy; 403, 404 or 405 from every public path; `403` internally without the secret.

- [ ] **Step 5: Exercise the summary with the real secret**

Run inside the container so the secret never leaves it:
```bash
ssh root@46.224.193.25 "docker exec tasks python -c \"
import os, httpx
sec = os.environ.get('INTERNAL_CALLBACK_SECRET','')
r = httpx.get('http://localhost:8210/account/summary',
    params={'user_email':'ralphbenitez32@gmail.com'},
    headers={'X-Internal-Secret': sec}, timeout=60)
d = r.json()
print('status:', r.status_code)
print('connected:', [c['id'] for c in d.get('connected',[])])
for m in d.get('not_connected',[]):
    print('  missing:', m['id'], '| how:', m['how'], '| link:', m['connect_url'])
\""
```
Expected: Gmail, Drive and Calendar under connected (this account has all three); the rest listed as missing, with Notion showing `how: login` and ClickUp showing `how: key`.

- [ ] **Step 6: Install the tool in Open WebUI**

The tool is a function, not a file the container reads from disk. Ralph installs it, since it is pasted into the admin UI:

1. Open `https://ai-ui.coolestdomain.win/admin/functions`
2. Click **Create**, paste the contents of `open-webui-functions/account_tool.py`, save
3. Confirm it appears **enabled**

Then grant it, the way the other native tools are granted, and confirm:
```bash
ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -t -c \"SELECT id, name, is_active FROM public.tool WHERE id LIKE '%account%';\""
```

- [ ] **Step 7: Prove it in a browser, which is the only proof that counts**

The structural tests cannot see whether a button appears. Ralph does this:

1. In a chat, ask **"can I connect ClickUp?"**. Expected: the assistant checks, says ClickUp is not connected, mentions where its key lives, and shows a **Connect ClickUp** button. Clicking it opens the Connections panel, since ClickUp has no login to open.
2. Ask **"what have I connected?"**. Expected: Gmail, Drive and Calendar listed as connected, without a button, because there is nothing to do.
3. Sign in as a user with nothing connected, or use a test account, and ask **"can I connect my email?"**. Expected: a **Connect Gmail** button that opens Google's login in a new tab.
4. With popups blocked for the site, click that button. Expected: the Connections panel opens AND the note about the blocked-popup icon appears. This is the path most likely to be wrong, and it is invisible to every test in this plan.
5. Type **"can you email me the report"** with everything connected. Expected: **no** connect card. The retired keyword watcher used to fire here, and this confirms it is gone.

- [ ] **Step 8: Stamp the deploy state**

`.deploy-state` is JSON and the orchestrator parses `['sha']`; a bare SHA breaks the next deploy.

```bash
cd "C:/All/Work - Code/ai_ui" && SHA=$(git rev-parse HEAD)
ssh root@46.224.193.25 "cd /root/proxy-server && printf '%s' '{\"sha\": \"'$SHA'\", \"deployed_at\": \"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'\", \"deployed_by\": \"Ralph Benitez\"}' > .deploy-state"
```

Two people work on this box and a second session has deployed mid-work before. Hash-check the server against your local copies before overwriting anything, and re-read `.deploy-state` afterwards rather than assuming your stamp is still current.

---

## Self-Review

**Spec coverage.** Every part of the spec's connect half maps to a task: knowing what is connected (Task 1); the model deciding rather than a regex, via a tool granted to every model (Task 2); the login/key split with only Google and Notion able to show a vendor login (Tasks 1 and 3); popup first with a one-time nudge and the panel as fallback (Task 3); retiring `detectConnectService` (Task 3 step 4); the login never being automated (stated in the constraints, asserted in Task 3's tests, and verified in Task 4 step 7).

**Deliberately out of scope**, and both are called out in the spec: creating agents and schedules by chat, which needs the two-phase propose/confirm machinery and gets its own plan; and anything that deletes.

**Naming consistency.** `summarise(email)` is defined in Task 1 and imported by Task 2's endpoint under that exact name; the endpoint test monkeypatches `ra.summarise`, which works because `routes_account` imports it into its own namespace. The marker `#aiui-connect:` is produced by `connect_hint` in Task 1 and consumed by `AIUI_CONNECT_MARKER` in Task 3; both are the same literal string. `aiuiOpenConnections` already exists in `integrations-ui.js` and is not created here.

**Known limitation carried forward.** The popup permission is per browser and per device, so allowing it on a laptop does not carry to a phone. That is true of every site and is not something this plan can change; the panel fallback is what makes it not matter.
