"""Small HTTP client with cookie jar, rate limiting, retries and bot-challenge detection."""

from __future__ import annotations

import http.cookiejar
import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

BOT_MARKERS = (
    "Pardon Our Interruption",
    "Incapsula",
    "Request unsuccessful",
    "Access Denied",
)


class HttpError(RuntimeError):
    pass


def is_bot_challenge(text: str) -> bool:
    return any(m in text for m in BOT_MARKERS)


class HttpClient:
    def __init__(
        self,
        cookie_file: str | Path | None = None,
        user_agent: str = config.UA_CHROME,
        delay: float = config.REQUEST_DELAY_SECONDS,
        retries: int = config.RETRIES,
        timeout: int = config.REQUEST_TIMEOUT,
    ) -> None:
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self.user_agent = user_agent
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.cj = http.cookiejar.MozillaCookieJar(str(self.cookie_file)) \
            if self.cookie_file else http.cookiejar.CookieJar()
        if self.cookie_file and self.cookie_file.exists():
            try:
                self.cj.load(ignore_discard=True, ignore_expires=True)
            except Exception:
                pass
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj)
        )

    def _save_cookies(self) -> None:
        if self.cookie_file:
            self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.cj.save(ignore_discard=True, ignore_expires=True)
            except Exception:
                pass

    def _sleep(self) -> None:
        if self.delay:
            time.sleep(self.delay * random.uniform(0.8, 1.2))

    def request(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: bytes | None = None,
        *,
        expect_json: bool = False,
        allow_bot: bool = False,
    ) -> str:
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            h = {"User-Agent": self.user_agent, "Accept": "text/html,*/*;q=0.8"}
            if headers:
                h.update(headers)
            try:
                text = self._raw_request(url, method, h, body)
                if not allow_bot and is_bot_challenge(text):
                    # Incapsula/Akamai set session cookies on the challenge page;
                    # save them so the retry carries the session.
                    self._save_cookies()
                    raise HttpError("bot challenge detected")
                self._save_cookies()
                return text
            except HttpError as e:
                if "bot challenge" in str(e):
                    # The challenge page set session cookies; retry with them
                    # (a second request usually succeeds, as Incapsula then
                    # recognizes the session).
                    last_err = e
                    if attempt < self.retries:
                        time.sleep(2 ** attempt)
                    continue
                last_err = e
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = e
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
        raise HttpError(f"request failed after {self.retries + 1} tries: {last_err}")

    def _raw_request(self, url: str, method: str, headers: dict, body: bytes | None) -> str:
        """Issue one HTTP request. Prefers curl_cffi (Chrome TLS fingerprint)
        which passes Coles' Incapsula, falls back to urllib."""
        if _HAS_CURL_CFFI:
            try:
                resp = cffi_requests.request(
                    method, url, headers=headers, data=body,
                    timeout=self.timeout, impersonate="chrome120",
                    cookies=self._cffi_cookies(),
                    verify=True,
                )
                self._update_jar_from_cffi(resp)
                return resp.text
            except Exception:
                pass  # fall back to urllib
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with self.opener.open(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", "ignore")

    def _cffi_cookies(self) -> dict:
        return {c.name: c.value for c in self.cj}

    def _update_jar_from_cffi(self, resp) -> None:
        if not hasattr(resp, "cookies"):
            return
        from urllib.parse import urlparse
        domain = urlparse(resp.url).hostname or ".coles.com.au"
        if domain.startswith("www."):
            domain = domain[4:]
        for name, value in resp.cookies.items():
            self.cj.set_cookie(http.cookiejar.Cookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain=domain, domain_specified=True, domain_initial_dot=True,
                path="/", path_specified=True, secure=True, expires=None,
                discard=True, comment=None, comment_url=None, rest={}, rfc2109=False,
            ))

    def get(self, url: str, headers: dict | None = None, **kw) -> str:
        self._sleep()
        return self.request(url, "GET", headers, **kw)

    def post(
        self,
        url: str,
        payload: dict,
        headers: dict | None = None,
        **kw,
    ) -> str:
        self._sleep()
        body = json.dumps(payload).encode("utf-8")
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        return self.request(url, "POST", h, body, **kw)

    def get_json(self, url: str, headers: dict | None = None, **kw) -> dict:
        text = self.get(
            url, headers={"Accept": "application/json", **(headers or {})}, **kw
        )
        return json.loads(text)
