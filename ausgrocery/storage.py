"""SQLite storage: current product snapshot + price history + crawl log."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    store            TEXT NOT NULL,
    product_id       TEXT NOT NULL,
    name             TEXT,
    brand            TEXT,
    size             TEXT,
    price_cents      INTEGER,
    was_price_cents  INTEGER,
    unit_price       TEXT,
    image_url        TEXT,
    url              TEXT,
    barcode          TEXT,
    ingredients      TEXT,
    allergens        TEXT,
    allergen_statement TEXT,
    allergen_claims  TEXT,
    dietary          TEXT,
    health_star      TEXT,
    storage          TEXT,
    usage            TEXT,
    origin           TEXT,
    description      TEXT,
    nutrition_json   TEXT,
    off_json         TEXT,
    fetched_at       TEXT,
    raw_json         TEXT,
    PRIMARY KEY (store, product_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    store       TEXT NOT NULL,
    product_id  TEXT NOT NULL,
    price_cents INTEGER,
    fetched_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_product
    ON price_history (store, product_id, fetched_at);

CREATE TABLE IF NOT EXISTS crawl_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    store TEXT,
    scope TEXT,
    status TEXT,
    message TEXT
);
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _cents(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _json(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _list(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(x) for x in value)
    return str(value)


def upsert_product(conn: sqlite3.Connection, row: dict, off_row: dict | None = None) -> None:
    store, pid = row["store"], row["product_id"]
    cur = conn.execute(
        "SELECT price_cents FROM products WHERE store=? AND product_id=?",
        (store, pid),
    )
    prev = cur.fetchone()
    prev_price = prev[0] if prev else None

    price = _cents(row.get("price"))
    conn.execute(
        """
        INSERT INTO products (
            store, product_id, name, brand, size, price_cents, was_price_cents,
            unit_price, image_url, url, barcode, ingredients, allergens,
            allergen_statement, allergen_claims, dietary, health_star, storage,
            usage, origin, description, nutrition_json, off_json, fetched_at,
            raw_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(store, product_id) DO UPDATE SET
            name=excluded.name, brand=excluded.brand, size=excluded.size,
            price_cents=excluded.price_cents,
            was_price_cents=excluded.was_price_cents,
            unit_price=excluded.unit_price, image_url=excluded.image_url,
            url=excluded.url, barcode=excluded.barcode,
            ingredients=excluded.ingredients, allergens=excluded.allergens,
            allergen_statement=excluded.allergen_statement,
            allergen_claims=excluded.allergen_claims,
            dietary=excluded.dietary, health_star=excluded.health_star,
            storage=excluded.storage, usage=excluded.usage,
            origin=excluded.origin, description=excluded.description,
            nutrition_json=excluded.nutrition_json,
            off_json=CASE WHEN excluded.off_json IS NOT NULL
                          THEN excluded.off_json ELSE products.off_json END,
            fetched_at=excluded.fetched_at, raw_json=excluded.raw_json
        """,
        (
            store, pid, row.get("name"), row.get("brand"), row.get("size"),
            price, _cents(row.get("was_price")), row.get("unit_price"),
            row.get("image_url"), row.get("url"), row.get("barcode"),
            row.get("ingredients"), _list(row.get("allergens")),
            _list(row.get("allergen_statement")), _list(row.get("allergen_claims")),
            _list(row.get("dietary")), row.get("health_star"),
            row.get("storage"), row.get("usage"), row.get("origin"),
            row.get("description"), _json(row.get("nutrition")),
            _json(off_row), row.get("fetched_at"), _json(row.get("raw")),
        ),
    )
    if prev_price != price:
        conn.execute(
            "INSERT INTO price_history (store, product_id, price_cents, fetched_at)"
            " VALUES (?,?,?,?)",
            (store, pid, price, row.get("fetched_at")),
        )
    conn.commit()


def log_crawl(conn: sqlite3.Connection, started_at: str, store: str,
              scope: str, status: str, message: str = "") -> None:
    conn.execute(
        "INSERT INTO crawl_log (started_at, store, scope, status, message)"
        " VALUES (?,?,?,?,?)",
        (started_at, store, scope, status, message),
    )
    conn.commit()


def now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
