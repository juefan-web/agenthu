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
| E4-seed | 真实管线预置：事件 → 派生（课程前缀标题）→ Focus 实际用时（API 覆盖值，无需真实等待）→ 课表事件 | Backend 凭据；独立于 E2/E3 |
| E4（门控） | M2 出口判据全链：避开课表的人话计划 → learned/default 双向估时断言 → 超时 Focus → 重排建议 → 接受即取代 → L1 记忆可修正（superseded-by 链）| `AGENTHU_E4_FULL=1`；依赖 A 侧 planner v2/估时学习/触发引擎/L1 写入者 |
| E5（门控） | M3 出口后端半边（API 造数）：上传→抽取/嵌入→同意门→提问→引用机械可核（page+quote 对 fixture 原文独立复核）→删 Learning Memory→同问不再体现→删回答 | `AGENTHU_E5_FULL=1`；栈见下方「E5 栈」；场景定义 `TASKS/m3-e5-exit-scenario.md` |
| E5-UI（门控） | M3 出口 UI 半边（构建包 + CDP）：Backend 登录→讲解视图→同意门→提问→引用标记/引用卡渲染与跳转高亮→删 Memory 同问不再体现→历史删除 | `AGENTHU_E5_UI=1`；构建包 CDP 运行 + `AGENTHU_TEST_BACKEND_URL`（与构建期 `VITE_BACKEND_URL` 同源）；campus 真机上传链不在本 spec（验收轮人工项） |
| E6（门控） | M4 出口六场景（构建包 + CDP，serial）：超时 Focus → L1 重排建议（run 级 basis 核验）→ Chat 请求 → `task.create` L2 卡片（同意门/202/深链/参数/到期/basis）→「为什么」同一 basis → 确认恰一次（UI 防双击 + API 并发双 mutation_id 任务恰 +1）→ provider 断供明确失败且计划/重排/Focus 仍可用 → 预算抑制 + L3 grant（值级 scope）自动派发 + 预算耗尽如实抑制 | `AGENTHU_E6_UI=1`；E6 栈见下方「E6 栈」；场景与缺口矩阵见 `TASKS/m4-b3-e6-exit.md`；provider 假件 = 本目录 `e6-replay.mjs` |

## 前置

1. **构建包**：`pnpm --filter @agenthu/desktop build` 后
   `pnpm --filter @agenthu/desktop tauri build`（或使用 debug 构建 exe）。
2. **本地 Backend**：仓库根 `docker compose --profile s3mock up -d db redis
   s3mock` + 本地 uvicorn（或 A 提供的联调实例）；构建包的
   `VITE_BACKEND_URL` 需指向它（构建期变量，见 `.env.example`）。
3. **安装测试依赖**：仓库根 `pnpm install`（`@playwright/test` 为 devDependency；
   CDP 附着不下载浏览器，无需 `playwright install`）。

### E5 栈（门控 `AGENTHU_E5_FULL=1`）

E5 走**真实栈**（与 E4 同口径）：compose `db redis s3mock` + 独立库
（如 `agenthu_e5`，alembic 从零 up）+ uvicorn + arq worker，进程环境
`STORAGE_BACKEND=minio`、`S3_ENDPOINT_URL=http://127.0.0.1:9090`、
`OPENAI_BASE_URL=http://127.0.0.1:9099/v1`、`OPENAI_API_KEY=<replay 占位
非空值>`；供应商侧是本目录的 `e5-replay.mjs`（零依赖 Node，
`node e5-replay.mjs` 起 :9099，recorded-replay 契约见任务文件）。运行：

```bash
AGENTHU_TEST_BACKEND_URL=http://127.0.0.1:8010 \
AGENTHU_TEST_BACKEND_EMAIL=e5@any AGENTHU_TEST_BACKEND_PASSWORD=any-value \
AGENTHU_E5_FULL=1 pnpm --filter @agenthu/desktop exec playwright test e5-m3-exit
```

（EMAIL/PASSWORD 仅作非空门槛——spec 自注册全新账号；worker 启动后确认
日志 `Starting worker for N functions`。）

### E6 栈（门控 `AGENTHU_E6_UI=1`）

E6 复用 E5 真实栈口径（compose `db redis s3mock` + 独立库 `agenthu_e6`
+ uvicorn + arq worker，env 同 E5 栈），provider 假件换 **`e6-replay.mjs`**
（`node e6-replay.mjs` 起 :9099）：默认 `grounding` 模式与 e5-replay 行为
一致，spec 经 `POST /__mode` 自行切换 `chat-tools`（首轮 function_call
`task.create` 提案 + 续轮文本收尾）与 `unavailable`（/v1/responses 503）。
构建包口径同 E5-UI（`--features tauri/custom-protocol` + CDP 9222）。运行：

```bash
AGENTHU_TEST_BACKEND_URL=http://127.0.0.1:8010 AGENTHU_TEST_BACKEND_EMAIL=e6@any AGENTHU_TEST_BACKEND_PASSWORD=any-value AGENTHU_E6_UI=1 pnpm --filter @agenthu/desktop exec playwright test e6-m4-exit-ui
```

六用例 serial 共享构建包内登录态（spec 自注册首账号，API 核账同账号）；
已知契约-实现缺口与场景↔判据映射见 `AGENT_CONTEXT/TASKS/m4-b3-e6-exit.md`。

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
| `AGENTHU_TEST_BACKEND_URL` / `AGENTHU_TEST_BACKEND_EMAIL` / `AGENTHU_TEST_BACKEND_PASSWORD` | Backend 测试账号（E3 数据级断言直连 API；应用内未登录 Backend 时也会用它在 UI 代填登录）；缺失时 E3/E4 skip |
| `AGENTHU_E4_FULL` | 置 `1` 时运行 E4 出口判据全链用例（依赖 A 侧 M2 写入者批次：planner v2 basis、估时学习、触发引擎、L1 写入者）；未设时仅 E4-seed 常开 |

## 已知口径

- **E4 全链运行前置**：worker 容器必须在（触发引擎经 arq cron `second={0,30}` 排水，E4 的 90s 建议轮询按此设计）；**连续两轮完整 E4 全链运行须间隔 ≥30 分钟**——触发引擎限频统计该用户任意历史建议（含已接受的），密集重跑会把第二轮的建议创建压住、轮询必超时。
- **2FA 半自动**：验证方式从 combobox 实际可选项动态选择（round-5 账号
  只有企业微信/短信；TOTP 仅在真实存在时兜底）。验证码仍由**人工输入**
  （密钥不出客户端），用例等待 ≤5 分钟（测试整体超时放宽到 10 分钟）。
  选实际方式后预计仅需 1 个验证码。
- **E3 依赖 E2 状态**（串行 worker=1）：单独跑 E3 需先完成一次采集同步。
- E2 重启后的包在套件结束后保持运行，由测试者手动关闭。
- 断网重试/队列恢复等故障注入场景属人工验收清单，暂不入冒烟。
- 选择器使用可见文案与可访问名（`getByRole`/`getByLabel`），与
  `CampusConnection` 的 RTL 测试同源，改文案时两侧同步。
