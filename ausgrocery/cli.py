"""Command line interface.

Run from the project root:
    python -m ausgrocery <command> ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .coles import Coles
from .http import HttpError
from .openfoodfacts import OpenFoodFacts, merge_fallback
from .storage import init_db, log_crawl, now, upsert_product
from .woolworths import Woolworths


def _save_probe(payload: dict, name: str) -> Path:
    out = config.DATA_DIR / name
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def cmd_probe(args) -> int:
    if args.target == "ww":
        ww = Woolworths()
        items = ww.search(args.term)
        pick = next((p for p in items if p.get("Price")), items[0] if items else None)
        if not pick:
            print("no products found")
            return 1
        out = ww.normalize(pick)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print("saved:", _save_probe(out, f"woolworths_{pick['Stockcode']}.json"))
    elif args.target == "coles":
        c = Coles()
        try:
            out = c.normalize(c.product(args.slug))
            print(json.dumps(out, ensure_ascii=False, indent=2))
            print("saved:", _save_probe(out, f"coles_{args.slug}.json"))
        finally:
            c.close_browser()
    else:
        print("unknown probe target", args.target)
        return 2
    return 0


def cmd_init_db(args) -> int:
    init_db(args.db)
    print(f"initialized {args.db}")
    return 0


def cmd_ww_crawl(args) -> int:
    db = init_db(args.db)
    ww = Woolworths()
    started = now()
    scope = f"{args.category_id}:{args.url}"
    count = 0
    try:
        for page_products in ww.crawl_category_all(
            args.category_id, args.url, args.max_pages
        ):
            for p in page_products:
                try:
                    row = ww.normalize(p)
                    if not row.get("price"):
                        continue  # zero-price rows are placeholders
                    upsert_product(db, row)
                    count += 1
                except Exception as e:
                    print(f"  skip bad product: {e}", file=sys.stderr)
            print(f"  page ok, cumulative {count}")
        log_crawl(db, started, "Woolworths", scope, "ok", f"{count} products")
        print(f"done: {count} products")
    except HttpError as e:
        log_crawl(db, started, "Woolworths", scope, "failed", str(e))
        print(f"crawl failed: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_ww_crawl_all(args) -> int:
    db = init_db(args.db)
    ww = Woolworths()
    started = now()
    try:
        cats = ww.list_categories()
    except Exception as e:
        print(f"category discovery failed ({e}); using example list", file=sys.stderr)
        cats = [{"id": c["id"], "name": c["name"], "url": c["url"]}
                for c in config.EXAMPLE_DEPARTMENTS]
    if not cats:
        cats = [{"id": c["id"], "name": c["name"], "url": c["url"]}
                for c in config.EXAMPLE_DEPARTMENTS]
    total = 0
    for cat in cats:
        url_path = cat.get("url") or cat.get("id")
        try:
            for page_products in ww.crawl_category_all(cat["id"], url_path):
                for p in page_products:
                    row = ww.normalize(p)
                    if row.get("price"):
                        upsert_product(db, row)
                        total += 1
            print(f"department ok: {cat.get('name')} ({url_path})")
        except HttpError as e:
            print(f"department failed: {cat.get('name')}: {e}", file=sys.stderr)
    log_crawl(db, started, "Woolworths", "all-categories",
              "partial" if total else "failed", f"{total} products")
    print(f"done: {total} products")
    return 0


def cmd_coles_crawl(args) -> int:
    db = init_db(args.db)
    c = Coles()
    started = now()
    count = 0
    try:
        for page_products in c.crawl_category_all(args.category, args.max_pages):
            for tile in page_products:
                slug = (tile.get("url") or "").rsplit("/", 1)[-1]
                if not slug:
                    continue
                try:
                    row = c.normalize(c.product(slug))
                except HttpError as e:
                    print(f"  detail failed {slug}: {e}", file=sys.stderr)
                    continue
                upsert_product(db, row)
                count += 1
            print(f"  page ok, cumulative {count}")
        log_crawl(db, started, "Coles", args.category, "ok", f"{count} products")
        print(f"done: {count} products")
    except HttpError as e:
        log_crawl(db, started, "Coles", args.category, "failed", str(e))
        print(f"crawl failed: {e}", file=sys.stderr)
        return 1
    finally:
        c.close_browser()
    return 0


def cmd_coles_product(args) -> int:
    db = init_db(args.db)
    c = Coles()
    try:
        row = c.normalize(c.product(args.slug))
        upsert_product(db, row)
        print(json.dumps(row, ensure_ascii=False, indent=2))
    finally:
        c.close_browser()
    return 0


def cmd_off(args) -> int:
    db = init_db(args.db)
    off = OpenFoodFacts()
    result = off.by_barcode(args.barcode)
    if not result:
        print(f"barcode {args.barcode}: not found")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_backfill_off(args) -> int:
    """Fill missing allergens/dietary/nutrition for rows with a barcode."""
    db = init_db(args.db)
    off = OpenFoodFacts()
    rows = db.execute(
        "SELECT store, product_id, barcode FROM products "
        "WHERE barcode IS NOT NULL AND barcode != '' "
        "AND (ingredients IS NULL OR allergens IS NULL)"
    ).fetchall()
    updated = 0
    for store, pid, barcode in rows:
        off_row = off.by_barcode(barcode)
        if not off_row:
            continue
        cur = db.execute(
            "SELECT raw_json, off_json FROM products WHERE store=? AND product_id=?",
            (store, pid),
        ).fetchone()
        primary = json.loads(cur[0]) if cur else {}
        # Rebuild a normalized row so missing fields can be patched.
        if store == "Woolworths":
            row = Woolworths().normalize(primary)
        else:
            row = Coles().normalize(primary)
        merge_fallback(row, off_row)
        upsert_product(db, row, off_row=off_row)
        updated += 1
        print(f"  backfilled {store} {pid} ({barcode})")
    print(f"done: {updated} products backfilled")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ausgrocery")
    p.add_argument("--db", default=str(config.DEFAULT_DB))
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(config.DEFAULT_DB))
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("probe", parents=[common], help="ad-hoc single-product check")
    sp.add_argument("target", choices=["ww", "coles"])
    sp.add_argument("term", nargs="?")
    sp.add_argument("slug", nargs="?")
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("init-db", parents=[common], help="create the SQLite schema")
    sp.set_defaults(func=cmd_init_db)

    sp = sub.add_parser("ww-crawl", parents=[common], help="crawl one Woolworths category")
    sp.add_argument("--category-id", required=True)
    sp.add_argument("--url", required=True, help="browse url segment")
    sp.add_argument("--max-pages", type=int, default=10_000)
    sp.set_defaults(func=cmd_ww_crawl)

    sp = sub.add_parser("ww-crawl-all", parents=[common], help="crawl all Woolworths categories")
    sp.add_argument("--max-pages", type=int, default=10_000)
    sp.set_defaults(func=cmd_ww_crawl_all)

    sp = sub.add_parser("coles-crawl", parents=[common], help="crawl one Coles category + details")
    sp.add_argument("--category", required=True)
    sp.add_argument("--max-pages", type=int, default=10_000)
    sp.set_defaults(func=cmd_coles_crawl)

    sp = sub.add_parser("coles-product", parents=[common], help="fetch one Coles product")
    sp.add_argument("--slug", required=True)
    sp.set_defaults(func=cmd_coles_product)

    sp = sub.add_parser("off", parents=[common], help="look up one barcode on Open Food Facts")
    sp.add_argument("--barcode", required=True)
    sp.set_defaults(func=cmd_off)

    sp = sub.add_parser("backfill-off", parents=[common], help="backfill missing fields via barcode")
    sp.set_defaults(func=cmd_backfill_off)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
