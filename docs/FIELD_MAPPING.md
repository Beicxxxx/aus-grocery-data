# Field mapping

Target shape (the "澳超助手"-style detail view):

| Target field | Woolworths | Coles | Open Food Facts (fallback) |
|---|---|---|---|
| name / size | `DisplayName`, `PackageSize` | `name`, `size` | `product_name`, `quantity` |
| price | `Price` | `pricing.now` | - |
| was price | `WasPrice` | `pricing.was` | - |
| unit price | `CupString` | `pricing.comparable` | - |
| large image | `LargeImageFile` | `images[0].zoom.path` | `image_front_url` |
| ingredients | `AdditionalAttributes.ingredients` | `additionalInfo[Ingredients]` | `ingredients_text` |
| allergens (contains) | `AdditionalAttributes.allergencontains` | `additionalInfo[Allergen]` (missing on some products) | `allergens_tags` |
| allergen claims | `allergystatement` (e.g. Dairy Free...) | same as Allergen | - |
| dietary/lifestyle | `lifestyleanddietarystatement` (Gluten Free, Halal, Kosher, Vegan...) | `lifestyle` (often null) | `labels_tags` |
| health star | `healthstarrating` | - | - |
| storage | `storageinstructions` | `additionalInfo[Storage instructions]` | - |
| usage | `usageinstructions` (often empty) | `additionalInfo[Usage instructions]` | - |
| origin | `countryoforigin` (often empty) | `countryOfOrigin.country` | `countries_tags` |
| description | `description` / `RichDescription` | `longDescription` | - |
| nutrition | `nutritionalinformation` (JSON string) | `nutrition.breakdown` (Per Serving / Per 100g/ml) | `nutriments` |

## Nutrition normalisation

Two stores expose the same concept with different shapes, so each store module
already converts to a common shape before storage:

- Woolworths -> `{"Carbohydrate": {"100g": "0.1g", "Serve": "0.2g"}, ...}`
- Coles -> `{"servings_per_package": "6.00", "serving_size": "250ml",
  "nutrients": {"Energy": {"per_serving": "10 kJ", "per_100g": "4 kJ"}, ...}}`

The frontend should render whichever keys exist; coverage stats can be computed
from `nutrition_json` being non-null.

## Verified coverage (2026-08-17, Lipton Ice Tea No Sugar Lemon 1.5L)

| Target field | Woolworths | Coles |
|---|---|---|
| price comparison | yes ($2.75 vs $5.50) | yes |
| ingredients | yes | yes |
| allergen statement | yes | no (Allergen block absent for this SKU) |
| nutrition table | yes | yes (breakdown) |
| dietary tags | yes (Kosher/Vegan/...) | no (lifestyle null) |
| storage / usage | storage yes | both yes |
| origin | no | yes (Australia) |

Every screenshot field is covered by at least one store.
