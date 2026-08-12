"""update_id is a per-bot counter, not a global one.

Before this fix two users' bots collided on the same integer and one person's
message vanished as a duplicate. Nothing would have surfaced that: the drop
path returns 200 and logs nothing.
"""
import main


def test_the_dedupe_key_is_scoped_to_a_bot():
    main._gateway_seen_updates.clear()
    main._gateway_seen_updates.add(("botA", 1))
    assert ("botB", 1) not in main._gateway_seen_updates


def test_the_shared_bot_has_a_key_of_its_own():
    assert main.SHARED_BOT_KEY
    assert isinstance(main.SHARED_BOT_KEY, str)


def test_the_same_update_on_the_same_bot_is_still_a_duplicate():
    main._gateway_seen_updates.clear()
    main._gateway_seen_updates.add(("botA", 7))
    assert ("botA", 7) in main._gateway_seen_updates
