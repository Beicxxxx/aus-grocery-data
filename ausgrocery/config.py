"""Defaults for the crawler. Override on the CLI."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB = DATA_DIR / "grocery.db"

UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
UA_FIREFOX = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) "
    "Gecko/20100101 Firefox/127.0"
)

REQUEST_DELAY_SECONDS = 1.5
RETRIES = 3
REQUEST_TIMEOUT = 30

WWS_PAGE_SIZE = 36      # browse/category page size used by the reference project
WWS_SEARCH_PAGE_SIZE = 24
COLES_PRODUCTS_PER_PAGE = 48

# Coles BFF (backend-for-frontend) API. The website ships this subscription
# key in its public runtime config; requests carry it in the
# ``ocp-apim-subscription-key`` header and bypass the Incapsula HTML layer.
# Override with the COLES_SUBSCRIPTION_KEY env var if Coles rotates it.
COLES_SUBSCRIPTION_KEY = os.environ.get(
    "COLES_SUBSCRIPTION_KEY", "eae83861d1cd4de6bb9cd8a2cd6f041e"
)
COLES_GRAPHQL_URL = "https://www.coles.com.au/api/graphql"
COLES_STORE_ID = "COL:0584"
COLES_SHOPPING_METHOD = "DELIVERY"
COLES_BUILD_ID_FILE = DATA_DIR / "coles_build_id.txt"
# Last known-good Next.js buildId, verified against the live site. Used as a
# bootstrap when the local cache is empty; refreshed automatically when stale.
COLES_DEFAULT_BUILD_ID = "20260812.2-bb7ba0d5c9ea46ad61a08d677a91d58d0e18ba03"

# Example categories (fallback when automatic category discovery fails).
EXAMPLE_DEPARTMENTS = [
    {"id": "1_6E4F4E4", "name": "Dairy, Eggs & Fridge",
     "url": "dairy-eggs-fridge"},
    {"id": "1_A2B3C4D5", "name": "Fruit & Vegetables",
     "url": "fruit-vegetables"},
]

COLES_EXAMPLE_CATEGORIES = [
    "dairy-eggs-fridge",
    "fruit-vegetables",
    "pantry",
]

OFF_API = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_FIELDS = (
    "code,product_name,brands,quantity,image_front_url,ingredients_text,"
    "allergens_tags,labels_tags,categories_tags,nutriments,countries_tags"
)
