"""Coles product detail + category listing via the public BFF API.

Coles' website is fronted by Incapsula on the HTML pages, but its backend
JSON/GraphQL API (used by the web client itself) is reachable directly when
requests carry the subscription key that the site ships in its runtime
config.  That gives us a free, proxy-free path that works from a flagged IP:

* product details  -> GraphQL ``GetProductDetails`` (no buildId needed)
* category tree    -> GraphQL ``GetShopProductsMenu``
* category listing -> Next.js ``/_next/data/<buildId>/en/browse/...json``

The Next.js JSON endpoint requires the current ``buildId``; when it goes
stale we refresh it from the site's public page or from the latest Wayback
Machine snapshot of the homepage.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Iterable

from . import config
from . import browser as browser_fallback
from .coles_queries import GRAPHQL_QUERIES
from .http import HttpClient, HttpError

COLES_BASE = "https://www.coles.com.au"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_WEB = "https://web.archive.org/web"

# Sparse detail fields used for batch product lookups. Kept well below the
# GraphQL complexity limit so many products fit into a single request
# (verified: 48 products per request works reliably).
BATCH_FIELD = """
  p{i}: product(storeId: $storeId, productId: "{pid}", shoppingMethod: $shoppingMethod, useV2NipAndAllergens: $useV2NipAndAllergens) {
    id
    name
    brand
    description
    size
    gtin
    lifestyle
    imageUris { uri }
    pricing { now was comparable }
    additionalInfo { title description }
    nutrition {
      servingsPerPackage
      servingSize
      breakdown { title nutrients { nutrient value } }
    }
    countryOfOrigin { country }
  }
