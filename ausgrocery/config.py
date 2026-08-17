"""Defaults for the crawler. Override on the CLI."""

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
