"""End-to-end proof on the local Docker stack: a real agent turn in a real
browser, answered by the fake model.

    python scripts/dev_e2e.py            # headless
    python scripts/dev_e2e.py --headed   # watch it

Steps 1 to 5 are asserted; the scene:tool and scene:fail turns are only
recorded, since what they show is the input for Part 2. Screenshots go to
dev/out/ (gitignored). Signs in as the dev admin from .env.dev and never
prints the password.
"""
import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from dev_check import read_env

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "dev" / "out"
BASE = "http://localhost:8090"
AGENTS = ["Ada", "Mia", "Dev"]
HELLO = "hello from local"
EXPECTED = "Ada here. You said: hello from local"


def dismiss_release_notes(page):
    """Open WebUI shows its What's New dialog to an account that has not seen
    this version yet, which is every fresh local admin. It covers the page
    and swallows clicks, so close it the way a person would. Closing it saves
    the version to the user's settings, so later runs never see it."""
    button = page.get_by_role("button", name="Okay, Let's Go!")
    try:
        button.wait_for(state="visible", timeout=5000)
    except PWTimeout:
        return False
    button.click()
    page.wait_for_timeout(500)
    return True


def step(n, text):
    print(f"step {n}: {text}", flush=True)


def agents_frame(page, timeout=60.0):
    """The AI Agents pane is /tasks/agents in an iframe the shell opens."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for f in page.frames:
            if "/tasks/agents" in f.url and f.name != "aiui-office":
                return f
        page.wait_for_timeout(250)
    raise SystemExit("FAIL: the AI Agents pane never loaded /tasks/agents")


def office_frame(page, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for f in page.frames:
            if f.name == "aiui-office" or "/tasks/office" in f.url:
                return f
        page.wait_for_timeout(250)
    return None


def ada_slot(office):
    """What the office shows for Ada right now, as plain text."""
    return office.evaluate("""() => {
      const slots = [...document.querySelectorAll('.who-slot')];
      const s = slots.find(e => (e.querySelector('.card-name') || {}).textContent === 'Ada');
      if (!s) return null;
      const who = s.querySelector('.who');
      const small = s.querySelector('.who-label small');
      const tool = s.querySelector('.tool-now');
      return {state: who ? who.getAttribute('data-state') : null,
              label: small ? small.textContent : null,
              tool: tool ? tool.textContent : null,
              robot: !!s.querySelector('svg, .robot')};
    }""")


def send(frame, text):
    box = frame.locator("form.ap-composer input[name=message]")
    box.fill(text)
    frame.locator("form.ap-composer button[type=submit]").click()


def wait_thread_settled(frame, quiet_ms=800, timeout=15.0):
    """Wait until #agent-thread stops changing for quiet_ms."""
    deadline = time.monotonic() + timeout
    last, since = None, time.monotonic()
    while time.monotonic() < deadline:
        now = frame.evaluate(
            "() => (document.getElementById('agent-thread') || {}).innerHTML || ''")
        if now != last:
            last, since = now, time.monotonic()
        elif (time.monotonic() - since) * 1000 >= quiet_ms:
            return
        frame.wait_for_timeout(100)
    raise SystemExit("FAIL: the thread never settled after picking Ada")


def mark_old_turns(frame):
    """Tag every turn already in the thread, so only a new one can match.
    Sends append (hx-swap beforeend), so the tags survive the reply."""
    return frame.evaluate("""() => {
      const t = [...document.querySelectorAll('#agent-thread .aturn')];
      t.forEach(e => e.setAttribute('data-e2e-old', '1'));
      return t.length;
    }""")


def last_turn_text(frame):
    return frame.evaluate("""() => {
      const t = [...document.querySelectorAll('#agent-thread .aturn')].pop();
      return t ? t.innerText.trim() : '';
    }""")


