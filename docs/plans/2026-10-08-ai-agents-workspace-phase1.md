# AI Agents page, Phase 1: chat-first workspace. Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or
> superpowers:subagent-driven-development) to implement this plan task by task.

**Goal:** Turn `/ai-agents` into the approved Slack-style workspace. A
conversation list sits on the left, the conversation fills the middle at full
height, and a details panel on the right shows the selected agent. The Agent
Office opens on demand inside the conversation area.

**Architecture:**
- Only `static/agents.html` and `static/agent-chat.css` change, plus their
  tests.
- Ralph's office files (`static/office.html`, `static/office/**`) are NOT
  touched. The office keeps its iframe, its postMessage bridge and its own
  layout. It simply is not on screen until it is opened.
- Every existing id stays, so the card logic, forms, memory, the htmx contract
  and the Phase 0 protocol keep working. Elements move and change role.
  Nothing is rewritten that does not have to be.

**Tech stack:** static HTML, CSS and vanilla JS, htmx, pytest plus Playwright
browser tests (local, stubbed).

**Design source:** `docs/plans/2026-10-05-ai-agents-workspace-design.md` and
`DESIGN.md`. **Decision recorded 2026-10-08:** the user chose the original
plan (office off the main screen) after being told that Ralph and the owner
were expanding the office on 10-07 and 10-08. Ralph's office code stays
intact and gets a full-height view when opened.

**Run tests** from `mcp-servers/tasks`:

```bash
DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest <files> -q -p no:cacheprovider
```

**Baseline before Task 1:** run the whole-suite command from
`docs/plans/2026-10-05-ai-agents-workspace-phase0.md` ("Whole-suite command")
on HEAD `d2e88fb00` and record the counts. Ralph's commits added tests, so the
783 from Phase 0 is out of date.

**Rules for every task:**
- Locate edits by quoted anchor, not line number.
- Write the test first, see it fail for the stated reason, implement, see it
  pass, run the neighbour suites, commit.
- No em or en dashes in agents.html. No emoji, no decorative icons.
- Escape all interpolated data with `esc()`.
- Every message listener checks origin AND source.
- Never auto-send a chat message.

**Old tests whose meaning changes:**
- `test_office_inline.py` assumes the office is visible on load and sits
  above the thread.
- `test_agents_ask_prefill.py` and `test_office_inline.py` assert the header
  texts "Chat with Iris" and "Chat with your agents".
- `test_agents_page_fit.py` assumes two columns.

Each task names the tests it changes. A changed test must assert the NEW
behaviour and must fail against the old page. Never delete a test silently: if
a behaviour is removed on purpose, replace its test with one asserting the
removal, and say so in the commit.

---

### Task 1: The office opens on demand and takes the conversation's place

**Files:**
- Modify: `static/agents.html`, the office dock IIFE (anchors:
  `var SHUT_KEY = "aiuiOfficeShut";`, `function show() {`,
  `function hide() {`, `if (saved(SHUT_KEY) === "1") hide();`) and the dock
  markup (`<section class="office-card" id="office-dock"`).
- Modify: `static/agent-chat.css`.
- Test: `tests/browser/test_office_inline.py`. Add the tests below; change the
  `page` fixture and every existing test that needs the office open, so that
  they open it first (helper `_open_office(page)` clicks `#office-open`).

**Behaviour:**
1. On a first visit the office is not on screen and no office iframe exists
   (`#office-body iframe` count 0). This keeps the lazy build.
2. `#office-open` (label "Agent Office") opens the office VIEW:
   - `#office-dock` is shown and fills the chat column (`height: 100%`, so
     the grip and its height logic are not used in this view);
   - `#agent-panel` is hidden;
   - the iframe is built.
3. `#office-close` is relabelled "Back to conversation". It hides the office
   and shows `#agent-panel` again.
4. Whether the office view was open is remembered under a NEW key,
   `aiuiOfficeView` (`"1"` while open). The old `aiuiOfficeShut` key is
   ignored, because its default (shown) is the old design.
