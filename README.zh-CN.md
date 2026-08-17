# Aus Grocery Data（澳洲超市商品数据管道）

用于“超市商品对比”应用的数据管道：覆盖 Coles 与 Woolworths，可选接入
Open Food Facts 补齐缺失字段。输出字段对应商品详情页的常见形态：
商品名、大图、双店价格、配料、过敏原声明、营养表、膳食/生活方式标签、
储存方法、使用方法、原产国。

## 功能

- **Woolworths**：通过公开浏览 API 进行全品类抓取（先访问浏览页预热
  cookie，再 `POST /apis/ui/browse/category`，每页 36 条）。已实测可用。
- **Coles**：商品详情通过服务端渲染的 `__NEXT_DATA__` JSON 解析；
  品类列表使用 Next.js `/_next/data/{buildId}/.../browse.json` 接口
  （参考项目方案，需未被 Incapsula 风控的 IP）。
- **Open Food Facts**：按条形码查询，仅在超市缺失过敏原/膳食标签/
  营养信息时兜底（数据来源单独记录）。
- **SQLite 存储**：`products`（当前快照）、`price_history`（每日价格点）、
  `crawl_log`（抓取日志）。
- **礼貌抓取**：请求间隔、指数退避重试、持久化 cookie、
  反爬拦截检测（"Pardon Our Interruption" / Incapsula）。
- **每日刷新**：按每天一轮设计（见 `docs/DEPLOYMENT.zh-CN.md`）。

## 快速开始

```powershell
python -m ausgrocery init-db --db data/grocery.db

# Woolworths：抓一个品类的前两页
python -m ausgrocery ww-crawl --category-id 1_6E4F4E4 --url dairy-eggs-fridge --max-pages 2

# Coles：抓单个商品详情
python -m ausgrocery coles-product --slug lipton-ice-tea-sugar-free-ice-tea-lemon-iced-tea-bottle-1.5l-5171521

# Open Food Facts：按条形码查询
python -m ausgrocery off --barcode 9300633556150

# 单商品探测（与实验脚本输出一致）
python -m ausgrocery probe ww "Lipton Ice Tea No Sugar Lemon"
python -m ausgrocery probe coles lipton-ice-tea-sugar-free-ice-tea-lemon-iced-tea-bottle-1.5l-5171521
```

结果写入 `data/*.json`（probe）与 `data/grocery.db`（抓取命令）。
字段映射见 `docs/FIELD_MAPPING.zh-CN.md`，合规说明见
`docs/DATA_SOURCES.zh-CN.md`。

## 行为说明

- **Coles（Imperva/Incapsula）**：同一 IP 连续请求后可能返回
  "Pardon Our Interruption" 人机挑战。客户端会重试并明确报告，
  不会静默猜错。稍后重跑、或换一个未被风控的住宅 IP 通常可以恢复
  （已验证：同一商品页在风控前可正常解析）。
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