def run_scene(page, frame, label, message, watch_s=20.0):
    """Send one scene, then watch the office and the thread. Records only."""
    print(f"scene {label}: sending {message!r}", flush=True)
    send(frame, message)
    sent = time.monotonic()
    frame.locator("#office-open").click()
    office = office_frame(page)
    seen = []
    while time.monotonic() - sent < watch_s and office is not None:
        try:
            now = ada_slot(office)
        except Exception:                               # noqa: BLE001
            now = None
        if now and (not seen or seen[-1][1] != now):
            seen.append((round(time.monotonic() - sent, 1), now))
        page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / f"e2e-{label}-office.png"))
    for t, s in seen:
        print(f"scene {label}: office at {t}s: Ada state={s['state']} "
              f"label={s['label']!r} tool={s['tool']!r}", flush=True)
    if not seen:
        print(f"scene {label}: office showed no Ada slot", flush=True)
    frame.locator("#office-close").click()
    page.wait_for_timeout(500)
    text = last_turn_text(frame)
    page.screenshot(path=str(OUT / f"e2e-{label}-chat.png"))
    print(f"scene {label}: thread shows:", flush=True)
    for line in text.splitlines():
        if line.strip():
            print(f"    {line.strip()}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--no-scenes", action="store_true")
    args = ap.parse_args()
    # Thread text can carry characters a Windows console codepage cannot
    # print; never let that crash the run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = read_env()
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. Sign in through the browser.
        page.goto(BASE + "/auth", wait_until="domcontentloaded")
        page.locator("input[type=email], input[name=email]").first.fill(
            env["DEV_ADMIN_EMAIL"])
        page.locator("input[type=password]").first.fill(env["DEV_ADMIN_PASSWORD"])
        page.locator("input[type=password]").first.press("Enter")
        page.wait_for_function(
            "() => !!localStorage.getItem('token') && !location.pathname.startsWith('/auth')",
            timeout=60000)
        step(1, "signed in through the browser")

        # 2. The AI Agents page and its roster.
        page.goto(BASE + "/ai-agents", wait_until="domcontentloaded")
        if dismiss_release_notes(page):
            print("closed Open WebUI's What's New dialog", flush=True)
        frame = agents_frame(page)
        try:
            frame.wait_for_function(
                """(want) => {
                  const got = [...document.querySelectorAll('.roster-row .roster-name')]
                    .map(e => e.textContent.trim());
                  return want.every(n => got.includes(n));
                }""", arg=AGENTS, timeout=60000)
        except PWTimeout:
            page.screenshot(path=str(OUT / "e2e-fail-roster.png"))
            raise SystemExit("FAIL: roster never showed Ada, Mia and Dev")
        step(2, f"/ai-agents roster shows {', '.join(AGENTS)}")

        # 3. Pick Ada and send. Picking loads her saved thread into
        # #agent-thread with an htmx GET, and earlier runs left the same
        # answer in it, so wait for that load before marking what is already
        # there. Counting bubbles before the load landed let an OLD bubble
        # satisfy step 4 and printed a send-to-bubble time of 0.00 s.
        with page.expect_response(
                lambda r: "/tasks/agents/chat/thread" in r.url, timeout=15000):
            frame.locator(".roster-row[data-agent-id]", has=frame.locator(
                ".roster-name", has_text="Ada")).first.click()
        frame.wait_for_function(
            "() => (document.getElementById('ap-who') || {}).textContent === 'Ada'",
            timeout=15000)
        wait_thread_settled(frame)
        mark_old_turns(frame)
        t0 = time.monotonic()
        send(frame, HELLO)
        step(3, f"picked Ada and sent {HELLO!r}")

        # 4. The agent bubble, in a turn that was not there before the send.
        try:
            frame.wait_for_function(
                """(want) => [...document.querySelectorAll('#agent-thread .aturn:not([data-e2e-old])')]
                     .some(t => [...t.querySelectorAll('.am.agent .atext')]
                       .some(e => e.textContent.includes(want)))""",
                arg=EXPECTED, timeout=60000, polling=50)
        except PWTimeout:
            page.screenshot(path=str(OUT / "e2e-fail-bubble.png"))
            print("thread: " + last_turn_text(frame))
            raise SystemExit("FAIL: no agent bubble with the fake answer")
        elapsed = time.monotonic() - t0
        # The fake model waits FAKE_DELAY_MS (1500) before it answers, so a
        # bubble any sooner cannot be the answer to this send.
        if elapsed < 1.5:
            raise SystemExit(f"FAIL: bubble after {elapsed:.2f} s is faster than "
                             "the fake model's 1.5 s delay, so it is a stale match")
        step(4, f"bubble {EXPECTED!r} after {elapsed:.2f} s from send")
        page.screenshot(path=str(OUT / "e2e-chat.png"))

        # 5. The office, and Ada's robot in it.
        frame.locator("#office-open").click()
        office = office_frame(page)
        if office is None:
            raise SystemExit("FAIL: the office never loaded")
        try:
            office.wait_for_function(
                """() => [...document.querySelectorAll('.who-slot .card-name')]
                     .some(e => e.textContent === 'Ada')""", timeout=30000)
        except PWTimeout:
            page.screenshot(path=str(OUT / "e2e-fail-office.png"))
            raise SystemExit("FAIL: no robot for Ada in the office")
        slot = ada_slot(office)
        page.screenshot(path=str(OUT / "e2e-office.png"))
        step(5, f"office has Ada's robot (state={slot['state']}, "
                f"robot drawn={slot['robot']})")
        frame.locator("#office-close").click()
        page.wait_for_timeout(500)

        # 6. Scenes, recorded rather than asserted.
        if not args.no_scenes:
            run_scene(page, frame, "tool", "scene:tool find the report")
            run_scene(page, frame, "fail", "scene:fail please")

        if errors:
            print("page errors seen:")
            for e in errors[:10]:
                print("    " + e[:200])
        print(f"screenshots: {OUT}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
