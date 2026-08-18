"""No-network smoke tests for normalization and storage."""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ausgrocery.coles import Coles, extract_product_id, parse_coles_nutrition
from ausgrocery.coles_queries import GRAPHQL_QUERIES
from ausgrocery.matching import (
    canonical_size,
    normalize_barcode,
    normalize_text,
    rebuild_groups,
)
from ausgrocery.merge import build_merged, pick_image
from ausgrocery.storage import init_db, upsert_product
from ausgrocery.woolworths import Woolworths, parse_ww_nutrition


COLES_RAW = {
    "id": 5171521,
    "name": "Ice Tea Sugar Free Ice Tea Lemon Iced Tea Bottle",
    "brand": "Lipton",
    "size": "1.5L",
    "gtin": "9300633000004",
    "pricing": {"now": 5.5, "was": None, "comparable": "$3.67/ 1L"},
    "images": [{"zoom": {"path": "/wcsstore/Coles-CAS/images/5/1/7/5171521-zm.jpg"}}],
    "additionalInfo": [
        {"title": "Ingredients", "description": "Water, Black Tea Extract (4%)."},
        {"title": "Storage instructions", "description": "Store in a cool, dry place."},
        {"title": "Usage instructions", "description": "Refrigerate after opening."},
    ],
    "countryOfOrigin": {"country": "Australia"},
    "longDescription": "Our favourite ice tea...",
    "lifestyle": None,
    "nutrition": {
        "servingsPerPackage": "6.00",
        "servingSize": "250ml",
        "breakdown": [
            {"title": "Per Serving", "nutrients": [
                {"nutrient": "Energy", "value": "10 kJ"},
                {"nutrient": "Sodium", "value": "18 mg"}]},
            {"title": "Per 100g/ml", "nutrients": [
                {"nutrient": "Energy", "value": "4 kJ"},
                {"nutrient": "Sodium", "value": "7 mg"}]},
        ],
    },
}


class TestWoolworths(unittest.TestCase):
    def test_normalize(self):
        ww = Woolworths()
        raw = {
            "Stockcode": 221228,
            "DisplayName": "Lipton Ice Tea No Sugar Lemon Flavour Iced Tea 1.5L",
            "Price": 2.75,
            "WasPrice": 5.5,
            "CupString": "$1.83 / 1L",
            "LargeImageFile": "https://cdn0.woolworths.media/x.jpg",
            "Barcode": "9358155000125",
            "AdditionalAttributes": {
                "ingredients": "Water, tea extract (4%).",
                "allergencontains": "",
                "allergystatement": "Dairy Free,Egg Free",
                "lifestyleanddietarystatement": "Kosher,Vegan",
                "nutritionalinformation": '{"Attributes": ['
                    '{"Name": "Energy kJ Quantity Per 100g - Total - NIP", "Value": "4.0kJ"},'
                    '{"Name": "Energy kJ Quantity Per Serve - Total - NIP", "Value": "10.0kJ"}]}',
            },
        }
        row = ww.normalize(raw)
        self.assertEqual(row["name"], raw["DisplayName"])
        self.assertEqual(row["price"], 2.75)
        self.assertEqual(row["allergen_claims"], ["Dairy Free", "Egg Free"])
        self.assertEqual(row["dietary"], ["Kosher", "Vegan"])
        self.assertEqual(row["nutrition"]["Energy kJ"], {"100g": "4.0kJ", "Serve": "10.0kJ"})

    def test_nutrition_parser(self):
        rows = parse_ww_nutrition('{"Attributes": ['
            '{"Name": "Sodium Quantity Per 100g - Total - NIP", "Value": "7.0mg"},'
            '{"Name": "Sodium Quantity Per Serve - Total - NIP", "Value": "18.0mg"}]}')
        self.assertEqual(rows, {"Sodium": {"100g": "7.0mg", "Serve": "18.0mg"}})
        self.assertIsNone(parse_ww_nutrition(None))


