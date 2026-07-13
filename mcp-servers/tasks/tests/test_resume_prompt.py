from claude_executor import build_resume_prompt


def test_resume_replays_full_history_and_says_continue():
    history = [
        {"role": "ai", "content": "What colour scheme?"},
        {"role": "admin", "content": "dark, teal accents"},
        {"role": "ai", "content": "How many pages?"},
        {"role": "admin", "content": "three"},
    ]
    p = build_resume_prompt(
        description="<rules>\n\nUSER REQUEST:\nbuild a portfolio",
        slug="portfolio-a1",
        user_email="u@x.com",
        conversation_history=history,
        latest_answer="three",
    )
    # earlier round is retained (not just the last answer)
    assert "dark, teal accents" in p
    assert "three" in p
    # continue-the-existing-app instruction
    assert "apps/portfolio-a1/" in p
    assert "do not" in p.lower() and "restart" in p.lower()
    # the original request/build context is included
    assert "build a portfolio" in p


def test_resume_without_history_still_continues_existing_app():
    p = build_resume_prompt(
        description="<rules>\n\nUSER REQUEST:\nbuild a shop",
        slug="shop-a1",
        latest_answer="use blue",
    )
    assert "apps/shop-a1/" in p
    assert "use blue" in p
    assert "build a shop" in p
