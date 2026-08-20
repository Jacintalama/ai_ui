"""Capture a thumbnail for every built app that does not have a fresh one.

New apps get their picture lazily: the card asks for it, gets a 404, and the
request queues a capture that lands before the next visit. That is fine going
forward and useless for the apps that already exist, which would each show a
blank card until somebody happened to open the list twice.

Run once, inside the tasks container, after deploying app_thumb:

    docker exec tasks python /app/scripts/backfill_app_thumbs.py

Strictly serial. This box has roughly 1.2GB available and each Chromium wants a
few hundred MB of it, so the whole point is to never have two open at once.
Safe to re-run: an app with a current picture is skipped.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_thumb  # noqa: E402


async def main() -> int:
    root = app_thumb._apps_root()
    if not os.path.isdir(root):
        print("no apps directory at", root)
        return 1

    slugs = sorted(d for d in os.listdir(root)
                   if os.path.isfile(os.path.join(root, d, "index.html")))
    print(f"{len(slugs)} apps with an index.html under {root}")

    done = skipped = failed = 0
    for i, slug in enumerate(slugs, 1):
        if not app_thumb.is_stale(slug):
            skipped += 1
            continue
        started = time.time()
        ok = await app_thumb.ensure_thumb(slug)
        took = time.time() - started
        if ok:
            done += 1
            size = os.path.getsize(app_thumb.thumb_path(slug)) // 1024
            print(f"  [{i}/{len(slugs)}] {slug}: {size}KB in {took:.1f}s")
        else:
            failed += 1
            print(f"  [{i}/{len(slugs)}] {slug}: FAILED after {took:.1f}s")

    print(f"\ncaptured {done}, already current {skipped}, failed {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
