"""Coles product detail + category listing.

Verified: product detail via the server-rendered `__NEXT_DATA__` JSON
(name, price, images, ingredients, storage, usage, origin, nutrition
breakdown, long description).

Category listing follows the Next.js JSON endpoint used by
aus_grocery_price_database: extract buildId from /browse, then
GET /_next/data/{buildId}/en/browse/{category}.json?slug=...&page=N.
That endpoint needs an IP that is not flagged by Incapsula.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from . import config
from .http import HttpClient

COLES_BASE = "https://www.coles.com.au"


class Coles:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient(
            cookie_file=config.DATA_DIR / "cookies_coles.txt",
            user_agent=config.UA_CHROME,
        )
        self._build_id: str | None = None
        self._primed = False

    def _prime(self) -> None:
        """Visit a browse page once so Incapsula issues a session cookie
        before product requests (mirrors the reference project's cookie
        priming for Woolworths)."""
        if self._primed:
            return
        try:
            self.client.get(f"{COLES_BASE}/browse", headers={"Accept": "text/html"},
                            allow_bot=True)
        except Exception:
            pass
        self._primed = True

    # ---- buildId -----------------------------------------------------------

    def update_build_id(self) -> str:
        self._prime()
        html = self.client.get(f"{COLES_BASE}/browse", headers={"Accept": "text/html"})
        m = re.search(r',"buildId":"([^"]+)"', html)
        if not m:
            raise RuntimeError("could not extract Coles buildId")
        self._build_id = m.group(1)
        return self._build_id

    def build_id(self) -> str:
        if not self._build_id:
            self.update_build_id()
        return self._build_id

    # ---- category listing ---------------------------------------------------

    def list_categories(self) -> list[dict]:
        bid = self.build_id()
        data = self.client.get_json(
            f"{COLES_BASE}/_next/data/{bid}/en/browse.json",
            headers={"Accept": "application/json"},
        )
        nodes = (
            data.get("pageProps", {})
            .get("allProductCategories", {})
            .get("catalogGroupView", [])
        )
        return [
            {"id": n.get("seoToken"), "name": n.get("name")}
            for n in nodes if n.get("seoToken")
        ]

    def crawl_category(self, category: str, page: int = 1) -> tuple[list[dict], int]:
        bid = self.build_id()
        url = (
            f"{COLES_BASE}/_next/data/{bid}/en/browse/{category}.json"
            f"?slug={category}&page={page}"
        )
        data = self.client.get_json(url, headers={"Accept": "application/json"})
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
        self._prime()
        html = self.client.get(f"{COLES_BASE}/product/{slug}")
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

    # ---- normalize ---------------------------------------------------------

    def normalize(self, p: dict) -> dict:
        info = {x.get("title"): x.get("description") for x in p.get("additionalInfo", [])}
        pricing = p.get("pricing") or {}
        images = p.get("images") or []
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


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
