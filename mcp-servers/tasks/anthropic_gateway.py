"""Where the Anthropic Messages API is, and how to authenticate to it.

One answer for every raw httpx caller in this service, read from the same
three environment variables the `anthropic` SDK and the Claude Code CLI read:

    ANTHROPIC_BASE_URL    e.g. https://openrouter.ai/api   (unset -> Anthropic)
    ANTHROPIC_API_KEY     sent as `x-api-key`
    ANTHROPIC_AUTH_TOKEN  sent as `Authorization: Bearer`

Why this exists. On 2026-09-02 the container was half on OpenRouter and half
broken: the SDK callers followed these variables, and two raw callers
(`routes_tasks.chat`, `fusion_engine`) had the Anthropic host as a string
literal and only ever sent `x-api-key`, so the gateway toggle that moved builds
and video to OpenRouter did nothing for them. They kept sending the dead key to
the dead host and nothing said so.

Two SDK behaviours are copied on purpose:

- Both headers are sent when both credentials are set. Anthropic reads
  `x-api-key`, OpenRouter reads `Authorization`, and neither rejects the other.
  A dead key sitting beside a live token therefore does not break anything,
  which is the situation this deployment is in.
- A base that already ends in `/v1` is not given a second one. `/v1/v1/messages`
  is a 404 that the CLI reports as "model may not exist", and that misdirection
  has cost an afternoon before.
"""
import os

DEFAULT_BASE = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


def _base() -> str:
    raw = (os.environ.get("ANTHROPIC_BASE_URL") or "").strip().rstrip("/")
    if not raw:
        return DEFAULT_BASE
    if raw.endswith("/v1"):
        raw = raw[: -len("/v1")]
    return raw


def messages_url() -> str:
    """The Messages endpoint for whichever host the environment names."""
    return f"{_base()}/v1/messages"


def auth_headers() -> dict[str, str]:
    """Credential headers only; empty when nothing is configured."""
    out: dict[str, str] = {}
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    token = (os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if key:
        out["x-api-key"] = key
    if token:
        out["Authorization"] = f"Bearer {token}"
    return out


def configured() -> bool:
    """True when at least one credential exists. Either is enough to try."""
    return bool(auth_headers())


def headers() -> dict[str, str]:
    """Everything a Messages request needs besides the body."""
    return {**auth_headers(), "anthropic-version": API_VERSION}
