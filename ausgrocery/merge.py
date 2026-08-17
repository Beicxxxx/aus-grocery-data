"""Merged product details: union of Woolworths + Coles + Open Food Facts.

The merged table is the union of every field the three sources expose for a
product group (matched by GTIN barcode).  Prices stay per-store so the app
can compare them side by side; text fields (ingredients, storage, usage,
origin, description) take the first non-empty value; list fields (allergens,
dietary tags, categories) are deduplicated unions.

Image selection: the best single image wins, in this order:

1. Open Food Facts front view (explicit front-of-pack photo) - upgraded to
   the full-resolution variant;
2. Woolworths ``large`` product image;
3. Coles product image (CDN).

An optional ``--check-white`` pass verifies the chosen image actually has a
white/near-white background by sampling the corners (requires Pillow).
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone

from .matching import normalize_barcode
from .openfoodfacts import upgrade_image_to_full


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _union_lists(*values) -> list[str] | None:
    """Deduplicated union of comma-separated / list values."""
    out: list[str] = []
    for v in values:
        if not v:
            continue
        items = v.split(",") if isinstance(v, str) else v
        for item in items:
            s = str(item).strip()
            if s and s.lower() != "none" and s not in out:
                out.append(s)
    return out or None


def _first(*values):
    for v in values:
        if v not in (None, "", "None"):
            return v
    return None


def _parse_off(row: dict) -> dict | None:
    raw = row.get("off_json")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _off_image(off: dict | None) -> tuple[str | None, str | None]:
    """Return (image_url, source) from OFF, preferring front view full-size."""
    if not off:
        return None, None
    return upgrade_image_to_full(off.get("image_url")), "OpenFoodFacts"


def pick_image(
    ww_url: str | None,
    co_url: str | None,
    off: dict | None = None,
    *,
    check_white: bool = False,
    verify: bool = False,
) -> tuple[str | None, str | None]:
    """Choose the best single product image.

    Priority: OFF front view (full res) > Woolworths large > Coles CDN.
    ``check_white`` validates the winner's corners are near-white (Pillow).
    """
    candidates: list[tuple[int, str, str]] = []
    off_url, off_src = _off_image(off)
    if off_url:
        candidates.append((0, off_url, "OpenFoodFacts"))
    if ww_url:
        candidates.append((1, ww_url, "Woolworths"))
    if co_url:
        candidates.append((2, co_url, "Coles"))
    candidates.sort(key=lambda c: c[0])
    if not candidates:
        return None, None
    # Only OFF candidates are worth verifying by default: supermarket CDN
    # images are stable, while OFF user-uploaded photos occasionally 404.
    if verify:
        verified = []
        for rank, url, source in candidates:
            if source == "OpenFoodFacts" and not _image_is_ok(url):
                continue
            verified.append((rank, url, source))
        if not verified:
            verified = candidates
        candidates = verified
    _, url, source = candidates[0]
    if not check_white or _is_white_background(url):
        return url, source
    for _, alt_url, alt_src in candidates[1:]:
        if _is_white_background(alt_url):
            return alt_url, alt_src
    return url, source


def _image_is_ok(url: str) -> bool:
    """True when the URL returns a decodable image (checks magic bytes)."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (image check)"}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            head = r.read(16)
        return head[:2] in (b"\xff\xd8", b"\x89P") or head[4:8] in (
            b"ftyp", b"WEBP", b"RIFF",
        )
    except Exception:
        return False
    return url, source


