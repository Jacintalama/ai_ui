"""Measure how the office robots' animation lines up with the chat bubbles,
on the local Docker stack (http://localhost:8090, fake model).

    python scripts/dev_sync_timing.py            # headless
    python scripts/dev_sync_timing.py --headed   # watch it

Records, does not assert: the numbers are the result. Exit 0 when the run
completed, 1 when it could not measure.

WHERE IT WATCHES, AND WHY NOT THE OFFICE'S OWN CHAT. office.html has a
conversation of its own (#deskchat), but it loads htmx without the SSE
extension (vendor/sse.js), so a send there draws the question, returns the
stream block, and nothing ever opens /tasks/agents/chat/stream: no round runs
and no answer arrives (measured 2026-10-13: 0 EventSources opened for the
chat after a send, the turn stayed unanswered for 8 s). So the chat used is
the AI Agents page (/tasks/agents inside /ai-agents), and the floor is the
office it docks (/tasks/office?embed=1, iframe "aiui-office"), which is a
same-origin child of that page.

ONE CLOCK. The observer is installed in the agents page and observes BOTH
documents: its own body for bubbles and the office iframe's body for mouths.
Every timestamp is the agents page's performance.now(), so the two series
share a clock with no cross-frame offset.

Mouths are taken two ways in the same callback: the attribute change on
.who[data-speaking] (the patch path), and a scan of every .who after each
batch of mutations, which also catches a robot rebuilt by innerHTML with the
attribute already on. The scan is what the numbers use.

Screenshots go to dev/out/ (gitignored). Signs in as the dev admin from
.env.dev and never prints the password or a token.
"""
import argparse
import sys
import time

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from dev_check import read_env
from dev_e2e import (AGENTS, BASE, OUT, agents_frame, dismiss_release_notes,
                     office_frame, send, wait_thread_settled)

ONE = "Ada, hello"
MEETING = "everyone answer: hello"

#: Installed in the agents page. Watches its own thread and the office
#: iframe's floor, on this page's clock.
PROBE = r"""() => {
  const office = document.querySelector('#office-body iframe');
  const odoc = office && office.contentDocument;
  if (!odoc || !odoc.body) return 'no office document';
  window.__t = [];
  window.__speaking = {};
  window.__state = {};
  window.__firstBubble = null;
  odoc.__probeTag = 'probe-' + Date.now();
  window.__probeTag = odoc.__probeTag;
  const nameOf = (id) => {
    const s = [...odoc.querySelectorAll('.who-slot')]
      .find(e => e.getAttribute('data-id') === id);
    const n = s && s.querySelector('.card-name');
    return n ? n.textContent : id;
  };
  const roomSnapshot = () => {
    const zone = odoc.querySelector('.zone[data-room="meeting"]');
    const floor = odoc.getElementById('rooms');
    const out = {planned: floor ? floor.getAttribute('data-meeting') : null,
                 inside: [], outside: [], walking: [],
                 dockHidden: !!document.getElementById('office-dock').hidden};
    if (!zone) return out;
    const z = zone.getBoundingClientRect();
    odoc.querySelectorAll('.who-slot').forEach(s => {
      const w = s.querySelector('.who') || s;
      const r = w.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const name = (s.querySelector('.card-name') || {}).textContent || s.getAttribute('data-id');
      const inRoom = cx >= z.left && cx <= z.right && cy >= z.top && cy <= z.bottom;
      (inRoom ? out.inside : out.outside).push(name);
      if (s.classList.contains('walking')) out.walking.push(name);
    });
    return out;
  };
  window.__roomSnapshot = roomSnapshot;
  const scanMouths = () => {
    const now = {};
    odoc.querySelectorAll('.who[data-speaking]').forEach(w => {
      now[w.getAttribute('data-id')] = 1;
    });
    const t = performance.now();
    Object.keys(now).forEach(id => {
      if (!window.__speaking[id]) window.__t.push({k: 'mouth_on', id, name: nameOf(id), t, via: 'scan'});
    });
    Object.keys(window.__speaking).forEach(id => {
      if (!now[id]) window.__t.push({k: 'mouth_off', id, name: nameOf(id), t, via: 'scan'});
    });
    window.__speaking = now;
  };
  scanMouths();                       // whoever is already talking is the baseline
  window.__t = [];
  const onMutations = (list) => {
    const t = performance.now();
    list.forEach(m => {
      const n = m.target;
      if (m.type === 'attributes' && m.attributeName === 'data-speaking') {
        window.__t.push({k: n.getAttribute('data-speaking') ? 'attr_on' : 'attr_off',
                         id: n.getAttribute('data-id'), t});
      }
      if (m.type === 'attributes' && m.attributeName === 'data-state'
          && n.classList.contains('who')) {
        // Recorded on a change of value only: the same value set twice in a
        // row is one change on screen.
        const id = n.getAttribute('data-id'), v = n.getAttribute('data-state');
        if (window.__state[id] !== v) {
          window.__state[id] = v;
          window.__t.push({k: 'state', id, name: nameOf(id), v, t});
        }
      }
      if (m.type === 'childList') m.addedNodes.forEach(a => {
        if (a.nodeType !== 1) return;
        const bubbles = a.matches('.am.agent') ? [a] : [...a.querySelectorAll('.am.agent')];
        bubbles.forEach(b => {
          // htmx lands one out-of-band answer in more than one mutation
          // record, so a bubble element is counted once.
          if (b.__probeSeen || !b.closest('#agent-thread')) return;
          b.__probeSeen = 1;
          const who = (b.querySelector('.awho') || {}).textContent || '';
          const ev = {k: 'bubble', name: who, t, room: roomSnapshot()};
          window.__t.push(ev);
          if (!window.__firstBubble) window.__firstBubble = ev;
        });
      });
    });
    scanMouths();
  };
  const cfg = {subtree: true, childList: true, attributes: true,
               attributeFilter: ['data-speaking', 'data-state']};
  new MutationObserver(onMutations).observe(document.body, cfg);
  new MutationObserver(onMutations).observe(odoc.body, cfg);
  // The same live feed the floor reads, opened here so each run event and
  // the source it carries land on this page's clock beside the mouths.
  if (window.__probeES) window.__probeES.close();
  window.__probeHello = false;
  window.__probeES = new EventSource('/api/tasks/agents/stream', {withCredentials: true});
  window.__probeES.addEventListener('hello', () => { window.__probeHello = true; });
  ['run_started', 'run_finished'].forEach(name => {
    window.__probeES.addEventListener(name, ev => {
      let e = {};
      try { e = JSON.parse(ev.data); } catch (x) { return; }
      window.__t.push({k: 'feed_' + name, id: e.agent_id, name: nameOf(e.agent_id),
                       source: e.source || null, status: e.status || null,
                       t: performance.now()});
    });
  });
  return 'ok';
}"""


