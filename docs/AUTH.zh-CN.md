# GitHub 推送与认证（免折腾方案）

## 背景

Codex 运行在受限沙箱中，有两个历史问题：

1. 无法写入系统级 gh 配置
   `C:\Users\...\AppData\Roaming\GitHub CLI\hosts.yml`（进程只读）；
2. 沙箱内 `git-remote-https.exe` 会崩溃（引用 0x0000000000000000 内存），
   导致 `git push` 直接失败。

## 方案：一键推送脚本

[scripts/push.ps1](/F:/Courses/FIT5120/aus-grocery-data/scripts/push.ps1)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\push.ps1
```

脚本做了什么：

1. 使用独立 gh 配置目录 `%TEMP%\gh-codex-config`（不碰系统 hosts.yml）；
2. 若 token 缺失，自动启动 GitHub 设备授权流程（浏览器确认一次）；
3. 用临时凭据文件提供 token（正斜杠路径避免 git 转义问题），
   `-c credential.helper=store --file=...` 隔离在本次命令；
4. 推送 `master`，完成后删除临时凭据文件。

Codex 已获批直接运行该脚本（免审批），推送不需要用户再操作。

## 第一次授权（或 token 过期时）

运行脚本后若提示需要登录，会打印类似：

```text
! First copy your one-time code: XXXX-XXXX
Press Enter to open https://github.com/login/device
```

用户只需要：打开 https://github.com/login/device → 输入验证码 →
选择 Beicxxxx → Authorize。之后 token 保存在 `%TEMP%\gh-codex-config\hosts.yml`，
有效期内推送都是静默完成。

## 为什么不再修改系统配置

给 `hosts.yml` 添加沙箱用户写权限被安全策略判定为"对凭据存储的持久权限
篡改"而拒绝。独立配置目录方案等价且更安全：token 只存在于
`%TEMP%\gh-codex-config`，需要时重新授权即可。

## 安全说明

- token 仅在推送瞬间写入 `%TEMP%\gh-codex-credentials`，推送后立即删除；
- `%TEMP%` 属于当前用户且会被系统定期清理，token 不会长期残留；
- 仓库中不保存任何 token，`data/` 与临时目录均在 `.gitignore` 中。
