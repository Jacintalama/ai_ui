"""DB-tier: seed_user_prompt records the user's original request once.

Runs in-container against aiui_test (needs AIUI_TEST_DB=1 + a test DATABASE_URL).
"""
from sqlalchemy import select

from chat_seed import seed_user_prompt
from models import ChatMessage


async def test_seed_inserts_user_prompt_once(db_session):
    await seed_user_prompt(db_session, "shop-a1", "u@x.com", "  build a candle shop  ")
    await db_session.commit()
    rows = (await db_session.execute(
        select(ChatMessage).where(ChatMessage.slug == "shop-a1")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].role == "user"
    assert rows[0].content == "build a candle shop"  # stripped

    # Idempotent: a second call for the same (slug, email) adds nothing.
    await seed_user_prompt(db_session, "shop-a1", "u@x.com", "different text")
    await db_session.commit()
    again = (await db_session.execute(
        select(ChatMessage).where(ChatMessage.slug == "shop-a1")
    )).scalars().all()
    assert len(again) == 1
    assert again[0].content == "build a candle shop"


async def test_seed_noop_on_empty_inputs(db_session):
    await seed_user_prompt(db_session, "", "u@x.com", "x")
    await seed_user_prompt(db_session, "s", "", "x")
    await seed_user_prompt(db_session, "s", "u@x.com", "")
    await seed_user_prompt(db_session, "s", "u@x.com", None)
    await db_session.commit()
    rows = (await db_session.execute(select(ChatMessage))).scalars().all()
    assert rows == []


async def test_seed_is_per_user(db_session):
    # Different viewers keep independent threads for the same slug.
    await seed_user_prompt(db_session, "shop-a1", "a@x.com", "a's request")
    await seed_user_prompt(db_session, "shop-a1", "b@x.com", "b's request")
    await db_session.commit()
    rows = (await db_session.execute(
        select(ChatMessage).where(ChatMessage.slug == "shop-a1")
    )).scalars().all()
    assert {r.user_email for r in rows} == {"a@x.com", "b@x.com"}
    assert len(rows) == 2
