"""Open Food Facts barcode lookup (CC-BY-SA licensed data).

Used only as a fallback for fields the supermarkets do not expose.
"""

from __future__ import annotations

import json

from . import config
from .http import HttpClient


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OpenFoodFacts:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient(
            user_agent="aus-grocery-data/0.1 (course project)",
            delay=0.5,
        )

    def by_barcode(self, barcode: str) -> dict | None:
        url = f"{config.OFF_API.format(barcode=barcode)}?fields={config.OFF_FIELDS}"
        data = self.client.get_json(url)
        if data.get("status") != 1 or not data.get("product"):
            return None
        p = data["product"]
        return {
            "store": "OpenFoodFacts",
            "product_id": p.get("code"),
            "name": p.get("product_name"),
            "brand": p.get("brands"),
            "size": p.get("quantity"),
            "image_url": p.get("image_front_url"),
            "barcode": p.get("code"),
            "ingredients": p.get("ingredients_text"),
            "allergens": [a for a in (p.get("allergens_tags") or [])],
            "dietary": [a for a in (p.get("labels_tags") or [])],
            "categories": [a for a in (p.get("categories_tags") or [])],
            "countries": [a for a in (p.get("countries_tags") or [])],
            "nutrition": p.get("nutriments"),
            "url": f"https://world.openfoodfacts.org/product/{p.get('code')}",
            "fetched_at": _now(),
            "raw": p,
        }


def merge_fallback(primary: dict, off: dict | None) -> dict:
    """Fill only missing non-core fields from OFF. Store prices/images are never
    overwritten; the OFF copy stays available in the row's off_json column."""
    if not off:
        return primary
    for field in ("ingredients", "allergens", "dietary", "nutrition"):
        if not primary.get(field) and off.get(field):
            primary[field] = off[field]
    return primary
