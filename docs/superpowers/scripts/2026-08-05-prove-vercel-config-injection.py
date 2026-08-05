"""Prove a database-backed app deploys to Vercel with a WORKING config.

The unit tests assert the payload is shaped right. They cannot prove the values
come from the real database row, nor that what IO serves and what Vercel would
serve now agree. This does both, against the live Postgres, without deploying
anything to Vercel.

Run inside the tasks container:
    docker exec tasks python /tmp/prove_vercel_config.py

Safety: creates ONE tasks.project_supabase row for a throwaway slug containing
"zz-probe", asserts on it, and deletes it in a finally block. It never touches
an existing row — it refuses to start if the probe slug already exists, and it
only ever deletes the exact slug it created.
"""
import asyncio
import sys

sys.path.insert(0, "/app")

PROBE_SLUG = "zz-probe-vercel-config"
PROBE_URL = "https://zzprobe123.supabase.co"
PROBE_ANON = "probe-anon-key-not-real"

PASS, FAIL = [], []


def check(label, ok, detail=""):
    (PASS if ok else FAIL).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")


async def main():
    import crypto_utils
    from db import session
    from models import ProjectSupabase
    from sqlalchemy import select, delete
    from routes_vercel import (
        _supabase_deploy_config, inject_supabase_config, to_vercel_files,
    )
    import main as tasks_main

    assert "zz-probe" in PROBE_SLUG, "refusing to touch a non-probe slug"

    async with session() as s:
        existing = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == PROBE_SLUG)
        )).scalar_one_or_none()
        if existing is not None:
            raise SystemExit(f"{PROBE_SLUG} already exists; refusing to overwrite")

    try:
        print("\n=== 1. link a database to a throwaway project ===")
        async with session() as s:
            s.add(ProjectSupabase(
                slug=PROBE_SLUG,
                supabase_url=PROBE_URL,
                anon_key_encrypted=crypto_utils.encrypt(PROBE_ANON),
                configured_by="probe@aiui",
            ))
            await s.commit()
        print(f"  linked {PROBE_SLUG} -> {PROBE_URL}")

        print("\n=== 2. the deploy path reads it back ===")
        cfg = await _supabase_deploy_config(PROBE_SLUG)
        check("deploy finds the linked database", cfg is not None)
        if cfg is None:
            raise SystemExit(1)
        check("url round-trips", cfg.url == PROBE_URL, cfg.url)
        check("anon key decrypts", cfg.anon_key == PROBE_ANON)
        check("config object carries no secret field",
              set(type(cfg).__dataclass_fields__) == {"url", "anon_key"})

        print("\n=== 3. the payload Vercel would receive ===")
        app_files = [
            ("index.html",
             b"<!doctype html><html><head><title>Probe</title></head>"
             b"<body><script src='./app.js'></script></body></html>"),
            ("app.js", b"const c = createClient(window.SUPABASE_URL, "
                       b"window.SUPABASE_ANON_KEY);"),
        ]
        pairs = inject_supabase_config(app_files, cfg, PROBE_SLUG)
        names = [rel for rel, _ in pairs]
        check("aiui-config.js is in the payload", "aiui-config.js" in names, str(names))

        blob = dict(pairs)
        cfg_js = blob["aiui-config.js"].decode()
        check("config carries the real url", PROBE_URL in cfg_js)
        check("config carries the real anon key", PROBE_ANON in cfg_js)

        idx = blob["index.html"].decode()
        check("index.html loads the config", "aiui-config.js" in idx)
        check("config loads before the app's own script",
              idx.index("aiui-config.js") < idx.index("app.js"))

        print("\n=== 4. Vercel and IO would serve the SAME values ===")
        # What IO injects at request time for this slug.
        io_tag = await tasks_main._supabase_inject_for(PROBE_SLUG)
        check("IO injects a config for this slug", bool(io_tag))
        check("IO and Vercel agree on the url", PROBE_URL in io_tag)
        check("IO and Vercel agree on the anon key", PROBE_ANON in io_tag)
        for g in ("window.SUPABASE_URL", "window.SUPABASE_ANON_KEY"):
            check(f"both define {g}", g in io_tag and g in cfg_js)

        print("\n=== 5. no secret leaves the platform ===")
        everything = b"".join(d for _, d in pairs)
        for bad in (b"postgresql://", b"service_role", b"oauth"):
            check(f"payload contains no {bad.decode()}", bad not in everything.lower())

        print("\n=== 6. it is a valid Vercel payload ===")
        vfiles = to_vercel_files(pairs)
        check("every entry base64-encodes", len(vfiles) == len(pairs))
        check("entries have the fields Vercel needs",
              all({"file", "data", "encoding"} <= set(f) for f in vfiles))

        print("\n=== 7. an app with NO database is untouched ===")
        none_cfg = await _supabase_deploy_config("zz-probe-does-not-exist")
        check("no link -> no config", none_cfg is None)
        check("payload unchanged when there is no database",
              inject_supabase_config(app_files, none_cfg, "x") == app_files)

        print(f"\n=== {len(PASS)} passed, {len(FAIL)} failed ===")
        if FAIL:
            for f in FAIL:
                print("  FAILED:", f)
            raise SystemExit(1)
        print("A database-backed app now deploys to Vercel with a working config.")
    finally:
        async with session() as s:
            await s.execute(
                delete(ProjectSupabase).where(ProjectSupabase.slug == PROBE_SLUG))
            await s.commit()
        print(f"cleaned up {PROBE_SLUG}")


asyncio.run(main())
