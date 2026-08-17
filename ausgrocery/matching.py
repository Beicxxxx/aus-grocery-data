"""Cross-store product matching: GTIN first, then normalized name matching.

Same grocery product is sold under different names and barcodes at the two
retailers (e.g. "Bega Stringers Cheese" vs "Cheese Stringers Original",
"12 Extra Large Free Range Eggs" vs "Free Range Extra Large Eggs 12 Pack").

Two passes:

1. **GTIN**: products sharing a barcode (EAN/UPC) are the same product.
2. **Name**: for the rest, compare brand (equal, or both store brands),
   canonical size, and the similarity of normalised name tokens.

Every product ends up in exactly one ``product_groups`` row; groups whose
members include both stores are the cross-store comparison units the app
renders side by side.
"""

from __future__ import annotations

import difflib
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

SCORE_DEFAULT = 0.78

# Spelling normalisation so "yoghurt" == "yogurt", "lite" == "light".
SYNONYMS = {
    "yoghurt": "yogurt",
    "lite": "light",
    "pkt": "pack",
    "pk": "pack",
    "packet": "pack",
    "strawb": "strawberry",
}

# Tokens that carry little product identity (container/pack words).
GENERIC_TOKENS = {
    "pack", "packs", "pk", "pkt", "x", "each", "ea", "bottle", "bottles",
    "can", "cans", "bag", "bags", "box", "boxes", "tub", "tubs",
    "carton", "cartons", "jar", "jars", "multi", "twin", "twinpack",
    "uht",
}

# Retailer's own brands; a Coles own-brand product is comparable with a
# Woolworths own-brand product even though the brand names differ.
STORE_BRANDS = {
    "woolworths", "woolworths essentials", "woolworths select",
    "woolworths organic", "woolworths macro", "coles", "coles dairy",
    "coles simply", "coles organic", "macro", "good yoke co",
}

