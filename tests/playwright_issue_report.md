# Playwright 连接故障报告

## 症状

- `page.goto('http://127.0.0.1:8501')` → **永远 Timeout**（60 秒也超时）
- `page.goto('http://example.com')` → **同样 Timeout**——完全无网络
- `httpx.get('http://127.0.0.1:8501')` → **200 OK**——服务器确认在跑
- 用户在自己终端手动 `headless=False` 启动 Playwright 浏览器 → **可以**连 localhost
- 同一个脚本从 Git Bash / CI 环境跑 → Chromium **网络全断**

## 已尝试（全部失败）

| 尝试 | 结果 |
|------|------|
| `headless=True` | Timeout |
| `headless=False` | Timeout |
| `channel='chrome'`（系统 Chrome） | Timeout |
| `channel='msedge'`（系统 Edge） | Timeout |
| `--no-sandbox --disable-setuid-sandbox` | Timeout |
| `--disable-web-security` | Timeout |
| `--host-resolver-rules=MAP localhost 127.0.0.1` | Timeout |
| `executable_path` 指定完整 Chrome 路径 | Timeout |
| `connect_over_cdp('http://127.0.0.1:9222')` | Timeout |

## 环境

- **OS:** Windows 11 中国版
- **Python:** 3.13（venv at `d:\Download_new\agno\.venv`）
- **Playwright Python:** 1.61.1（venv 内 pip 安装）
- **Playwright npm:** 1.61.1（全局 `npx` 安装）
- **Chromium 版本:**
  - `C:\Users\14564\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe`
  - `C:\Users\14564\AppData\Local\ms-playwright\chromium_headless_shell-1228\...`
  - 还有一个 `chromium-1208`
- **Shell:** Git Bash (MinGW)
- **测试脚本:** `d:\Download_new\agno\tests\test_playwright_e2e.py`
- **服务器:** FastAPI `:8001` + Streamlit `:8501`（httpx 确认可达）

## 关键线索

1. **httpx 能连、Chromium 不能连** → 不是服务器问题，是 Chromium 进程的网络栈受限
2. **system Chrome/Edge 也不行** → 不是 Playwright Chromium 的问题，是启动方式
3. **用户手动 `headless=False` 能连** → 当用户在 PowerShell 终端直接跑 Python 时，Chromium 进程继承了正确的 Windows 桌面会话网络
4. **Git Bash / CI 环境不行** → 可能是：
   - Git Bash 进程运行在不同的 Windows 会话/完整性级别
   - 缺少某个 Windows 网络权限（loopback exemption？）
   - 代理设置差异（`HTTP_PROXY` / `NO_PROXY` 环境变量）

## 建议排查方向

1. **检查 Windows Loopback 豁免：**
   ```powershell
   CheckNetIsolation LoopbackExempt -s
   ```
   看 Playwright/Chromium 进程是否被 UWP 网络隔离阻挡。

2. **对比 `set` 环境变量：**
   - 在 Git Bash 里跑 `set | grep -i proxy`
   - 在 PowerShell 里跑 `Get-ChildItem Env: | Where-Object {$_.Name -match 'proxy'}`
   - 如果 Git Bash 设了 `HTTP_PROXY` 但 Chromium 无法连代理，会导致该症状

3. **检查 Windows 防火墙：**
   Chromium 可执行文件是否被防火墙阻止出站。

4. **尝试用 npm 的 Playwright 替代 Python 的：**
   ```bash
   npx playwright test
   ```
   npm 版本可能使用不同的 Chromium 构建。

5. **用 `--disable-features=NetworkService` 绕过 Chromium 网络服务：**
   ```
   args=['--disable-features=NetworkService,NetworkServiceInProcess']
   ```

6. **检查是否是 Windows 凭据保护导致的：**
   Chromium 使用 Windows DPAPI 加密 cookies，某些企业策略可能阻止。
