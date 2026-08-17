# 商品详情合并表（WW + Coles + OFF 并集）

`merged_products` 是商品详情的统一数据源：对每个跨店商品组
（严格按 GTIN 条码匹配），取 Woolworths、Coles、Open Food Facts
三个来源所有字段的**并集**，并选择一张最优商品图。

## 字段策略

| 字段 | 策略 |
| --- | --- |
| 名称/规格 | 双店各自保留（`name_ww` / `name_coles`、`size_ww` / `size_coles`） |
| 价格 | 双店各自保留（`price_ww_cents` / `price_coles_cents` + 单位价） |
| 品牌 | 三源第一个非空 |
| 配料 | 三源第一个非空（WW 优先 → Coles → OFF） |
| 过敏声明 | 三源列表去重并集 |
| 膳食标签 | 三源列表去重并集 |
| 营养表 | 三源各自保留（`nutrition_json.sources`），预览时按营养项取并集 |
| 储存/用法/原产地 | 三源第一个非空 |
| 分类/国家 | OFF + 超市列表去重并集 |

## 图片选择（多选一）

1. **Open Food Facts 正视图**（`front_*`，升级为 `full` 高清版）优先；
2. 其次 **Woolworths `large` 商品图**；
3. 最后 **Coles CDN 商品图**。

`--verify-images` 会逐个验证 OFF 图片 URL 是否真的返回图片
（下载前 16 字节检查 magic），失败则回退下一候选。
`--check-white` 用 Pillow 检查图片四角是否接近白色，非白底时回退。

## 生成

```powershell
# 1) 抓取 + 条码匹配（也可分开跑）
python -m ausgrocery food-all --db data/grocery.db

# 2) 生成合并表
python -m ausgrocery merge --db data/grocery.db

# 3) 预览
python scripts/preview.py --db data/grocery.db --out data/preview.html
```

## OFF API：不需要 key

Open Food Facts 的**读取**接口不需要 API key 或账号，只需要：

1. 自定义 `User-Agent`，格式 `AppName/Version (ContactEmail)`；
2. 遵守速率限制：读 15 次/分/IP，搜索 10 次/分/IP；
3. 大批量场景（>几百个商品）优先使用官方 JSONL/CSV 导出。

需要账号的只有**写入**（上传图片、修改数据），本项目只读不涉及。
官方文档：https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/

### 当前 OFF 覆盖情况

- 试点阶段已对 120 个商品做了 OFF 回填（存于 `products.off_json`）；
- 合并表中 60 行含 OFF 数据，其中 54 行采用 OFF 正视图作为主图；
- 全量 5,459 组的 OFF 回填受速率限制（15/min），建议按官方
  JSONL 导出一次性加载，或分批回填（约 6 小时可跑完）。
