"""Cross-store field documentation lives in docs/FIELD_MAPPING.md.
This module only hosts shared helpers for row assembly."""

from __future__ import annotations


COMMON_FIELDS = [
    "store", "product_id", "name", "brand", "size", "price", "was_price",
    "unit_price", "image_url", "url", "barcode", "ingredients", "allergens",
    "allergen_statement", "allergen_claims", "dietary", "health_star",
    "storage", "usage", "origin", "description", "nutrition", "fetched_at",
]


def rows_equal_except_price(a: dict, b: dict) -> bool:
    """True when two normalized rows have the same non-price content."""
    def prune(d: dict) -> dict:
        return {k: v for k, v in d.items()
                if k not in ("price", "was_price", "unit_price", "fetched_at", "raw")}
    return prune(a) == prune(b)
