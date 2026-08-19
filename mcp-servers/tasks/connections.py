"""Connect your own account to a third-party tool.

The Connections dialog listed sixteen apps and could connect one. Behind four
of the fifteen greyed-out cards there was already a running container and an
indexed tool list: ClickUp with 172 tools, GitHub with 40, Trello with 25, n8n
with 20. What was missing was never the route to the vendor. It was anywhere to
put YOUR credential. Those containers take a single token from boot-time env,
so every call made with them acts as the platform account, and handing that to
everybody is the one thing this platform does not do.

This module is the part that can be reasoned about without a network or a
database: which providers exist, what each one needs, how to ask the vendor
whether a credential is real, and how to read the answer. The route layer owns
the HTTP call and the encrypted store, and the browser owns the form.

Two rules shape the whole thing.

Connected means checked. A card only says Connected after the vendor itself
confirmed the credential and named the account it belongs to. Accepting a
well-formed string would produce a card claiming a connection the user does not
have, and they would only find out when a tool failed.

Secrets go in and never come back. Values are encrypted before storage, never
returned by any endpoint, and `redact` exists so a log line or an error path
cannot leak one by accident.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

#: Longest account label rendered onto a card. The value comes from a third
#: party, so it is bounded here rather than trusted to be sane.
MAX_LABEL = 80


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    #: Secret fields are encrypted, never returned, and redacted in logs.
    secret: bool = True
    placeholder: str = ""


@dataclass(frozen=True)
class VendorAuth:
    """How to sign ANY request to this vendor as this user.

    Verification and every per-user tool call have to authenticate the same
    way. Two copies of "how do you sign a Trello request" is two chances to be
    wrong and one place to fix it, so it is stated here and both paths use it.
    """
    base_url: str
    headers: Dict[str, str] = _dc_field(default_factory=dict)
    params: Dict[str, str] = _dc_field(default_factory=dict)


@dataclass(frozen=True)
class VerifyRequest:
    url: str
    headers: Dict[str, str] = _dc_field(default_factory=dict)
    params: Dict[str, str] = _dc_field(default_factory=dict)


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    fields: List[Field]
    #: (values) -> VendorAuth. Raises ValueError on input the vendor could
    #: never accept, so a bad host is refused before a request leaves the box,
    #: and on missing credentials, so nothing goes out unsigned.
    build_auth: Callable[[Dict[str, str]], "VendorAuth"]
    #: Path appended to base_url to ask the vendor who this credential is.
    probe_path: str
    #: (json payload) -> the account name to show on the card.
    read_label: Callable[[dict], str]
    #: Where the user finds the credential. Shown under the form, because
    #: "paste your API token" is useless if you do not know where it lives.
    where: str = ""


def _clean(values: Dict[str, str], name: str) -> str:
    v = (values or {}).get(name)
    return v.strip() if isinstance(v, str) else ""


def _require(values: Dict[str, str], name: str) -> str:
    """A credential field, or refuse. A tool call for someone who never
    connected must not go out unsigned and come back as a confusing vendor
    401."""
    v = _clean(values, name)
    if not v:
        raise ValueError("Not connected: missing " + name)
    return v


def _http_base(values: Dict[str, str], name: str = "base_url") -> str:
    """A self-hosted base URL, validated. n8n has no fixed vendor host, so the
    user supplies one, which makes it attacker-controlled input by definition.
    """
    raw = _clean(values, name)
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a full http(s) URL, for example "
                         "https://n8n.yourdomain.com")
    return raw.rstrip("/")


def _clickup_auth(v):
    # ClickUp sends the raw token, with no Bearer prefix.
    return VendorAuth(base_url="https://api.clickup.com/api/v2",
                      headers={"Authorization": _require(v, "token")})


def _trello_auth(v):
    return VendorAuth(base_url="https://api.trello.com/1",
                      params={"key": _require(v, "api_key"),
                              "token": _require(v, "token")})


def _github_auth(v):
    return VendorAuth(
        base_url="https://api.github.com",
        headers={"Authorization": "Bearer " + _require(v, "token"),
                 "Accept": "application/vnd.github+json"})


def _notion_auth(v):
    return VendorAuth(
        base_url="https://api.notion.com/v1",
        # Notion refuses any request without this header, whatever the key is.
        headers={"Authorization": "Bearer " + _require(v, "token"),
                 "Notion-Version": "2022-06-28"})


def _n8n_auth(v):
    return VendorAuth(base_url=_http_base(v),
                      headers={"X-N8N-API-KEY": _require(v, "api_key")})


def _notion_label(d):
    d = d or {}
    bot = d.get("bot") or {}
    return bot.get("workspace_name") or d.get("name") or ""


PROVIDERS: Dict[str, Provider] = {
    "clickup": Provider(
        id="clickup",
        label="ClickUp",
        fields=[Field("token", "Personal API token", placeholder="pk_...")],
        where="ClickUp: avatar (bottom left), Settings, Apps, API Token.",
        build_auth=_clickup_auth,
        probe_path="/user",
        read_label=lambda d: ((d or {}).get("user") or {}).get("username", ""),
    ),
    "trello": Provider(
        id="trello",
        label="Trello",
        fields=[Field("api_key", "API key", placeholder="32 hex characters"),
                Field("token", "Token", placeholder="64 hex characters")],
        where="Trello: trello.com/power-ups/admin, open your Power-Up for the "
              "API key, then use the Token link beside it.",
        build_auth=_trello_auth,
        probe_path="/members/me",
        read_label=lambda d: (d or {}).get("username", ""),
    ),
    "github": Provider(
        id="github",
        label="GitHub",
        fields=[Field("token", "Personal access token",
                      placeholder="ghp_... or github_pat_...")],
        where="GitHub: Settings, Developer settings, Personal access tokens. "
              "Fine-grained tokens work.",
        build_auth=_github_auth,
        probe_path="/user",
        read_label=lambda d: (d or {}).get("login", ""),
    ),
    "notion": Provider(
        id="notion",
        label="Notion",
        fields=[Field("token", "Internal integration secret",
                      placeholder="secret_... or ntn_...")],
        where="Notion: notion.so/my-integrations, New integration, then share "
              "the pages you want it to reach with that integration.",
        build_auth=_notion_auth,
        probe_path="/users/me",
        read_label=_notion_label,
    ),
    "n8n": Provider(
        id="n8n",
        label="n8n",
        fields=[Field("base_url", "Your n8n URL", secret=False,
                      placeholder="https://n8n.yourdomain.com"),
                Field("api_key", "API key")],
        where="n8n: Settings, n8n API, Create an API key.",
        build_auth=_n8n_auth,
        probe_path="/api/v1/workflows?limit=1",
        # The workflows endpoint names no account, so the card falls back to
        # the provider label rather than showing Connected with nothing under it.
        read_label=lambda d: "",
    ),
}


def provider(provider_id: str) -> Optional[Provider]:
    return PROVIDERS.get(provider_id or "")


def required_fields(provider_id: str) -> List[str]:
    p = provider(provider_id)
    return [f.name for f in p.fields] if p else []


def missing_fields(provider_id: str, values: Dict[str, str]) -> List[str]:
    """Every missing field at once. Reporting them one at a time turns a
    two-field form into two round trips and two error messages."""
    return [n for n in required_fields(provider_id) if not _clean(values, n)]


def vendor_auth(provider_id: str, values: Dict[str, str]) -> VendorAuth:
    """How to sign a request to this vendor as this user."""
    p = provider(provider_id)
    if not p:
        raise ValueError("Unknown provider: " + str(provider_id))
    return p.build_auth(values or {})


def verify_request(provider_id: str, values: Dict[str, str]) -> VerifyRequest:
    """The one call that asks the vendor whether a credential is real."""
    p = provider(provider_id)
    if not p:
        raise ValueError("Unknown provider: " + str(provider_id))
    auth = p.build_auth(values or {})
    return VerifyRequest(url=auth.base_url + p.probe_path,
                         headers=auth.headers, params=auth.params)


def account_label(provider_id: str, payload: dict) -> str:
    """The account name shown under Connected.

    Bounded and stripped of angle brackets: it is third-party text on its way
    into the page, and "Connected" with nothing under it leaves the user unable
    to tell which account they just linked.
    """
    p = provider(provider_id)
    raw = ""
    if p:
        try:
            raw = p.read_label(payload or {}) or ""
        except Exception:
            raw = ""
    raw = "".join(c for c in str(raw) if c not in "<>").strip()
    if not raw:
        raw = p.label if p else "Connected"
    return raw[:MAX_LABEL]


def redact(provider_id: str, values: Dict[str, str]) -> Dict[str, str]:
    """Values safe to log or echo. A secret becomes a length, never a prefix:
    a prefix of a short token is most of the token."""
    p = provider(provider_id)
    if p:
        secret_names = {f.name for f in p.fields if f.secret}
    else:
        secret_names = set((values or {}).keys())
    out = {}
    for k, v in (values or {}).items():
        if k in secret_names:
            out[k] = ("<set, " + str(len(str(v or ""))) + " chars>") if v else "<empty>"
        else:
            out[k] = v
    return out