class TestColes(unittest.TestCase):
    def test_extract_product_id(self):
        self.assertEqual(
            extract_product_id(
                "lipton-ice-tea-sugar-free-ice-tea-lemon-iced-tea-bottle-1.5l-5171521"
            ),
            "5171521",
        )
        self.assertIsNone(extract_product_id("no-id-here"))

    def test_graphql_queries_present(self):
        for op in ("GetProductDetails", "GetShopProductsMenu"):
            self.assertIn(op, GRAPHQL_QUERIES)
            self.assertIn(f"query {op}", GRAPHQL_QUERIES[op])
        self.assertIn(
            "productVariationsFields",
            GRAPHQL_QUERIES["GetProductDetails"],
        )

    def test_normalize_graphql_shape(self):
        raw = {
            "id": 5171521,
            "name": "Ice Tea Sugar Free Ice Tea Lemon Iced Tea Bottle",
            "brand": "Lipton",
            "size": "1.5L",
            "gtin": "9300633000004",
            "pricing": {"now": 5.5, "was": None, "comparable": "$3.67/ 1L"},
            "images": [{"zoom": {"path": "/wcsstore/Coles-CAS/images/5/1/7/5171521-zm.jpg"}}],
            "additionalInfo": [
                {"title": "Ingredients", "description": "Water, Black Tea Extract (4%)."},
                {"title": "Storage instructions", "description": "Store in a cool, dry place."},
            ],
            "countryOfOrigin": {"country": "Australia"},
            "longDescription": "Our favourite ice tea...",
            "lifestyle": ["Vegan"],
            "nutrition": {
                "servingsPerPackage": "6.00",
                "servingSize": "250ml",
                "breakdown": [
                    {"title": "Per Serving", "nutrients": [
                        {"nutrient": "Energy", "value": "10 kJ"}]},
                    {"title": "Per 100g/ml", "nutrients": [
                        {"nutrient": "Energy", "value": "4 kJ"}]},
                ],
            },
        }
        row = Coles().normalize(raw)
        self.assertEqual(row["product_id"], "5171521")
        self.assertEqual(row["price"], 5.5)
        self.assertEqual(row["ingredients"], "Water, Black Tea Extract (4%).")
        self.assertEqual(row["dietary"], ["Vegan"])
        self.assertEqual(
            row["nutrition"]["nutrients"]["Energy"],
            {"per_serving": "10 kJ", "per_100g": "4 kJ"},
        )


