# Aus Grocery Data（澳洲超市商品数据管道）

用于“超市商品对比”应用的数据管道：覆盖 Coles 与 Woolworths，可选接入
Open Food Facts 补齐缺失字段。输出字段对应商品详情页的常见形态：
商品名、大图、双店价格、配料、过敏原声明、营养表、膳食/生活方式标签、
储存方法、使用方法、原产国。

## 功能

- **Woolworths**：通过公开浏览 API 进行全品类抓取（先访问浏览页预热
  cookie，再 `POST /apis/ui/browse/category`，每页 36 条）。已实测可用。
- **Coles**：优先走网站自用 BFF API——GraphQL `GetProductDetails` 批量变体
  一次请求 48 个商品详情、GraphQL `GetShopProductsMenu` 拿品类树、
  Next.js `/_next/data/{buildId}/en/browse/...json` 拿品类列表。
  请求携带网站公开发布的订阅密钥（`ocp-apim-subscription-key`），
  不需要代理、不需要浏览器，被 Incapsula 标记的 IP 也能直接抓取；
  仅 HTML 页面路径保留真实浏览器作最后兜底。
- **Open Food Facts**：按条形码查询，仅在超市缺失过敏原/膳食标签/
  营养信息时兜底（数据来源单独记录）。
- **SQLite 存储**：`products`（当前快照）、`price_history`（每日价格点）、
  `crawl_log`（抓取日志）、`product_groups`（跨店商品组）、
  `merged_products`（三源并集合并详情）。
- **跨店匹配**：严格按 GTIN 条形码匹配（不做名称模糊匹配，零误配），
  生成商品组，供前端并排展示双店价格与成分。
- **三源合并**：商品详情 = WW + Coles + Open Food Facts 字段并集；
  图片多选一（WW 大图优先 → Coles → OFF 正视图兜底），
  预览脚本直接消费合并表。
- **礼貌抓取**：请求间隔、指数退避重试、持久化 cookie、
  反爬拦截检测（"Pardon Our Interruption" / Incapsula）。
- **免费稳定**：Coles 走公开 BFF API，无需住宅代理、无需频繁更换 IP。
- **全量抓取**：`food-all` 一条命令抓完两家所有食品/饮品部门，
  Coles 批量详情让 2 万+ 商品在约 30 分钟内完成。
- **每日刷新**：按每天一轮设计（见 `docs/DEPLOYMENT.zh-CN.md`）。

## 快速开始

```powershell
python -m ausgrocery init-db --db data/grocery.db

# Woolworths：抓一个品类的前两页
python -m ausgrocery ww-crawl --category-id 1_6E4F4E4 --url dairy-eggs-fridge --max-pages 2

# Coles：抓单个商品详情
python -m ausgrocery coles-product --slug lipton-ice-tea-sugar-free-ice-tea-lemon-iced-tea-bottle-1.5l-5171521

# Coles：抓一个品类（支持多页）
python -m ausgrocery coles-crawl --category dairy-eggs-fridge --max-pages 1

# 跨店匹配：生成商品组（严格按 GTIN 条码）
python -m ausgrocery match --db data/grocery.db

# 全食品/饮品全量抓取（两家 + 自动跨店匹配）
python -m ausgrocery food-all --db data/grocery.db

# 生成三源合并详情表
python -m ausgrocery merge --db data/grocery.db

# 生成合并表预览
python scripts/preview.py --db data/grocery.db --out data/preview.html

# Open Food Facts：按条形码查询
python -m ausgrocery off --barcode 9300633556150

# 单商品探测（与实验脚本输出一致）
python -m ausgrocery probe ww "Lipton Ice Tea No Sugar Lemon"
python -m ausgrocery probe coles lipton-ice-tea-sugar-free-ice-tea-lemon-iced-tea-bottle-1.5l-5171521
```

结果写入 `data/*.json`（probe）与 `data/grocery.db`（抓取命令）。
字段映射见 `docs/FIELD_MAPPING.zh-CN.md`，合规说明见
`docs/DATA_SOURCES.zh-CN.md`，跨店匹配算法见 `docs/MATCHING.zh-CN.md`。

## 行为说明

- **Coles（Imperva/Incapsula）**：HTML 页面层有人机挑战，但网站自用的
  BFF 接口（GraphQL + Next.js JSON）只需携带订阅密钥即可匿名访问，
  与 IP 是否被标记无关。品类列表依赖的 `buildId` 会缓存到
  `data/coles_build_id.txt`；失效时自动从网站页面或 Wayback Machine
  快照刷新。只有极端情况下（BFF 接口变更）才回退到
  Playwright + 本机 Chrome，设置 `AUSGROCERY_NO_BROWSER=1` 可关闭该兜底。
- **Woolworths（Akamai）**：对数据中心 IP 的裸 POST 更严格；客户端会先
  GET 一次浏览页预热 cookie（与参考项目一致，本机实测可用）。
- 价格与商品信息会变化；每条记录都带 `fetched_at`，每次抓取都会向
  `price_history` 追加价格点。

## 参考项目

本项目为独立实现，抓取技术参考了以下开源项目：

- [tjhowse/aus_grocery_price_database](https://github.com/tjhowse/aus_grocery_price_database)
  （GPL-3.0）— 品类 worker 架构、Woolworths cookie 预热、Coles
  `_next/data` 列表接口。
- [tjhowse/python-woolworths](https://github.com/tjhowse/python-woolworths)
  （无许可证）— Woolworths UI API 端点清单。
- [abhinav-pandey29/coles-scraper](https://github.com/abhinav-pandey29/coles-scraper)
  （无许可证）— Coles cookie 拦截重试模式。
- [nguyentansinh123/Scraping-Coles-Woolworths-IGA](https://github.com/nguyentansinh123/Scraping-Coles-Woolworths-IGA)
  （无许可证）— 真实浏览器是 Coles 可靠兜底方案的佐证。

未从 GPL-3.0 或无许可证项目复制代码；接口与技术均为重新实现。
详见 `docs/DATA_SOURCES.zh-CN.md`。

## 项目结构

```text
aus-grocery-data/
  ausgrocery/          核心包（http、stores、storage、cli）
  docs/                字段映射、数据来源、部署说明（含中文版）
  data/                输出目录（git 忽略，含 sqlite 与 json）
  tests/               无网络冒烟测试
```

## 许可证

MIT，见 [LICENSE](LICENSE)。
