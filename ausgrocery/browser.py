"""Real-browser fallback for sites behind bot protection (Coles Incapsula).

Uses Playwright with the locally installed Chrome (channel="chrome").
Incapsula generally lets real browser sessions through; the fallback is
only used when the lightweight HTTP client hits a challenge.

Design:
- BrowserSession keeps ONE Chrome session open for the lifetime of a crawl
  process, so many product fetches reuse the same browser (no window popping
  per request; headless by default).
- Session cookies are fed back into the lightweight client so later requests
  skip the browser when the IP stays the same. Cookies are IP-bound, so they
  are an optimisation, not a requirement: if a challenge returns, the open
  browser session handles it again.
"""

from __future__ import annotations

import os
import time

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

CHALLENGE_MARKERS = (
    "Pardon Our Interruption",
    "Request unsuccessful",
    "Incapsula",
)


def _headless() -> bool:
    """Headless by default; set AUSGROCERY_BROWSER_HEADED=1 for visible mode."""
    return os.environ.get("AUSGROCERY_BROWSER_HEADED", "0") != "1"


class BrowserSession:
    """One persistent headless Chrome session reused across many fetches."""

    def __init__(self, timeout_ms: int = 90_000) -> None:
        from playwright.sync_api import sync_playwright

        self._p = sync_playwright().start()
        self._browser = self._p.chromium.launch(
            channel="chrome", headless=_headless(),
        )
        self._context = self._browser.new_context(
            user_agent=UA, viewport={"width": 1366, "height": 900}
        )
        self._page = self._context.new_page()
        self.timeout_ms = timeout_ms

    def fetch(self, url: str, timeout_ms: int | None = None) -> tuple[str, list[dict]]:
        """Navigate to url and return (html, cookies), retrying while the
        server serves a challenge page (Incapsula sometimes challenges
        consecutive navigations; a longer wait usually lets its JS finish)."""
        t = timeout_ms or self.timeout_ms
        for attempt in range(3):
            if attempt:
                time.sleep(3)  # space consecutive navigations
            self._page.goto(url, wait_until="domcontentloaded", timeout=t)
            self._page.wait_for_timeout(4_000 if attempt == 0 else 8_000)
            html = self._page.content()
            if not any(m in html for m in CHALLENGE_MARKERS):
                return html, self._context.cookies()
        raise RuntimeError(
            "browser still receiving challenge after retries for " + url
        )

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            try:
                self._p.stop()
            except Exception:
                pass
