"""DISCORD_USER_EMAIL_MAP parsing — env-var-driven Discord ID -> email lookup."""
from config import parse_discord_user_email_map


def test_unset_returns_empty():
    assert parse_discord_user_email_map("") == {}


def test_single_pair():
    result = parse_discord_user_email_map("100:alice@x.com")
    assert result == {"100": "alice@x.com"}


def test_multiple_pairs():
    result = parse_discord_user_email_map("100:alice@x.com,200:bob@y.com")
    assert result == {"100": "alice@x.com", "200": "bob@y.com"}


def test_email_lowercased():
    result = parse_discord_user_email_map("100:ALICE@X.COM")
    assert result["100"] == "alice@x.com"


def test_non_numeric_discord_id_dropped(caplog):
    result = parse_discord_user_email_map("not_a_snowflake:alice@x.com,200:bob@x.com")
    assert "not_a_snowflake" not in result
    assert result == {"200": "bob@x.com"}


def test_duplicate_email_warns(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        parse_discord_user_email_map("100:same@x.com,200:same@x.com")
    assert any("duplicate" in r.message.lower() for r in caplog.records)


def test_malformed_entry_dropped():
    result = parse_discord_user_email_map("100:alice@x.com,bad-no-colon,200:bob@x.com")
    assert result == {"100": "alice@x.com", "200": "bob@x.com"}
