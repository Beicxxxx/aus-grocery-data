# 真实浏览器兜底（Coles 反爬）

## 背景

Coles 使用 Imperva/Incapsula 反爬。同一 IP 连续请求后会返回
"Pardon Our Interruption" 人机挑战页，且该标记会持续一段时间。
轻量 HTTP 客户端（curl_cffi / urllib）在 IP 被标记后无法直接通过。

实测（2026-08-17）：

- curl.exe / curl_cffi / urllib 在 IP 被标记时全部被拦；
- Playwright + 本机 Chrome（headless）可以正常拿到真实商品页；
- 浏览器会执行 Incapsula 的 JavaScript 校验，因此基本不受 IP 标记影响。

## 实现

`ausgrocery/browser.py` 提供 `fetch_html(url)`，使用
Playwright 启动本机 Chrome（`channel="chrome"`，默认 headless），
等待页面渲染后返回 HTML。

`Coles._fetch_html()` 顺序：

1. 轻量请求（curl_cffi + cookie）尝试抓取；
2. 检测到人机挑战（"Pardon Our Interruption"）时，
   自动改用 Playwright 抓取同一 URL；
3. 浏览器抓取失败时重试一次，仍失败则抛出明确错误。

分类列表（`_next/data`）同样支持浏览器兜底：
直接访问 `/browse/{category}?page=N`，从 `__NEXT_DATA__` 解析结果。

## 依赖

```powershell
python -m pip install -r requirements.txt
```

- `curl_cffi`：轻量请求的 TLS 指纹模拟；
- `playwright`：浏览器兜底；
- 本机需安装 Google Chrome（`channel="chrome"` 直接复用，无需下载浏览器）。

## 可选开关

设置环境变量 `AUSGROCERY_NO_BROWSER=1` 可禁用浏览器兜底
（例如在无图形界面的服务器上不希望启动 Chrome）。

`AUSGROCERY_BROWSER_HEADED=1` 可强制有头模式（便于调试时观察）。

## 性能提示

浏览器每次调用约需 3–8 秒（启动 + 渲染）。只有被拦截时才触发，
正常路径仍是轻量请求。全量抓取时若 IP 被标记，建议混合使用：
Woolworths 走轻量请求，Coles 用浏览器兜底，或等待标记过期。
