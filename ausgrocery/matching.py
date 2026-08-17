"""Cross-store product matching: strict GTIN (barcode) matching only.

Same grocery product is sold under different names at the two retailers,
so name-based fuzzy matching can mis-pair lookalike products (e.g. regular
milk vs lactose-free milk).  Groups are therefore formed **only** when both
stores carry the same EAN/UPC/GTIN barcode.

Every product ends up in exactly one ``product_groups`` row; groups whose
members include both stores are the cross-store comparison units the app
renders side by side.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone


def normalize_text(value: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", value or "").lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    return " ".join(text.split())


def normalize_barcode(value: str) -> str | None:
    """Normalise a barcode to digits; None for bogus values.

    Accepts EAN-8 / UPC-A / EAN-13 / GTIN-14 (8-14 digits).
    """
    b = re.sub(r"[^0-9]", "", value or "")
    if len(b) < 8 or len(b) > 14:
        return None
    return b


def canonical_size(value: str) -> str | None:
    """Normalise a size string (kept as a general-purpose helper)."""
    s = (value or "").strip()
    if not s:
        return None
    s = re.sub(r"\s+", " ", s.lower())
    s = re.sub(r"([0-9])\s*([a-z]+)", r"\1 \2", s)
    s = s.strip()
    if re.fullmatch(r"[\d .,a-z]+", s):
        return s
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rebuild_groups(conn: sqlite3.Connection) -> dict:
    """Recompute all product groups from the current snapshot (GTIN only)."""
    rows = conn.execute(
        "SELECT store, product_id, name, brand, size, barcode FROM products"
    ).fetchall()
    products = [
        {
            "store": r[0], "product_id": r[1], "name": r[2] or "",
            "brand": r[3] or "", "size": r[4] or "", "barcode": r[5] or "",
        }
        for r in rows
    ]

    groups: list[dict] = []
    group_of: dict[tuple[str, str], int] = {}
    key_of: set[str] = set()

    def add_group(key: str, method: str, members: list[tuple[str, str]]) -> int:
        assert key not in key_of
        key_of.add(key)
        groups.append({"key": key, "method": method, "members": members})
        gid = len(groups) - 1
        for m in members:
            group_of[m] = gid
        return gid

    # ---- Pass 1: GTIN (strict) ---------------------------------------------
    by_barcode: dict[str, list[tuple[str, str]]] = {}
    for p in products:
        bc = normalize_barcode(p["barcode"])
        if bc:
            by_barcode.setdefault(bc, []).append((p["store"], p["product_id"]))
    for bc, members in by_barcode.items():
        add_group(f"gtin:{bc}", "gtin", _dedupe(members))

    # ---- Pass 2: singles ----------------------------------------------------
    for p in products:
        m = (p["store"], p["product_id"])
        if m not in group_of:
            add_group(f"single:{p['store']}:{p['product_id']}", "single", [m])

    _write_groups(conn, groups)
    return _report(conn, groups)


def _dedupe(members: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for m in members:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _write_groups(conn: sqlite3.Connection, groups: list[dict]) -> None:
    created = _now()
    with conn:
        conn.execute("DELETE FROM product_group_members")
        conn.execute("DELETE FROM product_groups")
        for g in groups:
            if not g["members"]:
                continue
            cur = conn.execute(
                "INSERT INTO product_groups (match_key, method, created_at)"
                " VALUES (?,?,?)",
                (g["key"], g["method"], created),
            )
            gid = cur.lastrowid
            conn.executemany(
                "INSERT INTO product_group_members (group_id, store, product_id)"
                " VALUES (?,?,?)",
                [(gid, m[0], m[1]) for m in g["members"]],
            )


def _report(conn: sqlite3.Connection, groups: list[dict]) -> dict:
    alive = [g for g in groups if g["members"]]
    total = len(alive)
    cross = 0
    by_method = {"gtin": 0, "single": 0}
    examples = []
    for g in alive:
        stores = {m[0] for m in g["members"]}
        by_method[g["method"]] = by_method.get(g["method"], 0) + 1
        if len(stores) == 2:
            cross += 1
            if len(examples) < 12:
                pairs = [
                    next(m for m in g["members"] if m[0] == s)
                    for s in ("Woolworths", "Coles")
                ]
                names = [
                    conn.execute(
                        "SELECT name, brand FROM products WHERE store=? AND product_id=?",
                        (s, pid),
                    ).fetchone()
                    for s, pid in pairs
                ]
                examples.append({
                    "method": g["method"],
                    "ww": f"{names[0][1] or ''} {names[0][0]}".strip()
                    if names[0] else pairs[0],
                    "coles": f"{names[1][1] or ''} {names[1][0]}".strip()
                    if names[1] else pairs[1],
                })
    return {
        "total_groups": total,
        "cross_store_groups": cross,
        "by_method": by_method,
        "examples": examples,
    }
