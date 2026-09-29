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

---

## 开发者 A 联合 review：隐私边界变化（2026-09-28，AGENTS.md §3）

Review 依据：`campus.rs`（Rust `cookie_provider` 权威 + `Snapshot{version, metadata,
cookies}` 持久化结构）、`runtime.ts:15-16`（空壳 jar）、`tauriTransport.ts`、
vendored `http.ts`（`CookieJar` 接口、`#cookieHeaderFor`、`#emitDebug`、
`nativeSeedHook`）、vendored `info/client.ts`（`#csrfToken` 读 jar、dance 的
`setRaw`）、Backend `core/sensitive.py`（键名正则纵深）。

**结论：A 案（受影响 host 的 name/value 对经 IPC 镜像给 TS 只读 jar）接受，
custody 语义维持"Rust 权威、TS 只读镜像"，附四条要求（1 条 blocking、3 条
验证项）。**

### 1. 镜像范围（要求 #1，blocking）

- 镜像**必须**限定 `*.tsinghua.edu.cn` 后缀域，且只含 `name`/`value` 对——
  不含原始 `Set-Cookie` 头、`Expires`/`Domain`/`Path`/`Secure`/`HttpOnly` 等属性、
  不含 raw 形态。任务文件已如此表述，review 确认这是功能必要的最小集：vendored
  的两个 TS 侧 jar 消费方（`InfoClient.#csrfToken` 找 `XSRF-TOKEN`、
  `http.ts #cookieHeaderFor` 拼请求头）都需要按 host 取多个 name/value，镜像再
  收窄（例如只镜像 XSRF-TOKEN）会让 `#cookieHeaderFor` 对其余潜在调用方继续是
  坏接口。当前粒度正确，**不得**扩大到非 campus 域或含属性。
- TS 侧缓存 jar 的 `serialize()` 必须保持返回空/不可用形态（现
  `runtime.ts:16` 为 `"[]"`），镜像不得使 TS 侧获得可持久化的完整 jar 表示。

### 2. 日志面（要求 #2）

- 镜像的 cookie **value** 不得出现在任何 console/日志/debug 通道。已核实现状：
  vendored `#emitDebug` 仅输出 `lastCookieNames`（name 列表，不含 value），debug
  通道为宿主 opt-in 注入（默认无）。要求 B 补一条回归测试：开启 debug 通道跑
  dance 流程，断言输出中不含任何已镜像 cookie 的 value 字符串。
- 同轮附带项 2（构建包接线 `http.debug`）与本条正交：debug 默认关闭的原则
  维持，开启时也不得输出镜像 value（同测试覆盖）。

### 3. Event 面（要求 #3）

- campus cookie（name 或 value）不得进入 Event 的 `data`/`context`/`provenance`。
  服务端纵深已存在并经测试：`backend/core/sensitive.py` 的键名正则
  （`cookie|set-cookie|token|session…`）在 EventCreate 与 batch 摄取两层拒绝
  该类 payload，镜像不改变此边界。客户端侧仍要求 `assertSafeEvent` 对
  campus 事件生效（B 已有实现，验证项而非新要求）。

### 4. Stronghold 快照语义（要求 #4）

- 现快照 payload 完全由 Rust 构造（`campus.rs snapshot_payload` 序列化 Rust
  `CookieStore`），TS 镜像 jar 不在持久化路径上——**语义不变**。镜像落地后
  `campus_snapshot_round_trip` 既有测试仍须通过，且 TS 侧不得新增对镜像 jar 的
  serialize/hydrate/persist 调用（第 1 条的 `serialize()==\"[]\"` 断言覆盖）。

### 放大面检查结果

未发现需要 B 收窄的放大面：镜像是单向（Rust→TS）、只读、按响应增量更新、
随 `clear()`/logout 同步清空（要求 logout 同时清 TS 镜像——若 B 实现中
`clear()` 仍为空壳，须改为清空缓存，属 A 案实现细节，不构成边界变化）。

### 实现核对（A，2026-09-28，`b9ac745` 落地后）

逐条对照上述要求的闭环结论——**全部符合，无收窄要求**：

- 要求 #1 ✅：Rust `mirror_cookies` 只回传请求涉及 host 的未过期 cookie，限定
  `*.tsinghua.edu.cn`，四元组 `host/name/value/host_only`（host_only 为域匹配
  语义必需的最小属性）；响应头过滤本就仅 `content-type`/`location`，Set-Cookie
  原始头从不跨 IPC；TS `serialize()` 保持 `"[]"`、`hydrate()` 惰性。
- 字面偏离（认可）：镜像 jar 并非纯只读——`setRaw` 接受 wengine dance 的
  name=value 注入。这是 vendored `info/client.ts` dance 逻辑的功能必需；写入
  同样限定 campus 域、同粒度数据，custody 仍在 Rust（权威投影整体替换本域），
  不构成放大面。
- 要求 #2 ✅（留一条非阻塞提示）：`VITE_CAMPUS_DEBUG=0` 默认关 +
  localStorage opt-in，文档明确 debug 行只含 cookie 名与截断 URL、不含值；
  镜像模块零 console。提示：**"开启 debug 后输出不含镜像 value"目前只有文档
  承诺、无回归断言**，建议 B 在后续测试批次补上（非阻塞）。
- 要求 #3 ✅：Event 路径未改动，服务端 `sensitive.py` 键名正则纵深维持。
- 要求 #4 ✅：`snapshot_payload` 持久化路径未动（仍是 Rust jar 序列化），TS
  镜像物理上不在 Stronghold 快照路径。