class TestMatching(unittest.TestCase):
    def _seed(self, conn, rows):
        for r in rows:
            conn.execute(
                "INSERT INTO products (store, product_id, name, brand, size, barcode)"
                " VALUES (?,?,?,?,?,?)",
                r,
            )
        conn.commit()

    def test_normalize(self):
        self.assertEqual(normalize_text("Yoghurt Lite!"), "yoghurt lite")
        self.assertEqual(normalize_text("café au lait"), "cafe au lait")
        self.assertIsNone(normalize_barcode(""))
        self.assertEqual(normalize_barcode(" 9300 6355 6150 "), "930063556150")
        self.assertIsNone(normalize_barcode("123"))
        self.assertEqual(canonical_size("1.5L"), "1.5 l")
        self.assertEqual(canonical_size("300mL x 12 pack"), "300 ml x 12 pack")

    def test_gtin_match(self):
        conn = init_db(":memory:")
        self._seed(conn, [
            ("Woolworths", "1", "Bega Stringers Cheese 160g", "Bega", "160g",
             "9310264910009"),
            ("Coles", "2", "Cheese Stringers Original 8 Pack", "Bega", "160g",
             "9310264910009"),
        ])
        report = rebuild_groups(conn)
        self.assertEqual(report["total_groups"], 1)
        self.assertEqual(report["cross_store_groups"], 1)
        self.assertEqual(report["by_method"]["gtin"], 1)

    def test_different_barcode_not_matched(self):
        conn = init_db(":memory:")
        self._seed(conn, [
            ("Woolworths", "1",
             "Sunny Queen 12 Extra Large Free Range Eggs 700g",
             "Sunny Queen", "700g", "1111111111111"),
            ("Coles", "2",
             "Free Range Extra Large Eggs 12 Pack",
             "Sunny Queen", "700g", "2222222222222"),
        ])
        report = rebuild_groups(conn)
        self.assertEqual(report["cross_store_groups"], 0)
        self.assertEqual(report["total_groups"], 2)

    def test_different_brand_not_matched(self):
        conn = init_db(":memory:")
        self._seed(conn, [
            ("Woolworths", "1", "Full Cream Milk 2L", "Dairy Farmers", "2L",
             "1111111111111"),
            ("Coles", "2", "Full Cream Milk 2L", "Pura", "2L",
             "2222222222222"),
        ])
        report = rebuild_groups(conn)
        self.assertEqual(report["cross_store_groups"], 0)
        self.assertEqual(report["total_groups"], 2)

    def test_different_size_not_matched(self):
        conn = init_db(":memory:")
        self._seed(conn, [
            ("Woolworths", "1", "Full Cream Milk 1L", "Pura", "1L",
             "1111111111111"),
            ("Coles", "2", "Full Cream Milk 2L", "Pura", "2L",
             "2222222222222"),
        ])
        report = rebuild_groups(conn)
        self.assertEqual(report["cross_store_groups"], 0)

    def test_store_brand_different_barcode_not_matched(self):
        conn = init_db(":memory:")
        self._seed(conn, [
            ("Woolworths", "1",
             "Woolworths Full Cream Long Life Milk UHT 1L",
             "Woolworths", "1L", "9300633386689"),
            ("Coles", "2", "Full Cream Long Life Milk",
             "Coles", "1L", "9300601325900"),
        ])
        report = rebuild_groups(conn)
        self.assertEqual(report["cross_store_groups"], 0)

    def test_rebuild_is_idempotent(self):
        conn = init_db(":memory:")
        self._seed(conn, [
            ("Woolworths", "1", "Bega Stringers Cheese 160g", "Bega", "160g",
             "9310264910009"),
            ("Coles", "2", "Cheese Stringers Original 8 Pack", "Bega", "160g",
             "9310264910009"),
        ])
        r1 = rebuild_groups(conn)
        r2 = rebuild_groups(conn)
        self.assertEqual(r1["total_groups"], r2["total_groups"])
        self.assertEqual(r1["cross_store_groups"], r2["cross_store_groups"])
        rows = conn.execute(
            "SELECT COUNT(*) FROM product_group_members"
        ).fetchone()[0]
        self.assertEqual(rows, 2)