5. Anything that opens a conversation from inside the office returns to the
   conversation:
   - a robot's Chat or a skill link (`aiui-office-ask`);
   - the meeting button.

   Implement it as `window.aiuiTalkTo` dispatching
   `CustomEvent("aiui:conversation-opened")` at its end. The dock listens for
   that event and calls `hide()`. The `aiui-office-ask` handler also calls
   `hide()` after it prefills the room (that path may not call `aiuiTalkTo`).
6. `#office-grip` stays in the DOM (tests and keyboard code reference it) but
   is hidden in this view.

**Step 1: Write the failing tests** (append to `test_office_inline.py`;
`page` is the existing fixture):

```python
def test_the_office_is_not_on_screen_until_it_is_opened(page):
    assert page.locator("#office-dock").is_hidden()
    assert page.locator("#office-body iframe").count() == 0
    assert page.locator("#agent-panel").is_visible()


def test_opening_the_office_gives_it_the_conversations_place(page):
    page.click("#office-open")
    page.locator("#office-body iframe").wait_for(state="attached")
    assert page.locator("#office-dock").is_visible()
    assert page.locator("#agent-panel").is_hidden()
    col = page.locator(".chat-column").bounding_box()
    dock = page.locator("#office-dock").bounding_box()
    assert dock["height"] > col["height"] * 0.9


def test_back_to_conversation_closes_the_office(page):
    page.click("#office-open")
    page.click("#office-close")
    assert page.locator("#office-dock").is_hidden()
    assert page.locator("#agent-panel").is_visible()
    assert page.locator("#office-close").inner_text() == "Back to conversation"


def test_a_robots_chat_returns_to_that_conversation(page):
    page.click("#office-open")
    frame = page.frame_locator("#office-body iframe")
    frame.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(400)
    assert page.locator("#office-dock").is_hidden()
    assert page.locator("#agent-panel").is_visible()
    assert page.locator("#ap-agent").input_value() == "agent-iris-a103"


def test_the_open_office_is_remembered(page):
    page.click("#office-open")
    page.reload()
    page.wait_for_selector("#office-dock", state="attached")
    page.wait_for_timeout(300)
    assert page.locator("#office-dock").is_visible()
```

**Step 2:** run `tests/browser/test_office_inline.py -k "not_on_screen or
conversations_place or back_to_conversation or returns_to_that or
is_remembered"`. Expect 5 failures: the office is visible on load, and the
button label is "Hide".

**Step 3: Implement.**
- Markup: `#office-close` text becomes "Back to conversation".
  `#office-open` loses `hidden` and its text becomes "Agent Office". In
  Task 2 it moves to the list footer; for now it can stay in the header.
- Dock IIFE:

```js
var VIEW_KEY = "aiuiOfficeView";
var panel = document.getElementById("agent-panel");
function show() {
  dock.hidden = false;
  grip.hidden = true;
  if (panel) panel.hidden = true;
  save(VIEW_KEY, "1");
  build();
  dock.style.height = "";
  var f = body.querySelector("iframe");
  if (f) {
    try {
      f.contentWindow.postMessage({ aiuiFrameVisible: true },
                                  window.location.origin);
    } catch (e) { /* not loaded yet: it catches up on its own tick */ }
  }
}
function hide() {
  dock.hidden = true;
  grip.hidden = true;
  if (panel) panel.hidden = false;
  save(VIEW_KEY, null);
}
document.body.addEventListener("aiui:conversation-opened", hide);
// replaces: if (saved(SHUT_KEY) === "1") hide(); else show();
if (saved(VIEW_KEY) === "1") show(); else hide();
```

  Remove the height and grip-drag code only if no remaining test references
  it. Otherwise leave it in place: it does nothing while the grip is hidden.
- `window.aiuiTalkTo` (talk-to script): add, as its last line,

```js
document.body.dispatchEvent(new CustomEvent("aiui:conversation-opened"));
```

