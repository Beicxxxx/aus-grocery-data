# 跨店商品匹配

同一个商品在 Coles 与 Woolworths 的名称、条形码往往不同
（例如 "Bega Stringers Cheese" vs "Cheese Stringers Original"、
"12 Extra Large Free Range Eggs" vs "Free Range Extra Large Eggs 12 Pack"）。
匹配器为前端提供"商品组"：一组 = 两家店里的同一个（或可比的）商品。

## 匹配流程（三级）

1. **GTIN（条形码）精确匹配**：双店条形码相同的商品视为同一商品。
2. **名称匹配**：剩余商品按 品牌 + 规格 + 归一化名称 比较：
   - 品牌需相同，或双方都是自有品牌（Woolworths / Coles / Coles Simply /
     Macro 等，视为可比）；
   - 规格需一致（`1.5L` = `1.5 l`，`300mL x 12 pack` 按原样比较）；
   - 名称去掉品牌/规格/通用词（bottle、pack、can 等）后，
     用 SequenceMatcher 相似度打分，默认阈值 0.78；
   - 同义词归一化：yoghurt→yogurt、lite→light。
3. **单店组**：没有跨店伙伴的商品自成一组，保证每个商品恰好属于一组。

## 生成与验证

```powershell
python -m ausgrocery match --db data/grocery.db
python -m ausgrocery match --db data/grocery.db --min-score 0.80  # 更严格
```

命令会重建 `product_groups` / `product_group_members` 并打印报告。
每次全量抓取后可重跑；匹配只依赖当前快照，可随时重建。

## 试点结果（dairy-eggs-fridge，284 个商品）

| 指标 | 数值 |
| --- | --- |
| 商品组总数 | 264 |
| 跨店匹配组 | 20（GTIN 8 + 名称扩展 12） |
| 每个商品的组归属 | 恰好 1 个（无孤儿、无重复） |

## 已知边界

- 名称相似度低于阈值的同款（如 "Cheese Slices Tasty 24 Pack" 与
  "Tasty Cheese Slices"）可能漏配；提高阈值更保守、降低阈值更激进。
- 自有品牌跨店配对（Woolworths 与 Coles 自家牛奶）在方法上视为"可比"，
  应用层仍应显示各自品牌，避免误导。
