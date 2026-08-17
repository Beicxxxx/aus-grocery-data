# 部署：每日刷新

管道按每天一轮设计。价格每天变化；营养、配料与过敏原变化缓慢，
每日全量抓取没有问题，数据库会保留 `fetched_at` 与 `price_history`。

## Windows 任务计划程序

1. 创建一个 `.bat`（或直接调用 PowerShell）：

```bat
@echo off
cd /d F:\Courses\FIT5120\aus-grocery-data
python -m ausgrocery ww-crawl-all --db data/grocery.db
python -m ausgrocery coles-crawl --category dairy-eggs-fridge --max-pages 5 --db data/grocery.db
python -m ausgrocery backfill-off --db data/grocery.db
```

2. 在任务计划程序中：创建每日任务，触发器设为例如 04:30，
   操作 = `cmd /c F:\...\daily.bat`。请使用手动跑过一次的同一账户，
   这样 cookie 已是热状态。

## Unix cron

```cron
30 4 * * * cd /srv/aus-grocery-data && python -m ausgrocery ww-crawl-all
```

## 运维说明

- 首次运行会生成 `data/cookies_woolworths.txt` / `data/cookies_coles.txt`。
- Coles 可能在同一 IP 连续请求后发起人机挑战；客户端会重试并记录，
  稍后重跑会从数据库继续（upsert）。
- `crawl_log` 记录每次运行的 store、scope、状态与信息。
- 规模预估：Woolworths 约 8–10 万 SKU、约 3 千页；Coles 约 5–6 万商品，
  若要完整详情每个商品需一次请求。Iteration 1 建议先抓少量品类。
