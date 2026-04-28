"""Generate static PNG previews for every template app.

Run this script once after you change a template, then commit the new PNGs
to git. Each preview is a 1280×800 desktop screenshot of the template's
index.html, saved to `template_apps/<key>/preview.png`. The gallery serves
these via /api/template-preview/<key>/preview.png — fast, reliable, no
service-worker drama.

Usage (from the repo root):
    pip install playwright
    python -m playwright install chromium
    python mcp-servers/tasks/scripts/generate_template_previews.py

Add `--keys landing,crud` to regenerate just a subset.
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import socketserver
import sys
import threading
from pathlib import Path

from playwright.async_api import async_playwright

# Resolve template_apps relative to this file so the script works from any CWD.
SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_APPS_DIR = SCRIPT_DIR.parent / "template_apps"

VIEWPORT = {"width": 1280, "height": 800}
WAIT_AFTER_LOAD_MS = 1500  # let Alpine mount + fonts paint
PORT = 0  # 0 = pick any free port


def discover_template_keys() -> list[str]:
    """Return every directory under template_apps/ that has an index.html."""
    if not TEMPLATE_APPS_DIR.is_dir():
        raise SystemExit(f"template_apps/ not found at {TEMPLATE_APPS_DIR}")
    keys = []
    for child in sorted(TEMPLATE_APPS_DIR.iterdir()):
        if child.is_dir() and (child / "index.html").is_file():
            keys.append(child.name)
    if not keys:
        raise SystemExit(f"No templates with index.html found under {TEMPLATE_APPS_DIR}")
    return keys


def start_local_server(serve_root: Path) -> tuple[socketserver.TCPServer, int]:
    """Spin up a tiny static HTTP server in a background thread.

    We need a real http:// origin (not file://) because some browsers and our
    templates' CDN scripts misbehave with file:// (e.g., CORS, cookies). The
    server stops when the calling code calls .shutdown().
    """

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_root), **kwargs)

        def log_message(self, *_args, **_kwargs):  # silence access logs
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", PORT), _Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


# Init script injected before each page loads. Critically, we DO NOT set
# window.SUPABASE_URL — that forces the real auth flow which fails against
# our dummy URL and leaves session=null. By leaving Supabase unset, the
# templates fall through to their "no Supabase" branch and fake a local
# session, rendering the real app UI for the screenshot.
INIT_SCRIPT = r"""
  try {
    localStorage.setItem('aiui_preview_mode', '1');
    // Seed a few demo todos / records so empty-state UIs aren't what we
    // capture. Templates that use localStorage as fallback storage pick
    // these up; the others ignore them harmlessly.
    if (!localStorage.getItem('todos')) {
      localStorage.setItem('todos', JSON.stringify([
        { id: 't1', title: 'Ship the new landing page', completed: true,  created_at: new Date().toISOString() },
        { id: 't2', title: 'Review pull request #42',    completed: false, created_at: new Date().toISOString() },
        { id: 't3', title: 'Plan Q2 roadmap',             completed: false, created_at: new Date().toISOString() },
        { id: 't4', title: 'Update billing settings',     completed: false, created_at: new Date().toISOString() },
      ]));
    }
  } catch (_) {}
"""


async def capture_one(page, base_url: str, key: str) -> Path:
    """Navigate to a template's index.html and snap a screenshot."""
    target = f"{base_url}/{key}/index.html"
    print(f"[{key}] navigating: {target}")
    await page.goto(target, wait_until="networkidle", timeout=20_000)
    # Let Alpine init + the no-Supabase session fallback fire.
    await page.wait_for_timeout(2_000)
    # If the template's auth gate redirected us to a login route, force
    # back to '/' and dispatch hashchange so applyRoute reruns with the
    # now-truthy session.
    try:
        await page.evaluate("""
          if (location.hash && /login|signin|signup/i.test(location.hash)) {
            location.hash = '#/';
            window.dispatchEvent(new HashChangeEvent('hashchange'));
          }
        """)
        await page.wait_for_timeout(2_500)
        # Second pass — some apps redirect again on the next applyRoute tick.
        await page.evaluate("""
          if (location.hash && /login|signin|signup/i.test(location.hash)) {
            location.hash = '#/';
            window.dispatchEvent(new HashChangeEvent('hashchange'));
          }
        """)
        await page.wait_for_timeout(1_500)
    except Exception:
        pass
    out = TEMPLATE_APPS_DIR / key / "preview.png"
    await page.screenshot(path=str(out), full_page=False)
    size_kb = out.stat().st_size / 1024
    print(f"[{key}] saved {out.relative_to(TEMPLATE_APPS_DIR.parent.parent.parent)} ({size_kb:.1f} KB)")
    return out


async def main_async(keys: list[str]) -> None:
    httpd, port = start_local_server(TEMPLATE_APPS_DIR)
    base_url = f"http://127.0.0.1:{port}"
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
                await context.add_init_script(INIT_SCRIPT)
                page = await context.new_page()
                for key in keys:
                    try:
                        await capture_one(page, base_url, key)
                    except Exception as exc:
                        print(f"[{key}] FAILED: {exc}", file=sys.stderr)
            finally:
                await browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--keys",
        help="Comma-separated subset of template keys to regenerate (default: all).",
    )
    args = p.parse_args()

    all_keys = discover_template_keys()
    if args.keys:
        wanted = [k.strip() for k in args.keys.split(",") if k.strip()]
        unknown = [k for k in wanted if k not in all_keys]
        if unknown:
            raise SystemExit(f"Unknown template keys: {unknown}. Available: {all_keys}")
        keys = wanted
    else:
        keys = all_keys
    print(f"Generating previews for: {keys}")
    asyncio.run(main_async(keys))
    print("Done.")


if __name__ == "__main__":
    main()
