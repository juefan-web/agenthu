# D8：Info 域 XSRF 依赖惰性 jar（merge-2 P0）

负责人：开发者 B。输入：`HANDOFF/2026-09-28-merge1-acceptance-round2-report.md`。
根因已经代码复核确认，无需重新诊断；诊断 worktree `C:\agenthu-dbg`（含 debug
补丁）保留供复现。

## 根因（已核实）

- `InfoClient.#csrfToken()`（`vendor/onethu/core/src/info/client.ts:950-963`）：
  `read()` 从 `this.#http.jar.getCookies(new URL(INFO_PREFIX))` 找 `XSRF-TOKEN`；
  无则 `#wengineCookieDance()` 后重读；仍无即 `throw new AuthRequiredError()`。
- 桌面运行时 `runtime.ts:16` 的 jar 是刻意的空壳（`getCookies: () => []`，
  「Cookies stay in Rust」）。dance 的 Set-Cookie 进入 Rust 原生存储，TS jar
  恒空 → `read()` 恒空 → **必然抛错**。与账号/网络无关。
- 调用链：`getSchedule → #ensureZhjw → #roamInfoService → #csrfToken`；
  `collectSnapshot` 的 `Promise.all` 被 schedule 侧否决，learnPromise 白跑。
- learn 域不受影响的原因：learn 的 `_csrf` 从课程列表页 HTML 正则提取
  （`learn/client.ts #fetchCsrf`），不读 jar。http.ts `#cookieHeaderFor` 也读
  jar 但同样惰性、无害（真实附 Cookie 由 Rust 每请求完成）。
- 影响面：所有走 `#roamInfoService` 的 info 业务（课表、个人信息、yyfw 漫游）
  在当前架构下永远失败。

## 修复方向（推荐 A 案，B 可按实现代价择优）

- **A 案（推荐，零 vendored 改动）**：`campus_request` 的响应载荷附带受影响
  host 的 Cookie 镜像（仅 `*.tsinghua.edu.cn`、仅 name/value 对，不含原始
  Set-Cookie 头与其他属性）；`tauriFetch` 在 resolve 前同步更新 TS 侧只读缓存
  jar，`getCookies` 从缓存读。custody 仍在 Rust（权威源），TS 只有只读镜像；
  dance（请求→响应→缓存更新→重读）时序天然成立。
- B 案：vendored `InfoClient.#csrfToken` 改为调用专用 Rust 命令（如
  `campus_xsrf_token`）取值——侵入 vendored 代码，且 jar 接口对其余潜在消费方
  仍是坏的，仅作备选。
- 隐私边界变化无论哪种方案都需记录：当前「Set-Cookie 永不进 WebView」的保证
  收窄为「原始 Set-Cookie 头不进 WebView；campus 域 name/value 对经 IPC 镜像
  给 TS 适配层」。写入 `CURRENT_STATE.md`，并与 A 共同 review（AGENTS.md §3）。

## 同轮附带项（小）

1. **采集路径错误透出**：`collectOnce`/`read` 把 `AuthRequiredError` 折叠成通用
   「校园会话已失效」——改为透出底层 message（本轮测试者需注入日志才可见真实
   错误）。加回归测试。
2. **构建包接线 `http.debug`**：官方包无法执行 LEARN-SILENT/INFO 现场定位
   （任务文件明确要求的步骤无法做）。提供 opt-in 开关（如环境变量或诊断菜单），
   默认关闭、不记敏感值。
3. **21ms 瞬态失败**：疑似采集失败后 `session.reset()` 与重新登录 `applyStatus`
   的状态同步竞态——D8 修复后观察是否复现，复现则修复并加测试。

## 验收标准

- 真实账号构建包：登录 → 采集（课表+校历+课程+作业全部成功）→ Event 入队 →
  同步；「重试同步」可操作，断网重试与队列恢复路径可测（round-2 被阻塞的
  验收项解除）。
- D2 未受信分支（双轮 2FA 提示）与 D3 错误透出/原地重发获得一次真实复测。
- DevTools 无 CSP violation 维持；新增测试（jar 缓存 dance→read、错误透出）
  与 lint/typecheck/test/build、cargo test、CI 全绿。
- 隐私边界变化记录 + A 的联合 review 意见。

## 不负责

- Backend 侧无对应改动；不重构 vendor 的 CookieJar 接口语义（如需改动先提
  契约讨论）。
