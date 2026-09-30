# 构建包主链冒烟（B-5.2，Playwright + CDP）

round-4 验收已证明 CDP 驱动构建包可行；本目录把它沉淀为可重复的回归套件，
目标是在每轮人工验收前先机器跑一遍主链（启动 → 登录/2FA → 采集 → 同步 →
专注入口 → 派生任务呈现），降低人工成本。**不在单元 CI 内运行**（需要构建
包、真实账号与本地 Backend），定位为发布前/验收前手动回归。round-5 起 E 组
spec 已按验收反馈修订；**M2 起的验收以本套件为常规工具**。

## 用例

| 用例 | 内容 | 前置 |
| --- | --- | --- |
| E1 外壳渲染 | 侧栏导航/标题/登录表单可见 | 无凭据可跑 |
| E2 主链 | 清会话重启 → 登录 → 2FA → 采集 → 同步归零 → 专注入口 | 校园凭据 + `AGENTHU_APP_EXE` |
| E3 派生任务 | 「校园采集」徽标、标题非 UUID、`due_at` 时刻与作业事件 `data.deadline` 配对一致（时区无关）、UI 与数据一致 | Backend 凭据；依赖 E2 的采集状态（串行跑） |

## 前置

1. **构建包**：`pnpm --filter @agenthu/desktop build` 后
   `pnpm --filter @agenthu/desktop tauri build`（或使用 debug 构建 exe）。
2. **本地 Backend**：仓库根 `docker compose --profile s3mock up -d db redis
   s3mock` + 本地 uvicorn（或 A 提供的联调实例）；构建包的
   `VITE_BACKEND_URL` 需指向它（构建期变量，见 `.env.example`）。
3. **安装测试依赖**：仓库根 `pnpm install`（`@playwright/test` 为 devDependency；
   CDP 附着不下载浏览器，无需 `playwright install`）。

## 启动构建包（带 CDP）

E1/E3 附着到**已运行**的包；E2 在带凭据运行时会自行「退出包进程 → 清
`campus.hold` → 带 CDP 重新拉起」（`AGENTHU_APP_EXE` 指向 exe 即可），
保证全新校园会话（登录表单必然存在）。

手动等价操作（不设 `AGENTHU_APP_EXE` 时按此准备后只跑 E1/E3，或重跑 E2）：

1. 退出包进程（`campus.hold` 被主进程持有，先退出才能删）。
2. 删除 `%LOCALAPPDATA%\dev.agenthu.desktop\campus.hold`。
3. 带 CDP 参数重新启动：

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

# 完整套件（E2 自动清会话重启，E3 校验派生任务）
AGENTHU_APP_EXE="<构建包路径>\Agenthu.exe" \
AGENTHU_TEST_USERNAME=2026xxxxxx \
AGENTHU_TEST_PASSWORD='...' \
AGENTHU_TEST_BACKEND_URL=http://127.0.0.1:8000 \
AGENTHU_TEST_BACKEND_EMAIL='qa@...' \
AGENTHU_TEST_BACKEND_PASSWORD='...' \
pnpm --filter @agenthu/desktop test:e2e
```

环境变量：

| 变量 | 作用 |
| --- | --- |
| `AGENTHU_CDP_URL` | CDP 地址，默认 `http://127.0.0.1:9222` |
| `AGENTHU_TEST_USERNAME` / `AGENTHU_TEST_PASSWORD` | 真实校园账号；缺失时主链用例 skip |
| `AGENTHU_APP_EXE` | 构建包 exe 路径；设置后 E2 自动完成「退出进程 → 清 `campus.hold` → 带 CDP 重启」，缺失时 E2 失败并提示手动口径 |
| `AGENTHU_CAMPUS_HOLD` | 覆盖 `campus.hold` 默认路径（`%LOCALAPPDATA%\dev.agenthu.desktop\campus.hold`） |
| `AGENTHU_TEST_BACKEND_URL` / `AGENTHU_TEST_BACKEND_EMAIL` / `AGENTHU_TEST_BACKEND_PASSWORD` | Backend 测试账号（E3 数据级断言直连 API；应用内未登录 Backend 时也会用它在 UI 代填登录）；缺失时 E3 skip |

## 已知口径

- **2FA 半自动**：验证方式从 combobox 实际可选项动态选择（round-5 账号
  只有企业微信/短信；TOTP 仅在真实存在时兜底）。验证码仍由**人工输入**
  （密钥不出客户端），用例等待 ≤5 分钟（测试整体超时放宽到 10 分钟）。
  选实际方式后预计仅需 1 个验证码。
- **E3 依赖 E2 状态**（串行 worker=1）：单独跑 E3 需先完成一次采集同步。
- E2 重启后的包在套件结束后保持运行，由测试者手动关闭。
- 断网重试/队列恢复等故障注入场景属人工验收清单，暂不入冒烟。
- 选择器使用可见文案与可访问名（`getByRole`/`getByLabel`），与
  `CampusConnection` 的 RTL 测试同源，改文案时两侧同步。
