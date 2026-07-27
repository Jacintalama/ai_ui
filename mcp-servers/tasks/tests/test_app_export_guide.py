"""Lukas's 'AI knows what is possible where' as a data table. Today every
target supports every app (all static); the supports() seam is where real
constraints live when server-side app types exist."""
from app_export import DEPLOY_TARGETS, AppProfile, build_deploy_guide

STATIC = AppProfile(True, False, False, 10_000, 3)
SUPA = AppProfile(True, True, False, 10_000, 3)
AI = AppProfile(True, False, True, 10_000, 3)


def test_five_targets_exist():
    keys = {t.key for t in DEPLOY_TARGETS}
    assert keys == {"github-pages", "netlify", "vercel", "cloudflare-pages", "own-server"}


def test_every_target_supports_todays_static_apps():
    for t in DEPLOY_TARGETS:
        ok, _ = t.supports(STATIC)
        assert ok, f"{t.key} should support a static app"


def test_every_target_has_steps():
    for t in DEPLOY_TARGETS:
        assert len(t.steps) >= 2, f"{t.key} needs real steps"


def test_guide_lists_every_target():
    md = build_deploy_guide(STATIC)
    for t in DEPLOY_TARGETS:
        assert t.name in md


def test_guide_warns_about_chat_proxy_only_when_used():
    assert "chat-proxy" in build_deploy_guide(AI)
    assert "chat-proxy" not in build_deploy_guide(STATIC)


def test_guide_mentions_supabase_config_only_when_used():
    assert "aiui-config.js" in build_deploy_guide(SUPA)
    assert "aiui-config.js" not in build_deploy_guide(STATIC)
