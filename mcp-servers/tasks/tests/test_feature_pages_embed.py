"""App Builder, Video Generation and Cron Jobs open inside the shell.

Until now these three were the only sidebar entries that NAVIGATED AWAY: a
click threw away the Open WebUI app and booted a standalone page, so the
sidebar vanished, the chat was lost, and coming back meant a second full boot.
Channels and Graph already opened in place. This pins the other three to the
same behaviour, and pins the two things a full navigation gave away for free
and an overlay has to earn back:

  1. A URL. An overlay lives inside the shell, so unless someone pushes one
     the address bar keeps describing the page the user was on before. Ralph
     asked for the feature's own name: /app-builder, /cronjobs,
     /video-generation.

  2. That the URL still WORKS on reload. This is the trap that makes this
     file worth more than the config it parses: /app-builder was already
     claimed by a Caddy alias that 308s to /tasks/app-builder. Pushing that
     URL would look perfect until someone pressed F5, at which point Caddy
     would answer first and bounce them straight back out of the shell.
     Nothing in task-panel.js can see that, so the check has to cross files.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
JS = (pathlib.Path(__file__).resolve().parents[1]
      / "static" / "task-panel.js").read_text(encoding="utf-8")

# label -> (what the iframe loads, what the address bar says)
EMBEDDED = {
    "App Builder": ("/tasks/app-builder", "/app-builder"),
    "Video Generation": ("/tasks/static/video.html", "/video-generation"),
    "Cron Jobs": ("/tasks/static/cron.html", "/cronjobs"),
    "Channels": ("/tasks/gateway/channels", "/channel"),
    "AI Agents": ("/tasks/agents", "/ai-agents"),
    # Nested on purpose, because the owner asked for it there: the office
    # is about the agents, and the address bar should say so. The rescue
    # matches the whole pathname, so a second segment costs it nothing.
    "Agent Office": ("/tasks/office", "/ai-agents/office"),
    "Graph": ("/tasks/graph", "/graph"),
}


def _chunk(label: str) -> str:
    """The NAV_ENTRIES literal for one entry."""
    entries = JS.split("const NAV_ENTRIES = [", 1)[1]
    return entries.split(f'label: "{label}"', 1)[1].split("attr:", 1)[0]


@pytest.mark.parametrize("label", sorted(EMBEDDED))
def test_the_feature_opens_in_the_shell_instead_of_navigating(label):
    assert "embed: true" in _chunk(label), (
        f"{label} still replaces the whole app with a standalone page")


@pytest.mark.parametrize("label", sorted(EMBEDDED))
def test_the_feature_loads_its_real_page(label):
    href, _ = EMBEDDED[label]
    assert f'href: "{href}"' in _chunk(label)


@pytest.mark.parametrize("label", sorted(EMBEDDED))
def test_the_address_bar_says_the_feature_name(label):
    _, url = EMBEDDED[label]
    assert f'urlPath: "{url}"' in _chunk(label)


@pytest.mark.parametrize("label", sorted(EMBEDDED))
def test_the_public_url_never_leaks_the_tasks_prefix(label):
    """What a person copies out of the address bar and pastes to a colleague.
    /tasks/... describes which container answers, which is nobody's business
    and was the exact complaint that got Channels moved to /channel."""
    _, url = EMBEDDED[label]
    assert not url.startswith("/tasks"), url


# --- the cross-file trap ------------------------------------------------

def _caddy() -> str:
    return (ROOT / "Caddyfile").read_text(encoding="utf-8")


def _caddy_literal_paths() -> set:
    """Paths Caddy answers itself, from `handle`/`handle_path` directives."""
    out = set()
    for kind, path in re.findall(r"^\s*(handle|handle_path)\s+(/\S+)\s*\{",
                                 _caddy(), re.M):
        out.add(path.rstrip("/") or "/")
    return out


def _caddy_path_regexps() -> list:
    """(?i)^/(app-builder|...)$ style matchers, which is how the App Builder
    alias claimed /app-builder without ever naming it in a handle line.

    Caddy's form is `path_regexp [<name>] <regexp>` — the name is optional, so
    the pattern is the last token either way. Requiring a name found nothing
    at all here and quietly turned this whole check into a no-op.
    """
    out = []
    for line in _caddy().splitlines():
        m = re.search(r"path_regexp\s+(.+)$", line.strip())
        if m:
            out.append(m.group(1).split()[-1])
    return out


def test_the_caddyfile_parser_actually_finds_something():
    """Both checks below are silently vacuous if the parse returns nothing,
    which is exactly what happened on the first draft of this file."""
    assert _caddy_literal_paths(), "no handle blocks parsed out of the Caddyfile"
    assert _caddy_path_regexps(), "no path_regexp matchers parsed out"


@pytest.mark.parametrize("label", sorted(EMBEDDED))
def test_caddy_does_not_answer_the_feature_url_itself(label):
    """A reload must reach the Open WebUI SPA so the overlay can reopen.

    If Caddy claims the path, F5 serves the bare page (or redirects to it) and
    the user is thrown out of the shell — the precise thing this change is
    meant to stop.
    """
    _, url = EMBEDDED[label]
    assert url not in _caddy_literal_paths(), (
        f"Caddy has a handle block for {url}; a reload would never reach the "
        f"SPA and the overlay could not reopen")
    for pattern in _caddy_path_regexps():
        assert not re.match(pattern, url), (
            f"Caddy path_regexp {pattern} captures {url}")


def test_the_old_standalone_urls_still_work():
    """Deep links that already exist in the wild keep working as bare pages:
    the scheduler posts /video-generator into Discord, and the knowledge graph
    links /cron-jobs and /Aiuibuilder. Making the sidebar embed must not break
    a link somebody already has."""
    literal = _caddy_literal_paths()
    assert "/video-generator" in literal
    assert "/cron-jobs" in literal
    assert any(re.match(p, "/Aiuibuilder") for p in _caddy_path_regexps()), \
        "the /Aiuibuilder alias was dropped along with /app-builder"


def test_every_pane_url_is_rescued():
    """The bounce list is a plain literal near the top of the file, because it
    has to run before anything else. If a new pane URL is added to NAV_ENTRIES
    and not to that list, the feature works from the sidebar and 404s when
    anyone pastes its URL — which is exactly the bug this was written for, and
    it hid in /channel for weeks."""
    literal = JS.split("const AIUI_URL_PATHS = [", 1)[1].split("]", 1)[0]
    rescued = set(re.findall(r'"([^"]+)"', literal))
    declared = set(re.findall(r'urlPath:\s*"([^"]+)"',
                              JS.split("const NAV_ENTRIES = [", 1)[1]))
    assert rescued == declared, rescued.symmetric_difference(declared)


def test_the_bounce_cannot_be_beaten_by_its_own_page():
    """location.replace() leaves the current document running. Without a guard,
    the sidebar observer fires on the doomed page, consumes the stored request
    and opens a pane that is thrown away a moment later, so the real load finds
    nothing and the user sits on "/". Pure race: it lost only when the script
    was cached enough to run early."""
    assert "aiuiLeavingForRescue" in JS
    body = JS.split("function aiuiPendingPath", 1)[1].split("\n  }", 1)[0]
    assert "if (aiuiLeavingForRescue) return null;" in body


def test_a_pane_never_opens_over_the_sign_in_page():
    """Signed out, the bounce lands on /auth. Opening there would cover the
    login form AND spend the request, so signing in would drop the user on a
    plain chat instead of the feature they asked for."""
    assert "const appIsUp" in JS
    assert "wanted && appIsUp" in JS


# --- the rescue must not sign anyone out ---------------------------------
#
# The bounce in task-panel.js used to be the only rescue, and it logged people
# out. task-panel.js loads at the END of body, after the SvelteKit bootstrap
# has started Open WebUI, whose root layout asks GET /api/v1/auths/ who the
# user is. location.replace("/") aborts that request, Open WebUI reads the
# network error as "no session" and deletes the token, and the page that then
# loads at "/" goes to /auth. Measured in a browser against production's
# files: 12 of 20 reloads at /ai-agents or /app-builder ended signed out,
# 0 of 10 at "/". Production's request log (mcp_proxy.api_analytics, read
# 2026-09-17) agreed: 24 of 28 password sign-ins over the 30 days before
# came 3 to 14 s after a full load of a pane URL.
#
# The override now rewrites the URL in <head>, before any of SvelteKit runs, so
# there is no navigation left to abort. These read the real override file:
# it is regenerated from the stock image on every Open WebUI upgrade, and a
# head script is the kind of thing that gets left behind.

def _override() -> str:
    return (ROOT / "openwebui-overrides" / "index.html").read_text(
        encoding="utf-8")


def _js_code(src: str) -> str:
    """Script text without comments, so a comment explaining why
    location.replace is dangerous does not count as calling it."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//.*$", "", src)


