"""Connecting by approving, instead of by pasting a token.

Eight connectors shipped and nobody connected one in two days. The likeliest
reason is the ask itself: digging a personal access token out of a vendor's
settings page is real work, and Notion's is the most buried of the lot. OAuth
replaces it with click, approve, done.

This module is the part that can be reasoned about without a network: which
providers can do this at all, how the authorization URL is built, how a
callback's `state` is proved, and how the token response is read. The route
layer owns the redirect and the exchange.

Two things here are security rather than plumbing.

`state` is bound to the user who started the flow and spendable exactly once.
Without the binding, anyone who can get a signed-in browser to follow a
callback URL can attach THEIR vendor account to YOUR user. That is account
grafting, not a login bug, and it is silent.

And this degrades. Until a deployment registers a developer app with the vendor
and sets a client id and secret, `configured()` is False and the dialog keeps
offering the paste-a-token form it has today. A Connect button that strands
someone on a vendor's error page is worse than a form that works.
"""
import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

import oauth_refresh as F

#: How long a half-finished authorization stays valid. Notion's own codes are
#: short lived; this only has to outlast a human reading a consent screen.
STATE_TTL_SEC = 900

#: Length of a PKCE verifier, in random bytes before encoding. 64 bytes of
#: urlsafe base64 is 86 characters, comfortably inside RFC 7636's 43 to 128
#: and made of nothing but its unreserved alphabet.
VERIFIER_BYTES = 64


def new_verifier() -> str:
    """A one-time secret for one authorization, never sent to the vendor
    until the code is exchanged.

    PKCE exists because the authorization CODE travels through the browser:
    the address bar, the history, any referrer or extension that sees it. A
    client secret proves the exchange is ours; this proves the exchange
    belongs to the same flow that asked for it, so a code captured in
    transit cannot be spent.
    """
    return secrets.token_urlsafe(VERIFIER_BYTES)


