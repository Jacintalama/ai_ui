"""Markdown subset -> document blocks -> docx/pdf bytes. Pure, no I/O."""
import io

from doc_builder import parse_blocks, split_bold


def test_parse_headings_and_paragraphs():
    md = "# Title\n\nHello world.\nSame paragraph.\n\n## Section\nBody."
    b = parse_blocks(md)
    assert b[0] == {"t": "h", "level": 1, "text": "Title"}
    assert b[1] == {"t": "p", "text": "Hello world. Same paragraph."}
    assert b[2] == {"t": "h", "level": 2, "text": "Section"}
    assert b[3] == {"t": "p", "text": "Body."}


def test_parse_lists():
    md = "- one\n- two\n\n1. first\n2) second"
    b = parse_blocks(md)
    assert b[0] == {"t": "ul", "items": ["one", "two"]}
    assert b[1] == {"t": "ol", "items": ["first", "second"]}


def test_parse_code_fence_and_table():
    md = "```\nx = 1\ny = 2\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |"
    b = parse_blocks(md)
    assert b[0] == {"t": "code", "text": "x = 1\ny = 2"}
    assert b[1] == {"t": "table", "rows": [["A", "B"], ["1", "2"]]}


def test_parse_never_raises_on_junk():
    assert parse_blocks("") == []
    assert parse_blocks("###### deep\n***\n> quote")  # no exception, some blocks


def test_split_bold():
    assert split_bold("a **b** c") == [("a ", False), ("b", True), (" c", False)]
    assert split_bold("plain") == [("plain", False)]
    assert split_bold("**all**") == [("all", True)]