def _head_rescue() -> tuple:
    """(offset, body) of the inline <head> script that records the pane path,
    or (-1, "") when the override has none."""
    html = _override()
    head = html.split("</head>", 1)[0]
    for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                         head, re.S):
        if "sessionStorage" in _js_code(m.group(1)):
            return m.start(), m.group(1)
    return -1, ""


def test_the_override_rescues_pane_urls_in_head():
    at, _ = _head_rescue()
    assert at >= 0, (
        "openwebui-overrides/index.html has no inline <head> script recording "
        "the pane path, so a reload at a pane URL falls back to the bounce in "
        "task-panel.js, which signs people out. Regenerated the override for "
        "an Open WebUI upgrade? Carry the head script over too.")


def test_the_head_rescue_runs_before_anything_else_on_the_page():
    """Before the SvelteKit bootstrap specifically, since that is what starts
    the session check; and before every other script, so nothing on the page
    ever reads the pane URL it is about to lose."""
    html = _override()
    at, _ = _head_rescue()
    boot = html.find('import("/_app/immutable/entry/start.')
    assert boot >= 0, "SvelteKit bootstrap not found; this check would be vacuous"
    assert 0 <= at < boot
    assert at == html.find("<script"), "another script runs before the rescue"


def test_the_head_rescue_knows_every_pane_url():
    """Same list as the fallback in task-panel.js, which
    test_every_pane_url_is_rescued keeps equal to NAV_ENTRIES. A URL missing
    here would still be rescued, but by the bounce, and so would still sign
    people out."""
    _, body = _head_rescue()
    assert "AIUI_URL_PATHS = [" in body, "no path list in the head rescue"
    head_paths = set(re.findall(
        r'"([^"]+)"', body.split("AIUI_URL_PATHS = [", 1)[1].split("]", 1)[0]))
    panel_paths = set(re.findall(
        r'"([^"]+)"', JS.split("const AIUI_URL_PATHS = [", 1)[1].split("]", 1)[0]))
    assert head_paths == panel_paths, head_paths.symmetric_difference(panel_paths)


