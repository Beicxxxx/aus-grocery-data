"""Command line interface.

Run from the project root:
    python -m ausgrocery <command> ...
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import config
from .coles import Coles
from .http import HttpError
from .matching import rebuild_groups
from .merge import build_merged
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
            ids = [str(t.get("id")) for t in page_products if t.get("id")]
            for p in c.batch_products(ids):
                try:
                    row = c.normalize(p)
                except Exception as e:
                    print(f"  normalize failed {p.get('id')}: {e}", file=sys.stderr)
                    continue
                upsert_product(db, row)
                count += 1
            print(f"  page ok, cumulative {count}")
        log_crawl(db, started, "Coles", args.category, "ok", f"{count} products")
        print(f"done: {count} products")
    except (HttpError, RuntimeError) as e:
        log_crawl(db, started, "Coles", args.category, "failed", str(e))
        print(f"crawl failed: {e}", file=sys.stderr)
        return 1
    finally:
        c.close_browser()
    return 0


FOOD_EXCLUDE = {
    # Coles
    "cleaning-laundry", "health-beauty", "baby", "pet", "home-garden",
    "tobacco", "liquorland", "bonus-entry-products", "down-down",
    # Woolworths (best-effort)
    "household", "health-wellness", "personal-care", "baby", "pet",
    "liquor", "tobacco", "back-to-school", "garden", "home",
}


def _is_food(cat: dict) -> bool:
    text = f"{cat.get('name', '')} {cat.get('url', '')}".lower()
    if any(k in text for k in FOOD_EXCLUDE):
        return False
    food_markers = (
        "fruit", "veget", "meat", "seafood", "dairy", "egg", "fridge",
        "bakery", "deli", "pantry", "drink", "frozen", "freezer", "chip", "snack",
        "health food", "wellness", "lunch", "world food", "dietary",
        "international", "chocolate", "confectionery", "biscuit", "breakfast", "coffee",
        "tea", "sauce", "pasta", "rice", "cooking", "baby food",
    )
    return any(k in text for k in food_markers)


def cmd_food_all(args) -> int:
    """Crawl all food & drink departments at both stores, then match."""
    db = init_db(args.db)
    started = now()
    total = {"Woolworths": 0, "Coles": 0}

    # ---- Woolworths --------------------------------------------------------
    if args.store in ("ww", "both"):
        ww = Woolworths()
        try:
            cats = ww.list_categories()
        except Exception as e:
            print(f"Woolworths category discovery failed: {e}", file=sys.stderr)
            cats = [{"id": c["id"], "name": c["name"], "url": c["url"]}
                    for c in config.EXAMPLE_DEPARTMENTS]
        ww_cats = [c for c in cats if _is_food(c)]
        print(f"Woolworths food departments: {[c.get('url') or c.get('name') for c in ww_cats]}")
        for cat in ww_cats:
            url_path = cat.get("url") or cat.get("id")
            scope = f"{cat.get('id')}:{url_path}"
            try:
                for page_products in ww.crawl_category_all(cat["id"], url_path):
                    for p in page_products:
                        try:
                            row = ww.normalize(p)
                            if not row.get("price"):
                                continue
                            upsert_product(db, row)
                            total["Woolworths"] += 1
                        except Exception as e:
                            print(f"  skip {cat.get('name')}: {e}", file=sys.stderr)
                    print(f"  WW {cat.get('name')}: cumulative {total['Woolworths']}")
            except HttpError as e:
                log_crawl(db, started, "Woolworths", scope, "failed", str(e))
                print(f"  WW department failed {cat.get('name')}: {e}", file=sys.stderr)

    # ---- Coles -------------------------------------------------------------
    if args.store in ("coles", "both"):
        c = Coles()
        try:
            co_cats = [x for x in c.list_categories() if _is_food(x)]
        except Exception as e:
            print(f"Coles category discovery failed: {e}", file=sys.stderr)
            co_cats = [{"id": x, "name": x, "url": x} for x in config.COLES_EXAMPLE_CATEGORIES]
        print(f"Coles food departments: {[x.get('id') for x in co_cats]}")
        for cat in co_cats:
            slug = cat.get("id") or cat.get("url")
            scope = slug
            try:
                for page_products in c.crawl_category_all(slug):
                    ids = [str(t.get("id")) for t in page_products if t.get("id")]
                    for p in c.batch_products(ids):
                        try:
                            row = c.normalize(p)
                            upsert_product(db, row)
                            total["Coles"] += 1
                        except Exception as e:
                            print(f"  skip {cat.get('name')}: {e}", file=sys.stderr)
                    print(f"  Coles {cat.get('name')}: cumulative {total['Coles']}")
            except HttpError as e:
                log_crawl(db, started, "Coles", scope, "failed", str(e))
                print(f"  Coles department failed {cat.get('name')}: {e}", file=sys.stderr)
            finally:
                c.close_browser()

    log_crawl(db, started, "both", "food-all",
              "ok" if any(total.values()) else "failed",
              f"WW={total['Woolworths']} Coles={total['Coles']}")
    print(f"done: Woolworths={total['Woolworths']} Coles={total['Coles']}")

    # ---- match -------------------------------------------------------------
    if not args.no_match:
        report = rebuild_groups(db)
        print(f"match: {report['cross_store_groups']} cross-store groups "
              f"(of {report['total_groups']})")
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
    """Fill missing allergens/dietary/nutrition for rows with a barcode.

    With ``--cross-only`` only barcodes that appear in both stores (i.e. the
    cross-store comparison groups) are queried, which keeps the API load
    proportional to the previewed data instead of the whole catalogue.
    """
    db = init_db(args.db)
    if args.cross_only:
        rows = db.execute(
            """
            SELECT p.store, p.product_id, p.barcode
            FROM products p
            JOIN product_group_members m ON m.store = p.store
                AND m.product_id = p.product_id
            JOIN product_groups g ON g.group_id = m.group_id
            WHERE p.barcode IS NOT NULL AND p.barcode != ''
              AND p.off_json IS NULL
              AND g.group_id IN (
                  SELECT group_id FROM product_group_members
                  GROUP BY group_id HAVING COUNT(DISTINCT store) = 2
              )
            """
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT store, product_id, barcode FROM products "
            "WHERE barcode IS NOT NULL AND barcode != '' "
            "AND (ingredients IS NULL OR allergens IS NULL)"
        ).fetchall()
    updated = 0
    missed = 0
    # Group rows by barcode so each barcode is queried once.
    by_barcode: dict[str, list[tuple[str, str]]] = {}
    for store, pid, barcode in rows:
        by_barcode.setdefault(barcode, []).append((store, pid))

    barcodes = list(by_barcode)
    workers = max(1, min(8, args.threads))
    off_results: dict[str, dict | None] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(OpenFoodFacts().by_barcode, b): b
            for b in barcodes
        }
        done = 0
        for future in as_completed(future_map):
            b = future_map[future]
            off_results[b] = future.result()
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(barcodes)} barcodes queried")

    for barcode, targets in by_barcode.items():
        off_row = off_results.get(barcode)
        if not off_row:
            missed += 1
            continue
        for store, pid in targets:
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
        if updated % 100 == 0:
            print(f"  {updated} backfilled (missed {missed})")
    print(f"done: {updated} products backfilled, "
          f"{missed} barcodes not found on OFF")
    return 0


def cmd_match(args) -> int:
    db = init_db(args.db)
    report = rebuild_groups(db)
    print("== 跨店商品匹配报告 ==")
    print(f"商品组总数: {report['total_groups']}")
    print(f"跨店匹配组: {report['cross_store_groups']}")
    print(f"匹配方式: {report['by_method']}")
    print()
    print("== 示例 ==")
    for ex in report["examples"]:
        print(f"  [{ex['method']}] {ex['ww']}  <->  {ex['coles']}")
    return 0


def cmd_merge(args) -> int:
    db = init_db(args.db)
    report = build_merged(db, check_white=args.check_white,
                          verify_images=args.verify_images)
    print("== 三源合并表 ==")
    print(f"合并行数: {report['merged_rows']}")
    print(f"含 Woolworths: {report['with_ww']}")
    print(f"含 Coles: {report['with_coles']}")
    print(f"含 Open Food Facts: {report['with_off']}")
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
    sp.add_argument("--cross-only", action="store_true",
                    help="only backfill barcodes in cross-store groups")
    sp.add_argument("--threads", type=int, default=4,
                    help="parallel OFF lookups (default 4)")
    sp.set_defaults(func=cmd_backfill_off)

    sp = sub.add_parser("match", parents=[common],
                        help="rebuild cross-store product groups (GTIN only)")
    sp.set_defaults(func=cmd_match)

    sp = sub.add_parser("merge", parents=[common],
                        help="build merged product details (WW + Coles + OFF union)")
    sp.add_argument("--check-white", action="store_true",
                    help="verify the chosen image has a white background "
                         "(downloads images; requires Pillow)")
    sp.add_argument("--verify-images", action="store_true",
                    help="verify the chosen image URL actually returns an image, "
                         "falling back to the next candidate")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("food-all", parents=[common],
                        help="crawl all food & drink departments at both stores")
    sp.add_argument("--store", choices=["both", "ww", "coles"], default="both",
                    help="which store(s) to crawl (default both)")
    sp.add_argument("--no-match", action="store_true",
                    help="skip the cross-store matching step")
    sp.set_defaults(func=cmd_food_all)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
