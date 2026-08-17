# 跨店商品匹配（严格条码）

同一个商品在 Coles 与 Woolworths 的名称往往不同（例如
"Nuttelex Buttery Table Spread" vs "Nuttelex Buttery Spread"），
名称模糊匹配容易误配外观相似但实际不同的商品（如普通全脂奶 vs
无乳糖全脂奶）。因此匹配**只使用条形码（EAN/UPC/GTIN）**：

> 双店条形码完全一致 → 同一商品组；否则各自单店成组。

## 规则

1. 条形码清洗为纯数字（忽略空格/连字符），接受 8–14 位
   （EAN-8 / UPC-A / EAN-13 / GTIN-14）；长度不合法的视为无条码。
2. 相同条码的所有商品（跨店）归入一个 `gtin` 组。
3. 无条码或条码不跨店的商品各自成 `single` 组。
4. **不做**品牌、规格、名称相似度匹配——保证零误配。

## 生成与验证

```powershell
python -m ausgrocery match --db data/grocery.db
```

命令会重建 `product_groups` / `product_group_members` 并打印报告。
每次全量抓取后重跑即可；匹配只依赖当前快照，可随时重建。

## 全量结果（2026-08-18，两家食品/饮品全量）

| 指标 | 数值 |
| --- | --- |
| 商品总数 | 30,177（WW 15,944 + Coles 14,233） |
| 商品组总数 | 24,718 |
| 跨店匹配组 | 5,459（全部为 GTIN 精确匹配） |

示例（同一商品双店名称不同但条码一致，正确配对）：

```text
Nuttelex Buttery Table Spread 500g  <->  Nuttelex Buttery Spread
Sunny Queen 12 Extra Large Free Range Eggs 700g
  <->  Sunny Queen Free Range Extra Large Eggs 12 Pack
```

## 已知边界

- 双店条码不同但实际相同的商品不会配对（保守策略，宁缺勿错）；
- 缺失/无效条码的商品不会参与跨店匹配；
- 若某商品双店条码相同但并非同一商品（极罕见，条码本身唯一标识
  EAN-13 商品规格），请以商品实物为准核对。