def test_the_head_rescue_hands_over_to_the_panel_without_navigating():
    """It writes the exact record aiuiPendingPath() reads, then changes the
    URL in place. Any real navigation here would bring the logout back."""
    _, body = _head_rescue()
    code = _js_code(body)
    key = re.search(r'const AIUI_PENDING_KEY = "([^"]+)"', JS).group(1)
    assert f'"{key}"' in code, f"head rescue does not write {key}"
    assert "path: location.pathname" in code and "at: Date.now()" in code
    assert 'history.replaceState(history.state, "", "/")' in code
    assert "try" in code and "catch" in code, "a storage error must not break the page"
    assert not re.search(r"location\.(replace|assign|reload)\s*\(", code)
    assert not re.search(r"location(\.href)?\s*=(?!=)", code)


def test_the_panel_keeps_the_bounce_for_an_override_without_the_head_script():
    """An override regenerated without the head script still needs a way off
    SvelteKit's 404, and the bounce is it. With the head script in place the
    pathname is already "/" when task-panel.js runs, so the bounce never
    fires."""
    rescue = JS.split("function rescueDirectFeatureUrl", 1)[1].split("})();", 1)[0]
    assert 'location.replace("/")' in rescue


# --- "no loading" -------------------------------------------------------

def test_an_opened_page_is_kept_alive_instead_of_rebuilt():
    """Ralph asked for these to open with no loading. A fresh iframe per open
    means a blank pane and a full page boot every single time, so the frames
    are cached and reopening only unhides one."""
    assert "AIUI_FRAMES" in JS
    # The close path must hide the shell, not tear it down; removing it would
    # throw away every cached frame and put the loading back.
    close_body = JS.split("function closeAiuiEmbed", 1)[1].split("\n    }", 1)[0]
    assert "w.remove()" not in close_body and "wrap.remove()" not in close_body


def test_switching_features_does_not_close_and_reopen_the_shell():
    """The outside-click handler closes the overlay, and it used to name the
    Graph entry alone. With five embedded entries, clicking any OTHER one
    would close the overlay first and reload the page being opened."""
    assert "NAV_EMBED_SELECTOR" in JS
    assert 'closest("[data-aiui-graph]")' not in JS


def test_a_backgrounded_page_is_told_to_stop_polling():
    """Keeping pages alive keeps their timers alive. App Builder polls every
    8s, so a user who opened it once would keep hitting the server from a
    hidden frame forever. The pause is advisory and fails open."""
    assert "aiuiFrameVisible" in JS
    projects = (pathlib.Path(__file__).resolve().parents[1]
                / "static" / "projects.html").read_text(encoding="utf-8")
    assert "aiuiFrameVisible" in projects


def test_the_shell_only_counts_as_open_when_it_is_showing():
    """The reopen-on-reload check asks whether an embed is already open. With
    a shell that persists hidden, a bare [data-aiui-embed] lookup answers yes
    forever and landing on /cronjobs would show nothing at all."""
    assert '[data-aiui-embed][data-open]' in JS