- `aiui-office-ask` handler: after `prefill(msg.ask);`, call `hide();`.
- CSS (agent-chat.css): `#office-dock:not([hidden]) { flex: 1 1 auto; height: 100%; }`

**Step 4:**
1. Fix the remaining `test_office_inline.py` tests.
   - Any test that needs the floor calls `_open_office(page)` first.
   - Any test that asserted the old stacked order (office above the thread,
     the grip resize, height remembered, "Hide" plus "Show the office") is
     REPLACED by one asserting the new behaviour. List each replaced test in
     the commit message.
   - Ralph's tests about the floor's content (rooms, robots, meeting,
     handoffs) stay as they are, behind `_open_office`.
2. Run the whole of `test_office_inline.py`, `test_office_page.py`,
   `test_agents_hidden_pane.py`, `test_open_pane_message.py` and
   `test_agents_ask_prefill.py`. All must pass.

**Step 5:** commit: "Agents page: the office opens on demand and takes the
conversation's place".

---

### Task 2: A conversation list on the left

**Files:**
- Modify: `static/agents.html`. Add the new `<nav>` markup as the first
  child of `.agents-layout`. Move the existing `.section-head` (search,
  Connections, New agent) into it. Add a `drawRoster()` script.
- Modify: `static/agent-chat.css`.
- Create: `tests/browser/test_agents_roster.py`. Copy the server and stub
  fixture pattern from `tests/browser/test_agents_ask_prefill.py`
  (`_shell_as_owner`), with an owner and two agents: Iris (Drive librarian)
  and Bo, owned by me.

**Behaviour:**
1. Markup:

```html
<nav class="agents-roster" id="agent-roster" aria-label="Conversations">
  <!-- the existing .section-head moves here unchanged (ids kept) -->
  <div class="roster-list" id="roster-list" role="list"></div>
  <div class="roster-foot">
    <button class="link-btn" type="button" id="office-open">Agent Office</button>
    <a class="link-btn" id="roster-graph" href="/tasks/graph">Knowledge graph</a>
  </div>
</nav>
```

   `#open-connections` stays inside the moved `.section-head`.
2. `drawRoster()` runs on `aiui:cards-drawn`. It reads the drawn cards
   (`#my-agents .card[data-agent-id]`), which are already filtered by the
   search and by ownership, and builds:
   - the first row: `<button class="roster-row" data-room="1">` reading
     "Everyone", with the agents' names joined by ", " as its second line;
   - one row per card: `<button class="roster-row" data-agent-id="...">`
     holding:
     - `<span class="roster-av" style="background:hsl(H 45% 32%)">I</span>`,
       where H comes from `avatarHue(name)` (expose it as
       `window.__aiuiAgents.avatarHue`) and the letter is the first letter of
       the name;
     - the name;
     - the role, taken from `.card-role` text;
     - a status word, only when the card's status is `waiting` ("Needs you")
       or `failed` ("Failed"), read from the card's status element class.

   All text is set with `textContent`, never `innerHTML`.
3. Clicking a row calls `window.aiuiTalkTo(id, name)`; the Everyone row calls
   `window.aiuiTalkTo("", "")`.
4. `paint()` in the talk-to script sets `aria-current="true"` on the row for
   the current conversation (the Everyone row when `current.id` is empty) and
   removes it from the others. `drawRoster()` calls `paint` logic too, by
   firing after `paint`, or `paint` is exposed as `window.__aiuiPaintTalk`.
5. "Knowledge graph": when framed (`window.parent !== window`), the click is
   prevented and `window.parent.postMessage({type: "aiui:open-pane", path:
   "/graph"}, location.origin)` is sent instead (the Phase 0 protocol).
   Standalone, the plain link works.
6. CSS: `.roster-row` is a 48px tall, full-width, transparent button with a
   radius of 8px. Hover and `[aria-current=true]` use `var(--surface-2)`.
   The avatar is 28px with a 6px radius, white 12px/500 text. The role uses
   `var(--text-2)` at 13px with an ellipsis. There is no coloured side stripe.

