"""Opt-in browser channel for machines where the default one crashes.

On a Windows dev machine (2026-10-13, Playwright 1.52) the default headless
shell crashed the office page ("Target crashed") on every test, while full
Chromium and Edge rendered it. Set PW_CHANNEL=chromium (or msedge) to run the
browser tier there. Unset, nothing changes.
"""
import os

try:
    from playwright.sync_api import BrowserType
except ImportError:                                         # pragma: no cover
    BrowserType = None

_CHANNEL = os.environ.get("PW_CHANNEL", "").strip()

if BrowserType is not None and _CHANNEL:
    _launch = BrowserType.launch

    def _launch_on_channel(self, *args, **kwargs):
        if self.name == "chromium":
            kwargs.setdefault("channel", _CHANNEL)
        return _launch(self, *args, **kwargs)

    BrowserType.launch = _launch_on_channel

# This file is ALSO what `from conftest import ...` resolves to for every
# test module collected after tests/browser/ (both conftests are imported as
# the bare name `conftest` under the default import mode, and the later one
# wins). Eight tests outside this directory import repo_root_or_skip that
# way, so it is re-exported here; see tests/repo_checkout.py.
from repo_checkout import repo_root_or_skip  # noqa: E402,F401
