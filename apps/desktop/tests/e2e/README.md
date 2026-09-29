# 构建包主链冒烟（B-5.2，Playwright + CDP）

round-4 验收已证明 CDP 驱动构建包可行；本目录把它沉淀为可重复的回归套件，
目标是在每轮人工验收前先机器跑一遍主链（启动 → 登录/2FA → 采集 → 同步 →
专注入口），降低人工成本。**不在单元 CI 内运行**（需要构建包、真实账号与
本地 Backend），定位为发布前/验收前手动回归。

## 前置

1. **构建包**：`pnpm --filter @agenthu/desktop build` 后
   `pnpm --filter @agenthu/desktop tauri build`（或使用 debug 构建 exe）。
2. **本地 Backend**：仓库根 `docker compose --profile s3mock up -d db redis
   s3mock` + 本地 uvicorn（或 A 提供的联调实例）；构建包的
   `VITE_BACKEND_URL` 需指向它（构建期变量，见 `.env.example`）。
3. **安装测试依赖**：仓库根 `pnpm install`（`@playwright/test` 为 devDependency；
   CDP 附着不下载浏览器，无需 `playwright install`）。

## 启动构建包（带 CDP）

Windows 上经 WebView2 环境变量开远程调试端口：

```powershell
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9222"
& "<构建包路径>\Agenthu.exe"
```

Git Bash：

```bash
WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9222" "/path/to/Agenthu.exe" &
```

## 运行

```bash
# 无凭据：只跑「启动并渲染外壳」用例
pnpm --filter @agenthu/desktop test:e2e

# 带真实账号：跑完整主链
AGENTHU_TEST_USERNAME=2026xxxxxx \
AGENTHU_TEST_PASSWORD='...' \
pnpm --filter @agenthu/desktop test:e2e
```

环境变量：

| 变量 | 作用 |
| --- | --- |
| `AGENTHU_CDP_URL` | CDP 地址，默认 `http://127.0.0.1:9222` |
| `AGENTHU_TEST_USERNAME` / `AGENTHU_TEST_PASSWORD` | 真实校园账号；缺失时完整链用例 skip |

## 已知口径

- **2FA 半自动**：TOTP 验证码由测试密钥体系外的因素决定（客户端不持有
  TOTP secret），完整链用例在验证码输入框出现后等待**人工输入**（≤5 分钟
  超时）。若后续引入测试专用 TOTP secret 保管方案，可在此处自动化。
- 断网重试/队列恢复等故障注入场景属人工验收清单，暂不入冒烟。
- 选择器使用可见文案与可访问名（`getByRole`/`getByLabel`），与
  `CampusConnection` 的 RTL 测试同源，改文案时两侧同步。