**Step 1: Tests** (complete them in the new file):
- `test_the_list_starts_with_everyone_then_each_agent`: the row texts begin
  with "Everyone", then "Iris", then "Bo".
- `test_picking_an_agent_opens_their_conversation`: click the Iris row;
  `#ap-agent` is "agent-iris-a103" and the row has `aria-current="true"`.
- `test_everyone_goes_back_to_the_room`: click Iris, then Everyone;
  `#ap-agent` is "" and the Everyone row is current.
- `test_search_filters_the_list`: type "bo" in `#agent-search`; the rows are
  Everyone and Bo only.
- `test_a_name_is_text_not_markup`: an agent named `<img src=x onerror=...>`
  shows that literal text and adds no `img` element.
- `test_knowledge_graph_asks_the_shell_when_framed`: in the shell fixture,
  record `window.parent` messages; clicking the link sends `aiui:open-pane`
  with path `/graph`, and the pane does not navigate.
- `test_nothing_is_sent_by_picking`: no POST to chat/send.

**Step 2:** run the file. Expect every test to fail, because `#roster-list`
does not exist.

**Step 3:** implement as above.

**Step 4:**
1. Run `test_agents_roster.py`, `test_agents_page.py`,
   `test_agents_ask_prefill.py`, `test_office_inline.py`,
   `test_agents_page_a11y.py` and `test_static_page_js.py`. All must pass.
2. Fix any pinned test that located the search or the buttons inside
   `.agents-main`. The ids are unchanged, so most selectors still work.

**Step 5:** commit: "Agents page: a conversation list on the left".

---

### Task 3: The conversation header says who hears you

**Files:**
- Modify: `static/agents.html` (`paint()` in the talk-to script, and the
  `.ap-head` markup).
- Test: `tests/browser/test_agents_roster.py`, plus updates to
  `test_agents_ask_prefill.py` and `test_office_inline.py` where they assert
  the old texts.

**Behaviour:**
1. Room:
   - `#ap-who` reads "Everyone";
   - `#ap-sub` reads "<names> hear this. Each answers only if it has
     something to add.", where `<names>` joins the agents' names with ", "
     and " and " when there are 3 or fewer, and reads "All N agents"
     otherwise;
   - the placeholder reads "Message everyone".
2. Private conversation:
   - `#ap-who` is the agent's name;
   - `#ap-sub` reads "<role>. Only <name> hears this conversation.", or
     "Only <name> hears this conversation." when there is no role;
   - the placeholder reads "Message <name>".
3. `#ap-everyone` stays in the DOM but is always hidden: the list replaces
   it.
4. The names and the role come from the roster or the cards (DOM text), and
   are set with `textContent`.

**Step 1: Tests:**
- `test_the_room_header_names_who_hears_it` (Iris and Bo):
  - `#ap-who` reads "Everyone";
  - `#ap-sub` reads "Iris and Bo hear this. Each answers only if it has
    something to add.";
  - the placeholder reads "Message everyone".
- `test_a_private_header_names_the_agent_and_role` (Iris):
  - `#ap-who` reads "Iris";
  - `#ap-sub` reads "Drive librarian. Only Iris hears this conversation.";
  - the placeholder reads "Message Iris".
- Update `test_agents_ask_prefill.py::test_the_shell_opens_your_agents_own_conversation`,
  which asserts "Chat with Iris", to assert "Iris". Update every other
  "Chat with ..." assertion found by
  `grep -rn "Chat with" tests/browser/*.py` the same way.

**Steps 2 to 5:** red, implement, green on the same suites as Task 2, then
commit: "Agents page: the conversation says who hears it".

---

### Task 4: The details panel on the right

**Files:**
- Modify: `static/agents.html`:
  - the `.chat-column` header gets a `#details-toggle` button;
  - `.agents-main` becomes the details panel;
  - the talk-to `paint()` marks the current card;
  - the "Your agents" heading becomes "Details" in a private conversation.
