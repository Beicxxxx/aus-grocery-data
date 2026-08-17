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

浏览器会话在整个 CLI 命令结束后自动关闭（`close_browser`），
不会残留后台进程。

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

首次浏览器启动约 5–8 秒；之后同一会话内每个商品约 3–5 秒。
只有被拦截时才触发，正常路径仍是轻量请求。

## 已知边界

- Incapsula 的会话 cookie 与 IP 绑定：换 IP 后旧 cookie 失效属正常，
  浏览器会话会自动重新建立。
- 被**长期标记**的 IP（例如持续高频请求过的 IP）可能连真实浏览器也
  收到持久挑战。此时需要换网络（手机热点）或等待标记降级
  （通常数小时到一天）。这是网站风控策略，不是代码问题。
