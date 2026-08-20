"""A glimpse of the app on its own card.

The Built apps list described each project in words and showed none of them.
Every card carried the same layout, so twenty landing pages looked identical
and the only way to tell a keyboard site from an aircon site was to read the
prompt underneath. A picture of the page answers that instantly.

The picture has to come from a real browser, and that is the constraint the
whole design bends around: this box has roughly 1.2GB available and Chromium
wants a few hundred MB. So a screenshot is never taken while somebody is
waiting for a page. It is captured once, cached on disk beside the app, and
served as a static file; the card asks for the file and quietly shows nothing
if it is not there yet.

What these tests pin down is when a cached picture stops being true, and that a
slug coming from a URL cannot be used to read or write outside the apps tree.
"""
import asyncio
import os
import time

import pytest

import app_thumb


@pytest.fixture
def apps(tmp_path, monkeypatch):
    monkeypatch.setattr(app_thumb, "_apps_root", lambda: str(tmp_path))

    def build(slug, files=("index.html",), thumb_age=None):
        d = tmp_path / slug
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_text("<title>x</title>", encoding="utf-8")
        if thumb_age is not None:
            t = d / ".thumb"
            t.mkdir(exist_ok=True)
            png = t / "preview.jpg"
            png.write_bytes(b"\x89PNG")
            stamp = time.time() + thumb_age
            os.utime(png, (stamp, stamp))
        return d

    return build


# --- when a cached picture is still true ----------------------------------

def test_no_picture_yet_counts_as_stale(apps):
    apps("klakk")
    assert app_thumb.is_stale("klakk") is True


def test_a_picture_newer_than_the_app_is_fresh(apps):
    apps("klakk", thumb_age=+60)
    assert app_thumb.is_stale("klakk") is False


def test_a_picture_older_than_the_app_is_stale(apps):
    """An enhance rewrites the page. A card still showing the previous version
    is worse than showing nothing, because it looks current."""
    apps("klakk", thumb_age=-60)
    assert app_thumb.is_stale("klakk") is True


def test_a_file_added_after_the_picture_makes_it_stale(apps):
    d = apps("klakk", thumb_age=-60)
    (d / "styles.css").write_text("body{}", encoding="utf-8")
    assert app_thumb.is_stale("klakk") is True


def test_its_own_output_does_not_make_it_stale(apps):
    """The thumbnail lives inside the app directory. Counting it as a source
    file would make every app permanently stale and re-screenshot forever."""
    apps("klakk", thumb_age=+1)
    assert app_thumb.is_stale("klakk") is False


def test_build_leftovers_do_not_make_it_stale(apps):
    """.git and .video churn without the page changing. Watching them would
    burn a Chromium launch for a screenshot identical to the cached one.

    The picture is newer than the page here, so the only thing that could make
    it stale is the noise.
    """
    d = apps("klakk", thumb_age=+1)
    for noisy in (".git", ".video", "node_modules"):
        sub = d / noisy
        sub.mkdir(exist_ok=True)
        (sub / "f").write_text("x", encoding="utf-8")
        os.utime(sub / "f", (time.time() + 600, time.time() + 600))
    assert app_thumb.is_stale("klakk") is False


def test_an_app_that_does_not_exist_is_not_stale(apps):
    """Nothing to photograph, so nothing to schedule. Returning True would
    queue a capture for every 404."""
    assert app_thumb.is_stale("never-built") is False


# --- a slug from a URL cannot escape the apps tree ------------------------

@pytest.mark.parametrize("bad", [
    "../../etc", "..", "a/../../b", "/etc/passwd", "a/b",
    "", "   ", ".", ".thumb", "a\\b", "app;rm -rf /",
])
def test_a_hostile_slug_is_refused(bad, apps):
    with pytest.raises(ValueError):
        app_thumb.thumb_path(bad)


@pytest.mark.parametrize("ok", ["klakk", "aircon-page-5564", "a_b-1", "x"])
def test_a_real_slug_is_accepted(ok, apps):
    p = app_thumb.thumb_path(ok)
    assert p.endswith(os.path.join(ok, ".thumb", "preview.jpg"))


def test_a_hostile_slug_is_refused_by_the_staleness_check_too(apps):
    """Both entry points take the slug straight from a URL."""
    for bad in ("../../etc", "a/b"):
        assert app_thumb.is_stale(bad) is False


# --- the queue that keeps Chromium off the request path -------------------

async def test_concurrent_requests_for_one_app_capture_once(apps, monkeypatch):
    """A page with twenty cards fires twenty requests at once. Launching a
    browser per request would take the box down.

    Fired concurrently on purpose: awaiting them one after another proves
    nothing, because the first has already finished and released the slug.
    """
    apps("klakk")
    calls = []

    async def fake_capture(slug):
        calls.append(slug)
        await asyncio.sleep(0.02)   # hold the slot, as a real capture would
        return True

    monkeypatch.setattr(app_thumb, "_capture", fake_capture)
    await asyncio.gather(*(app_thumb.ensure_thumb("klakk") for _ in range(8)))
    assert calls == ["klakk"]


async def test_captures_never_run_two_browsers_at_once(apps, monkeypatch):
    """Different apps may all need a picture at the same time. They queue
    rather than launching a Chromium each."""
    for slug in ("a", "b", "c", "d"):
        apps(slug)
    concurrent = 0
    peak = 0

    async def fake_capture(slug):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.02)
        concurrent -= 1
        return True

    monkeypatch.setattr(app_thumb, "_capture", fake_capture)
    await asyncio.gather(*(app_thumb.ensure_thumb(s) for s in "abcd"))
    assert peak == 1


async def test_a_fresh_picture_is_never_recaptured(apps, monkeypatch):
    apps("klakk", thumb_age=+60)
    calls = []

    async def fake_capture(slug):
        calls.append(slug)
        return True

    monkeypatch.setattr(app_thumb, "_capture", fake_capture)
    await app_thumb.ensure_thumb("klakk")
    assert calls == []


async def test_a_failed_capture_does_not_wedge_the_app_forever(apps, monkeypatch):
    """If a crash left the slug marked in-flight, that app could never get a
    picture again without a restart."""
    apps("klakk")

    async def boom(slug):
        raise RuntimeError("browser died")

    monkeypatch.setattr(app_thumb, "_capture", boom)
    await app_thumb.ensure_thumb("klakk")          # must not raise
    assert not app_thumb.is_capturing("klakk")


async def test_a_capture_failure_is_swallowed(apps, monkeypatch):
    """A missing browser must never turn into a failed page load. The card
    simply shows no picture."""
    apps("klakk")

    async def boom(slug):
        raise RuntimeError("no chromium")

    monkeypatch.setattr(app_thumb, "_capture", boom)
    assert await app_thumb.ensure_thumb("klakk") is False