def challenge_for(verifier: str) -> str:
    """What goes on the authorize URL: base64url of SHA-256 of the verifier,
    with the padding stripped, as RFC 7636 specifies for `S256`.

    Unpadded is not a style choice here. The spec says so, and Airtable
    compares the string it was sent.
    """
    digest = hashlib.sha256((verifier or "").encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _env(name: str, default: str = "") -> str:
    """Indirection so tests can drive configured() without touching os.environ."""
    return os.environ.get(name, default)


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    label: str
    authorize_endpoint: str
    token_endpoint: str
    #: Extra query parameters the vendor requires on the authorize URL.
    authorize_extra: Dict[str, str]
    #: (token json) -> (credential values, account label). Raises ValueError if
    #: the vendor did not actually return a token.
    read_token: Callable[[dict], Tuple[Dict[str, str], str]]
    #: How the CLIENT authenticates at the token endpoint. Three values,
    #: because three vendors wanted three things:
    #:
    #:   "basic"          HTTP Basic, standard base64. Notion. Built by
    #:                    httpx, which is where it has always been built.
    #:   "basic_urlsafe"  HTTP Basic, base64URL. Airtable documents this,
    #:                    and the two alphabets differ exactly when the
    #:                    encoded `id:secret` contains + or /, so httpx
    #:                    cannot be used for it.
    #:   "body"           client_id and client_secret in the request body.
    #:                    GitHub and ClickUp.
    token_auth: str = "basic"
    #: How the token REQUEST is encoded: "json" or "form". Notion and ClickUp
    #: both document a JSON body. GitHub documents no content type at all, so
    #: it gets the form encoding RFC 6749 specifies, which is also what
    #: GitHub's own examples send.
    token_body: str = "json"
    #: Whether this vendor wants `redirect_uri` in a REFRESH body too.
    #:
    #: True for HubSpot alone, whose refresh request documents it beside the
    #: client id and secret. RFC 6749 does not ask for it on a refresh and
    #: no other vendor here wants it, which is precisely how it gets left
    #: out: the connect works, the card says Connected, every tool works,
    #: and half an hour later the renewal 400s and the person is told to
    #: reconnect. That reads as a flaky vendor rather than a missing
    #: parameter, which is the most expensive kind of bug to find.
    refresh_needs_redirect: bool = False
    #: Whether this vendor requires PKCE. Airtable does, and says plainly
    #: that omitting `S256` earns `invalid_grant`. False everywhere else,
    #: and not a harmless default to flip: a `code_challenge` sent to a
    #: vendor that never asked for one is an unknown parameter on somebody
    #: else's authorize URL.
    pkce: bool = False


def _notion_token(payload: dict) -> Tuple[Dict[str, str], str]:
    token = (payload or {}).get("access_token") or ""
    if not token:
        # Some flows return 200 with an error body. Storing an empty credential
        # would produce a card claiming a connection that cannot work.
        raise ValueError("Notion did not return an access token.")
    label = ((payload or {}).get("workspace_name")
             or ((payload or {}).get("owner") or {}).get("name")
             or "Notion workspace")
    # Bounded and de-tagged where it enters, as well as escaped where it is
    # rendered. This is a name a third party chose and we put on a page.
    clean = "".join(c for c in str(label) if c not in "<>").strip()
    return (F.with_expiry({"token": token}, payload),
            (clean or "Notion workspace")[:80])


#: What the person is asked to approve on GitHub's consent screen. `repo`
#: because an automation that cannot open an issue or push a commit is not
#: worth connecting, and GitHub's OAuth apps have no narrower repository
#: scope: the fine-grained alternative is a GitHub App, which is a different
#: product and a different build. `read:user` is what makes their login
#: readable, so the card can say which account is connected.
#:
#: Space-delimited, as GitHub's docs specify. These are also the exact boxes
#: to tick when registering the app.
#:
#: Overridable, and EMPTY is the meaningful value (2026-11-03). We
#: registered a GitHub App rather than an OAuth App, and for a GitHub App
#: `scope` does not control anything: permissions are fine-grained on the
#: app itself and the person chooses which repositories at install time,
#: which is the whole reason for going that way. GitHub's own words are
#: that beyond `offline_access`, "no other scopes are supported for GitHub
#: Apps", so sending `repo` there is at best ignored and at worst refused.
#:
#: Left as the OAuth App value by default so a deployment that registered
#: the old kind keeps working untouched. Setting GITHUB_SCOPE to an empty
#: string drops the parameter entirely.
GITHUB_SCOPE = os.environ.get("GITHUB_SCOPE", "repo read:user").strip()

#: The app's slug, from github.com/apps/<slug>. Empty means a classic OAuth
#: App and the ordinary authorize URL.
#:
#: This exists because of what happened the first time anyone connected
#: (2026-11-03). The connect succeeded, the card said Connected as the right
#: account, /user answered, and the account could see NOTHING: zero
#: repositories, zero installations.
#:
#: Authorising a GitHub App and installing one are two different acts.
#: Authorisation says who you are. INSTALLATION is what grants access to
#: repositories, and sending somebody to /login/oauth/authorize gets the
#: first without ever offering the second. The result is a credential that
#: works, names the right person, and reaches nothing, which is the worst
#: shape a connection can have: it passes every check we make.
#:
#: The install page does both, because the app is registered with "request
#: user authorization during installation", so it redirects back to the same
#: callback with the same code and state. One page, one approval, and the
#: person picks their repositories on it.
GITHUB_APP_SLUG = os.environ.get("GITHUB_APP_SLUG", "").strip()


def install_url(state: str = "") -> str:
    """Where somebody goes to give the app access to repositories.

    Corrected 2026-11-03, the same day it was introduced. The connect was
    pointed straight at this page, which fixed a first install and broke
    every reconnect: for an app somebody has ALREADY installed, this page
    says Configure rather than Install, and finishing it updates their
    repository selection and never redirects back with a code. Measured in
    the log as seven `oauth/start` calls and zero callbacks.

    So the connect uses the ordinary authorize URL, which always returns a
    code, and this is offered afterwards to the people who turn out to have
    no installation behind their token. Both paths end somewhere.
    """
    if not GITHUB_APP_SLUG:
        return ""
    base = "https://github.com/apps/" + GITHUB_APP_SLUG + "/installations/new"
    return base + ("?" + urlencode({"state": state}) if state else "")


def _bare_token(payload: dict, vendor: str,
                extra: Optional[Dict[str, str]] = None
                ) -> Tuple[Dict[str, str], str]:
    """A token response that carries the token and nothing else.

    GitHub and ClickUp both answer with just an access token, so neither can
    name the account here. The label is left empty on purpose and the route
    asks the vendor who this is, which verifies the token in the same breath.

    Both of them also answer 200 with an error body rather than a 4xx when the
    code is spent or wrong, so this is the only place that failure is caught.
    """
    token = (payload or {}).get("access_token") or ""
    if not token:
        raise ValueError(vendor + " did not return an access token.")
    values = {"token": token}
    values.update(extra or {})
    # An expiry and a refresh token, when the vendor sent them, so a token
    # that dies can be renewed (`oauth_refresh`). The vendor sends a refresh
    # token exactly once, in this response, so one thrown away here cannot be
    # recovered afterwards. Inert for all three providers below, none of
    # which sends either, and it is what makes HubSpot and Airtable possible.
    return F.with_expiry(values, payload), ""


def _github_token(payload: dict) -> Tuple[Dict[str, str], str]:
    return _bare_token(payload, "GitHub")


#: What the person approves on Airtable's consent screen.
#:
#: Exactly what the seven Airtable tools call and nothing else. list_my_bases
#: and list_tables read schema, list_records reads data, and whoami returns
#: an email address only with `user.email:read`, without which the card would
#: say "Connected" over a blank where the account name goes.
#:
#: The two write scopes landed on 2026-11-12 with the tools that need them,
#: which is the way this was written to grow: "if a write tool lands, this
#: grows and people re-approve, which is honest". create_table needs
#: `schema.bases:write`; create_record and update_record need
#: `data.records:write`.
#:
#: SO EVERY AIRTABLE CONNECTION MADE BEFORE THAT DATE CAN READ AND CANNOT
#: WRITE, because a token carries what was approved the day it was made and a
#: refresh renews that same grant. The vendor's answer for it is a 403 whose
#: own words are "Invalid permissions, or the requested model was not found",
#: which reads like a wrong base id, so `mytools._scope_hint` adds the one
#: sentence that helps: reconnect from Connections.
#:
#: Space delimited, as Airtable's docs specify, and overridable so a
#: deployment can widen it without a release.
#:
#: `or` rather than a default argument to `get`, which is not pedantry. The
#: variable is declared in compose as `${AIRTABLE_SCOPE:-}`, so an unset one
#: reaches the container as an EMPTY STRING, and `os.environ.get(name,
#: default)` would then hand back that empty string instead of the default:
#: a connect asking for no scopes at all, which Airtable has no reading of.
#: GITHUB_SCOPE solves the same problem from the other end, by putting its
#: default in compose, because for a GitHub App an empty scope is a
#: meaningful value and has to survive. For Airtable it is meaningless, so
#: the default belongs here, in one place, where it cannot drift from the
#: list of what the tools actually call.
AIRTABLE_SCOPE = (os.environ.get("AIRTABLE_SCOPE")
                  or "data.records:read data.records:write "
                     "schema.bases:read schema.bases:write "
                     "user.email:read").strip()


def _airtable_token(payload: dict) -> Tuple[Dict[str, str], str]:
    # Airtable sends access_token, refresh_token and expires_in, and
    # `_bare_token` keeps all three now, which is the whole reason the
    # renewal had to exist before this provider could.
    return _bare_token(payload, "Airtable")


#: What the person approves on HubSpot's consent screen.
#:
#: Exactly what the five HubSpot tools call: contacts read and write, deals
#: read, companies read. No more, because asking for permission this
#: platform cannot use is the opposite of the boundary work the rest of this
#: service just did, and a consent screen is something a person reads.
#:
#: `oauth` is deliberately absent even though every call needs it. HubSpot
#: adds that scope to every public app by itself, which is what lets the
#: whoami tool and the connect's own probe read
#: `/account-info/v3/details` without asking for anything: that endpoint's
#: only requirement is `oauth`. Listing it again would be noise.
#:
#: Space delimited and named `scope`, singular, as HubSpot's docs specify.
#: The token RESPONSE calls the same thing `scopes`, which is a good way to
#: send the plural by mistake and leave the required parameter absent.
#:
#: `or` rather than a default argument to `get`, for the reason spelled out
#: above AIRTABLE_SCOPE: compose declares it as `${HUBSPOT_SCOPE:-}`, so an
#: unset one arrives as an empty string and `get(name, default)` would hand
#: back the empty string rather than the default. Here that would be a
#: connect asking for no scopes, which HubSpot refuses outright, since
#: unlike GitHub's it is a required parameter.
HUBSPOT_SCOPE = (os.environ.get("HUBSPOT_SCOPE")
                 or "crm.objects.contacts.read crm.objects.contacts.write "
                    "crm.objects.companies.read "
                    "crm.objects.deals.read").strip()


def _hubspot_token(payload: dict) -> Tuple[Dict[str, str], str]:
    """HubSpot's exchange, which dies in 1800 seconds.

    The response carries `hub_id`, which is exactly the portal id the card
    shows, and the label is still left empty so the route goes and asks.
    That is not a wasted call: it proves the token WORKS before any card
    says Connected, through the same function the paste form and the Test
    button use. The first real GitHub connect is why that matters. It
    named the right account, answered every check we made, and reached
    nothing, and a connection shaped like that costs an afternoon to tell
    apart from a broken tool.
    """
    return _bare_token(payload, "HubSpot")


#: What the person approves on Atlassian's consent screen.
#:
#: Exactly what the six Jira tools call: work read for list_my_projects,
#: search_issues and get_issue, work write for create_issue and
#: comment_on_issue, and user read so the card can name the account.
#:
#: `offline_access` is not optional. An Atlassian access token lasts an
#: hour, and without this scope no refresh token is ever issued, so a
#: one-click connect would be a connection that dies in an hour with
#: nothing able to renew it. That is worse than the paste form it
#: replaces, which is the same trap HubSpot was held back for.
#:
#: Nothing with `delete:` in it, because no tool here deletes anything and
#: a consent screen is something a person reads.
#:
#: `or` rather than a default argument to `get`, for the reason spelled out
#: above AIRTABLE_SCOPE: compose declares these as `${JIRA_SCOPE:-}`, so an
#: unset one arrives as an empty string and `get(name, default)` would hand
#: back that empty string: a connect asking for no scopes at all.
JIRA_SCOPE = (os.environ.get("JIRA_SCOPE")
              or "read:jira-work write:jira-work read:jira-user "
                 "offline_access").strip()


def _jira_token(payload: dict) -> Tuple[Dict[str, str], str]:
    """Atlassian's token response, which names no site.

    The label is left empty and NOT filled in by the usual vendor probe,
    because at this moment there is nothing to probe: an OAuth token for
    Jira cannot address any Jira until the callback has asked
    accessible-resources which sites it can reach. That hop supplies both
    the cloud id and the name on the card.

    `scheme` is recorded for the same reason ClickUp records it: so a
    later reader knows what kind of credential this is without inferring
    it from the token's shape.
    """
    return _bare_token(payload, "Jira", {"scheme": "bearer"})


#: What the person approves on Dropbox's consent screen.
#:
#: Read only, and exactly what the four tools call: account_info.read for
#: the probe and the card's name, files.metadata.read for listing,
#: searching and reading one file's details. Upload, delete, download and
#: share links each need another scope and each is a separate card.
#:
#: A scope here also has to be ticked in the app's own Permissions tab in
#: the App Console, which is the half nobody remembers: asking for a scope
#: the app was never granted is an authorize URL that refuses.
DROPBOX_SCOPE = (os.environ.get("DROPBOX_SCOPE")
                 or "account_info.read files.metadata.read").strip()


#: What the person approves on LinkedIn's consent screen.
#:
#: These four are the ONLY permissions open to every developer, and they
#: come from two products that are added in the Developer Portal with no
#: approval: Sign In with LinkedIn using OpenID Connect (openid, profile,
#: email) and Share on LinkedIn (w_member_social). Asking for one more
#: makes this a partner application nobody has approved, and the
#: authorize URL simply refuses.
LINKEDIN_SCOPE = (os.environ.get("LINKEDIN_SCOPE")
                  or "openid profile email w_member_social").strip()


def _linkedin_token(payload: dict) -> Tuple[Dict[str, str], str]:
    """LinkedIn's token response.

    NO REFRESH TOKEN. LinkedIn issues those to approved programs only, so
    an ordinary app gets an access token good for about sixty days and
    nothing to renew it with. `_bare_token` keeps the expiry, which is
    what makes the card able to say a connection has run out rather than
    a call failing for no stated reason.

    The `id_token` is deliberately dropped: it is a signed claim about who
    signed in, not a credential for calling anything, and storing it would
    put the longest string in the response into the credential blob for no
    use at all.
    """
    return _bare_token(payload, "LinkedIn")


def _dropbox_token(payload: dict) -> Tuple[Dict[str, str], str]:
    """Dropbox's token response.

    It carries an account_id and a uid but no name and no email, so the
    label is left empty and the route asks
    /2/users/get_current_account, which proves the token in the same
    breath.
    """
    return _bare_token(payload, "Dropbox")


def _clickup_token(payload: dict) -> Tuple[Dict[str, str], str]:
    # ClickUp sends a personal token raw and an OAuth token as a Bearer, and
    # both arrive in the same `token` field, so which one this is has to be
    # recorded here. See connections._clickup_auth.
    return _bare_token(payload, "ClickUp", {"scheme": "Bearer"})


PROVIDERS: Dict[str, OAuthProvider] = {
    "notion": OAuthProvider(
        id="notion",
        label="Notion",
        authorize_endpoint="https://api.notion.com/v1/oauth/authorize",
        token_endpoint="https://api.notion.com/v1/oauth/token",
        # owner=user is what makes this a per-person grant rather than an
        # internal integration bound to one workspace.
        authorize_extra={"response_type": "code", "owner": "user"},
        read_token=_notion_token,
        token_auth="basic",
    ),
    "linkedin": OAuthProvider(
        id="linkedin",
        label="LinkedIn",
        authorize_endpoint="https://www.linkedin.com/oauth/v2/authorization",
        token_endpoint="https://www.linkedin.com/oauth/v2/accessToken",
        authorize_extra={"response_type": "code", "scope": LINKEDIN_SCOPE},
        read_token=_linkedin_token,
        token_auth="body",
        token_body="form",
    ),
    "dropbox": OAuthProvider(
        id="dropbox",
        label="Dropbox",
        authorize_endpoint="https://www.dropbox.com/oauth2/authorize",
        token_endpoint="https://api.dropboxapi.com/oauth2/token",
        authorize_extra={
            "response_type": "code",
            "scope": DROPBOX_SCOPE,
            # The whole reason Dropbox is viable at all. Without this the
            # grant returns a short-lived access token and NO refresh
            # token, so the connection is dead in about four hours with
            # nothing able to renew it.
            "token_access_type": "offline",
        },
        read_token=_dropbox_token,
        # Dropbox documents both Basic and the client in the body; the
        # body is what their own curl example sends, and it is the one
        # shape this service already has working for GitHub and HubSpot.
        token_auth="body",
        token_body="form",
    ),
    "jira": OAuthProvider(
        id="jira",
        label="Jira",
        # Atlassian's OAuth 2.0 (3LO) endpoints. Note the host: the
        # approval happens at auth.atlassian.com, NOT at the person's own
        # site, and the API afterwards is at api.atlassian.com. None of
        # the three is the address they type into a browser.
        authorize_endpoint="https://auth.atlassian.com/authorize",
        token_endpoint="https://auth.atlassian.com/oauth/token",
        authorize_extra={
            "response_type": "code",
            "scope": JIRA_SCOPE,
            # Without this the token is issued for the wrong audience: the
            # connect succeeds, the card says Connected, and every API
            # call answers 401 with nothing in it pointing here.
            "audience": "api.atlassian.com",
            # A second approval by somebody who has already approved
            # returns NO refresh token otherwise, so a reconnect would
            # quietly produce a credential that cannot be renewed.
            "prompt": "consent",
        },
        read_token=_jira_token,
        # Atlassian documents a JSON body carrying the client id and
        # secret, not HTTP Basic.
        token_auth="body",
        token_body="json",
    ),
    "github": OAuthProvider(
        id="github",
        label="GitHub",
        authorize_endpoint="https://github.com/login/oauth/authorize",
        token_endpoint="https://github.com/login/oauth/access_token",
        authorize_extra={"scope": GITHUB_SCOPE},
        read_token=_github_token,
        token_auth="body",
        token_body="form",
    ),
    "clickup": OAuthProvider(
        id="clickup",
        label="ClickUp",
        # Not a typo and not a path we shortened: ClickUp's authorize page
        # really is app.clickup.com/api, while its token endpoint is on
        # api.clickup.com. Two different hosts, one of them surprising.
        authorize_endpoint="https://app.clickup.com/api",
        token_endpoint="https://api.clickup.com/api/v2/oauth/token",
        # No scopes at all. ClickUp asks the person which Workspaces to
        # authorize instead, which is a better question than a scope list.
        authorize_extra={},
        read_token=_clickup_token,
        token_auth="body",
    ),
    "airtable": OAuthProvider(
        id="airtable",
        label="Airtable",
        # Read off Airtable's own OAuth reference on 2026-11-11, because the
        # card asked for that rather than for a guess.
        authorize_endpoint="https://airtable.com/oauth2/v1/authorize",
        token_endpoint="https://airtable.com/oauth2/v1/token",
        authorize_extra={"response_type": "code", "scope": AIRTABLE_SCOPE},
        read_token=_airtable_token,
        # base64URL of client_id:client_secret, which their docs state and
        # httpx's BasicAuth cannot produce.
        token_auth="basic_urlsafe",
        token_body="form",
        pkce=True,
    ),
    "hubspot": OAuthProvider(
        id="hubspot",
        label="HubSpot",
        # Read off HubSpot's own OAuth and migration guides on 2026-11-12.
        authorize_endpoint="https://app.hubspot.com/oauth/authorize",
        # FOUR live HubSpot token endpoints exist and picking the wrong
        # one is a connect that never works. This is the one that applies,
        # and the reason is the app, not the API:
        #
        # Legacy public apps CANNOT BE CREATED any more, as of 23 June
        # 2026. So the only app anybody can register for this is on the
        # new developer platform, and that platform's own OAuth quickstart
        # says /oauth/v3/token on api.hubapi.com, which is also the host
        # every other HubSpot call in this service already uses.
        #
        # The other three, written down so nobody has to find them twice:
        #   /oauth/v1/token        sunset 2027-02-16, and what every
        #                          HubSpot example on the internet shows.
        #   /oauth/2026-03/token   what the LEGACY v1 migration guide
        #                          points legacy apps at. A right answer
        #                          to a different question.
        #   api.hubspot.com/oauth/2026-09/token
        #                          in the newest reference, on a different
        #                          host. Where this moves next.
        token_endpoint="https://api.hubapi.com/oauth/v3/token",
        # No response_type. HubSpot's documented required parameters are
        # client_id, redirect_uri and scope, and nothing else belongs on
        # somebody else's authorize URL.
        authorize_extra={"scope": HUBSPOT_SCOPE},
        read_token=_hubspot_token,
        # client_id and client_secret in the body, form encoded: GitHub's
        # working configuration exactly, which is why this needed no new
        # machinery once the refresh existed.
        token_auth="body",
        token_body="form",
        # The one thing here that is not GitHub's configuration.
        refresh_needs_redirect=True,
    ),
}


#: Vendors that could do OAuth 2.0 but are deliberately NOT here yet, so the
#: next person does not read the gap as an oversight.
#:
#: EMPTY since 2026-11-12, and kept rather than deleted, because the rule it
#: carries outlived its members and the next vendor with a short-lived token
#: needs to meet it.
#:
#: It held HubSpot and Airtable, and the reason it gave was right: both
#: return a `refresh_token` and an access token that dies in under an hour,
#: HubSpot in 1800 seconds and Airtable in 3600, and nothing in this service
#: refreshed anything. So a one-click connect for either would have worked
#: for half an hour and then quietly stopped, with the card still reading
#: "Connected" because a stored credential is all it checks, replacing a
#: paste form that hands over a token which never expires. A downgrade.
#:
#: `oauth_refresh` closed that on 2026-11-11 (PR #186), proven on the box
#: against ClickUp's real token endpoint. Airtable went in straight
#: afterwards with the PKCE it also needed, and HubSpot on 2026-11-12 with
#: no new machinery at all.
#:
#: The rule, for whoever adds the next one: a token that dies needs
#: somewhere to be renewed BEFORE its button is offered, or the connect is
#: worse than the form it replaces.
NEEDS_TOKEN_REFRESH_FIRST: frozenset = frozenset()


#: Vendors whose one-click connect is NOT an OAuth 2.0 code exchange, so they
#: cannot live in PROVIDERS above and are handled by their own route.
#:
#: Trello (2026-10-30) is the only one. It offers exactly two ways to get a
#: user token, and neither is OAuth 2.0: its own `1/authorize` flow, and
#: OAuth 1.0a. Atlassian's RFC-89 proposed adding OAuth 2.0 and then
#: deprecating both, but nothing confirms it has shipped, so this is the
#: ground truth to build on rather than something to wait out.
#:
#: `1/authorize` is the one used here, and Trello's own guide calls it the
#: simpler route. The token comes back in the URL FRAGMENT, which a server
#: never receives, so trello_connect.py serves a page that reads it in the
#: browser and posts it back.
NON_OAUTH2_ONE_CLICK = frozenset({"trello"})


def one_click(provider_id: str) -> bool:
    """Whether this vendor can be connected without pasting a credential, by
    any route. What the card should offer a button for."""
    pid = provider_id or ""
    return pid in PROVIDERS or pid in NON_OAUTH2_ONE_CLICK


def supports_oauth(provider_id: str) -> bool:
    """Whether this vendor can do OAuth 2.0, the code exchange this module
    implements.

    False for n8n, which is the user's own server, and for Zapier, whose Catch
    Hook is a webhook rather than a grant. Neither will ever offer this, and a
    card must not imply otherwise. Also false for Trello, which has a
    one-click connect but not this one: see NON_OAUTH2_ONE_CLICK.
    """
    return (provider_id or "") in PROVIDERS


def _env_names(provider_id: str) -> Tuple[str, str]:
    stem = provider_id.upper().replace("-", "_")
    return stem + "_CLIENT_ID", stem + "_CLIENT_SECRET"


def configured(provider_id: str) -> bool:
    """Whether this deployment can actually complete the flow.

    Half configured counts as off. An id with no secret cannot complete an
    exchange, so offering the button would strand the user on the vendor's site
    with nothing to come back to.
    """
    if not supports_oauth(provider_id):
        return False
    cid, csec = _env_names(provider_id)
    return bool(_env(cid) and _env(csec))


def client_credentials(provider_id: str) -> Tuple[str, str]:
    cid, csec = _env_names(provider_id)
    return _env(cid), _env(csec)


def basic_header(provider_id: str) -> Dict[str, str]:
    """The Authorization header for a token request, or {} when there is
    none to send.

    Only ever non-empty for a `basic_urlsafe` vendor, which today is only
    Airtable. Notion's `basic` keeps going through httpx, which has built
    that header correctly since the exchange was written: a refactor
    underneath a working token endpoint buys nothing and risks the one
    provider that would notice.
    """
    provider = PROVIDERS.get(provider_id or "")
    if not provider or provider.token_auth != "basic_urlsafe":
        return {}
    client_id, client_secret = client_credentials(provider_id)
    pair = (client_id + ":" + client_secret).encode("utf-8")
    # Padded, because a Basic header is padded base64. base64url is a
    # different ALPHABET, not a different padding rule; PKCE's unpadded form
    # is a separate requirement stated separately in RFC 7636.
    return {"Authorization":
            "Basic " + base64.urlsafe_b64encode(pair).decode("ascii")}


def client_in_body(provider_id: str) -> bool:
    """Whether the client id and secret belong in the request body.

    False for both Basic kinds. Airtable's docs forbid the header when there
    is no secret and make client_id in the body optional when there is one,
    so sending the secret twice would be sending it somewhere it was never
    asked for.
    """
    provider = PROVIDERS.get(provider_id or "")
    return bool(provider) and provider.token_auth == "body"


def authorize_url(provider_id: str, client_id: str, redirect_uri: str,
                  state: str, verifier: str = "") -> str:
    """Where to send the browser to ask for consent.

    Takes the VERIFIER and computes the challenge here, rather than taking a
    challenge from the caller. Deliberate: if a caller could pass a
    challenge, a caller could pass the verifier by mistake, and that puts
    the one-time secret in the same URL as the code it is meant to protect.
    One function knows the difference, and it is this one.

    A PKCE vendor with no verifier is refused rather than handed a URL it
    will reject, because Airtable answers `invalid_grant` for that and the
    person would see a connect that failed with no cause.
    """
    provider = PROVIDERS.get(provider_id or "")
    if not provider:
        raise ValueError("No OAuth for provider: " + str(provider_id))
    params = {"client_id": client_id, "redirect_uri": redirect_uri,
              "state": state}
    params.update(provider.authorize_extra)
    if provider.pkce:
        if not verifier:
            raise ValueError(provider.label + " requires PKCE, so this flow "
                             "needs a verifier before it has a URL.")
        params["code_challenge"] = challenge_for(verifier)
        params["code_challenge_method"] = "S256"
    # An empty value means "do not ask for this at all", not "ask for
    # nothing". `scope=` on the URL is a request for an empty scope, which
    # a GitHub App has no reading of, so the parameter has to be absent
    # rather than blank.
    params = {k: v for k, v in params.items() if str(v or "").strip()}
    return provider.authorize_endpoint + "?" + urlencode(params)


def read_token_response(provider_id: str, payload: dict):
    provider = PROVIDERS.get(provider_id or "")
    if not provider:
        raise ValueError("No OAuth for provider: " + str(provider_id))
    return provider.read_token(payload or {})


@dataclass(frozen=True)
class Started:
    """Who began an authorization, and the PKCE secret it was begun with.

    The verifier has to survive between two separate requests: the one that
    built the authorize URL and the one that exchanges the code. There is
    nowhere else to keep it, because a state is spent on first read and the
    verifier has to come out of the same pop.
    """
    email: str
    verifier: str = ""


class StateStore:
    """CSRF states, in process memory, spendable once.

    In memory on purpose: a state outliving a restart buys nothing, and the
    worst case is a user clicking Connect again. Expired entries are swept on
    every mint, because an abandoned flow must not leak an entry forever.
    """

    def __init__(self):
        self._states: Dict[str, Tuple[Started, float]] = {}

    def mint(self, email: str, now: Optional[float] = None,
             verifier: str = "") -> str:
        now = time.time() if now is None else now
        for key in [k for k, (_, exp) in self._states.items() if exp < now]:
            self._states.pop(key, None)
        state = secrets.token_urlsafe(24)
        self._states[state] = (Started(email, verifier), now + STATE_TTL_SEC)
        return state

    def take(self, state: Optional[str],
             now: Optional[float] = None) -> Optional[Started]:
        """Who started this flow and with what verifier, or None. Removes
        the entry either way, so a replayed callback is inert."""
        now = time.time() if now is None else now
        item = self._states.pop((state or "").strip(), None)
        if not item:
            return None
        started, expires = item
        return started if expires >= now else None

    def consume(self, state: Optional[str],
                now: Optional[float] = None) -> Optional[str]:
        """The email that started this flow, or None. Removes it either way.

        Kept because Trello's own road and everything written before PKCE
        asks only this question. It is `take` with the verifier dropped.
        """
        started = self.take(state, now)
        return started.email if started else None

    def size(self) -> int:
        return len(self._states)

    def clear(self) -> None:
        self._states.clear()


#: One store for the service. Module level so the start and the callback, which
#: are separate requests, see the same states.
STATES = StateStore()
