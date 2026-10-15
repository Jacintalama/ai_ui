"""End-to-end check of agent team jobs against the local Docker stack.

    python scripts/dev_job_e2e.py

Needs `bash scripts/dev_up.sh up` on the fake model. Two scenarios, in the
team chat of /ai-agents, signed in as the dev admin:

1. Close the page mid-job. "scene:job ..." gets the lead's plan card, Start
   runs it, the page is closed after step 1 lands, and a fresh page later
   shows all three step results, the lead's final answer and "Done".
2. Restart tasks mid-job. Same start, then the tasks container is restarted
   after step 1; the worker resumes and the job still ends "Done".

Prints plain numbered lines and exits 1 on the first miss. Never prints the
password or a token. Spec: docs/plans/2026-10-14-agent-team-jobs-part-a.md,
Task 14.
"""
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from dev_check import read_env
from dev_e2e import BASE, OUT, agents_frame, dismiss_release_notes, send

STEPS = 3
JOB_TIMEOUT_S = 90


def say(n, text):
    print(f"{n}. {text}", flush=True)


def fail(text):
    print(f"FAIL: {text}", flush=True)
    raise SystemExit(1)


def sign_in(page, env):
    page.goto(BASE + "/auth", wait_until="domcontentloaded")
    page.locator("input[type=email], input[name=email]").first.fill(
        env["DEV_ADMIN_EMAIL"])
    page.locator("input[type=password]").first.fill(env["DEV_ADMIN_PASSWORD"])
    page.locator("input[type=password]").first.press("Enter")
    page.wait_for_function(
        "() => !!localStorage.getItem('token') && !location.pathname.startsWith('/auth')",
        timeout=60000)


def open_team_chat(page):
    page.goto(BASE + "/ai-agents", wait_until="domcontentloaded")
    dismiss_release_notes(page)
    frame = agents_frame(page)
    frame.wait_for_selector(".roster-row .roster-av", timeout=60000)
    if frame.evaluate("() => (document.getElementById('ap-agent') || {}).value"):
        fail("the open conversation is not the team chat")
    frame.wait_for_timeout(1500)
    return frame


def newest_card(frame):
    return frame.locator("#agent-thread .ajob").last


def propose_and_start(frame, n, words):
    before = frame.locator("#agent-thread .ajob").count()
    send(frame, words)
    try:
        frame.wait_for_function(
            "(n) => document.querySelectorAll('#agent-thread .ajob').length > n",
            arg=before, timeout=20000)
    except PWTimeout:
        fail("no plan card appeared for a job request")
    card = newest_card(frame)
    job_id = (card.get_attribute("id") or "").replace("job-", "")
    steps = card.locator(".ajob-steps li").all_inner_texts()
    say(n, f"plan card {job_id[:8]} with {len(steps)} steps: {steps}")
    if len(steps) != STEPS:
        fail(f"expected {STEPS} steps")
    card.get_by_role("button", name="Start").click()
    frame.wait_for_function(
        "(id) => { const c = document.getElementById('job-' + id);"
        " return c && /Running|step/i.test(c.textContent) && !/Start/.test(c.textContent); }",
        arg=job_id, timeout=15000)
    say(n + 1, "Start pressed: the card says it is running and shows Stop")
    return job_id


def wait_step(frame, label, timeout_s=30):
    frame.wait_for_function(
        "(l) => [...document.querySelectorAll('#agent-thread .astep')]"
        ".some(e => e.textContent.trim() === l)",
        arg=label, timeout=timeout_s * 1000)


def wait_done(frame, job_id, timeout_s=JOB_TIMEOUT_S):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        frame.evaluate("() => window.htmx && htmx.ajax('GET', '/tasks/agents/chat/thread', '#agent-thread')")
        frame.wait_for_timeout(2500)
        status = frame.evaluate(
            "(id) => { const c = document.getElementById('job-' + id);"
            " const s = c && c.querySelector('.ajob-status'); return s ? s.textContent : ''; }",
            job_id)
        if status.strip().lower().startswith(("done", "stopped", "cancelled")):
            return status.strip()
    fail(f"job {job_id[:8]} did not finish within {timeout_s} s")


def check_results(frame, n, job_id):
    labels = frame.locator("#agent-thread .astep").all_inner_texts()
    want = [f"Step {i} of {STEPS}" for i in range(1, STEPS + 1)]
    missing = [w for w in want if w not in labels]
    if missing:
        fail(f"missing step results: {missing} (saw {labels[-6:]})")
    say(n, f"all {STEPS} step results are in the chat")
    card = frame.locator(f"#job-{job_id}")
    after = card.evaluate(
        "c => { const out = []; let e = c.nextElementSibling;"
        " while (e) { if (e.matches('.am.agent')) out.push(e.textContent.trim().slice(0, 80)); e = e.nextElementSibling; }"
        " return out; }")
    say(n + 1, f"messages after the card: {len(after)}; last: {after[-1] if after else ''!r}")


def healthz_ok():
    try:
        return urllib.request.urlopen(BASE + "/tasks/healthz", timeout=3).status == 200
    except Exception:
        return False


def restart_tasks():
    cmd = ["docker", "compose", "-p", "aiui-dev", "--env-file", ".env.dev",
           "-f", "docker-compose.dev.yml", "restart", "tasks"]
    subprocess.run(cmd, check=True, capture_output=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if healthz_ok():
            return
        time.sleep(2)
    fail("tasks did not come back after the restart")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = read_env()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chromium")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        sign_in(page, env)
        say(1, "signed in")

        # Scenario 1: close the page mid-job.
        frame = open_team_chat(page)
        job = propose_and_start(frame, 2, "scene:job prepare the weekly summary")
        wait_step(frame, f"Step 1 of {STEPS}")
        say(4, "step 1 landed live; closing the page")
        page.close()
        time.sleep(8)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        frame = open_team_chat(page)
        status = wait_done(frame, job)
        say(5, f"reopened: the card says {status!r}")
        if not status.lower().startswith("done"):
            fail("scenario 1 did not end Done")
        check_results(frame, 6, job)
        page.screenshot(path=str(OUT / "job-e2e-closed-page.png"))

        # Scenario 2: restart tasks mid-job.
        job2 = propose_and_start(frame, 8, "scene:job prepare the monthly report")
        wait_step(frame, f"Step 1 of {STEPS}")
        say(10, "step 1 landed; restarting the tasks container")
        restart_tasks()
        say(11, "tasks is back")
        page.reload(wait_until="domcontentloaded")
        frame = open_team_chat(page)
        status = wait_done(frame, job2)
        say(12, f"after the restart the card says {status!r}")
        if not status.lower().startswith("done"):
            fail("scenario 2 did not end Done")
        check_results(frame, 13, job2)
        page.screenshot(path=str(OUT / "job-e2e-restart.png"))
        say(15, f"page errors: {errors or 'none'}")
        browser.close()
    print("PASS: both job scenarios", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