def normalize_text(value: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace, synonyms."""
    text = unicodedata.normalize("NFKD", value or "").lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    tokens = []
    for tok in text.split():
        tokens.append(SYNONYMS.get(tok, tok))
    return " ".join(tokens)


def normalize_barcode(value: str) -> str | None:
    b = re.sub(r"[^0-9]", "", value or "")
    # EAN-8 / UPC-A / EAN-13 / GTIN-14; drop bogus short values.
    if len(b) < 8 or len(b) > 14:
        return None
    return b


def canonical_size(value: str) -> str | None:
    """Normalise a size string into a comparable form.

    ``400g`` -> ``400 g``, ``1.5L`` -> ``1.5 l``,
    ``300mL x 12 pack`` -> ``300 ml x 12 pack``.
    """
    s = (value or "").strip()
    if not s:
        return None
    s = re.sub(r"\s+", " ", s.lower())
    s = re.sub(r"([0-9])\s*([a-z]+)", r"\1 \2", s)
    s = s.replace(" x ", " x ").strip()
    if re.fullmatch(r"[\d .,a-z]+", s):
        return s
    return None


def brand_tokens(brand: str) -> list[str]:
    return normalize_text(brand).split()


def name_tokens(name: str, brand: str, size: str) -> list[str]:
    """Name tokens minus brand and size tokens."""
    n = normalize_text(name).split()
    b = set(brand_tokens(brand))
    s = set((canonical_size(size) or "").replace("x", " x ").split())
    s.discard("x")
    return [t for t in n if t not in b and t not in s]


def brands_compatible(brand_a: str, brand_b: str) -> bool:
    a = normalize_text(brand_a)
    b = normalize_text(brand_b)
    if not a or not b:
        return True
    if a == b:
        return True
    # Store-brand vs store-brand (e.g. Woolworths vs Coles own label).
    return a in STORE_BRANDS and b in STORE_BRANDS


def name_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    a = sorted(t for t in tokens_a if t not in GENERIC_TOKENS)
    b = sorted(t for t in tokens_b if t not in GENERIC_TOKENS)
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rebuild_groups(
    conn: sqlite3.Connection,
    min_score: float = SCORE_DEFAULT,
) -> dict:
    """Recompute all product groups from the current snapshot."""
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

    def merge_into(target: int, members: list[tuple[str, str]]) -> None:
        for m in members:
            old = group_of.get(m)
            if old is not None and old != target:
                for mem in groups[old]["members"]:
                    group_of[mem] = target
                groups[target]["members"].extend(groups[old]["members"])
                groups[old]["members"] = []
            elif old is None:
                group_of[m] = target
                groups[target]["members"].append(m)
        groups[target]["members"] = _dedupe(groups[target]["members"])

    def link(p: dict, q: dict) -> None:
        """Merge two products (and their existing groups) by name match."""
        pk = (p["store"], p["product_id"])
        qk = (q["store"], q["product_id"])
        pg = group_of.get(pk)
        qg = group_of.get(qk)
        if pg is None and qg is None:
            add_group(f"name:{pk[0]}:{pk[1]}", "name", [pk, qk])
            return
        if pg is not None and qg is None:
            merge_into(pg, [qk])
            return
        if pg is None and qg is not None:
            merge_into(qg, [pk])
            return
        # Both already grouped (single-store GTIN groups): union them.
        if pg == qg:
            return
        members = _dedupe(groups[pg]["members"] + groups[qg]["members"])
        method = "gtin+name" if (
            groups[pg]["method"] == "gtin" and groups[qg]["method"] == "gtin"
        ) else "name"
        groups[pg]["members"] = members
        groups[pg]["method"] = method
        for m in members:
            group_of[m] = pg
        groups[qg]["members"] = []

    # ---- Pass 1: GTIN -----------------------------------------------------
    by_barcode: dict[str, list[tuple[str, str]]] = {}
    for p in products:
        bc = normalize_barcode(p["barcode"])
        if bc:
            by_barcode.setdefault(bc, []).append((p["store"], p["product_id"]))
    for bc, members in by_barcode.items():
        add_group(f"gtin:{bc}", "gtin", _dedupe(members))

    # ---- Pass 2: name + brand + size --------------------------------------
    ww = [p for p in products if p["store"] == "Woolworths"]
    co = [p for p in products if p["store"] == "Coles"]

    # Precompute tokens once.
    for p in products:
        p["_tokens"] = name_tokens(p["name"], p["brand"], p["size"])
        p["_size"] = canonical_size(p["size"])
        p["_brand"] = normalize_text(p["brand"])

    coles_open = list(co)

    for p in ww:
        if not _eligible(p, group_of, groups):
            continue
        best: tuple[float, dict | None] = (0.0, None)
        for q in coles_open:
            if not _eligible(q, group_of, groups):
                continue
            if p["_size"] != q["_size"]:
                continue
            if not brands_compatible(p["brand"], q["brand"]):
                continue
            score = name_similarity(p["_tokens"], q["_tokens"])
            if score > best[0]:
                best = (score, q)
        score, q = best
        if q is not None and score >= min_score:
            link(p, q)

    # ---- Pass 3: singles ----------------------------------------------------
    for p in products:
        m = (p["store"], p["product_id"])
        if m not in group_of:
            add_group(f"single:{p['store']}:{p['product_id']}", "single", [m])

    _write_groups(conn, groups)
    return _report(conn, groups)


def _eligible(
    p: dict,
    group_of: dict[tuple[str, str], int],
    groups: list[dict],
) -> bool:
    """A product can still gain a cross-store partner when it has no group,
    or its current group only contains one store."""
    gid = group_of.get((p["store"], p["product_id"]))
    if gid is None:
        return True
    return len({m[0] for m in groups[gid]["members"]}) == 1


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
                continue  # group was merged away
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
    by_method = {"gtin": 0, "name": 0, "single": 0}
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
