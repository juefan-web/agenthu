# Merge-1 Windows 构建包人工测试报告（2026-09-28）

审核人以 Windows 构建包对 Merge-1（`integration/study-time-m0` = Backend
`61fcf82` + 客户端 `a2693e9`）做了端到端人工验收。**结论：不建议转正合并**。
以下七项缺陷（D1-D7）已逐项经代码复核确认属实，根因定位到代码行；修复任务
已立项：A 见 `TASKS/backend-merge1-review-fixes.md`（D5/D7），B 见
`TASKS/client-merge1-review-fixes.md`（D1/D2/D3/D4/D6）。登录链修复参照上游
OneTHU `dev3` 的 `infoLib.ts`/`clients.ts`/`transport.ts` 实现。

## D1（P0）校园采集在登录成功后仍确定性失败

- 现象：登录/2FA 全部成功后，采集报"校园会话已失效，请重新登录"。
- 失败链：`onethuAdapter.ts` `requireLearnSession` → `learn.resume()` 失败 →
  read 层自动 restore+probe（info 域成功、learn 域失败）→ 重试仍失败 → reset。
- 根因（三个结构性缺口）：
  1. 登录后没有显式 learn 漫游——`tauriAuthGateway.ts` 的 `run` 只调用
     `login()`，注释明确写着刻意跳过（"A second direct CAS roam here would
     prompt for 2FA again"），跳过了二次 2FA 却没有给 learn 会话替代建立路径；
  2. `runtime.ts` 从未接线 `learn.credentialProvider`，vendored
     `silentRelogin()` 的账密路径（路径二）永远是死路，唯一活路 `/f/login`
     SSO（路径一）在真实环境失败；
  3. 失败现场缺少 vendored 自带的 `LEARN-SILENT` debug 日志输出，无法定位
     `/f/login` 的具体失败环节。

## D2（P0）登录出现双轮 2FA / 静默回到认证方式选择页

- 根因：vendored info-lib `login()` 成功后调用 `roam(helper, "id", ...)`，该
  分支用账密（`i_user`/`i_pass`）**重新完整登录 id**，响应含"二次认证"即再触发
  一轮 2FA（外层还有 `for (let i = 0; i < 2; i++)` 重试）。测试账号是全新
  未受信设备，双轮必现，且 UI 没有任何提示。
- 上游对照：OneTHU `dev3` 结构相同，但依赖 **finger3 受信设备链**
  （首轮 2FA 的 SAVE_FINGER 返回 `fingerGenPrint`，roam 重放时携带即可免二次
  认证）+ 链自愈逻辑消化。用户要求"不应当登录两次"，落点：登录前灌入存量
  finger3 使受信链生效（一次登录内不重复认证）；未受信设备时第二轮 2FA 必须
  有显式 UI 提示与链自愈，参照上游 `infoLib.ts`。

## D3（P1）2FA 恢复路径断裂

- `send2fa` 守卫 `!this.methodGate || !this.completion` 在首轮 2FA 结束后即
  永久失效（报错文案与人工测试现场一字不差），失败后原地重发不可用；
- 上游 `LoginError(m3)` 被 catch 折叠，真实错误 message 从未透出；
- 180s 总超时从 `login()` 起算并覆盖两轮 2FA，超时即静默 `logout()` 销毁全部
  会话链，用户输入到一半被踢回。

## D4（P2）今日计划显示 UUID 而非任务标题

- `packages/contracts` 的 `PlanItemSchema`（`index.ts`）没有 `title` 字段，
  `App.tsx` 渲染 `item.task_id`（UUID）。
- 注：Backend 冻结契约中 `title` 一直是"允许的额外字段"（客户端 Zod 直接
  strip），因此后端 drift check 无法发现"客户端没有用上"这类缺口——检查工具
  的结构性盲区，需 B 侧补 `title: z.string()` 后双方同步冻结基线。

## D5（P1）current-state 并发首请求 500（表现为 CORS 错误）

- 根因：`backend/services/current_state.py` `get_or_create_state()` 无锁先查
  后插，并发首请求双 INSERT 撞 `uq_current_states_user`，未捕获
  IntegrityError → 500；人工测试 5 并发复现 2/5。
- 次生：未处理异常由 ServerErrorMiddleware 生成（在 CORSMiddleware 之外），
  500 不带 CORS 头，WebView 端表现为 CORS 错误，掩盖真实 5xx。
- 修复：A（任务文件含验收标准）。

## D6（P1）生产 CSP 拦截 Tauri IPC（上轮收紧 CSP 引入的回归）

- 生产 `csp` 的 `connect-src` 只有 `'self'` 与两个本地 Backend 源，缺
  `http://ipc.localhost`（Windows WebView2 上 Tauri v2 IPC 目标源，与页面源
  `http://tauri.localhost` 不同 host，`'self'` 覆盖不到）→ 生产构建 IPC 全断
  → 登录/采集/同步全部失败。
- guard 脚本 `check-csp.mjs` 只做反向校验（拒绝危险项），对必需 IPC 源无
  正向要求，因此拦不住该回归。修复：B 补 `ipc: http://ipc.localhost` 并给
  guard 加正向校验。

## D7（P2）当日空草稿计划吸收不了新任务

- 根因：`backend/services/planner.py` `resolve_today_plan()` 复用当日 open
  plan 时不检查 items 是否为空；`is_client_valid_plan` 对空 items 返回
  `all([]) == True`，新建任务后 today 永远返回旧空草稿。
- 修复：A（复用条件加「items 非空 或 无待排任务」）。

## 流程备注

- 两侧修完、CI 全绿后重跑 Windows 构建包人工验收（清单见两个任务文件），
  通过后 PR #1 方可转正合并。
- 完成报告必须附可 fetch 的 commit hash（对 A、B 一视同仁）。