class TestMerge(unittest.TestCase):
    def _seed_pair(self, conn, barcode="9310264910009"):
        # Two products with the same barcode, plus one with OFF fallback data.
        conn.execute(
            "INSERT INTO products (store, product_id, name, brand, size, "
            "price_cents, unit_price, image_url, barcode, ingredients, "
            "allergen_claims, dietary, storage, origin, nutrition_json)"
            " VALUES ('Woolworths','1','Bega Stringers Cheese','Bega','160g',"
            " 600, '$3.75/ 100g', 'https://cdn0.woolworths.media/x.jpg', ?,"
            " 'Milk, Salt', 'Gluten Free,Egg Free', 'Vegetarian', "
            " 'Keep refrigerated', 'Australia',"
            " '{\"nutrients\":{\"Energy\":{\"100g\":\"1200 kJ\"}}}')",
            (barcode,),
        )
        conn.execute(
            "INSERT INTO products (store, product_id, name, brand, size, "
            "price_cents, unit_price, image_url, barcode, ingredients, "
            "allergen_claims, dietary, storage, origin)"
            " VALUES ('Coles','2','Cheese Stringers Original 8 Pack','Bega','160g',"
            " 750, '$4.69/ 100g', 'https://www.coles.com.au/8/123.jpg', ?,"
            " NULL, 'Contains Milk', NULL, NULL, NULL)",
            (barcode,),
        )
        conn.execute(
            "INSERT INTO product_groups (group_id, match_key, method, created_at)"
            " VALUES (1, ?, 'gtin', '2026-01-01T00:00:00+00:00')",
            (f"gtin:{barcode}",),
        )
        conn.execute(
            "INSERT INTO product_group_members (group_id, store, product_id)"
            " VALUES (1,'Woolworths','1'), (1,'Coles','2')"
        )
        conn.commit()

    def test_union_fields(self):
        conn = init_db(":memory:")
        self._seed_pair(conn)
        # Attach OFF data to the WW row.
        conn.execute(
            "UPDATE products SET off_json=? WHERE store='Woolworths' AND product_id='1'",
            (
                '{"name":"Bega Stringers","image_url":"https://images.openfoodfacts.org/'
                'front_en.1.full.jpg","ingredients":"Milk, Salt, Culture",'
                '"allergens":["en:milk","en:gluten"],"dietary":["en:vegetarian",'
                '"en:vegan"],"categories":["en:snacks"],"countries":["en:australia"],'
                '"nutrition":{"energy":"1200 kJ"}}',
            ),
        )
        conn.commit()

        report = build_merged(conn)
        self.assertEqual(report["merged_rows"], 1)
        row = conn.execute("SELECT * FROM merged_products").fetchone()
        cols = [c[0] for c in conn.execute("SELECT * FROM merged_products LIMIT 0").description]
        m = dict(zip(cols, row))

        # Union of allergen claims: WW free claims + Coles contains + OFF tags.
        allergens = (m["allergens"] or "").split(",")
        self.assertIn("Contains Milk", allergens)
        self.assertIn("Gluten Free", allergens)
        self.assertIn("en:milk", allergens)
        self.assertIn("en:gluten", allergens)
        # Deduplicated: "en:vegetarian" should appear once.
        self.assertEqual(allergens.count("en:vegetarian"), 0)  # vegetarian is dietary
        dietary = (m["dietary"] or "").split(",")
        self.assertEqual(dietary.count("Vegetarian"), 1)
        # OFF tags are kept as-is (en:...); WW human labels as-is.
        self.assertIn("en:vegan", dietary)
        self.assertIn("en:vegan", dietary)

        # Ingredients: WW has a value, so it wins over OFF.
        self.assertEqual(m["ingredients"], "Milk, Salt")
        # Prices stay per-store.
        self.assertEqual(m["price_ww_cents"], 600)
        self.assertEqual(m["price_coles_cents"], 750)
        # OFF categories/countries unions.
        self.assertIn("en:snacks", m["categories"])
        self.assertIn("en:australia", m["countries"])

    def test_image_priority_ww_first_even_with_off(self):
        conn = init_db(":memory:")
        self._seed_pair(conn)
        conn.execute(
            "UPDATE products SET off_json=? WHERE store='Woolworths' AND product_id='1'",
            (
                '{"name":"Bega Stringers","image_url":"https://images.openfoodfacts.org/'
                'front_en.1.400.jpg"}',
            ),
        )
        conn.commit()
        report = build_merged(conn)
        self.assertEqual(report["merged_rows"], 1)
        row = conn.execute("SELECT image_url, image_source FROM merged_products").fetchone()
        # WW large wins over OFF front view.
        self.assertEqual(row[0], "https://cdn0.woolworths.media/x.jpg")
        self.assertEqual(row[1], "Woolworths")

    def test_image_priority_coles_over_off_when_no_ww(self):
        conn = init_db(":memory:")
        self._seed_pair(conn)
        conn.execute(
            "UPDATE products SET image_url=NULL WHERE store='Woolworths' AND product_id='1'"
        )
        conn.execute(
            "UPDATE products SET off_json=? WHERE store='Woolworths' AND product_id='1'",
            (
                '{"name":"Bega Stringers","image_url":"https://images.openfoodfacts.org/'
                'front_en.1.400.jpg"}',
            ),
        )
        conn.commit()
        report = build_merged(conn)
        self.assertEqual(report["merged_rows"], 1)
        row = conn.execute("SELECT image_url, image_source FROM merged_products").fetchone()
        self.assertEqual(row[0], "https://www.coles.com.au/8/123.jpg")
        self.assertEqual(row[1], "Coles")

    def test_off_image_as_last_resort(self):
        conn = init_db(":memory:")
        self._seed_pair(conn)
        conn.execute(
            "UPDATE products SET image_url=NULL WHERE store='Woolworths' AND product_id='1'"
        )
        conn.execute(
            "UPDATE products SET image_url=NULL WHERE store='Coles' AND product_id='2'"
        )
        conn.execute(
            "UPDATE products SET off_json=? WHERE store='Woolworths' AND product_id='1'",
            (
                '{"name":"Bega Stringers","image_url":"https://images.openfoodfacts.org/'
                'front_en.1.400.jpg"}',
            ),
        )
        conn.commit()
        report = build_merged(conn)
        self.assertEqual(report["merged_rows"], 1)
        row = conn.execute("SELECT image_url, image_source FROM merged_products").fetchone()
        self.assertEqual(row[0], "https://images.openfoodfacts.org/front_en.1.full.jpg")
        self.assertEqual(row[1], "OpenFoodFacts")

    def test_image_priority_without_off(self):
        conn = init_db(":memory:")
        self._seed_pair(conn)
        report = build_merged(conn)
        self.assertEqual(report["merged_rows"], 1)
        row = conn.execute("SELECT image_url, image_source FROM merged_products").fetchone()
        self.assertEqual(row[1], "Woolworths")
        self.assertEqual(row[0], "https://cdn0.woolworths.media/x.jpg")

    def test_pick_image_white_check(self):
        # Without OFF: WW large wins; with check_white and no Pillow it is kept.
        url, src = pick_image(
            "https://cdn0.woolworths.media/x.jpg",
            "https://www.coles.com.au/8/123.jpg",
            check_white=True,
        )
        self.assertEqual(src, "Woolworths")


