# 数据来源与合规说明

## 概览

管道使用两类来源：

1. **Open Food Facts**：开放数据库，CC-BY-SA 许可，提供文档化 API。
   用于补全缺失的过敏原 / 膳食标签 / 营养信息。
2. **Woolworths.com.au 与 Coles.com.au 公开页面**：无需登录即可浏览；
   数据来自网站自身使用的接口。这不是官方 API，也不属于开放数据许可。

课程项目（如 FIT5120 包容性设计课题）中，请如实表述：
"Open Food Facts 开放数据库 + 两家零售商公开商品页（非官方采集，
记录抓取时间，仅供参考）"。不要把零售商页面说成"开放数据"。

## "公开"在这里的含义

- Woolworths 的搜索/品类接口允许匿名 HTTP 请求；网站本身无需登录即可浏览。
- Coles 网站自用的 BFF 接口（GraphQL `/api/graphql` 与
  Next.js `/_next/data/...` JSON）允许携带其公开订阅密钥匿名请求；
  网站本身无需登录即可浏览。密钥出现在每个访问者的浏览器里，
  若 Coles 轮换密钥，可通过 `COLES_SUBSCRIPTION_KEY` 环境变量覆盖。
- 两家均未发布第三方开发者 API 或数据许可。robots.txt 禁止
  `/search/`（Coles）与 `/shop/search`（Woolworths）；两家均使用
  反爬保护（Incapsula / Akamai）。

## 产品免责声明

Woolworths 明确标注过敏原与膳食过滤"仅供参考"；消费者必须核对实物标签。
应用界面应展示类似提示：

> 信息来自零售商公开页面与 Open Food Facts，采集于特定日期；
> 食用前请以商品实物标签为准。

## 参考项目

- tjhowse/aus_grocery_price_database — GPL-3.0。架构与接口技巧启发了
  本项目；未复制代码（本项目为 MIT）。
- tjhowse/python-woolworths — 无许可证；仅参考端点清单。
- abhinav-pandey29/coles-scraper — 无许可证；参考 cookie 拦截模式。
- nguyentansinh123/Scraping-Coles-Woolworths-IGA — 无许可证；
  参考浏览器兜底模式。
