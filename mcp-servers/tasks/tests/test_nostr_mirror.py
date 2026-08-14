"""The Nostr key modules exist twice, and must never drift.

webhook-handler signs with them; tasks validates a pasted key with them so a
typo is refused in the browser with a reason instead of failing thirty seconds
later inside a background loop, where the user would see only "saved" followed
by nothing ever working.

Two containers with separate dependency sets cannot import each other, and the
repository already carries this exact pattern for the terminal client
(scripts/io.py mirrored to static/io.py). Copies are fine. Copies that drift
are not, and a signing primitive that differs between the service that signs
and the service that validates would accept keys the signer cannot use.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
PAIRS = [
    (ROOT / "webhook-handler" / "gateway" / "nip19.py",
     ROOT / "mcp-servers" / "tasks" / "nostr_nip19.py"),
    (ROOT / "webhook-handler" / "gateway" / "schnorr.py",
     ROOT / "mcp-servers" / "tasks" / "nostr_schnorr.py"),
]


def test_both_copies_exist():
    for source, mirror in PAIRS:
        assert source.exists(), source
        assert mirror.exists(), mirror


def test_every_mirror_is_byte_identical_to_its_source():
    # Byte identical, not "equivalent". Anything looser needs a judgement call
    # at review time, which is what lets a drift through.
    for source, mirror in PAIRS:
        assert mirror.read_bytes() == source.read_bytes(), (
            f"{mirror.name} has drifted from {source}. Copy it again rather "
            f"than editing one side.")


def test_the_mirrors_import_nothing_from_their_home_package():
    # What makes a copy safe: neither file reaches into gateway/, so the same
    # bytes work in a service that has no gateway package at all.
    for _, mirror in PAIRS:
        text = mirror.read_text(encoding="utf-8")
        assert "from gateway" not in text and "import gateway" not in text
