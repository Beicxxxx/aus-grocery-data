# 浏览器兜底（Coles 最后手段）

## 背景

Coles 使用 Imperva/Incapsula 反爬，**HTML 页面层**在 IP 被标记后会返回
"Pardon Our Interruption" 人机挑战页。但网站自用的 BFF 接口
（GraphQL `/api/graphql` 与 Next.js `/_next/data/...` JSON）不受此限制：
携带网站公开发布的订阅密钥后，从被标记的 IP 也能直接返回数据。

因此本项目的默认路径完全不需要浏览器：

1. 商品详情 -> GraphQL `GetProductDetails`（无需 buildId）；
2. 品类树   -> GraphQL `GetShopProductsMenu`；
3. 品类列表 -> Next.js `/_next/data/{buildId}/en/browse/...json`。

浏览器仅在**极端兜底**时使用：当 BFF 接口本身失效（例如 Coles 改版），
需要直接抓取 HTML 页面时，才启动 Playwright + 本机 Chrome 会话。

## 浏览器会话实现

`ausgrocery/browser.py` 提供 `BrowserSession`（持久会话）：

- 使用 Playwright 启动本机 Chrome（`channel="chrome"`），**默认 headless**，
  不会弹出任何窗口；
- 一个抓取进程只启动一次浏览器，多个商品请求复用同一会话；
- 每次导航后检查页面内容，若 Incapsula 又返回挑战页，自动等待并重试；
- 浏览器获取到的会话 cookie 会回填给轻量客户端，IP 不变时后续请求
  直接走轻量通道，更快。

`Coles._fetch_html()` 顺序：

1. 轻量请求（curl_cffi + cookie）尝试抓取；
2. 检测到人机挑战（"Pardon Our Interruption"）时，
   自动改用 Playwright 抓取同一 URL；
3. 浏览器抓取失败时重试一次，仍失败则抛出明确错误。

## buildId 刷新策略

品类列表依赖 Next.js 的 `buildId`，该值会随 Coles 部署更新而失效。
刷新顺序：

1. 本地缓存 `data/coles_build_id.txt`（上次成功解析的值）；
2. 仓库内置"最后已知可用"默认值（验证过当前站点兼容）；
3. 直接请求 `/browse` 页面（若未被 Incapsula 拦截）；
4. Wayback Machine 最近首页快照（解析其中的 buildId）。

`buildId` 通常几天到一周才变一次，日常每日抓取几乎不会走到第 3、4 步。

## 依赖

```powershell
python -m pip install -r requirements.txt
```

- `curl_cffi`：轻量请求的 TLS 指纹模拟；
- `playwright`：浏览器兜底（默认路径不会启动）；
- 本机需安装 Google Chrome（`channel="chrome"` 直接复用，无需下载浏览器）。

## 可选开关

- `AUSGROCERY_NO_BROWSER=1`：禁用浏览器兜底；
- `AUSGROCERY_BROWSER_HEADED=1`：强制有头模式（便于调试时观察）；
- `COLES_SUBSCRIPTION_KEY=xxx`：Coles 轮换订阅密钥时覆盖。
