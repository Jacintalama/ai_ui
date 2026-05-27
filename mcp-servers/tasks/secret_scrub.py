"""Redact common credential patterns from any text touching disk or logs."""
import re

_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "<REDACTED_ANTHROPIC>"),
    (re.compile(r"AIza[A-Za-z0-9_-]{20,}"), "<REDACTED_GOOGLE>"),
    (re.compile(r"duffel_test_[A-Za-z0-9_-]{20,}"), "<REDACTED_DUFFEL>"),
    (re.compile(r"duffel_live_[A-Za-z0-9_-]{20,}"), "<REDACTED_DUFFEL>"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "<REDACTED_JWT>"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "<REDACTED_GITHUB>"),
    (re.compile(r"xoxb-[A-Za-z0-9-]{30,}"), "<REDACTED_SLACK>"),
]


def scrub(text: str) -> str:
    """Replace every match of every pattern with its placeholder. Idempotent."""
    if not text:
        return text
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text