def _is_white_background(url: str, threshold: int = 235) -> bool | None:
    """Sample the four corners; True when they are near-white.

    Returns None when the image cannot be downloaded/decoded (callers then
    accept the candidate as-is).
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (image check)"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        img = Image.open(__import__("io").BytesIO(data)).convert("RGB")
        w, h = img.size
        if w < 4 or h < 4:
            return None
        corners = [
            img.getpixel((1, 1)),
            img.getpixel((w - 2, 1)),
            img.getpixel((1, h - 2)),
            img.getpixel((w - 2, h - 2)),
        ]
        return all(sum(c) / 3 >= threshold for c in corners)
    except Exception:
        return None


def _nutrition_union(ww_row: dict, co_row: dict, off: dict | None) -> str | None:
    """Merge the nutrition tables from every source into one JSON payload."""
    merged: dict = {"sources": {}}
    for label, row in (("Woolworths", ww_row), ("Coles", co_row)):
        raw = row.get("nutrition_json") if row else None
        if raw:
            try:
                merged["sources"][label] = json.loads(raw)
            except (TypeError, ValueError):
                pass
    if off and off.get("nutrition"):
        merged["sources"]["OpenFoodFacts"] = off["nutrition"]
    if not merged["sources"]:
        return None
    return json.dumps(merged, ensure_ascii=False)


def build_merged(
    conn: sqlite3.Connection,
    *,
    check_white: bool = False,
    verify_images: bool = False,
) -> dict:
    """Rebuild ``merged_products`` from products + product_groups.

    One merged row per cross-store group (barcode key).  Single-store groups
    are skipped (they have nothing to compare).
    """
    groups = conn.execute(
        """
        SELECT g.group_id, g.method, m.store, m.product_id
        FROM product_groups g
        JOIN product_group_members m ON m.group_id = g.group_id
        ORDER BY g.group_id, m.store
        """
    ).fetchall()

    by_group: dict[int, dict[str, dict]] = {}
    for gid, method, store, pid in groups:
        row = conn.execute(
            "SELECT * FROM products WHERE store=? AND product_id=?",
            (store, pid),
        ).fetchone()
        if not row:
            continue
        cols = [c[0] for c in conn.execute("SELECT * FROM products LIMIT 0").description]
        by_group.setdefault(gid, {})[store] = dict(zip(cols, row))

    created = _now()
    merged_rows = []
    stats = {"groups": 0, "with_ww": 0, "with_coles": 0, "with_off": 0}

    with conn:
        conn.execute("DELETE FROM merged_products")
        for gid, members in by_group.items():
            ww = members.get("Woolworths")
            co = members.get("Coles")
            if not ww or not co:
                continue  # single-store group: nothing to compare
            off = _parse_off(ww) or _parse_off(co)
            barcode = normalize_barcode(ww.get("barcode") or co.get("barcode"))
            if not barcode:
                continue

            image_url, image_source = pick_image(
                ww.get("image_url"), co.get("image_url"), off,
                check_white=check_white,
                verify=verify_images,
            )
            allergens = _union_lists(
                ww.get("allergen_claims"), co.get("allergen_claims"),
                off and off.get("allergens"),
            )
            dietary = _union_lists(
                ww.get("dietary"), co.get("dietary"),
                off and off.get("dietary"),
            )
            categories = _union_lists(
                ww.get("categories"), co.get("categories"),
                off and off.get("categories"),
            )
            countries = _union_lists(
                ww.get("countries"), co.get("countries"),
                off and off.get("countries"),
            )
            nutrition = _nutrition_union(ww, co, off)

            conn.execute(
                """
                INSERT INTO merged_products (
                    barcode, group_id, name_ww, name_coles, brand,
                    size_ww, size_coles, price_ww_cents, price_coles_cents,
                    unit_price_ww, unit_price_coles,
                    image_url, image_source, ingredients,
                    allergens, allergen_statement, allergen_claims, dietary,
                    nutrition_json, storage, usage, origin, description,
                    categories, countries, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    barcode, gid,
                    ww.get("name"), co.get("name"),
                    _first(ww.get("brand"), co.get("brand"), off and off.get("brand")),
                    ww.get("size"), co.get("size"),
                    ww.get("price_cents"), co.get("price_cents"),
                    ww.get("unit_price"), co.get("unit_price"),
                    image_url, image_source,
                    _first(ww.get("ingredients"), co.get("ingredients"),
                           off and off.get("ingredients")),
                    _join(allergens), _join(_union_lists(ww.get("allergen_statement"),
                                                          co.get("allergen_statement"))),
                    _join(allergens), _join(dietary), nutrition,
                    _first(ww.get("storage"), co.get("storage")),
                    _first(ww.get("usage"), co.get("usage")),
                    _first(ww.get("origin"), co.get("origin")),
                    _first(ww.get("description"), co.get("description")),
                    _join(categories), _join(countries),
                    created,
                ),
            )
            stats["groups"] += 1
            stats["with_ww"] += 1
            stats["with_coles"] += 1
            if off:
                stats["with_off"] += 1
            merged_rows.append(barcode)

    return {
        "merged_rows": len(merged_rows),
        **stats,
    }


def _join(values) -> str | None:
    return ",".join(values) if values else None
