import sqlite3

db = sqlite3.connect(r"F:\Courses\FIT5120\aus-grocery-data\data\grocery.db")
print("rows with off_json:", db.execute(
    "SELECT COUNT(*) FROM products WHERE off_json IS NOT NULL"
).fetchone()[0])
print("total rows:", db.execute("SELECT COUNT(*) FROM products").fetchone()[0])
print()
print("off_json sample:")
for r in db.execute(
    "SELECT store, product_id, name, barcode, off_json FROM products "
    "WHERE off_json IS NOT NULL LIMIT 3"
):
    print(" ", r[0], r[1], r[2], r[3])
    print("   ", (r[4] or "")[:300])
