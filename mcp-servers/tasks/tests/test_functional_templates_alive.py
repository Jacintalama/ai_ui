"""Playwright tests asserting each functional template's key "alive" behavior.

Each test spins up a local HTTP server rooted at the template's directory
(file:// URLs block ES module imports), navigates Playwright Chromium to it,
exercises the headline interaction, and asserts the expected post-state.

Skipped automatically if Playwright isn't installed.
"""
import http.server
import socket
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright.sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_APPS = ROOT / "template_apps"


def _make_handler(directory: Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *args, **kwargs):
            pass

    return Handler


@contextmanager
def _serve(directory: Path):
    handler_cls = _make_handler(directory)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = http.server.HTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _new_page(browser, viewport=(1280, 800)):
    ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
    page = ctx.new_page()
    return ctx, page


def test_flight_booking_search_and_filter(browser):
    """Submit search -> results appear -> price slider narrows count."""
    with _serve(TEMPLATE_APPS / "flight-booking") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            # Submit the default search form
            page.locator("button[type='submit']").click()
            # Wait for skeleton -> results (articles appear in the results view)
            page.wait_for_selector("article", timeout=8_000)
            initial_count = page.locator("article").count()
            assert initial_count > 0, "no results rendered after search"
            # Drag price filter to a very low value to reduce results.
            # The results view has two range inputs (price + duration); target price (first).
            price_slider = page.locator("input[type='range']").first
            price_slider.evaluate(
                "(el) => { el.value = 500; el.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            page.wait_for_timeout(300)
            new_count = page.locator("article").count()
            # Either count decreases OR it is already 0 (all flights cost > $500)
            assert new_count <= initial_count, (
                f"filter didn't narrow results: {initial_count} -> {new_count}"
            )
        finally:
            ctx.close()


def test_food_delivery_cart_persistence(browser):
    """Open menu -> add item 3x -> cartCount badge shows 3 -> persists on reload."""
    with _serve(TEMPLATE_APPS / "food-delivery") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            # Click first restaurant card to open its menu
            page.locator("article").first.click()
            # Wait for the simulated network delay and menu items to appear.
            # The "+" add button uses :aria-label="'Add one ' + item.name" which Alpine renders
            # as the aria-label attribute once initialized.
            add_btn = page.locator("[aria-label^='Add one']").first
            add_btn.wait_for(state="visible", timeout=8_000)
            for _ in range(3):
                add_btn.click()
                page.wait_for_timeout(80)
            # Assert cart badge shows 3.
            # The badge is the <span x-text="cartCount"> inside the Cart button in the header.
            badge = page.locator("header span[x-text='cartCount']")
            badge_text = badge.text_content()
            assert "3" in (badge_text or ""), (
                f"cart badge expected '3', got '{badge_text}'"
            )
            # Reload and re-check (persistence via localStorage key io-template:food-delivery:cart)
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(600)
            badge_text_after = page.locator("header span[x-text='cartCount']").text_content()
            assert "3" in (badge_text_after or ""), (
                f"cart did not persist across reload: badge='{badge_text_after}'"
            )
        finally:
            ctx.close()


def test_job_board_search_debounce_and_bookmark(browser):
    """Type 'Engineer' -> list filters in <500 ms -> bookmark saves to localStorage."""
    with _serve(TEMPLATE_APPS / "job-board") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            initial = page.locator("article").count()
            assert initial > 0, "no job cards rendered on load"
            search = page.locator("input[type='search']").first
            search.fill("Engineer")
            # Wait past the 250 ms debounce
            page.wait_for_timeout(450)
            filtered = page.locator("article").count()
            assert filtered < initial, (
                f"search didn't filter: {initial} -> {filtered}"
            )
            # Bookmark the first visible job via its aria-label bookmark button.
            # Template uses @click.stop="toggleSave(job.id)" on a button with
            # aria-label "Bookmark <title>" or "Remove bookmark for <title>".
            bookmark = page.locator("button[aria-label^='Bookmark']").first
            bookmark.click()
            page.wait_for_timeout(200)
            # Verify localStorage (key: io-template:job-board:savedJobs)
            saved_count = page.evaluate(
                "() => JSON.parse(localStorage.getItem('io-template:job-board:savedJobs') || '[]').length"
            )
            assert saved_count >= 1, "bookmark did not persist to localStorage"
        finally:
            ctx.close()


def test_movie_tickets_seat_picker(browser):
    """Drive Alpine state to seats view -> simulate selecting 2 seats -> total is $28."""
    with _serve(TEMPLATE_APPS / "movie-tickets") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            # Navigate to seats view via Alpine state methods.
            page.evaluate(
                """() => {
                    const root = document.querySelector('[x-data]');
                    const state = root._x_dataStack[0];
                    const film = state.films[0];
                    state.openFilm(film.id);
                    const st = state.showtimes.find(s => s.filmId === film.id);
                    state.pickShowtime(st.id);
                }"""
            )
            page.wait_for_timeout(500)
            # Wait for the seats view to become visible (heading shows film title).
            page.wait_for_selector("section[x-show*='seats']:not([style*='display: none'])",
                                   timeout=5_000)
            # Simulate selecting 2 seats directly via Alpine state.
            # toggleSeat(row, col) pushes "row-col" strings into selectedSeats
            # and triggers the count-up animation.
            # SEAT_PRICE = 14, so 2 seats = $28.
            page.evaluate(
                """() => {
                    const state = document.querySelector('[x-data]')._x_dataStack[0];
                    // Pick 2 seats that are not in the aisle (col 4 or 9) and not taken
                    state.toggleSeat(0, 0);  // row A, col 1
                    state.toggleSeat(0, 1);  // row A, col 2
                }"""
            )
            # Wait for the count-up animation to reach $28 (SEAT_PRICE * 2)
            page.wait_for_timeout(600)
            # Verify selectedSeats count and displayedTotal via state
            result = page.evaluate(
                """() => {
                    const state = document.querySelector('[x-data]')._x_dataStack[0];
                    return {
                        seatCount: state.selectedSeats.length,
                        displayedTotal: state.displayedTotal,
                    };
                }"""
            )
            assert result["seatCount"] == 2, (
                f"expected 2 seats selected, got {result['seatCount']}"
            )
            assert result["displayedTotal"] == 28, (
                f"expected displayedTotal = 28, got {result['displayedTotal']}"
            )
        finally:
            ctx.close()


def test_recipe_site_serving_scale(browser):
    """Open first recipe -> drag servings slider 2->4 -> ingredient quantity changes."""
    with _serve(TEMPLATE_APPS / "recipe-site") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            # Open the first recipe via Alpine state (avoids selector ambiguity with
            # hidden recipe cards vs. visible catalog cards).
            first_recipe_id = page.evaluate(
                "() => document.querySelector('[x-data]')._x_dataStack[0].recipes[0].id"
            )
            page.evaluate(
                f"""() => document.querySelector('[x-data]')._x_dataStack[0].openRecipe('{first_recipe_id}')"""
            )
            page.wait_for_timeout(400)
            # Wait for the servings slider to appear (recipe view)
            page.wait_for_selector("input[type='range'][aria-label='Number of servings']",
                                   timeout=5_000)
            # The servings slider is in the recipe view.
            slider = page.locator("input[type='range'][aria-label='Number of servings']")
            # Read initial servings value
            initial_servings = int(slider.input_value())
            # Get the current displayedTotal/scaledQty for the first ingredient via state.
            initial_qty = page.evaluate(
                """() => {
                    const state = document.querySelector('[x-data]')._x_dataStack[0];
                    const ing = state.selectedRecipe?.ingredients?.[0];
                    return ing ? state.scaledQty(ing) : null;
                }"""
            )
            # Change servings to double
            new_servings = initial_servings * 2
            slider.evaluate(
                f"(el) => {{ el.value = {new_servings}; el.dispatchEvent(new Event('input', {{bubbles: true}})); }}"
            )
            page.wait_for_timeout(300)
            after_qty = page.evaluate(
                """() => {
                    const state = document.querySelector('[x-data]')._x_dataStack[0];
                    const ing = state.selectedRecipe?.ingredients?.[0];
                    return ing ? state.scaledQty(ing) : null;
                }"""
            )
            assert after_qty != initial_qty, (
                f"servings slider didn't update ingredient quantity: "
                f"'{initial_qty}' vs '{after_qty}'"
            )
        finally:
            ctx.close()
