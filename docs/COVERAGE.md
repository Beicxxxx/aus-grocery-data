# 抓取覆盖率（2026-08-18）

以下数字来自本机抓取，用于演示/进度报告，不代表全站保证。

## Coles 食品/饮品全量（2026-08-18）

11 个食品部门全量（meat-seafood、fruit-vegetables、dairy-eggs-fridge、
bakery、deli、pantry、dietary-world-foods、chips-chocolates-snacks、
lunchbox、drinks、frozen），通过 BFF API 批量详情（48 个商品/请求）：

| 指标 | 数值 |
| --- | --- |
| 处理商品记录 | 19,718 |
| 唯一商品（products 表） | 14,233 |
| 单页耗时 | ~2–6 秒（批量前 90 秒） |
| 总耗时 | 约 45 分钟 |

字段覆盖率（全量商品）：

| 字段 | 覆盖率 |
| --- | --- |
| 商品图 | ~100% |
| 条形码 | ~100% |
| 价格 | ~97% |
| 配料 | ~95%+ |
| 营养信息 | ~95%+ |

## Woolworths 食品/饮品全量（2026-08-18）

11 个食品部门全量（fruit-veg、poultry-meat-seafood、deli、
dairy-eggs-fridge、bakery、lunch-box、freezer、snacks-confectionery、
pantry、international-foods、drinks）：

| 指标 | 数值 |
| --- | --- |
| 处理商品记录 | 25,562 |
| 唯一商品（products 表） | 15,944 |
| 总耗时 | 约 40 分钟 |

字段覆盖率：价格/图片 100%、条形码 79%、配料 68%、营养 67%、
膳食标签 68%、过敏声明 65%（生鲜与非包装商品天然无配料/营养字段）。

## 全量跨店匹配（两家全量后）

24,273 个商品组，其中 **5,904 组跨店可比**（GTIN 精确匹配为主，
名称/品牌/规格扩展 319 组）。示例（Chobani 全系列均精确匹配）：

```text
Chobani 15G Protein Greek Yogurt Banana Pouch 150g ($2.60)
  <->  15g High Protein Greek Yogurt Banana Pouch ($3.30)
```

## Woolworths 试点（3 个品类 × 2 页）

约 190 个商品入库。字段覆盖率：

| 字段 | 覆盖率 |
| --- | --- |
| 商品图 | 100% |
| 描述 | 100% |
| 配料 | 95% |
| 过敏声明 | 97% |
| 膳食标签 | 96% |
| 营养信息 | 91% |
| 储存信息 | 73% |

膳食标签示例：Halal 9 件、Vegan 103 件、Gluten Free 154 件
（来自试点窗口的数据）。

## 每日刷新

```powershell
python -m ausgrocery food-all --db data/grocery.db
```

幂等：重复抓取只覆盖更新同一批商品，不会产生重复行；每次都会追加
价格历史并重建跨店匹配。

## 结论

- 双店覆盖用户需要的核心字段（名称、大图、价格、配料、过敏、
  营养、膳食标签、储存/使用、原产地）。
- Coles 的过敏原块与 lifestyle 字段并非每个 SKU 都有；
  缺失时由 Open Food Facts 兜底（若条形码可查）。

## 跨店匹配（同一批次）

284 个商品全部归属唯一商品组，其中 20 组跨店可比
（8 组由 GTIN 匹配、12 组由名称/品牌/规格扩展）。
详见 `docs/MATCHING.zh-CN.md`。