"""

BATCH_QUERY = (
    "query BatchDetails($storeId: BrandedId!, $shoppingMethod: ShoppingMethod, "
    "$useV2NipAndAllergens: Boolean) {\n{fields}\n}"
)
COLES_BATCH_SIZE = 48


def extract_product_id(slug: str) -> str | None:
    """Pull the trailing numeric id from a Coles product slug.

    ``lipton-...-bottle-1.5l-5171521`` -> ``5171521``
    ``8150288``                         -> ``8150288``
    """
    m = re.search(r"-(\d{4,})$", slug.strip())
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{4,}", slug.strip()):
        return slug.strip()
    return None


class Coles:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient(
            cookie_file=config.DATA_DIR / "cookies_coles.txt",
            user_agent=config.UA_CHROME,
        )
        self.api_key = config.COLES_SUBSCRIPTION_KEY
        self.store_id = config.COLES_STORE_ID
        self.shopping_method = config.COLES_SHOPPING_METHOD
        self._build_id: str | None = self._load_build_id()
        self._primed = False
        self._browser: browser_fallback.BrowserSession | None = None

    # ---- helpers -----------------------------------------------------------

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"ocp-apim-subscription-key": self.api_key}
        if extra:
            h.update(extra)
        return h

    def _gql(self, operation: str, variables: dict) -> dict:
        """POST one of the site's own GraphQL operations."""
        payload = {
            "query": GRAPHQL_QUERIES[operation],
            "variables": variables,
            "operationName": operation,
        }
        try:
            data = self.client.post_json(
                config.COLES_GRAPHQL_URL,
                payload,
                headers=self._headers({"Accept": "application/json"}),
                no_cookies=True,
            )
        except HttpError as e:
            raise HttpError(f"Coles GraphQL {operation} failed: {e}") from e
        errors = data.get("errors")
        if errors:
            msgs = "; ".join(str(x.get("message")) for x in errors)
            raise HttpError(f"Coles GraphQL {operation}: {msgs}")
        return data

    def _load_build_id(self) -> str | None:
        try:
            cached = (
                config.COLES_BUILD_ID_FILE.read_text(encoding="utf-8").strip()
                or None
            )
            if cached:
                return cached
        except OSError:
            pass
        return config.COLES_DEFAULT_BUILD_ID

    def _save_build_id(self, bid: str) -> None:
        try:
            config.COLES_BUILD_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
            config.COLES_BUILD_ID_FILE.write_text(bid, encoding="utf-8")
        except OSError:
            pass

    def _prime(self) -> None:
        """Best-effort cookie priming for the HTML fallback path."""
        if self._primed:
            return
        try:
            self.client.get(
                f"{COLES_BASE}/browse",
                headers=self._headers({"Accept": "text/html"}),
                allow_bot=True,
            )
        except Exception:
            pass
        self._primed = True

    # ---- buildId -----------------------------------------------------------

    def update_build_id(self) -> str:
        """Refresh the Next.js buildId: site page -> Wayback -> error."""
        self._prime()
        try:
            html = self.client.get(
                f"{COLES_BASE}/browse",
                headers=self._headers({"Accept": "text/html"}),
                allow_bot=True,
            )
            bid = _extract_build_id(html)
            if bid:
                self._build_id = bid
                self._save_build_id(bid)
                return bid
        except Exception:
            pass
        bid = self._build_id_from_wayback()
        if bid:
            self._build_id = bid
            self._save_build_id(bid)
            return bid
        raise RuntimeError(
            "could not resolve Coles buildId (browse page blocked and "
            "no Wayback snapshot available)"
        )

    def build_id(self) -> str:
        if not self._build_id:
            self.update_build_id()
        return self._build_id

    def _build_id_from_wayback(self) -> str | None:
        """Extract the current buildId from recent archived homepages."""
        # 1) List recent snapshots of the homepage (newest last).
        q = urllib.parse.urlencode({
            "url": "www.coles.com.au/",
            "from": "20260101",
            "output": "json",
            "fl": "timestamp,original",
            "filter": ["statuscode:200", "mimetype:text/html"],
            "collapse": "digest",
            "limit": "10",
        }, doseq=True)
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    f"{WAYBACK_CDX}?{q}",
                    headers={"User-Agent": "Mozilla/5.0"},
                ),
                timeout=60,
            ) as r:
                rows = json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:
            return None
        # 2) Try each snapshot, newest first, with a small retry.
        for ts in (row[0] for row in rows[1:] if row):
            url = f"{WAYBACK_WEB}/{ts}id_/https://www.coles.com.au/"
            for _ in range(2):
                try:
                    with urllib.request.urlopen(
                        urllib.request.Request(
                            url,
                            headers={"User-Agent": "Mozilla/5.0"},
                        ),
                        timeout=60,
                    ) as r:
                        html = r.read(2_000_000).decode("utf-8", "ignore")
                    bid = _extract_build_id(html)
                    if bid:
                        return bid
                    break
                except Exception:
                    time.sleep(1)
        return None

    # ---- category tree -----------------------------------------------------

    def list_categories(self) -> list[dict]:
        try:
            data = self._gql("GetShopProductsMenu", {
                "storeId": self.store_id,
                "withCampaignLinks": False,
                "campaignCount": 0,
            })
            nodes = data["data"]["menuItems"]["items"]
            return [
                {"id": n.get("seoToken") or n.get("id"), "name": n.get("name")}
                for n in nodes
                if n.get("seoToken")
            ]
        except HttpError:
            pass
        bid = self.build_id()
        try:
            data = self.client.get_json(
                f"{COLES_BASE}/_next/data/{bid}/en/browse.json",
                headers=self._headers({"Accept": "application/json"}),
                no_cookies=True,
            )
        except HttpError:
            html = self._fetch_html(f"{COLES_BASE}/browse")
            data = _extract_next_data(html)
        nodes = (
            data.get("pageProps", {})
            .get("allProductCategories", {})
            .get("catalogGroupView", [])
        )
        return [
            {"id": n.get("seoToken"), "name": n.get("name")}
            for n in nodes if n.get("seoToken")
        ]

    # ---- category listing ---------------------------------------------------

    def crawl_category(self, category: str, page: int = 1) -> tuple[list[dict], int]:
        bid = self.build_id()
        url = (
            f"{COLES_BASE}/_next/data/{bid}/en/browse/{category}.json"
            f"?slug={category}&page={page}"
        )
        try:
            data = self.client.get_json(
                url,
                headers=self._headers({"Accept": "application/json"}),
                no_cookies=True,
            )
        except HttpError:
            # Stale buildId (Coles rebuilds often): refresh once and retry.
            self._build_id = None
            self.update_build_id()
            bid = self.build_id()
            url = (
                f"{COLES_BASE}/_next/data/{bid}/en/browse/{category}.json"
                f"?slug={category}&page={page}"
            )
            data = self.client.get_json(
                url,
                headers=self._headers({"Accept": "application/json"}),
                no_cookies=True,
            )
        results = (
            data.get("pageProps", {})
            .get("searchResults", {})
            .get("results", [])
        )
        products = [r for r in results if r.get("_type") == "PRODUCT"]
        total = int(
            data.get("pageProps", {})
            .get("searchResults", {})
            .get("noOfResults") or len(products)
        )
        return products, total

    def crawl_category_all(
        self,
        category: str,
        max_pages: int = 10_000,
    ) -> Iterable[list[dict]]:
        page = 1
        while page <= max_pages:
            products, total = self.crawl_category(category, page)
            if not products:
                return
            yield products
            if page * config.COLES_PRODUCTS_PER_PAGE >= total:
                return
            page += 1

    # ---- product detail -----------------------------------------------------

    def product(self, slug: str) -> dict:
        """Fetch one product: GraphQL first, then Next.js JSON, then HTML."""
        pid = extract_product_id(slug)
        if pid:
            try:
                data = self._gql("GetProductDetails", {
                    "storeId": self.store_id,
                    "productId": pid,
                    "shoppingMethod": self.shopping_method,
                    "useV2NipAndAllergens": True,
                })
                p = data.get("data", {}).get("product")
                if p:
                    return p
            except HttpError:
                pass
        try:
            bid = self.build_id()
            data = self.client.get_json(
                f"{COLES_BASE}/_next/data/{bid}/en/product/{slug}.json?slug={slug}",
                headers=self._headers({"Accept": "application/json"}),
                no_cookies=True,
            )
            p = data.get("pageProps", {}).get("product")
            if p:
                return p
        except HttpError:
            pass
        self._prime()
        html = self._fetch_html(f"{COLES_BASE}/product/{slug}")
        return self.parse_product_html(html)

    def batch_products(self, product_ids: Iterable[str | int]) -> list[dict]:
        """Fetch many product details in one GraphQL request per batch.

        Returns products in the same shape as ``product()`` (id, name, brand,
        size, gtin, lifestyle, imageUris, pricing, additionalInfo, nutrition,
        countryOfOrigin). Invalid ids are skipped.
        """
        ids = [str(x) for x in product_ids]
        out: list[dict] = []
        for i in range(0, len(ids), COLES_BATCH_SIZE):
            chunk = ids[i:i + COLES_BATCH_SIZE]
            fields = "\n".join(
                BATCH_FIELD.replace("{i}", str(j)).replace("{pid}", pid)
                for j, pid in enumerate(chunk)
            )
            payload = {
                "query": BATCH_QUERY.replace("{fields}", fields),
                "variables": {
                    "storeId": self.store_id,
                    "shoppingMethod": self.shopping_method,
                    "useV2NipAndAllergens": True,
                },
                "operationName": "BatchDetails",
            }
            try:
                data = self.client.post_json(
                    config.COLES_GRAPHQL_URL,
                    payload,
                    headers=self._headers({"Accept": "application/json"}),
                    no_cookies=True,
                )
            except HttpError:
                continue
            for k, v in (data.get("data") or {}).items():
                if v:
                    out.append(v)
        return out

    def parse_product_html(self, html: str) -> dict:
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html, re.S,
        )
        if not m:
            raise RuntimeError("Coles product page has no __NEXT_DATA__ "
                               "(bot challenge or page format change)")
        data = json.loads(m.group(1))
        queries = data["props"]["pageProps"]["initialState"]["digitalGraphQLApi"]["queries"]
        for q in queries.values():
            if q.get("endpointName") == "GetProductDetails":
                return q["data"]["product"]
        raise RuntimeError("GetProductDetails not found in __NEXT_DATA__")

    def _fetch_html(self, url: str) -> str:
        """Lightweight HTTP first; real-browser fallback on bot challenge."""
        try:
            return self.client.get(
                url,
                headers=self._headers({"Accept": "text/html"}),
            )
        except HttpError as e:
            if "bot challenge" in str(e) and not os.environ.get("AUSGROCERY_NO_BROWSER"):
                return self._fetch_with_browser(url)
            raise

    def _fetch_with_browser(self, url: str) -> str:
        if self._browser is None:
            self._browser = browser_fallback.BrowserSession()
        try:
            html, cookies = self._browser.fetch(url)
        except Exception:
            # Network may have switched; recreate the session once.
            self.close_browser()
            self._browser = browser_fallback.BrowserSession()
            html, cookies = self._browser.fetch(url)
        self._apply_browser_cookies(cookies)
        return html

    def close_browser(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            finally:
                self._browser = None

    def _apply_browser_cookies(self, cookies: list[dict]) -> None:
        """Feed cookies from the real-browser session into the lightweight
        client so subsequent requests pass without opening a browser."""
        for c in cookies:
            domain = c.get("domain") or ""
            if not domain:
                continue
            initial_dot = domain.startswith(".")
            self.client.cj.set_cookie(http.cookiejar.Cookie(
                version=0, name=c.get("name"), value=c.get("value"),
                port=None, port_specified=False,
                domain=domain.lstrip("."), domain_specified=True,
                domain_initial_dot=initial_dot,
                path=c.get("path") or "/", path_specified=True,
                secure=bool(c.get("secure")),
                expires=c.get("expires"), discard=not c.get("expires"),
                comment=None, comment_url=None, rest={}, rfc2109=False,
            ))
        self.client._save_cookies()

    # ---- normalize ---------------------------------------------------------

    def normalize(self, p: dict) -> dict:
        info = {x.get("title"): x.get("description") for x in p.get("additionalInfo", [])}
        pricing = p.get("pricing") or {}
        images = p.get("images") or []
        if not images and p.get("imageUris"):
            uri = p["imageUris"][0].get("uri")
            images = [{"zoom": {"path": uri}}] if uri else []
        nutrition = p.get("nutrition") or {}
        origin = p.get("countryOfOrigin") or {}
        return {
            "store": "Coles",
            "product_id": str(p.get("id")),
            "name": p.get("name"),
            "brand": p.get("brand"),
            "size": p.get("size"),
            "price": pricing.get("now"),
            "was_price": pricing.get("was"),
            "unit_price": pricing.get("comparable"),
            "image_url": (
                f"{COLES_BASE}{images[0]['zoom']['path']}" if images else None
            ),
            "url": f"{COLES_BASE}/product/{p.get('id')}",
            "barcode": p.get("gtin"),
            "ingredients": info.get("Ingredients"),
            "allergens": _as_list(info.get("Allergen")),
            "allergen_statement": None,
            "allergen_claims": _as_list(info.get("Allergen")),
            "dietary": _as_list(p.get("lifestyle")),
            "health_star": None,
            "storage": info.get("Storage instructions") or info.get("Storage"),
            "usage": info.get("Usage instructions") or info.get("Usage"),
            "origin": origin.get("country"),
            "description": p.get("longDescription") or p.get("description"),
            "nutrition": parse_coles_nutrition(nutrition),
            "fetched_at": _now(),
            "raw": p,
        }


def parse_coles_nutrition(n: dict) -> dict | None:
    if not n:
        return None
    breakdown = n.get("breakdown") or []
    rows = {}
    for block in breakdown:
        label = block.get("title")
        key = {"Per Serving": "per_serving", "Per 100g/ml": "per_100g"}.get(label)
        if not key:
            continue
        for item in block.get("nutrients") or []:
            name = item.get("nutrient")
            if name:
                rows.setdefault(name, {})[key] = item.get("value")
    return {
        "servings_per_package": n.get("servingsPerPackage"),
        "serving_size": n.get("servingSize"),
        "nutrients": rows or None,
    }


def _as_list(value) -> list[str] | None:
    if not value:
        return None
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value).split(",") if x.strip()]


def _extract_build_id(html: str) -> str | None:
    m = re.search(r',"buildId":"([^"]+)"', html)
    return m.group(1) if m else None


def _extract_next_data(html: str) -> dict:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S,
    )
    if not m:
        raise RuntimeError("__NEXT_DATA__ not found in page")
    return json.loads(m.group(1))


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
