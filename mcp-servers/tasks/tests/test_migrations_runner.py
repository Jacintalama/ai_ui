"""Which files the startup migration runner will execute.

This exists because of an outage. `012_add_agent_host.down.sql` sat in the
migrations directory, and the runner globs *.sql and sorts, which puts
"012_x.down.sql" before "012_x.sql" since "." sorts before "s". Every single
startup therefore dropped agent_host and immediately re-added it.

Postgres never reclaims a dropped column's slot. After roughly 1593 restarts
tasks.executions reached the hard limit of 1600 columns and the service stopped
booting entirely, in a way no image rollback could fix, because every version
runs this same function before serving anything.
"""
import pathlib

import db

MIGRATIONS = pathlib.Path(db.__file__).parent / "migrations"


def _would_run():
    """db.py's OWN selection, not a copy of it.

    The first version of this file re-implemented the filter here, so it passed
    with the bug present: it was testing itself.
    """
    return db.migration_files()


def test_no_rollback_script_is_ever_run_on_startup():
    assert [f.name for f in _would_run() if ".down." in f.name] == []


def test_rollbacks_are_not_loose_in_the_migrations_directory():
    # Belt and braces with the filter above: a rollback that is not there
    # cannot be run even if the filter is removed.
    assert list(MIGRATIONS.glob("*.down.sql")) == []


def test_the_migrations_that_do_run_are_still_found():
    names = [f.name for f in _would_run()]
    assert len(names) > 20, "the filter must not have swallowed everything"
    assert "001_init.sql" in names
    assert "012_add_agent_host.sql" in names, (
        "the UP half of the pair must still run")


def test_a_rollback_kept_for_reference_is_still_in_the_repository():
    # Deleting it would lose the ability to undo 012 by hand.
    assert (MIGRATIONS / "rollbacks" / "012_add_agent_host.down.sql").exists()


def test_no_migration_adds_a_column_it_also_drops():
    # The shape of the bug, independent of filenames: an add/drop pair in the
    # set that runs every startup burns a column slot per restart, and a table
    # only gets 1600 for its whole lifetime.
    added, dropped = set(), set()
    for f in _would_run():
        text = f.read_text(encoding="utf-8").lower()
        for line in text.splitlines():
            if "add column" in line:
                added.add(line.split("add column")[1].replace("if not exists", "").strip().split()[0])
            if "drop column" in line:
                dropped.add(line.split("drop column")[1].replace("if exists", "").strip().split()[0].rstrip(";"))
    assert not (added & dropped), f"added and dropped every startup: {added & dropped}"