- Modify: `static/agent-chat.css`, the layout grid.
- Test: `tests/browser/test_agents_roster.py`, `tests/browser/test_agents_page_fit.py`.

**Behaviour:**
1. Grid at 1181px and wider:

```css
grid-template-columns: 232px minmax(0, 1fr) var(--agents-width, 300px);
.agents-layout.details-closed { grid-template-columns: 232px minmax(0, 1fr); }
.agents-layout.details-closed .agents-main { display: none; }
```

   Columns: roster 1, chat column 2, `.agents-main` 3. Ralph's
   `--agents-width` clamp (260 to 420, default 300) and `#ap-resize` stay; the
   handle now resizes the details column.
2. `#details-toggle` ("Details", `aria-expanded`, `aria-controls` set to the
   `.agents-main` id) toggles `.details-closed`. The choice is remembered
   under `aiui-details-open` ("1" or "0"). The default is open when
   `window.innerWidth >= 1440`, closed otherwise.
3. In a private conversation, `.agents-main` shows only that agent's card:
   - `paint()` sets `data-current` on `#my-agents .card[data-agent-id=current]`
     and on the layout `data-talking="1"`;
   - CSS rule:
     `.agents-layout[data-talking="1"] #my-agents .card:not([data-current]) { display: none; }`.
   - In the room every card shows: this is where agents are managed.
4. `.card-foot .chat-with` is hidden by CSS: the list replaces it. Keep the
   element, because Phase 0 code and tests reference it.
5. The section heading `#mine-count` stays in the moved `.section-head`
   (roster). `.agents-main` gets its own small heading `#details-title`:
   "Your agents" in the room, the agent's name in a private conversation.

**Step 1: Tests:**
- `test_three_panes_at_wide_widths` (1500x1000, details open): the roster
  x is less than the chat column x, which is less than `.agents-main` x; the
  window does not scroll; the composer is on screen.
- `test_details_shows_only_the_open_agent`: click Iris; exactly one visible
  `#my-agents .card`, and it is Iris's.
- `test_details_can_be_closed_and_it_is_remembered`: click
  `#details-toggle`; `.agents-main` is hidden and `aria-expanded` is
  "false"; after a reload it is still hidden.
- `test_the_conversation_gets_the_room` (1920x1080): the `.ap-thread` height
  is at least 700.
- Update `test_agents_page_fit.py` to the three-column geometry. The intent
  stays: no window scroll, composer visible, the cards column scrolls itself.

**Steps 2 to 5:** red, implement, green on the Task 2 suites plus
`test_agents_page_fit.py` and `test_embedded_page_chrome.py`, then commit:
"Agents page: details for the open agent on the right".

---

### Task 5: Smaller windows: two panes, then one

**Files:** `static/agent-chat.css`, `static/agents.html` (a small pane-state
script), and the test file `tests/browser/test_agents_roster.py`.

**Behaviour:**
1. From 700 to 1180px:
   - the grid is `232px minmax(0,1fr)`;
   - `.agents-main` becomes a sheet (`position: fixed; top: 0; right: 0;
     bottom: 0; width: min(360px, 92vw)`, on the panel layer, with a 1px
     left border and the Float shadow `0 4px 8px rgba(0,0,0,.45)`), shown
     only while details is open;
   - Details defaults to closed;
   - Escape closes the sheet. Extend the single Phase 0 Escape handler; do
     not add a second `"Escape"` string, because a test pins exactly one.
2. Under 700px, one pane at a time, through `data-pane` on `.agents-layout`:
   - `list`: the roster fills the width;
   - `chat`: the chat column fills the width. A `#pane-back` button reading
     "Agents" shows in the conversation header only at this width;
   - `details`: `.agents-main` fills the width, with a `#details-done`
     button reading "Done".

   Selecting a row sets `chat`. Details sets `details`. Done returns to
   `chat`. Back returns to `list`. The default is `list`, unless `?ask=` or
   an `aiui-agents-ask` arrives, which sets `chat`.