def sign_in(page, env):
    page.goto(BASE + "/auth", wait_until="domcontentloaded")
    page.locator("input[type=email], input[name=email]").first.fill(
        env["DEV_ADMIN_EMAIL"])
    page.locator("input[type=password]").first.fill(env["DEV_ADMIN_PASSWORD"])
    page.locator("input[type=password]").first.press("Enter")
    page.wait_for_function(
        "() => !!localStorage.getItem('token') && !location.pathname.startsWith('/auth')",
        timeout=60000)


def to_room(frame):
    """The scenes run in the room (Everyone), where a meeting can be called."""
    if frame.evaluate("() => (document.getElementById('ap-who') || {}).textContent") != "Everyone":
        frame.locator('.roster-row[data-room="1"]').first.click()
        frame.wait_for_function(
            "() => (document.getElementById('ap-who') || {}).textContent === 'Everyone'",
            timeout=15000)
    wait_thread_settled(frame)


def floor_quiet(office, timeout=150.0):
    """No robot talking or working, and no meeting standing. A meeting stays
    on the floor for 90 s after its last word (office.js MEETING_SECONDS), so
    a scene started sooner would find the team already in the room."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        busy = office.evaluate("""() => {
          const f = document.getElementById('rooms');
          return {meeting: f ? f.getAttribute('data-meeting') : null,
                  speaking: document.querySelectorAll('.who[data-speaking]').length,
                  working: document.querySelectorAll('.who[data-state="working"]').length};
        }""")
        if not busy["meeting"] and not busy["speaking"] and not busy["working"]:
            return True
        time.sleep(1.0)
    return False


def office_shown(frame):
    return frame.evaluate("() => !document.getElementById('office-dock').hidden")


def show_office(frame):
    if not office_shown(frame):
        frame.locator("#office-open").click()


def show_chat(frame):
    if office_shown(frame):
        frame.locator("#office-close").click()


def run_scene(page, frame, office, label, message, quiet_ms=3000, cap_s=60.0):
    """Send one message from the conversation, switch to the office the way a
    person would, and record every mouth and bubble until it all stops."""
    # Watched on screen: the floor's fallback poll runs only while visible.
    show_office(frame)
    if not floor_quiet(office):
        print(f"scene {label}: WARNING the floor never went quiet before the send",
              flush=True)
    show_chat(frame)
    wait_thread_settled(frame)
    ok = frame.evaluate(PROBE)
    if ok != "ok":
        raise SystemExit(f"FAIL: could not install the probe: {ok}")
    frame.wait_for_function("() => window.__probeHello === true", timeout=15000)
    t_send = frame.evaluate("() => performance.now()")
    send(frame, message)
    frame.locator("#office-open").click()
    shot_taken = False
    start = time.monotonic()
    last_len, last_change = 0, time.monotonic()
    while time.monotonic() - start < cap_s:
        state = frame.evaluate("""() => ({n: window.__t.length,
            bubble: !!window.__firstBubble,
            speaking: Object.keys(window.__speaking).length})""")
        if state["bubble"] and not shot_taken:
            page.screenshot(path=str(OUT / f"sync-{label}-first-bubble.png"))
            shot_taken = True
        if state["n"] != last_len:
            last_len, last_change = state["n"], time.monotonic()
        elif (state["bubble"] and not state["speaking"]
              and (time.monotonic() - last_change) * 1000 >= quiet_ms):
            break
        time.sleep(0.1)
    page.screenshot(path=str(OUT / f"sync-{label}-office.png"))
    data = frame.evaluate("""() => ({t: window.__t, first: window.__firstBubble,
        same: (document.querySelector('#office-body iframe').contentDocument || {}).__probeTag === window.__probeTag})""")
    show_chat(frame)
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / f"sync-{label}-chat.png"))
    if not data["same"]:
        print(f"scene {label}: WARNING the office document was replaced mid-scene; "
              "its mouths after that were not observed", flush=True)
    return t_send, data


def describe(e, t_send):
    at = f"{e['t'] - t_send:7.0f} ms"
    k = e["k"]
    if k == "bubble":
        r = e.get("room") or {}
        return (f"{at}  bubble {e['name']}  (meeting room holds: "
                f"{', '.join(r.get('inside', [])) or 'nobody'}; "
                f"data-meeting={r.get('planned')!r})")
    if k.startswith("feed_"):
        extra = e.get("source") or e.get("status") or ""
        return f"{at}  feed {k[5:]} {e['name']} {extra}".rstrip()
    if k == "state":
        return f"{at}  data-state {e['name']} -> {e['v']}"
    if k in ("mouth_on", "mouth_off"):
        return f"{at}  {k} {e['name']}"
    return f"{at}  {k} {e.get('id', '')}"


def print_timeline(label, t_send, data, n):
    n += 1
    print(f"{n}. scene {label}: timeline from send, one clock "
          "(agents page performance.now):", flush=True)
    for e in sorted(data["t"], key=lambda e: e["t"]):
        if e["k"].startswith("attr_"):
            continue
        print("      " + describe(e, t_send), flush=True)
    return n


def report_one(t_send, data, n):
    ev = data["t"]
    bubbles = [e for e in ev if e["k"] == "bubble" and e["name"] == "Ada"]
    ons = [e for e in ev if e["k"] == "mouth_on" and e["name"] == "Ada"]
    offs = [e for e in ev if e["k"] == "mouth_off" and e["name"] == "Ada"]
    lines = []
    if not bubbles:
        lines.append("scene a: no bubble from Ada arrived")
    else:
        b = bubbles[0]["t"]
        lines.append(f"scene a: send to Ada's bubble: {b - t_send:.0f} ms")
        if ons:
            lines.append(f"scene a: mouth_on - bubble: {ons[0]['t'] - b:+.0f} ms "
                         f"(send to mouth_on {ons[0]['t'] - t_send:.0f} ms)")
        else:
            lines.append("scene a: mouth_on - bubble: Ada's mouth never moved")
        if offs:
            lines.append(f"scene a: mouth_off - bubble: {offs[0]['t'] - b:+.0f} ms")
        else:
            lines.append("scene a: mouth_off - bubble: Ada's mouth never stopped "
                         "within the watch")
        if ons and offs:
            lines.append(f"scene a: mouth open for {offs[0]['t'] - ons[0]['t']:.0f} ms")
    if bubbles:
        r = bubbles[0].get("room") or {}
        lines.append("scene a: meeting room at Ada's bubble holds: "
                     f"{', '.join(r.get('inside', [])) or 'nobody'} "
                     f"(data-meeting={r.get('planned')!r})")
    feed = [e for e in ev if e["k"] == "feed_run_started" and e["name"] == "Ada"]
    if feed:
        lines.append(f"scene a: the feed's run_started for Ada says source={feed[0]['source']}")
    others = sorted({e["name"] for e in ev if e["k"] == "mouth_on" and e["name"] != "Ada"})
    if others:
        lines.append(f"scene a: other mouths that moved: {', '.join(others)}")
    attr = [e["k"] for e in ev if e["k"].startswith("attr_")]
    lines.append(f"scene a: data-speaking attribute changes seen: {len(attr)} "
                 f"({', '.join(attr) or 'none'})")
    for line in lines:
        n += 1
        print(f"{n}. {line}", flush=True)
    return n


def report_meeting(t_send, data, n):
    ev = data["t"]
    first = data["first"]
    bubbles = [e for e in ev if e["k"] == "bubble"]
    ons = [e for e in ev if e["k"] == "mouth_on"]
    offs = [e for e in ev if e["k"] == "mouth_off"]
    lines = []
    if not first:
        lines.append("scene b: no bubble arrived")
    else:
        r = first["room"] or {}
        inside = r.get("inside", [])
        lines.append(f"scene b: first bubble ({first['name']}) after "
                     f"{first['t'] - t_send:.0f} ms from send")
        lines.append(f"scene b: robots inside the meeting room at the first bubble: "
                     f"{len(inside)} ({', '.join(inside) or 'none'}); "
                     f"floor data-meeting={r.get('planned')!r}; "
                     f"walking: {', '.join(r.get('walking', [])) or 'none'}; "
                     f"office dock hidden: {r.get('dockHidden')}")
    lines.append("scene b: mouth_on order: " +
                 (", ".join(f"{e['name']}@{e['t'] - t_send:.0f}" for e in ons) or "none"))
    lines.append("scene b: bubble order:   " +
                 (", ".join(f"{e['name']}@{e['t'] - t_send:.0f}" for e in bubbles) or "none"))
    lines.append("scene b: mouth_off order: " +
                 (", ".join(f"{e['name']}@{e['t'] - t_send:.0f}" for e in offs) or "none"))
    same = [e["name"] for e in ons] == [e["name"] for e in bubbles]
    lines.append(f"scene b: mouth_on order equals bubble order: {'yes' if same else 'no'}")
    def gap(e, b):
        return f"{e['t'] - b['t']:+.0f} ms" if e else "never"
    for b in bubbles:
        on = next((e for e in ons if e["name"] == b["name"]), None)
        off = next((e for e in offs if e["name"] == b["name"]), None)
        src = next((e["source"] for e in ev if e["k"] == "feed_run_started"
                    and e["name"] == b["name"]), None)
        lines.append(f"scene b: {b['name']}: mouth_on - bubble {gap(on, b)}, "
                     f"mouth_off - bubble {gap(off, b)}, feed source={src}")
    most = max((len((e.get("room") or {}).get("inside", [])) for e in bubbles),
               default=0)
    lines.append(f"scene b: most robots in the meeting room at any bubble: {most}")
    for line in lines:
        n += 1
        print(f"{n}. {line}", flush=True)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = read_env()
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        sign_in(page, env)
        page.goto(BASE + "/ai-agents", wait_until="domcontentloaded")
        dismiss_release_notes(page)
        frame = agents_frame(page)
        try:
            frame.wait_for_function(
                """(want) => {
                  const got = [...document.querySelectorAll('.roster-row .roster-name')]
                    .map(e => e.textContent.trim());
                  return want.every(n => got.includes(n));
                }""", arg=AGENTS, timeout=60000)
        except PWTimeout:
            print("FAIL: roster never showed Ada, Mia and Dev")
            return 1
        to_room(frame)

        # Build the office once; it then stays loaded behind the conversation.
        frame.locator("#office-open").click()
        office = office_frame(page)
        if office is None:
            print("FAIL: the office never loaded")
            return 1
        office.wait_for_function(
            "(n) => document.querySelectorAll('.who-slot').length >= n",
            arg=len(AGENTS), timeout=30000)
        office.wait_for_function(
            "() => !!document.querySelector('.zone[data-room=\"meeting\"]')",
            timeout=30000)
        if office.parent_frame != frame:
            print("FAIL: the office frame is not a child of the agents page, "
                  "so one clock cannot cover both")
            return 1

        n = 0
        t_send, data = run_scene(page, frame, office, "one", ONE)
        n = report_one(t_send, data, n)
        n = print_timeline("a", t_send, data, n)
        t_send, data = run_scene(page, frame, office, "meeting", MEETING)
        n = report_meeting(t_send, data, n)
        n = print_timeline("b", t_send, data, n)

        if errors:
            n += 1
            print(f"{n}. page errors seen: {len(errors)}")
            for e in errors[:5]:
                print("    " + e[:200])
        n += 1
        print(f"{n}. screenshots: {OUT}", flush=True)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
