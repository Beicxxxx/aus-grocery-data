"""No-network smoke tests for normalization and storage."""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ausgrocery.coles import Coles, extract_product_id, parse_coles_nutrition
from ausgrocery.coles_queries import GRAPHQL_QUERIES
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
