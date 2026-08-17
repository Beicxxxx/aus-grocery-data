"""Woolworths public UI API access.

Verified working paths (2026-08):
- GET /apis/ui/Search/products          -> search results with full attributes
- GET /apis/ui/PiesCategoriesWithSpecials -> department list
- POST /apis/ui/browse/category         -> paginated category products
  (requires a prior GET of the browse page to prime the cookie jar)
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Iterable

from . import config
from .http import HttpClient

WW_BASE = "https://www.woolworths.com.au"


def _url(path: str, **query) -> str:
    q = urllib.parse.urlencode(query)
    return f"{WW_BASE}{path}?{q}" if q else f"{WW_BASE}{path}"


class Woolworths:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient(
            cookie_file=config.DATA_DIR / "cookies_woolworths.txt",
            user_agent=config.UA_FIREFOX,
        )

    # ---- search -----------------------------------------------------------

    def search(self, term: str, page: int = 1, page_size: int = 24) -> list[dict]:
        data = self.client.get_json(
            _url("/apis/ui/Search/products", searchTerm=term,
                 pageSize=page_size, pageNumber=page),
            headers={"Referer": f"{WW_BASE}/"},
        )
        out = []
        for group in data.get("Products") or []:
            out.extend(group.get("Products") or [])
        return out

    # ---- categories --------------------------------------------------------

    def list_categories(self) -> list[dict]:
        """Best-effort department discovery via PiesCategoriesWithSpecials."""
        self._prime_cookies("browse")
        data = self.client.get_json(
            f"{WW_BASE}/apis/ui/PiesCategoriesWithSpecials",
            headers={"Referer": f"{WW_BASE}/shop/browse"},
        )
        cats = data.get("Categories") or []
        out = []
        for c in cats:
            nid = c.get("NodeId") or c.get("Id")
            if nid:
                out.append({
                    "id": nid,
                    "name": c.get("Description") or c.get("Name"),
                    "url": c.get("UrlFriendlyName") or c.get("SeoToken"),
                })
        return out

    # ---- category crawl ----------------------------------------------------

    def _prime_cookies(self, url_path: str) -> None:
        try:
            self.client.get(
                f"{WW_BASE}/shop/browse/{url_path}",
                headers={"Accept": "text/html"},
                allow_bot=True,
            )
        except Exception:
            pass

    def crawl_category(
        self,
        category_id: str,
        url_path: str,
        page: int = 1,
        page_size: int = config.WWS_PAGE_SIZE,
    ) -> tuple[list[dict], int]:
        """Fetch one page of a category. Returns (products, total_record_count)."""
        self._prime_cookies(url_path)
        payload = {
            "categoryId": category_id,
            "pageNumber": page,
            "pageSize": page_size,
            "sortType": "TraderRelevance",
            "url": f"/shop/browse/{url_path}",
            "location": f"/shop/browse/{url_path}",
            "formatObject": json.dumps({"name": url_path.replace("-", " ").title()}),
            "isSpecial": False,
            "isBundle": False,
            "isMobile": False,
            "filters": [],
            "token": "",
            "gpBoost": 0,
            "isHideUnavailableProducts": False,
            "isRegisteredRewardCardPromotion": False,
            "enableAdReRanking": False,
            "groupEdmVariants": True,
            "categoryVersion": "v2",
        }
        text = self.client.post(
            f"{WW_BASE}/apis/ui/browse/category",
            payload,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{WW_BASE}/shop/browse/{url_path}",
            },
        )
        data = json.loads(text)
        products = []
        for bundle in data.get("Bundles") or []:
            products.extend(bundle.get("Products") or [])
        total = int(data.get("TotalRecordCount") or len(products))
        return products, total

    def crawl_category_all(
        self,
        category_id: str,
        url_path: str,
        max_pages: int = 10_000,
    ) -> Iterable[list[dict]]:
        page = 1
        while page <= max_pages:
            products, total = self.crawl_category(category_id, url_path, page)
            if not products:
                return
            yield products
            if page * config.WWS_PAGE_SIZE >= total:
                return
            page += 1

    # ---- normalize ---------------------------------------------------------

    def normalize(self, p: dict) -> dict:
        a = p.get("AdditionalAttributes") or {}
        return {
            "store": "Woolworths",
            "product_id": str(p.get("Stockcode")),
            "name": p.get("DisplayName") or p.get("Name"),
            "brand": p.get("Brand"),
            "size": p.get("PackageSize"),
            "price": p.get("Price"),
            "was_price": p.get("WasPrice"),
            "unit_price": p.get("CupString"),
            "image_url": p.get("LargeImageFile"),
            "url": f"{WW_BASE}/shop/productdetails/{p.get('Stockcode')}",
            "barcode": p.get("Barcode"),
            "ingredients": a.get("ingredients"),
            "allergens": _comma_list(a.get("allergencontains")),
            "allergen_statement": _comma_list(a.get("allergenmaybepresent")),
            "allergen_claims": _comma_list(a.get("allergystatement")),
            "dietary": _comma_list(a.get("lifestyleanddietarystatement")),
            "health_star": a.get("healthstarrating"),
            "storage": a.get("storageinstructions"),
            "usage": a.get("usageinstructions"),
            "origin": a.get("countryoforigin"),
            "description": a.get("description") or p.get("Description"),
            "nutrition": parse_ww_nutrition(a.get("nutritionalinformation")),
            "fetched_at": _now(),
            "raw": p,
        }


def parse_ww_nutrition(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    rows = {}
    for attr in data.get("Attributes") or []:
        name = attr.get("Name") or ""
        m = re.match(r"^(.*?) Quantity Per (100g|Serve)(?: - Total)? - NIP$", name)
        if m:
            rows.setdefault(m.group(1), {})[m.group(2)] = attr.get("Value")
    return rows or None


def _comma_list(value) -> list[str] | None:
    if not value:
        return None
    return [x.strip() for x in str(value).split(",") if x.strip()]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
