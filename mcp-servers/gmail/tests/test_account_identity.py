"""An account is keyed by its address, never by its user id.

The incident this guards, read off production on 2026-10-29: one account had a
row in all three Google token tables keyed by its Open WebUI user id,

    gmail_tokens     d741f063-d6b4-4d28-9abb-9bf30b43fa9e
    gdrive_tokens    d741f063-d6b4-4d28-9abb-9bf30b43fa9e
    calendar_tokens  d741f063-d6b4-4d28-9abb-9bf30b43fa9e

alongside a correct row keyed by the address. Every read asks by address, so
the id-keyed rows were written, never read, and never reported: the account
looked connected to the browser and unconnected to everything else.

The three rows came from one `connect=all` consent, which writes all three
tables from a single identity. The identity came from the browser, which took
it from the JWT, which carries an id and no address.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import account_identity as ai


EMAIL = "someone@example.com"
USER_ID = "d741f063-d6b4-4d28-9abb-9bf30b43fa9e"


async def _never_called(_key):
    raise AssertionError("an address must not cost a database round trip")


async def _knows(key):
    return EMAIL if key == USER_ID else None


# --- telling the two apart ---------------------------------------------------

@pytest.mark.parametrize("value", [
    EMAIL, "a@b", "default@local", "  spaced@example.com  ",
])
def test_an_address_is_recognised(value):
    assert ai.looks_like_email(value) is True


@pytest.mark.parametrize("value", [
    USER_ID, "", "   ", "nobody", "no at sign", None,
])
def test_anything_without_an_at_is_not_an_address(value):
    assert ai.looks_like_email(value) is False


def test_a_user_id_is_recognised_by_shape():
    assert ai.looks_like_user_id(USER_ID) is True
    assert ai.looks_like_user_id(EMAIL) is False


# --- the read path, which is forgiving ---------------------------------------

async def test_an_address_passes_through_untouched():
    assert await ai.canonical_email(EMAIL, _never_called) == EMAIL


async def test_an_address_is_trimmed():
    assert await ai.canonical_email("  %s  " % EMAIL, _never_called) == EMAIL


async def test_a_user_id_is_resolved_to_its_address():
    """The repair. A client that still sends an id reaches the right account
    instead of being told it has no connection."""
    assert await ai.canonical_email(USER_ID, _knows) == EMAIL


async def test_an_unknown_id_comes_back_unchanged_when_reading():
    """Not an error: the caller then reports 'not connected', which is what it
    would have reported anyway. Reading must never raise over this."""
    async def knows_nobody(_key):
        return None
    assert await ai.canonical_email(USER_ID, knows_nobody) == USER_ID


async def test_no_resolver_is_not_an_error_when_reading():
    assert await ai.canonical_email(USER_ID) == USER_ID


# --- the write path, which is not ---------------------------------------------

async def test_writing_a_resolvable_id_stores_the_address():
    assert await ai.canonical_email(USER_ID, _knows, required=True) == EMAIL


async def test_writing_an_unresolvable_id_refuses():
    """The whole point. A token stored under a key nothing will ever ask for
    is worse than a connect that visibly failed, because it looks like it
    worked."""
    async def knows_nobody(_key):
        return None
    with pytest.raises(ai.UnknownAccount) as err:
        await ai.canonical_email(USER_ID, knows_nobody, required=True)
    assert "user id" in str(err.value)


async def test_the_refusal_says_what_to_do():
    with pytest.raises(ai.UnknownAccount) as err:
        await ai.canonical_email(USER_ID, None, required=True)
    assert "Reload" in str(err.value)


async def test_writing_an_address_never_refuses():
    assert await ai.canonical_email(EMAIL, None, required=True) == EMAIL


async def test_a_resolver_returning_junk_is_not_trusted():
    """A resolver that hands back something that is not an address must not
    turn into a token key, or this module would be re-introducing the bug it
    exists to stop."""
    async def knows_junk(_key):
        return "still-not-an-address"
    with pytest.raises(ai.UnknownAccount):
        await ai.canonical_email(USER_ID, knows_junk, required=True)


# --- placeholders, the last way two people could share a key -----------------

async def test_a_placeholder_is_refused_on_the_write_path():
    """`default@local` has an @, so every shape test passes it. It is still
    not an account: a token stored under it belongs to whoever asks next."""
    with pytest.raises(ai.UnknownAccount) as err:
        await ai.canonical_email("default@local", None, required=True)
    assert "placeholder" in str(err.value)


async def test_a_placeholder_is_fine_on_a_box_with_no_database():
    """Local dev has one account and it is called default@local."""
    assert await ai.canonical_email(
        "default@local", None, required=True,
        placeholders_ok=True) == "default@local"


async def test_a_placeholder_still_reads_fine():
    """Reading as default@local is how a dev box works and how a misconfigured
    request reports 'not connected'. Neither should raise."""
    assert await ai.canonical_email("default@local") == "default@local"


async def test_a_real_address_is_not_mistaken_for_a_placeholder():
    assert await ai.canonical_email(EMAIL, None, required=True) == EMAIL
