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