class TestColes(unittest.TestCase):
    def test_normalize(self):
        row = Coles().normalize(COLES_RAW)
        self.assertEqual(row["name"], "Ice Tea Sugar Free Ice Tea Lemon Iced Tea Bottle")
        self.assertEqual(row["ingredients"], "Water, Black Tea Extract (4%).")
        self.assertEqual(row["storage"], "Store in a cool, dry place.")
        self.assertEqual(row["usage"], "Refrigerate after opening.")
        self.assertEqual(row["origin"], "Australia")
        self.assertEqual(row["nutrition"]["nutrients"]["Energy"], {
            "per_serving": "10 kJ", "per_100g": "4 kJ"})

    def test_nutrition_parser(self):
        n = parse_coles_nutrition(COLES_RAW["nutrition"])
        self.assertEqual(n["servings_per_package"], "6.00")
        self.assertEqual(n["nutrients"]["Sodium"], {
            "per_serving": "18 mg", "per_100g": "7 mg"})


class TestStorage(unittest.TestCase):
    def test_upsert_and_history(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = init_db(Path(tmp) / "g.db")
            row = {"store": "Woolworths", "product_id": "221228", "name": "Tea",
                   "price": 2.75, "was_price": 5.5,
                   "fetched_at": "2026-08-17T00:00:00+00:00",
                   "ingredients": "Water", "allergens": ["Milk"],
                   "nutrition": {"a": 1}, "raw": {"x": 1}}
            upsert_product(db, row)
            self.assertEqual(db.execute("select count(*) from products").fetchone()[0], 1)
            self.assertEqual(db.execute("select count(*) from price_history").fetchone()[0], 1)
            row2 = dict(row, price=2.90, fetched_at="2026-08-18T00:00:00+00:00")
            upsert_product(db, row2)
            self.assertEqual(db.execute("select price_cents from products").fetchone()[0], 290)
            self.assertEqual(db.execute("select count(*) from price_history").fetchone()[0], 2)
            db.close()


if __name__ == "__main__":
    unittest.main()
