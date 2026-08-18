"""Open Food Facts barcode lookup (ODbL / CC-BY-SA licensed data).

Reading product data does **not** require an API key.  The only requirement
is a custom ``User-Agent`` of the form ``AppName/Version (ContactEmail)``.
Write operations (image upload, edits) need an account, but this pipeline is
read-only.

Rate limits (per IP): 15 reads/min, 10 searches/min.  For larger volumes
the official JSONL/CSV exports are the recommended path.

Reference: https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/
"""

from __future__ import annotations

import json
import re

from . import config
from .http import HttpClient


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upgrade_image_to_full(url: str | None) -> str | None:
    """Upgrade an OFF front image URL to the full-resolution variant.

    ``.../front_en.45.400.jpg`` -> ``.../front_en.45.full.jpg``
    """
    if not url:
        return None
    return re.sub(r"\.(\d{2,4})\.(jpg|png)$", r".full.\2", url)


class OpenFoodFacts:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient(
            user_agent=config.OFF_USER_AGENT,
            delay=1.0,  # stay under 15 req/min
        )

    def by_barcode(self, barcode: str) -> dict | None:
        """Look up one product via the v3 API. Returns a normalised row."""
        url = f"{config.OFF_API_V3.format(barcode=barcode)}?fields={config.OFF_FIELDS_V3}"
        try:
            text = self.client.get(url)
            data = json.loads(text)
        except Exception:
            return None
        if data.get("status") != 1 or not data.get("product"):
            return None
        p = data["product"]

        # Collect every front-view image variant; prefer the full-resolution one.
        front_images: list[str] = []
        images = p.get("images") or {}
        for key in sorted(images):
            if "front" not in key:
                continue
            sizes = (images[key] or {}).get("sizes") or {}
            for size_name in ("full", "400", "200"):
                url = (sizes.get(size_name) or {}).get("url")
                if url:
                    front_images.append(url)
                    break
        image_url = (
            front_images[0]
            if front_images
            else upgrade_image_to_full(p.get("image_front_url"))
            or p.get("image_front_url")
        )

        return {
            "store": "OpenFoodFacts",
            "product_id": p.get("code"),
            "name": p.get("product_name"),
            "brand": p.get("brands"),
            "size": p.get("quantity"),
            "serving_size": p.get("serving_size"),
            "servings_per_package": (p.get("nutriments") or {}).get(
                "servings_per_package"
            ),
            "image_url": image_url,
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
