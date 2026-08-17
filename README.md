# Aus Grocery Data

Data pipeline for a grocery comparison app (price, ingredients, allergens,
nutrition, dietary tags) covering Coles and Woolworths, with an optional
Open Food Facts fallback for missing fields.

中文说明见 [README.zh-CN.md](README.zh-CN.md).

The output shape follows a supermarket product-comparison detail view: name,
large image, both-store prices, ingredients, allergen statement, nutrition
table, dietary/lifestyle tags, storage and usage instructions, country of
origin.

## Features

- Woolworths: full-category crawl via the public browse API (cookie priming +
  `POST /apis/ui/browse/category`, page size 36). Verified working.
- Coles: product detail via the server-rendered `__NEXT_DATA__` JSON;
  category listing via the Next.js `/_next/data/{buildId}/.../browse.json`
  endpoint when reachable. Detail parse verified; listing follows the
  approach used by the Go project below and needs a live IP that is not
  flagged by Incapsula.
- Open Food Facts: barcode lookup used only to fill missing allergens /
  dietary tags / nutrition (source is recorded separately).
- SQLite storage: `products` (current snapshot), `price_history`
  (daily price points), `crawl_log`.
- Polite crawling: request delay, retries with backoff, persistent cookie
  jar, bot-challenge detection ("Pardon Our Interruption", Incapsula).
- Daily refresh: designed for one run per day (see `docs/DEPLOYMENT.md`).

## Quick start

```powershell
python -m ausgrocery init-db --db data/grocery.db

# Woolworths: one department, first pages
python -m ausgrocery ww-crawl --category-id 1_6E4F4E4 --url dairy-eggs-fridge --max-pages 2

# Coles: one product detail
python -m ausgrocery coles-product --slug lipton-ice-tea-sugar-free-ice-tea-lemon-iced-tea-bottle-1.5l-5171521

# Open Food Facts fallback by barcode
python -m ausgrocery off --barcode 9300633556150

# Ad-hoc probe (same output as the earlier experiment)
python -m ausgrocery probe ww "Lipton Ice Tea No Sugar Lemon"
python -m ausgrocery probe coles lipton-ice-tea-sugar-free-ice-tea-lemon-iced-tea-bottle-1.5l-5171521
```

Results are written to `data/*.json` (probe) and `data/grocery.db`
(crawl commands). See `docs/FIELD_MAPPING.md` for the exact field mapping
and `docs/DATA_SOURCES.md` for the licensing/compliance notes.

## Notes on behaviour

- Coles (Imperva/Incapsula) can return a "Pardon Our Interruption" challenge
  from an IP after a handful of requests. The client retries with backoff and
  reports the challenge instead of guessing. Re-running later, or from a
  residential/home IP that has not been flagged, usually works (verified:
  the same product page parsed correctly before the flag).
- Woolworths (Akamai) is stricter with raw POSTs from datacentre IPs; the
  client first GETs a browse page to prime the cookie jar, which matched the
  behaviour of the reference project and worked from this machine.
- Prices and product data change; every row stores `fetched_at`, and every
  crawl appends to `price_history`.

## Reference projects

This project is an independent implementation. The crawling techniques were
informed by:

- [tjhowse/aus_grocery_price_database](https://github.com/tjhowse/aus_grocery_price_database)
  (GPL-3.0) - category worker architecture, cookie priming for Woolworths,
  Coles `_next/data` listing endpoint.
- [tjhowse/python-woolworths](https://github.com/tjhowse/python-woolworths)
  (no licence) - Woolworths UI API endpoint inventory.
- [abhinav-pandey29/coles-scraper](https://github.com/abhinav-pandey29/coles-scraper)
  (no licence) - cookie-interception retry pattern for Coles.
- [nguyentansinh123/Scraping-Coles-Woolworths-IGA](https://github.com/nguyentansinh123/Scraping-Coles-Woolworths-IGA)
  (no licence) - proof that a real browser session is the reliable fallback
  for Coles.

No code was copied from GPL-3.0 or unlicensed projects; the interfaces and
techniques are re-implemented here. See `docs/DATA_SOURCES.md`.

## Project layout

```text
aus-grocery-data/
  ausgrocery/          main package (http, stores, storage, cli)
  docs/                field mapping, data sources, deployment
  data/                git-ignored output (json probes + sqlite db)
  tests/               smoke tests (no network)
```