3. Every row and button is at least 44px tall under 700px.
4. The layout fills the height at every width (no page scroll), and each pane
   scrolls itself.

**Step 1: Tests:**
- `test_two_panes_at_1000`: at 1000x800 the roster and the chat column are
  side by side, and `.agents-main` is hidden; Details opens it as a sheet
  over the chat, and Escape closes it.
- `test_one_pane_at_a_time_on_a_phone`: at 390x844 only the roster is
  visible; clicking Iris shows only the chat column with the composer on
  screen; "Agents" returns to the list.
- `test_phone_targets_are_44px`: every visible button in the roster and in
  the conversation header is at least 44px tall.
- `test_an_ask_on_a_phone_lands_in_the_conversation`: opening the page with
  `?ask=hello` at 390 shows the chat pane with "hello" in the box.

**Steps 2 to 5:** red, implement, green (the Task 4 suites), then commit:
"Agents page: two panes on medium screens, one at a time on phones".

---

### Task 6: Reading width and the type scale

**Files:** `static/agents.html` (CSS), `static/agent-chat.css`, and the test
file `tests/browser/test_agents_page_a11y.py` (extend it).

**Behaviour:**
1. `.ap-thread` content sits in a centred column at most 760px wide, and
   message text is capped at 68ch. Wrap with CSS on `.aturn` and
   `.aempty`, using `margin-inline: auto; width: 100%; max-width: 760px`.
2. Every font size on the page is one of 12, 13, 14, 16 or 20px:
   - 10.5, 11 and 11.5px become 12;
   - 12.5px becomes 13;
   - 13.5px becomes 14;
   - 15px becomes 16 for headings, or 14 for UI text;
   - 17 and 24px become 20.

   Office files are out of scope.
3. The chat avatar `.aav` becomes a solid `hsl(H 45% 32%)` with white text,
   matching the roster. Find where `agent_chat_render.py` sets the avatar
   style. If it emits a gradient, change it to the solid fill in the same
   commit, with a test in `tests/test_agent_chat_render.py`.

**Step 1: Tests:**
- `test_only_the_five_sizes_are_used`: collect the computed `font-size` of
  every visible element in the agents frame at 1500x1000, with details open
  and the New agent form opened. The set must be a subset of
  {12, 13, 14, 16, 20}.
- `test_messages_have_a_reading_width`: a stubbed long message's `.atext`
  is at most 760px wide.
- `test_avatars_are_solid`: `.roster-av` and `.aav` have no
  `background-image`.

**Steps 2 to 5:** red, implement, green (the a11y, roster, page and render
suites), then commit: "Agents page: one type scale and a reading width".

---

### Task 7: Whole suite, review, browser, deploy

1. Run the whole-suite command, plus `tests/browser/test_agents_roster.py`.
   Record the counts and compare them with the baseline.
2. Code review: dispatch `superpowers:code-reviewer` on
   `git diff d2e88fb00..HEAD`.
3. Fix important findings, test-first.
4. Run Impeccable detect on the deployed copies, on the server (method in
   `project_ai_agents_page_ux` memory). Target: 0 tiny-text and 0
   low-contrast findings in agents.html.
5. Deploy, following the Phase 0 method:
   1. Fetch fork and rebase. STOP if Ralph changed agents.html or
      agent-chat.css meanwhile; merge test-first.
   2. Hash-sweep the server against `.deploy-state`.
   3. Ship the files with git archive, cp in place, rebuild tasks, check
      healthz, compare served bytes, write `.deploy-state`.
6. Real browser on the live site at 1920, 1366, 768 and 390px:
   - screenshots;
   - pick Iris, check the header;
   - open and close the office, and a robot Chat returns to the
     conversation;
   - Details toggles;
   - phone pane flow.

   Never send a message.
7. Push to `fork/main`.
