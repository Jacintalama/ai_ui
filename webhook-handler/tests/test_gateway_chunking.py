"""Replies are chunked on paragraph boundaries.

Telegram hard-caps a message at 4096 characters. A model answer that goes over
must arrive as several readable messages, not one truncated one and not a
mid-word split when a paragraph break was available.
"""
import pytest

from gateway.base import chunk_text


def test_short_text_is_one_chunk():
    assert chunk_text("hello", 4096) == ["hello"]


def test_empty_text_produces_nothing():
    assert chunk_text("", 4096) == []


def test_text_at_exactly_the_limit_is_not_split():
    text = "a" * 4096
    assert chunk_text(text, 4096) == [text]


def test_paragraphs_are_the_preferred_seam():
    para = "x" * 3000
    chunks = chunk_text(f"{para}\n\n{para}", 4096)
    assert chunks == [para, para]


def test_a_single_oversized_paragraph_is_hard_split():
    chunks = chunk_text("y" * 10000, 4096)
    assert len(chunks) == 3
    assert all(len(c) <= 4096 for c in chunks)


@pytest.mark.parametrize("limit", [50, 500, 4096])
def test_no_content_is_lost_and_no_chunk_is_oversized(limit):
    text = "\n\n".join(f"paragraph {i} " + "z" * (i * 37) for i in range(20))
    chunks = chunk_text(text, limit)
    assert all(0 < len(c) <= limit for c in chunks)
    strip = lambda s: s.replace("\n", "")
    assert "".join(strip(c) for c in chunks) == strip(text)


def test_a_zero_limit_means_no_chunking():
    # A platform that declares max_message_length = 0 has no cap.
    assert chunk_text("a" * 9000, 0) == ["a" * 9000]
