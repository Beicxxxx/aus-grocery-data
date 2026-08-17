"""Real-browser fallback for sites behind bot protection (Coles Incapsula).

Uses Playwright with the locally installed Chrome (channel="chrome").
Incapsula generally lets real browser sessions through; the fallback is
only used when the lightweight HTTP client hits a challenge.
"""

from __future__ import annotations

import os
import time

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def fetch_html(url: str, timeout_ms: int = 90_000) -> str:
    """Load url in a real Chrome window (headless when possible) and return HTML."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=os.environ.get("AUSGROCERY_BROWSER_HEADED", "1") != "1",
        )
        try:
            page = browser.new_page(user_agent=UA, viewport={"width": 1366, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Let Incapsula / client-side rendering settle.
            page.wait_for_timeout(3_500)
            return page.content()
        finally:
            browser.close()


def fetch_html_with_retry(url: str, attempts: int = 2) -> str:
    last = None
    for i in range(attempts):
        try:
            return fetch_html(url)
        except Exception as e:  # browser can be flaky on first launch
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"browser fetch failed after {attempts} tries: {last}")
