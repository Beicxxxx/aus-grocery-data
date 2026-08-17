# Deployment: daily refresh

The pipeline is designed for one run per day. Prices change daily; nutrition,
ingredients and allergens change rarely, so a full crawl can run daily without
concern while the DB keeps `fetched_at` and `price_history`.

## Windows Task Scheduler

1. Create a `.bat` (or call PowerShell directly):

```bat
@echo off
cd /d F:\Courses\FIT5120\aus-grocery-data
python -m ausgrocery ww-crawl-all --db data/grocery.db
python -m ausgrocery coles-crawl --category dairy-eggs-fridge --max-pages 5 --db data/grocery.db
python -m ausgrocery backfill-off --db data/grocery.db
```

2. In Task Scheduler: create a daily task, trigger at e.g. 04:30, action =
   `cmd /c F:\...\daily.bat`. Use the same account that ran the crawler once
   manually so the cookie jar is warm.

## Unix cron

```cron
30 4 * * * cd /srv/aus-grocery-data && python -m ausgrocery ww-crawl-all
```

## Operational notes

- First run primes `data/cookies_woolworths.txt` / `data/cookies_coles.txt`.
- Coles may challenge an IP after several requests. The client retries and
  logs; re-running later continues from the same database (upserts).
- `crawl_log` records each run's store, scope, status and message.
- Expected scale: Woolworths ~80-100k SKUs in ~3k pages; Coles ~50-60k
  products requiring one detail request each when full details are wanted.
  Start with a few categories for Iteration 1.
