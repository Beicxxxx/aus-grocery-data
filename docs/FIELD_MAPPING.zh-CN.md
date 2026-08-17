# 字段映射

目标形态（超市商品对比详情视图）：

| 目标字段 | Woolworths | Coles | Open Food Facts（兜底） |
|---|---|---|---|
| 名称 / 规格 | `DisplayName`、`PackageSize` | `name`、`size` | `product_name`、`quantity` |
| 价格 | `Price` | `pricing.now` | - |
| 原价 | `WasPrice` | `pricing.was` | - |
| 单价 | `CupString` | `pricing.comparable` | - |
| 大图 | `LargeImageFile` | `images[0].zoom.path` | `image_front_url` |
| 配料 | `AdditionalAttributes.ingredients` | `additionalInfo[Ingredients]` | `ingredients_text` |
| 过敏原（含） | `AdditionalAttributes.allergencontains` | `additionalInfo[Allergen]`（部分商品缺失） | `allergens_tags` |
| 过敏声明 | `allergystatement`（如 Dairy Free...） | 同 Allergen | - |
| 膳食/生活方式 | `lifestyleanddietarystatement`（Gluten Free、Halal、Kosher、Vegan...） | `lifestyle`（常为空） | `labels_tags` |
| 健康星级 | `healthstarrating` | - | - |
| 储存方法 | `storageinstructions` | `additionalInfo[Storage instructions]` | - |
| 使用方法 | `usageinstructions`（常为空） | `additionalInfo[Usage instructions]` | - |
| 原产国 | `countryoforigin`（常为空） | `countryOfOrigin.country` | `countries_tags` |
| 描述 | `description` / `RichDescription` | `longDescription` | - |
| 营养表 | `nutritionalinformation`（JSON 字符串） | `nutrition.breakdown`（每份 / 每 100g/ml） | `nutriments` |

## 营养信息标准化

两家超市同一概念的数据结构不同，各 store 模块已转换为统一结构再入库：

- Woolworths -> `{"Carbohydrate": {"100g": "0.1g", "Serve": "0.2g"}, ...}`
- Coles -> `{"servings_per_package": "6.00", "serving_size": "250ml",
  "nutrients": {"Energy": {"per_serving": "10 kJ", "per_100g": "4 kJ"}, ...}}`

前端按存在的键渲染即可；覆盖率统计可通过 `nutrition_json` 是否非空计算。

## 已实测覆盖（2026-08-17，Lipton 无糖柠檬冰红茶 1.5L）

| 目标字段 | Woolworths | Coles |
|---|---|---|
| 价格对比 | 有（$2.75 vs $5.50） | 有 |
| 配料 | 有 | 有 |
| 过敏声明 | 有 | 无（该 SKU 无 Allergen 块） |
| 营养表 | 有 | 有（breakdown） |
| 膳食标签 | 有（Kosher/Vegan/...） | 无（lifestyle 为空） |
| 储存 / 使用 | 储存有 | 两者都有 |
| 原产国 | 无 | 有（Australia） |

截图中的每个字段至少有一家可提供。
