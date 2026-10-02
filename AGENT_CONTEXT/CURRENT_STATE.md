# CURRENT_STATE

Updated: 2026-10-02 · Milestone: **M3（让回答有据可依：资料摄取 + Memory 检索/grounding + 引用）**。M2 已关闭（main `e2a80e6`，出口判据「四绿三窗口双人」达成，见 2026-10-02 条目）。M0/M1 已合并（PR #1-#15，round-5 数据闭环验收通过 + e2e 首跑解锁）；对概念基线的完整差距评估见 `HANDOFF/2026-09-30-implementation-evaluation.md`（§8 七子句：4 达成 + 1 部分 + 2 缺失），M2 出口判据即该报告末节的场景化 §8 全句。路线大纲（M2–M8）已经 A/B 确认采纳（**D-030 accepted**，含三处修订：M3 同步产出删除/依赖图设计、TECH_STACK 依赖方已注取代、m2-breakdown 已对齐大纲口径）。
· 集成分支 `integration/study-time-m0` 已合并 Backend（`61fcf82`）与客户端
（`a2693e9`），冲突已解决，双侧 CI 与联合 drift check 全绿（draft PR #1）。
· **Merge-1 Windows 构建包人工测试结论：不建议转正合并**（见
`HANDOFF/2026-09-28-merge1-manual-test-report.md`，D1-D7 七项缺陷经代码复核全部
属实）。修复任务已立项：A 见 `TASKS/backend-merge1-review-fixes.md`（D5/D7），
B 见 `TASKS/client-merge1-review-fixes.md`（D1/D2/D3/D4/D6）。登录链修复参照上游
OneTHU dev3 实现，要求一次登录不重复认证。
· **A 的 D5/D7 与 B 的 D1/D2/D3/D4/D6 修复均已完成并推送到本分支**（A 见下方
第四轮修复之后的新条目，B 见客户端小节），双侧自动检查全绿。
· **Merge-2 验收结论（2026-09-28，`bcd53c8`）：仍不建议转正**（见
`HANDOFF/2026-09-28-merge1-acceptance-round2-report.md`）。D2/D4/D5/D6/D7 现场
确认修复通过；D1 的 learn 域修复生效，但采集卡在新的 **D8（P0）**：Info 域
XSRF 依赖惰性 jar（`InfoClient.#csrfToken` 读 `getCookies`，桌面 jar 为空壳），
确定性失败，已立项 `TASKS/client-merge2-d8-info-xsrf.md`（B）。A 的非阻塞
加固项立项 `TASKS/backend-merge2-hardening.md`。断网重试/队列恢复验收仍被
D8 阻塞；转正门槛 = D8 修复 + 第三轮构建包人工验收。
· **Merge-3 验收结论（2026-09-28，`bad00c7`）：仍不建议转正**（见
`HANDOFF/2026-09-28-merge1-acceptance-round3-report.md`）。D8 修复验证通过
（镜像 jar 打通 info 域 XSRF，learn 全链 success）；D2 未受信双轮提示与 D3
错误透出真实环境确认。新阻塞 **D9（P0）**：vendor 教务课表直连
`http://zhjw.cic.tsinghua.edu.cn:80`，Rust 白名单仅放行 https:443 双处拒绝
（根因含 vendor 加白注释：webvpn 包装 zhjw 曾实测撞引导壳，直连是上游验证
过的路径，故修复采用单 host http 窄开口而非改走 webvpn）。另有 D3 残留
（错误态缺原地重试入口）。**A 临时不在，本轮全部任务归 B**，见
`TASKS/client-merge3-d9-and-residuals.md`（D9、D3 残留、时延复核、compose
healthy 转 CI、debug 无 cookie 值断言）。转正门槛 = D9/D3 残留修复 +
第四轮构建包人工验收（重点：采集 → 入队 → 断网重试与队列恢复 → 真实数据
全链）。
· **Merge-4 验收（2026-09-29，`6a72dfd`）：D1-D9 全部真实环境通过，主线全链
  首次闭环**（见 `HANDOFF/2026-09-29-merge1-acceptance-round4-report.md`）：
  采集四域 100 条 / 同步 0.6s / 断网入队 100 条 / 恢复重试 939ms 全部按去重键
  正确结算；D3 残留原地重试实测闭环；全程 0 CSP violation。
  **D10 裁定（协调人，2026-09-29）：属 M1 范围决策，非 PR #1 缺陷**。依据：
  ① 事实成立——campus 事件类型与 Backend handler 注册表零交集；② 但 M0/M1
  冻结契约与 TECH_STACK M1 的 A 侧范围（Event 接收去重、Task/Deadline API、
  CurrentState 投影）从未包含 campus 事件派生 handler，Backend M1 规划原文即
  「真实（手动优先）导入适配层」；③ Task/Plan/Focus 链已在 API 造数路径完整
  验证（round-2/3）。round-3 任务文件中「真实数据驱动全链」的验收措辞系
  协调人在未知派生功能缺失时的预设，按「验收项只验证已承诺工作」原则修正。
  D10 立项为 **M1-1**（`TASKS/m1-1-assignment-event-derivation.md`，B 负责，
  A 回归后补 review），含已预核实的 deadline 时区坑（vendor naive 串 ×
  UTCDatetime = 8 小时偏移）。**据此 PR #1 转正合并进 main（2026-09-29）**。
  勘误：round-4 报告遗留项「compose healthy 终验移交」实际已于 merge-3 后由
  CI `compose-smoke` job 闭环（连续绿），无需人工环境。

## 开发者 A：Backend（`m0/backend-foundation` @ `61fcf82`）

- 完整 Backend 骨架：FastAPI、PostgreSQL/SQLAlchemy/Alembic、Redis/Arq、S3 兼容存储、
  Docker Compose、CI、Ruff、Pyright、pytest。
- 冻结 Auth / Event / Task / Goal / CurrentState / Memory / Plan / Focus / File /
  Permission / Audit / Jobs / Health 契约；两个迁移（13 → 14 表）从零验证无漂移。
- 确定性 planner 与完整 Study + Time 闭环集成测试；`GET /v1/plans/today` 与 Focus start
  由 advisory lock 保证并发幂等（D-019）。
- OpenAPI 导出到 `openapi.json`（40 paths）；OpenAPI/Zod 漂移检查挂入 CI（含
  `--require-zod`），冻结客户端 Zod 快照在 `tests/fixtures/client_contract.ts`（D-021）。
- Event 去重键转义与客户端 `eventDedupeKey` 一致（`\`/`:`，D-010）。
- **第四轮审阅修复（2026-09-28）**：
  - **K1**：client-invalid 计划不可创建（无 `task_id` 拒绝、时间从 `planned_minutes`
    回填）不可确认；`current_plan_for` 在 SQL 层过滤（`backend/services/plan_validity.py`，
    D-023）。
  - **C1**：每个 event handler 运行在 SAVEPOINT 内；DB 级 handler 失败不再回滚原始
    Event（用真实 PostgreSQL 错误验证）。
  - **S1**：`ENVIRONMENT` 默认 `production`（弱 `SECRET_KEY`/`S3_SECRET_KEY` 加载即拒）；
    认证端点限流（429 + `Retry-After`）；登录 dummy-hash 抹平 timing；job id 用户域化（D-025）。
  - **C2**：每个 Focus 完成都发 `focus.completed`（`completed` 标志收尾 session）；
    跨 session 实际时长累计；COMPLETED 粘滞、`completed_at` 不重写。
  - **C4**：全部 datetime 输入共享 `EventCreate` 的 naive→UTC 规则（`UTCDatetime`）。
  - 卫生项：审计中间件 DB 写移出事件循环；死代码 `recompute_user_current_state` 删除
    （D-024）；README 移除 `createbuckets` 引用。
- 验证快照：ruff/format/pyright 干净；全量 pytest（db/redis/s3mock）**182 passed**，
  1 skipped；漂移检查（`--require-zod`）通过；迁移 up→down→up + `alembic check` 通过；
  远端 CI run `36408669500` 绿。
- **Merge-1 人工测试修复（2026-09-28，本分支）**：
  - **D5**：`get_or_create_state` 改幂等插入（PostgreSQL `INSERT ... ON CONFLICT
    DO NOTHING`，其他方言 savepoint + IntegrityError 回退），并发首请求不再 500；
    注册 app 级 `Exception` handler——未处理异常返回约定 envelope 并按 Origin
    匹配补齐 CORS 头（`ServerErrorMiddleware` 在 CORS 之外，500 曾被 WebView
    显示为 CORS 错误）。回归：`test_current_state_concurrency.py`（5 连接 barrier
    竞态，恰好一行 state）+ `test_cors.py` 两个 500 envelope/CORS 断言。
  - **D7**：`latest_open_plan` 复用条件加「items 非空 或 无 pending tasks」——
    当日空草稿不再吞掉新建任务（`is_client_valid_plan` 对空 items 恒真的盲区）。
    回归：空草稿 → 建任务 → today 重排含新任务（`test_plans.py`）。
  - 协作项（D4）后端侧确认：联合 drift check（真实 `packages/contracts` +
    冻结快照）无漂移，`title` 保持"允许的额外字段"直到 B 落地
    `PlanItemSchema.title` 后双方同步冻结基线。
  - 文档：`HANDOFF/2026-09-28-merge1-manual-test-report.md` 补录（修复
    CURRENT_STATE 的悬空引用）。
  - 验证快照：ruff/pyright 干净；全量 pytest **187 passed**，1 skipped；漂移检查
    （`--require-zod`，双 Zod 源）通过。
- **Merge-2 期间 Backend 加固（2026-09-28，非合并门槛，见
  `TASKS/backend-merge2-hardening.md`）**：
  - `docker-compose.yml`：`api` 补 readiness 探针（`/health/ready`，含 db+存储
    检查）、`worker` 补 arq 心跳键探针（`arq:queue:health-check` 为 PSETEX TTL
    键，过期即 worker 死亡）；`--reload` 与代码 bind mount 移入显式 `dev`
    profile 的 `api-dev`（`docker compose --profile dev up api-dev`），`api`
    变为 production-like。两条探针命令均已在本地真实 uvicorn/arq 服务上验证
    通过（镜像构建因本机无法访问 Docker Hub 留给 CI docker-build job 首跑）。
  - CI 新增 `pip-audit` job（全环境漏洞扫描；当前 0 漏洞 0 豁免——唯一发现
    pytest 8.4.2 PYSEC-2026-1845 已通过升级消除：pytest 9.0.3 + pytest-asyncio
    1.4.0，187 测试全绿、警告 12→2）与 `docker-build` job（只构建不推送，防
    Dockerfile 漂移）。
  - **D8 隐私边界联合 review 已给出**（全文见 `TASKS/client-merge2-d8-info-xsrf.md`
    末节）：接受 A 案（campus 域 name/value 对经 IPC 镜像给 TS 只读 jar），
    1 条 blocking 要求（镜像限定 `*.tsinghua.edu.cn` 且不含 Set-Cookie 原始头/
    属性，TS `serialize()` 保持空）+ 3 条验证项（debug 通道不含 value 的回归
    测试、Event 面服务端纵深已确认、Stronghold 快照路径不含 TS 镜像）；未发现
    需要收窄的放大面。
- **M1 期独立任务（2026-09-29，`feature/m1-currentstate-projection`，见
  `TASKS/backend-m1-tasks.md`）**：
  - **A-1（还债）**：D9 明文 cookie 边界的悬空联合 review 已补齐——**D-026**
    落地（裁定 + 残余风险 + revisit 条件：上游 ZHJW_PREFIX 转 https 当天收回
    窄口）；对 `6a72dfd` 的实现核对（范围最小性 / 重定向继承 / 伪造测试覆盖）
    附于 `TASKS/client-merge3-d9-and-residuals.md` 末节，**结论通过、无收窄
    要求**，一条非阻塞提醒（vendor 升级流程带窄口收回检查）。
  - **A-2（M1-2 预研→落地）**：CurrentState 投影语义冻结为 **D-027** 并完成
    实现——`available_minutes` = override 优先，否则
    `max(0, 本地日剩余 − 今日课表重叠 − 当前任务剩余估时)`（课表取
    `time.schedule.entry` 事件、同 upstream_id 只取最新版本次、naive 串按
    DEFAULT_TIMEZONE 组合；rest_reserve 显式 0；derived 不落列避免与 M1-1
    迁移分叉）；`context` 派生链 override > 在课 > 专注中 > 进行中任务 >
    即将上课（≤30min）> 空闲 > None，经内部 `context_label` 传递，**客户端
    契约零变化**（drift 双源验证无漂移）。可观测性：`recent_state.
    available_minutes_breakdown` 记录输入摘要。8 个回归测试（固定时钟去
    flaky）覆盖全部分支。完整口径与 B 的 round-5 对齐清单见
    `TASKS/m1-2-currentstate-projection.md`。
  - 验证快照：ruff/pyright 干净；全量 pytest **195 passed**，1 skipped；
    drift check（`--require-zod` 双 Zod 源）无漂移。
  - A-3 backlog（keyset 分页、Redis 限流、Memory 预研）按窗口排期，未动。
- **M1-1 Backend 实现（2026-09-29，`feature/assignment-event-derivation`）**：
  - 阶段 0 契约冻结落地为 **D-028**（派生规则、Task upsert 键与 Event dedupe
    键的关系、deadline 时区 a 案、不派生清单、回滚语义）。
  - 实现：`tasks.source_upstream_id` 列 + `(user_id, source, source_upstream_id)`
    唯一约束（迁移 `b1d4a7c90e12` up/down 已验证）；`study.assignment.
    discovered|updated` handler 运行在 C1 savepoint 内（幂等 upsert、
    submitted/graded → COMPLETED 粘滞、`*_raw` 溯源进 `extra`）；deadline
    naive 拒收作用在两个边界（events 单发 422 + batch `rejected` 不入库；
    `TaskCreate/Update` deadline 422——C4 对 deadline 的定向收紧，其他
    datetime 维持 naive→UTC）。`source_upstream_id` 不进 `TaskCreate`，
    `TaskRead` 暴露（客户端 Zod strip，契约零变化）。
  - 测试：6 个派生回归（创建/更新不重复/deadline 刷新、submitted 粘滞、
    naive 双边界拒收、并发同键恰好一个 Task、真实载荷回放含 `*_raw`）+
    main-chain 测试同步派生任务的新语义。
  - 验证快照：ruff/pyright 干净；全量 pytest **201 passed**，1 skipped；
    OpenAPI 刷新；drift check（`--require-zod` 双 Zod 源）无漂移；迁移
    up→down→up + `alembic check` 通过。
- **Round-5 遗留跟进（2026-09-29，`feature/round5-derivation-followups`，
  见 D-028 附录 / D-027 附录 / D-029）**：
  - **L5（已实现）**：哨兵作业（deadline 距事件时刻 >2 年，如上游 2099 占位）
    Event 层照常入库、派生层排除（回归测试含 submitted 哨兵与正常对照）。
  - **L3（已实现 + B 协作项）**：派生标题规则 = `{course_name}：{title}`
    （course_name 存在时，缺省纯 title，回退链 course/upstream），`course_name`
    进 `extra`。根因：vendor 标题是裸作业名、`CampusAssignment` 未携带 vendor
    已有的 `courseName`——**B 侧协作**：适配层补 `courseName` 并在事件
    `data.course_name` 透传（落地前按缺省分支渲染，向后兼容）。
  - **L4（确认记录）**：当日含项草稿/已确认计划不自动吸收新任务是 D-019/
    D-023 的预期（保护确认语义），显式路径 = cancel → 重排；M2 议「建议重排」
    提示（Level 1）。
  - **L2（D-029 冻结）**：tasks/events 统一 keyset 分页契约（opaque cursor、
    复合排序键、cursor 路径不返回 total、offset 兼容期后弃用），实现排 M2；
    短期过渡 = B 侧请求 `limit=200`（PR #14 已落地）。**D-029 附录（09-30，
    B 的 review 备注 1）补形状裁定**：tasks 裸数组保持、游标走 `X-Next-Cursor`
    响应头；events 走 `Page.next_cursor` 字段；cursor+offset 同传 422。
  - **L1（D-027 附录裁定）**：breakdown 经 `recent_state` 入契约（B 侧 Zod 一行
    `z.record(z.unknown())`），不建独立诊断端点；M2 实现。
  - 验证快照：派生回归 8 个全过；全量 **202 passed**（哨兵/标题用例并入）；
    ruff/pyright 干净。
  - **review 后续（09-30）**：PR #13 已合并（`bd834f1`）；B 的三条 review
    备置已裁定——备注 1（tasks 裸数组形状遗漏）补为 **D-029 附录**；备注 2/3
    （哨兵残留、空标题重置）保持现状并记录于 **D-028 附录补充**。

## 开发者 B：客户端（`feature/client-tauri-campus-adapter` @ `a2693e9`）

目标：Windows 上的 Study + Time 客户端路径；OneTHU 固定版本 → `CampusAdapter` →
统一 Event → Backend。不修改 Backend 数据库或 Agent 决策。

- React/Vite/Tauri 2 工程、共享 Zod 契约、vendored `@onethu/core`、Tauri transport、
  SQLite 待同步 Event/游标、Focus 草稿、Backend JWT 会话（操作串行化、晚到 401 守卫、
  持久化失败回滚）、Today/任务/Focus 工作台。
- 性能修复：HTTP Client 按会话复用；Stronghold 快照只在登录/变化时写；采集链并行。
- 风险修复：Cookie 按快照变化持久化；LocalEventQueue 损坏隔离备份；去重键转义。
- **安全加固（2026-09-28 审阅分配，见 `TASKS/client-security-hardening.md`）**：
  生产 CSP 收紧为 `self` + 本地 Backend 源（移除 `https:` 通配与 `unsafe-eval`，开发源
  移入 `devCsp`）；`scripts/check-csp.mjs` 挂入 build 拒绝回归；Backend 登录发起前清
  密码 state；Rust `queue_list` 逐行容错（坏行跳过+日志+不删数据，附单测）；
  `createCampusRuntime` 只暴露 `adapter`。
- **安全加固（2026-09-28 审阅分配，见 `TASKS/client-security-hardening.md`）**：
  生产 CSP 收紧为 `self` + 本地 Backend 源（移除 `https:` 通配与 `unsafe-eval`，开发源
  移入 `devCsp`）；`scripts/check-csp.mjs` 挂入 build 拒绝回归；Backend 登录发起前清
  密码 state；Rust `queue_list` 逐行容错（坏行跳过+日志+不删数据，附单测）；
  `createCampusRuntime` 只暴露 `adapter`。
  2FA 等待期密码驻留不修：vendored info-lib 的 id roam 需重放明文密码，属上游约束。
- **Merge-1 修复（2026-09-28，见 `TASKS/client-merge1-review-fixes.md`，参照上游 OneTHU
  dev3 `infoLib.ts`/`clients.ts`）**：
  - **D1**：登录链成功后显式 `roam(helper,"id","bb5df852…/0")` 建立 learn 会话（失败容忍，
    采集时 resume/凭据链兜底）；`runtime.ts` 接线 `learn.credentialProvider` → gateway
    `silentReloginCredentials()`（仅登录链内存凭据期间供应，指纹/受信凭据取自 helper，
    避免与 session 展示指纹分叉）。
  - **D2**：设备指纹与 finger3 从 Stronghold 元数据回填（restore 探活前与每次 login 前），
    指纹跨登录稳定 → 受信设备 roam 重放免第二轮 2FA；未受信设备第二轮触发时状态携带
    `notice`（「安全策略要求对本机再次验证」）由 UI 显式展示，不再静默回选方式页。
  - **D3**：methodGate/codeGate 每轮由 hook 重建（多轮 2FA 原生支持）；验证码错误等使链
    settle 后，`send2fa`/`verify2fa` 用内存凭据自动重启链并应答方式（上游自愈同义，链纪元
    守卫防旧链收尾清掉新链状态）；上游 `LoginError` 中文文案直接透出（英文诊断折叠）；
    180s 超时改为每轮空闲独立计时，超时/取消文案分离。
  - **D4**：`PlanItemSchema` 增加 `title: z.string()`（与 A 的 D-021 冻结快照对齐，联合
    drift check 通过）；今日计划显示 `title`，`task_id` 仅作 key。
  - **D6**：`csp`/`devCsp` 的 `connect-src` 增加 `ipc: http://ipc.localhost`（Tauri v2 IPC）；
    guard 增加正向校验，缺失即构建失败（失败路径已实测）。
  - 凭据保留策略调整：校园账密在登录链存续期间保留于内存（链自愈与 learn 静默重登所
    需，上游 inflight 同语义），logout/下次登录/超时即清；仍不落盘。
  - 验证：桌面端 lint/typecheck/44 测试/build（含 CSP guard）、contracts lint/3 测试、
    根级 `pnpm lint/typecheck/test`（4 workspace）、`cargo test`（tauri.conf.json 编译期
    校验）全绿；`ENVIRONMENT=local check_contract_drift --zod` 无漂移；guard 缺 IPC 源
    失败路径实测拦截。
- **Merge-2 修复（2026-09-28 深夜，见 `TASKS/client-merge2-d8-info-xsrf.md`）**：
  - **D8（P0）Info 域 XSRF 读取失败**：`campus_request` 响应新增只读 Cookie 镜像
    （`cookies` 字段：受影响 host 的 host/name/value/hostOnly 四元组，仅
    `*.tsinghua.edu.cn`，匹配交给 cookie_store 的 RFC 6265 语义）；`tauriFetch` 在
    resolve 前并入 TS 侧镜像 jar（`cookieMirror.ts`：按 host 整体替换、`setRaw` 支撑
    wengine dance 注入、`clear` 接 `session.reset`）；`runtime.ts` 换掉空壳 jar。XSRF
    读取（webvpn 域）与 dance（请求→投影→注入→重读）时序成立，课表侧不再必然失败。
    Rust 侧新增 `mirror_cookies` 纯函数单测；TS 侧新增 dance→read 回归测试。
  - **隐私边界变化（待 A 联审，AGENTS.md §3）**：原保证「Set-Cookie 永不进 WebView」
    收窄为「原始 Set-Cookie 头与其余属性（Expires/HttpOnly/SameSite 等）不进 WebView；
    campus 域（仅 `*.tsinghua.edu.cn`）的 host/name/value/hostOnly 经 IPC 镜像给 TS
    适配层」。custody 仍在 Rust 原生仓（唯一权威，TS 镜像只读 + dance 注入）。
  - 附带：采集路径 `AuthRequiredError` 的底层 message 直接透出（不再折叠为通用
    「校园会话已失效」，附回归测试）；`http.debug` 构建包 opt-in 接线（构建期
    `VITE_CAMPUS_DEBUG=1` 或 DevTools `localStorage["agenthu.campus-debug"]="1"`，
    默认关闭；日志行仅 cookie 名与截断 URL，不含值，`.env.example` 已记录）。
  - 21ms 瞬态失败项按任务文件先观察，未改代码。
  - 验证：desktop 9 文件/50 测试、build、根级 lint/typecheck/test、`cargo test`
    7 测试全绿。
- **Merge-3 修复（2026-09-29，见 `TASKS/client-merge3-d9-and-residuals.md`，A 临时
  不在本轮全部归 B）**：
  - **D9（P0）教务课表直连被拒**：`allowed_campus_url` 为 `zhjw.cic.tsinghua.edu.cn`
    单 host 开 `http:80` 精确窄口（方案 a；b 案 webvpn /http/ 被 vendor 加白注释
    证伪——教务 host 的 wengine 票从未建立，上游 2026-09-19 起统一直连）。不做子域
    通配、不放开其他 http；重定向策略复用同函数自然继承。Rust 单测覆盖：接受
    zhjw http:80，拒绝其他 http host、zhjw 其他端口、`x.zhjw.…` 子域伪造与
    `zhjw.cic.tsinghua.edu.cn.evil.test` 后缀伪造。
  - **隐私/安全边界变化（A 回归后补联合 review 与 DECISIONS 编号）**：该 host 的
    教务会话 cookie 以明文 http:80 传输，范围限单 host，与上游实测路径一致。
  - **D3 残留（错误态原地重试）**：gateway 受控暴露 `canRetryTwoFactor`/
    `retryTwoFactor`（内部从 `restartChain` 提取 `reviveChain`，链纪元语义不变）；
    凭据仍在内存时 UI 错误态显示「重试验证（免重输密码）」——重启整链回 2FA
    表单或受信直接就绪；凭据已清（logout/超时后）维持完整登录表单。回归测试
    覆盖两分支（回表单 / 直接就绪）与入口关闭。
  - **错误码透出时延结论（观察项，未改代码）**：~30s 上限与 Rust transport 的
    单请求超时一致（`CampusClients` reqwest `timeout(30s)`）——上游 VERITY_CODE
    挂起时错误在超时点才落地；请求 settle 后客户端传播是微任务级
    （hook → signal.resolve → Promise.race，无额外轮询/退避）。收紧上限会误伤
    慢校园页面，维持 30s；若 round-4 实测需要更快反馈，候选方案是验证提交后的
    中间「正在完成登录」状态（需适配器自动应用终态，另行立项）。
  - **继承 A 的移交项**：①CI 新增 `compose-smoke` job（`docker compose -f …
    docker-compose.ci-smoke.yml --profile s3mock up -d --wait db redis s3mock api
    worker` + `/health/ready` 冒烟 + teardown；override 文件把 api/worker 的对象
    存储指向 s3mock 并钉 test 环境——compose healthy 人工移交终结）；②debug 通道
    脱敏 `redactCampusDebugLine`（`name=token` 形态 ≥20 字符长值遮蔽、cookie 名单
    与 URL 保留、超长行截断），runtime sink 接线，附「不含 cookie value」回归断言
    测试（A 的非阻塞建议）。
  - 验证：desktop 9 文件/53 测试、build、`cargo test` 7 测试、ci.yml 与 compose
    override YAML 校验通过；compose 真实拉起由 CI `compose-smoke` job 验证（本机
    无 Docker）。
- 验证：桌面端 lint/typecheck/39 测试/build（含 CSP guard）与 `cargo test`（6 测试）
  通过；CI（Client checks）绿。
- **M1 客户端加固（2026-09-29，`feature/client-m1-hardening` 自 main 拉出，见
  `TASKS/client-m1-hardening.md`）**：
  - **B-1**：`EventSyncCoordinator.flush` single-flight（采集完成/online 监听/手动
    重试三入口共享同一在途 Promise）；单批失败指数退避重试（默认 3 次、1s 起步），
    认证失败不重试（重发同 Token 无意义），超限停发并透出「已重试 N 次」文案，
    事件保留待同步队列等下次触发按批续传。回归测试覆盖并发共享、退避序列、
    超限停发、认证直抛、批间断点续传。
  - **B-2**：Rust 队列库重构为 `QueueStore`（单一长连接 + WAL + 5s busy_timeout，
    懒初始化于 `QueueDb`，全部 queue_*/focus_* 命令共享）。测试：WAL 模式断言、
    坏行隔离（store 级）、4 线程 × 25 次并发 add/list 全量落库（100/100，无
    locked/丢失）、事件/游标/草稿往返与幂等。
  - **B-3**：`campus_restore` 对版本不兼容/损坏快照自清理（返回 None → idle →
    登录表单即引导，测试覆盖未来版本/坏载荷/空载荷）；`assertSafeEvent` 移入
    `createEventQueue` 边界（SafeEventQueue 包装），未配置 Backend 的直接入队
    路径不再绕过敏感字段检查（附测试）。
  - **B-5.1**：`CampusConnection` 抽出为独立组件（`src/components/`，campus 单例
    移至 `src/campus/instance.ts`），Testing Library 覆盖登录/2FA 状态机 9 个
    用例：凭据提交即清密码、方式选择、双轮提示、验证码提交（含信任设备）、
    错误透出、原地重试两分支、取消重置、就绪态。
  - **B-4（backendUrl 运行时配置，暂缓待 A 对齐）**：倾向方案是 Backend 请求经
    Tauri 原生受控转发（与 `campus_request` 同构：原生侧持用户确认过的源
    allowlist，WebView CSP 无需放宽 `connect-src`；代价是 BackendClient 换
    transport，且原生转发无浏览器 CORS——Backend CORS 白名单可顺势收紧）。
    WebView-fetch 方案不可行：Tauri v2 CSP 仅构建期静态，运行时放行任意源等于
    回退到已废除的 `https:` 通配。方案定稿需 A 参与（安全模型 + CORS）。
  - **B-5.2（Playwright 冒烟，暂缓）**：round-4 已证 CDP 驱动构建包可行；沉淀为
    `tests/e2e/`（构建包 + `--remote-debugging-port` + data-testid 选择器驱动
    登录→采集→同步→计划→Focus），作为发布前回归套件，不在单元 CI 内跑。
  - 验证：desktop 10 文件/69 测试（+16）、lint/typecheck/build、contracts、
    `cargo test` 10 测试（+3）全绿。

## 尚未满足的验收项（合并 main 的前置门槛）

- **Windows 构建包人工端到端演练**（两位开发者共同）：校园登录/2FA → 采集 →
  Event 同步 → Task/Plan（显示 `title`）→ 确认计划 → Focus 完成 → 断网重试与冲突处理；
  DevTools 无 CSP violation，拒绝 Event 可见原因且不重复上传。
- 客户端开放项（2026-09-29 `feature/client-m1-hardening` 更新）：`flush`
  single-flight 与重试上限、SQLite `busy_timeout`/连接复用、`campus_restore`
  自清理、`assertSafeEvent` 无条件执行、Testing Library 状态机测试**均已完成**
  （见客户端小节 M1 加固条目）；剩 `backendUrl` 运行时配置（B-4，待与 A 对齐
  安全模型后动手）、Playwright 构建包冒烟（B-5.2，发布前回归套件）、Android
  凭据存储/通知。
- 发布前完成 OneTHU BSL 1.1、LearnX 及依赖许可的逐文件分发审查。

## Blockers / decisions needed

- **B 侧评审/会签（2026-10-01，第二轮）**：PR #18（D-031 迁移 + 契约同步）
  核验通过并合并 `de4e0dc`（本地 ruff/84 unit/drift 双源全绿 + CI 六项
  success；迁移与 B 修订逐项一致、`basis` never-null validator 边界确认、
  快照预置四行形状无误）。PR #19 B 会签随分支落盘：**D-032 转 accepted**、
  隐私文档双签转 accepted 并转录 **D-033**、迁移方案 §8 两项裁定——
  **superseded-by 方向确认**（B 独立复核坐实矛盾机制；D-031 §3 补勘误
  注记）、**correction_status 语义端点化采纳**（B 作为 Memory 页实现者
  补落地口径：correct 端点收覆盖值内部走版本链、reject 保持 REJECTED
  live 占位、页面按钮 ↔ 端点一一对应）。B 下一步：镜像四行 Zod（
  `basis`/`recent_state` optional-only、`replaces_plan_id`/`replan_reason`
  `.nullable().optional()`——三种形状别混）→ basis 面板/重排建议 UI/
  Memory 页（含三语义端点接线）→ E4 spec。

- **M2 B 侧第一批（2026-10-01）**：
  - **App.tsx 拆分已完成并在 main**——⚠ 落地方式异常：B 的暂存文件被同日
    协调人的提交 `9ba07c1`（Hermes 预研归档 + D-032 草案）一并裹入并推送
    main，**该提交信息未提及拆分**。内容即 B 验证过的树（87 测试/lint/
    build 全绿），main CI 六项亦全 success，功能无损；查证谱系以本条为准。
    拆分内容：应用级单例（backend/queue/focusDraft/sync）从 App.tsx 模块
    常量改为 `app/services.tsx` Context 注入（`useServices()`，测试可替换），
    视图拆入 `features/{plans,tasks,focus,backend}`，App.tsx 339→209 行纯壳；
    M2 三个新 UI 面（basis 面板/重排建议/Memory 页）落点已就位。纯重构
    零行为变化。
  - **e2e 两处健壮性修订**（首跑报告）在 PR #17 等 review：E1 标题放宽为
    任一主视图（旧实例可能停在任务/专注视图）、校园「密码」标签加
    `exact`（Playwright getByLabel 默认子串匹配会命中「Backend 密码」）。
  - **下一步依赖**：三个新 UI 面等 A 的 D-031 §5 契约同步（Zod 双源 +
    OpenAPI 原子落地，否则 drift 必红）——A 迁移 PR 出来后 B 接；E4 spec
    同期落地（含冷启动 seed 与 estimate_source 双向断言）。
- **Round-5 E 组 spec 修订已落地**（`feature/e2e-round5-revision`，round5-followups
  B-1）：E2 前置态改为「退出包进程 → 清 `campus.hold` → 带 CDP 重启」
  （`appProcess.ts`，需 `AGENTHU_APP_EXE`；先杀进程再删文件，等旧实例 CDP
  端口释放后才拉新实例）；2FA 方式从 combobox 实际可选项动态选择（不再
  硬编码 totp；按钮文案随方式适配）；测试超时放宽到 10 分钟（原 config
  180s 与等待人工验证码 300s 的既有矛盾顺手修复）。E3「派生任务出现且
  截止时间无偏移」**断言已按 A 的 request-changes 修订**（`3a9f2a5`）：
  偏移正则（环境耦合——docker UTC 库返回 Z 形态必误报）改为**时刻配对**
  ——作业事件 `data.deadline`（JSONB 原样载荷，+08:00 恒定）建时刻集合，
  派生任务 `due_at` 时刻须命中（8h 偏移必不命中、任何 tz 序列化不误报）；
  事件侧 +08:00 形态断言保留（客户端序列化不变量）；tasks/events 直连
  均 `limit=200`。UI 断言同前（徽标、标题非 UUID、页面引擎渲染比对）。
  e2e 目录补真类型检查（`@types/node` + `tests/e2e/tsconfig.json` 接入
  lint——此前仅 `--list` 转译口径）。首跑待与测试人约时间（E1 无凭据 +
  E2/E3 真实链，动态方式后预计验证码 1 个）；首跑通过后 M2 起验收以 e2e
  为常规工具。**等 A re-review**。
- **PR #13（round5 followups）B 侧 review 已完成：Approve 并合并 `bd834f1`**，
  三条备注记录在 PR review（① D-029 冻结设计遗漏——`/v1/tasks` 今天是裸数组
  响应非 Page，加服务端游标是破坏性形状变更，实现前需补形状迁移策略与
  cursor/offset 优先级；② 哨兵 early-return 会跳过后续更新事件，已派生任务
  以旧 deadline 残留的理论边角；③ 标题改为无条件赋值，空 title 事件会回退
  标题——客户端恒发非空 title，理论边角）。备注 1 已由 A 补为 **D-029 附录**
  （PR #15，B approve 并入 `434dafd`；B 补记了 `X-Next-Cursor` 会被 B-4 代理
  响应头白名单剥掉的落地依赖——M2 实现需加白名单一行，否则打包客户端静默
  停在第一页）。
- **B 协作项已落地并合并**（PR #14 `6ad5814`，PR #13 的配套）：
  适配层 `CampusAssignment` 补 `courseName`——vendor `Homework.courseName` 仅
  外部源携带，learn 作业从 `getCourseList` 建 `courseId→name` 映射
  （`getAssignments` 与 `collectOnce` 两个采集路径都接）；`events.ts`
  透传 `data.course_name`（缺失 null，后端按缺省分支兼容）；`getTasks`
  短期 `limit=200`（D-029 过渡）。87 测试（+2）/lint/build 全绿。
  **生效条件**：标题合成对既有任务在下次语义版本变化的采集时刷新。
- OneTHU 源/API 不可达 → 服务端 adapter 保持显式 stub。
- `minio/minio` 镜像上游 404 → 本地用 `s3mock` profile 验证。
- 联合 CI 应跑真实的 `packages/contracts` Vitest/typecheck；Backend 分支只有冻结
  快照替身（D-021）。
- **B 已正式 review 并 approve PR #9（GitHub 首次正式 approve；合并 `efc4c8c`）**，
  审查记录在 `HANDOFF/2026-09-29-b-review-pr9-task-source.md`。核验：diff 5 文件
  与声明一致；派生链路 `event.source → Task.source` 代码路径独立核实；本地重跑
  ruff/83 unit/drift 双 Zod 源全绿；分支 CI 6 checks 全 success。§3a 勘误准确
  反映 PR #4 审查备注 #1 的事实（rejected=移出+透出、恢复路径=重新采集、禁止
  保留重发特殊分支）。
- **PR #9 的客户端闭环已落地**（`feature/task-source-badge`，M1-1 B 侧验收项 2
  收尾）：`TaskSchema` 双侧（contracts + 冻结快照）加 `source: z.string().optional()`
  （旧 Backend 载荷缺失该字段仍可解析）；TaskList 从 App.tsx 抽为
  `components/TaskList.tsx` 并加来源徽标——`onethu` 标「校园采集」、未知来源
  显示原始字符串、manual/缺省不标；新增 6 个 RTL 用例 + 2 个 contracts 契约
  用例（source 保留、backend-only 字段剥离）；drift 双源无漂移，desktop 85
  测试 + contracts 5 测试 + lint/typecheck/build 全绿。注意：drift 检查器按
  逗号分割 Zod 对象体，对象内注释会被误解析为字段名——注释须写在 schema
  定义上方。
- **B 对 PR #4（D-028 实现 + B-4 拍板）的审查已完成：Approve**，记录在
  `HANDOFF/2026-09-29-b-review-pr4-derivation.md`（备注：D-028 §3a「留在客户端
  队列」措辞与客户端既有 rejected-移除行为不一致，建议文本勘误；`ClientTask`
  补 `source` 一行即可解锁「来源可辨识」UI）。
- **M1-1 客户端侧已落地**（`feature/m1-1-client-tz-events`）：`events.ts` 的
  `deadline`/`late_deadline`/`publish_time` 三字段统一经 `asCampusIso` 输出
  `+08:00` tz-aware ISO（naive 北京本地解释），原串保留 `*_raw` 溯源；旧
  `asIso` 的 `new Date()` 宿主时区依赖一并修复——assignment 的
  `occurred_at` 与课表 date-only 的 `occurred_at` 都按北京本地解释（旧实现
  date-only 走 UTC 零点 = 北京 08:00，偏 8 小时）。派生任务展示核对：截止
  时间经 aware ISO 回传后 `toLocaleString` 在任意 OS 时区正确；重复采集不翻倍
  由服务端唯一约束保证（A 已测）；「来源可辨识」等 `ClientTask.source` 补充。
  desktop 76 测试（+7 映射用例）/lint/build 全绿。
- **B-4 backendUrl 运行时配置已实现**（`feature/backend-request-proxy`，按 A 的
  2026-09-29 拍板）：新增 `backend_request` Tauri 命令——Rust 侧 allowlist 为
  唯一事实源（build.rs 注入构建期 `VITE_BACKEND_URL` 常量 + `backend_origins`
  SQLite 表持久化用户显式添加的源），转发谓词要求源在列且 https（loopback
  例外允许 http）；请求头白名单（Authorization/Content-Type/Accept）、响应头
  白名单（content-type/retry-after/location，**Set-Cookie 一律不透传**）、无
  cookie、**不跟随重定向**（Authorization 永不跨源）。TS 侧 `backendFetch`
  经 IPC 转发（浏览器开发模式沿用 fetch）；登录面板新增「Backend 地址」
  设置（Rust 验证通过才持久化 localStorage 并重载；清空回落构建期默认）。
  生产 CSP 收紧为 `'self' + ipc:`（Backend 源全部移出，guard 改为反向校验
  「生产 connect-src 不得出现 Backend 源」，失败路径已实测）；devCsp 保留
  浏览器开发源。Rust 4 个新单测（谓词/入列校验/头过滤/持久化并入），
  desktop 69 测试/build 全绿。构建包人工验收项：换源免重建实测 + DevTools
  无新增 CSP violation。
- **B 对 PR #3（D-026/D-027）的审查已完成：Approve**，记录在
  `HANDOFF/2026-09-29-b-review-pr3-currentstate.md`（含两条非阻塞备注：
  课表最新修订解析失败时会回退旧修订的边缘场景、派生 label 的 recompute
  时效已知悉）。round-5 呈现层对齐同步落地于
  `feature/current-state-presentation`：今日计划标题新增 `available_minutes`
  徽标（`formatAvailableMinutes`，`XhYm` 格式，null 不渲染），「空闲」派生
  默认与 None 占位文案确认维持。desktop 56 测试/build 全绿。
- **B-5.2 构建包冒烟已脚手架化**（`feature/e2e-smoke`，`tests/e2e/`）：Playwright
  经 CDP 附着已运行的构建包 WebView（`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=
  --remote-debugging-port=9222` 启动，README 记录全流程）；两用例——外壳渲染
  （无凭据可跑）与真实账号主链（登录/2FA→采集→同步归零→专注入口；2FA 验证码
  人工输入半自动，≤5 分钟等待）。vitest 已排除 `tests/**` 防误收集；不在单元
  CI 内运行，定位为发布前/验收前手动回归。本机无构建包故未实跑，`--list`
  收集与编译已验证。

## Next（2026-10-02 更新：**M2 正式关闭，M3 双侧开闸**）

- **M3 首日教训遗留清偿（B，`fix/clock-sensitive-plan-assertions`）**：
  ① **墙钟类断言全量排查完成——该类已全部有守卫，无新增缺口**。守卫三形态：
  共享 helper `_skip_late_night`（test_plans 4 处 + test_client_main_chain
  1 处）、内联守卫（test_focus_loop <65 分钟、test_plans_concurrency
  首测 <130——注意 git grep \"_skip_late_night\" 搜不到内联形态，盘点须按
  \"midnight/skip\" 模式二次排查）、固定晨间 `start_at`（orders 测试与
  test_planner_v2 整类——从设计上脱离墙钟，优于跳过）。其余 `plans/today`
  调用者（contract/cors/复用类/并发隔离）断言的是 ID/复用不变量或空列表下
  空洞的 per-item 检查，与时钟无关。② diffPlans 5s flake：desktop vitest
  `testTimeout` 上调至 10s（两次复现均在默认 5s；只影响失败反馈延迟）。

- **M2 关闭（收口报告：`HANDOFF/2026-10-02-m2-closure.md`）**：AGENTS §8
  验收句在自动化 E4 出口判据全链走通——**四绿三窗口双人**（A 02:00/10:04/
  11:26，B 11:37 于 main `6bd1839` 全新栈+新账号，2 passed 27.3s）。
  合并清单 #17–#32 全部双审；教训五条入库（夜间墙钟守卫类待 M3 首日
  全量排查、枚举绑定漂移与纯迁移库封堵、CI flake 观察项、worktree 规则、
  D1 时账 ~13s→≤2.5s）。
- **M3 队列（并行开闸）**：A = pgvector 切片、D-033 资料摄取（provider
  政策首核为摄取硬前置）、Memory 检索接线、批末重算尾巴、D-029 分页
  （含 B-4 代理 `x-next-cursor` 白名单一行）。B = 讲解页/引用跳转（等 A
  后端切片）。
- **D-033 资料摄取批次开出（2026-10-02 晚，A @ `feature/m3-materials-ingestion`）**：
  前置全达成（#36 会签/双核完成 → 摄取解锁；#35 pgvector 已合 main）。范围 =
  后端摄取管线全链 + 供应商边界第一刀，规格与接口冻结见
  `TASKS/m3-materials-ingestion.md`（§8 为 B 侧并行依据）：迁移
  `c8f2a14d6b93`（material_chunks + grounding_consents 两表 +
  file_objects.course_name）；内容安全扫描器（`core/scanner_rules.py` 版本化，
  指令形态 hard block 不入库、不可见 Unicode flag+归一化重扫、对抗 fixture
  回归）；抽取器（PDF 文本层 / PPTX / txt，按页分块 ≤2000 字符）；
  `adapters/model_provider/`（OpenAI embeddings，fail-closed 无 key 即拒；
  Responses 构造 `store=False` 钉死 + 断言测试）；per-course opt-in
  （`GET/PUT /v1/grounding-consent`，同意文案 v1 版本化，旧版本 opt-in 422，
  文案含「≤30 天滥用监控保留」披露）；worker `extract_material` /
  `embed_course_backfill` + 两个兜底 cron（lost-enqueue 扫描 60s 宽限 +
  对象孤儿重试）；上传带 `course_name` 表单字段才进管线（非课程文件零影响）；
  **删除顺序修正**（行事务先删 chunks 级联，对象 best-effort + Redis orphan
  集，D-033 §5）；`GET /v1/files/{id}/chunks`。验证：单测+集成 262 passed、
  ruff/format 干净、迁移 up→down→up + alembic check 无漂移、契约 drift 零
  （客户端 Zod 无改动）。**未做（后续批次）**：向量召回（等 #37）、grounded
  回答/引用校验、HNSW、worker 任务函数的 Redis 端到端专测（编排逻辑已服务层
  覆盖）。**语义注记**：关闭 opt-in 不删已有 embedding（本地数据，删除是
  Level 2 独立动作）；flagged chunk 入库但永不嵌入/外送；blocked 不入库仅
  文件元数据计数。

## Next（2026-09-29 更新：**M1-1 验收通过，正式收口**）

- **Round-5 验收（2026-09-29，main `aa9773e`）：A/B/C/D 四组全部通过，无
  P0/P1 缺陷**（报告：`HANDOFF/2026-09-29-round5-acceptance-report.md`，三处
  计划修订已按修订口径执行）。真实采集 103 条 → rejected 0（+08:00 判据）→
  50 个派生任务（徽标/标题/分钟级截止一致）→ 幂等不翻倍 → D-027 投影首次
  实测（「在课」context + 2h15m 徽标）→ 换源免重构建（8001 独立库证伪式
  验证）→ 断网队列重放不翻倍 → 全程 0 CSP violation。**Study + Time 真实
  数据闭环达成**（勘误 2026-09-30：此前写「§8 首阶段验收主链达成」系
  过度声明——§8 共七个子句，round-5 实际达成 4 项 + 计划授权半项；
  「可解释计划」「偏差重规划」「学习记忆」三项目前缺失，见
  `HANDOFF/2026-09-30-implementation-evaluation.md` 的逐句记分卡）。
- **E 组（e2e 工具化）✅ 已完成（2026-09-30 首跑全绿）**：spec 三处修订
  （PR #12，含 E3 绝对时刻配对）+ 首跑 **3 passed (2.2m)**、人工验证码 1 个
  （报告：`HANDOFF/2026-09-30-e2e-first-run-report.md`）。**M2 起验收工具化
  正式解锁**；下一轮验收口径：e2e（E1-E3）先跑，人工组聚焦故障注入与新增
  功能。首跑暴露两处 spec 健壮性问题（E1 视图假设、E2 选择器歧义，代码已
  核实 L44/L47）——B 小 PR 修订（不阻塞，复跑已全绿）。
- 后续任务已分派：`TASKS/round5-followups.md`（B：E 组 ✅ + D1 快速失败；
  A：L2 ✅ 短期 / D-029 正解、L1/L3/L4/L5 ✅ 已裁定或实现）。
- M2 规划输入：D1 断网快速失败、L1 breakdown 出口、L4 草稿吸收语义、
  events/tasks keyset 分页、多 worker Redis 限流；M3 Memory/Grounding
  预研启动。
- **M2 阶段 0 契约冻结产出（2026-09-30，A @ `feature/m2-phase0-contract-freeze`，
  待 B 评审）**：三项冻结为 **D-031**（PlanItem.basis 与 recent_state 入
  契约、重排建议 Level 1 形状与「接受即取代」、Memory 五项扩展形状与
  M2 六列/M3 embedding 切片、`estimate_source` 估时语义）；LLM 推迟已由
  D-030 覆盖。随附 M3 两份先决文档草案：`TASKS/m3-memory-schema-migration.md`
  （含 D-030 修订要求的删除/依赖图设计）、`TASKS/m3-course-materials-privacy.md`
  （课程资料隐私/合规，待双人签署）；E4 场景草案与 fixture 冷启动注意见
  `TASKS/m2-phase0-contract-freeze.md`。
- **A 第一批落地（2026-10-01，独立 worktree 作业）**：PR #16 已合并
  （`129c2f4`，D-031 accepted 含 B 两处修订）。A 已正式 **approve PR #17**
  （e2e 健壮性小修；根因核验：`App.tsx:260`「Backend 密码」标签致
  getByLabel 子串双匹配）。闸门 **PR #18**（`feature/d031-migrations-
  contract-sync` @ `5c2a05c`）开出：两条迁移（`d41c8f2a9b07`
  `plan_items.basis` + `e52a9d3b1c48` memories M2 切片——六列+遥测两列+
  版本感知部分唯一索引（B 修订版直建）+supersedes 反向链索引+evidence
  GIN+kind 按 level 回填）+ D-031 §5 Backend 侧契约同步（**basis 线上永不为
  null**，缺省 `{}` 走 recent_state 模式——冻结 Zod 行 optional-only 拒绝
  null，与 B 给 replaces_plan_id 补 `.nullable()` 同源问题；`ClientPlan`
  补 `replaces_plan_id` 映射；冻结快照按 title 先例预置四行待 B 镜像；
  OpenAPI 刷新）。验证：**211 passed**（main 202）/ruff/pyright 0 errors/
  迁移 up→down→up + `alembic check`/drift 双源全绿。PR 内 flag 了
  **supersedes_id 链方向矛盾**（live=IS NULL+索引+FOR UPDATE 仅
  superseded-by 方向自洽；§5 括注「新行指旧行」与之冲突）。**签认欠账已办**
  （`feature/a-signoffs-d032-m3docs`）：D-032 A 签（待 B）、两份 M3 先决
  文档 A 签；迁移方案 §8 提交两项待 B 会签裁定（supersedes_id 方向勘误
  提案 = superseded-by、correction_status 语义端点化 A 立场倾向采纳）。
- **PR #18/#19/#20 收口 + A 第二批（2026-10-01）**：#18/#19 已由 B approve
  并合并（`de4e0dc`/`ea46ee3`）；**superseded-by 方向经双方独立复核确认**
  （D-031 §3 勘误注记落盘）、语义端点化采纳（排 M2 Memory 页批次）、
  D-032 双签转正、隐私决策转录 **D-033**；A 已 approve PR #20（四行 Zod
  镜像，drift 双源交叉验证通过）。**A 第二批在途**
  （`feature/memory-lifecycle-endpoints`）：Memory 三语义端点
  （`confirm`/`correct`/`reject`，correct 走 superseded-by 版本链，
  reject 保持 live 占位；`MemoryCreate/Update` 移除 correction_status
  直填）+ **接受即取代**（confirm 带 `replaces_plan_id` 的计划同事务
  SUPERSEDED 被替代 CONFIRMED 计划，幂等跳过非 CONFIRMED）。
  **实现期新裁定**（迁移方案 §3 补记 + 迁移 `f63b7e2a5c91`）：superseded-by
  的写入顺序被部分唯一索引钉死（旧行先退、新行后插），旧行指针指向尚未
  插入的新行 → **FK 定为 DEFERRABLE INITIALLY DEFERRED**（commit 时校验）；
  live-key 冲突走 D-003 先查后插模式（savepoint 只兜真竞态，避免 flush
  失败毒化共享测试会话）。验证：**215 passed**（main 211）/ruff/pyright 0/
  迁移 up→down→up + `alembic check`/drift 双源全绿。
- **A 第三批（2026-10-01 晚，`feature/planner-v2-estimate-learning`）——
  planner v2 + 估时学习 + L1/L2 写入者**：① `slots_v2`——空闲槽（复用
  `_today_schedule_entries` + 10 分钟缓冲、08:00 起算、日终截止）→ 确定性
  打分（slack+goal+priority）→ >90 分钟拆块 → 塞槽总量受 D-027 口径
  available_minutes 约束（badge 与计划不再打架）；每项写结构化 basis
  （deadline/slack/estimate+source/slot_reason/score/at_risk），中文人话
  reason 由 `plan_reason` 从 basis 渲染（**strategy 标签泄露为 reason 的
  旧回退已删除**——正是评估报告的原始批评）。② 估时学习——`focus.completed`
  同步写 L1 episode（含 deviation_note、evidence 指向事件）+ L2 行
  （`estimate:course:<course>` 中位数 / `estimate_ratio:user` 截尾均值，走
  `upsert_keyed_memory` superseded-by 版本链、REJECTED 阻断再派生、值不变
  不换版本）；planner 经 D-031 §4 阶梯读取（user > learned:course(n≥2) >
  learned:ratio(n≥3) > default，激活由样本数门控而非通用置信度下限）。
  **ratio 采样勘误（A 提案待 B 会签）**：无计划项的完成不计样本。
  ③ **plans 列表 status 过滤改客户端枚举**（draft→{DRAFT,PENDING_CONFIRMATION}、
  superseded→{SUPERSEDED,CANCELLED}，大小写都收）——修复 #22 横幅与 E4
  spec 的 `?status=draft` 422（D-009 客户端契约优先；已实证 422 复现）。
  验证：**220 passed**（main 215，+5 planner v2 集成）/pyright 0/ruff/
  drift 双源绿。E4 服务端孪生测试 = `test_planner_v2.py`（避课表/learned
  双向/拒绝阻断/状态过滤）。
- **A 第四批 = M2 末批写入者（2026-10-01 深夜，`feature/trigger-engine`）——
  重排建议触发引擎**：`services/replan_triggers.py` 四类触发（Focus 超时
  ≥1.3×/提前 ≤0.5×【reason 引用实际分钟数，E4 断言点】、确认后 48h 内
  新任务【L4 显式路径，手动任务经 tasks 端点同样标脏】、已确认项时段已过
  未开始【排除 RUNNING/PAUSED 会话】、今日课表确认后变更；摆状态触发待
  CurrentState 补齐后置）。**签名幂等**（已产生过建议的事实不再重复触发，
  重复评估不叠加）；**限频** ≤1 条/30 分钟，逾期任务（at-risk）豁免；
  **新触发自动取消同目标旧建议**（#22 审阅备注 3）；**绝不改已确认计划**
  （L4）、绝不调用 `replan()`，建议 = `generate_plan(DRAFT,
  replaces_plan_id, replan_reason)`。**Worker 首批真实任务**（D-024）：
  摄取路径 best-effort 标脏（同步 Redis `agenthu:trigger:dirty`，宕机不
  阻塞摄取）+ arq cron 每 30s `drain_trigger_evaluation`（轮询粒度即去抖
  + 引擎幂等兜底）。验证：**227 passed**（main 220，+7 触发/worker）/
  pyright 0/ruff/drift 绿；四个 today 测试加「深夜窗口跳过」守卫（v2
  预算随墙钟收缩是「徽标与计划一致」的正确行为，orders 测试改固定晨间
  start_at 求确定性）。**E4 全链服务端依赖至此齐备**，剩
  `AGENTHU_E4_FULL=1` 联合首跑。批末重算/哈希去重优化（评估 #4）显式
  后置小尾巴 PR。
- **E4 全链首跑通过（2026-10-02，A，PR #29 分支上验证）——M2 出口判据
  达成**：`AGENTHU_E4_FULL=1` **2 passed**（seed 1.9s + 全链 28.5s），AGENTS
  §8 七要素首次全链断言走通（记录：`HANDOFF/2026-10-02-e4-full-first-run.md`）。
  首跑逼出 **PR #29** 两个真缺陷：① memory_kind 枚举绑定漂移（create_all
  测试库按成员名渲染 CHECK 与迁移小写 CHECK 不一致，alembic check 盲区）
  → kind 列 values_callable 绑定值 + 纯迁移库回归测试；② 学习写入与任务
  完成共生死 → 拆独立 handler（C1 各自 savepoint）。
- **深夜空草稿翻搅修复（2026-10-02 上午，A，`feature/empty-draft-reuse`，
  PR #30）**：协调人移交的产品裁定落地为 **D-019 附录**——v2 预算上限引入
  「有待办但放不下」新状态，复用条件精确化为「**无可摆放待办**时允许复用
  当日空草稿」（`latest_open_plan` 空候选经 `_nothing_placeable` 判定，镜像
  `_generate_v2_items` 摆放资格；备选「退休旧空草稿」不采）。全日课表
  覆盖测试确定性触发看守；既有 D7 回归（可摆放时重新生成）继续绿。深夜
  每刷新累积一条空草稿的翻搅自此消除。**B review 增补（PR #30）**：镜像
  谓词的漂移定约 = 同 fixture 双跑钉子测试
  （`test_nothing_placeable_mirrors_generate_v2_items`，三场景断言两谓词
  一致）；`latest_open_plan` 空草稿可摆放时继续找更旧非空草稿的遍历语义
  一并核验。
- **M2 关闭 / M3 开闸（2026-10-02，main `e2a80e6`）**：出口判据「四绿三
  窗口双人」达成（A 02:00 热修分支 / A 10:04 / A 11:26 主干 / B 11:37
  主干独立栈复跑）；33 条决策、32 个 PR 全双审。M3 首日教训动作
  「全量排查墙钟类断言」已完成：剩余 `datetime.now` 调用点均为已加守卫、
  now 相对差值（无午夜边界）或跨午夜退化通过型，无需改动。
- **A M3 首批 = pgvector 切片（2026-10-02，A，`feature/m3-pgvector-embedding`）
  ——`memories.embedding vector(1536)` 落库**：① compose `db` 镜像
  `postgres:16-alpine` → `pgvector/pgvector:pg16`（**tag 勘误**：冻结文本
  的 `pgvector/pgvector:16` 在 Docker Hub 不存在——09-30 拉取失败的真实
  原因，非网络封锁；正确滚动 tag 为 `pg16`，实证 = pgvector 0.8.7 /
  PG 16.15；带 `POSTGRES_IMAGE` 覆盖变量沿 MINIO/S3MOCK 先例；CI 跑
  compose 即验证可拉取，workflow 零改动）。② 迁移 `b7e4d0a95c13`
  （CREATE EXTENSION vector + 列；down 对称删列+删扩展，文档 §7.3）。
  ③ 模型 `Vector(1536)` 列（pgvector 包入依赖；反射经 `ischema_names`
  注册，`alembic check` 无漂移）；`MemoryRead` 只读透出（backend-only，
  客户端契约零影响，openapi 重导）。④ conftest 测试库预装扩展
  （create_all 路径需要）。验证：**231 passed**（main 230，+1 embedding
  往返）/pyright 0/ruff/drift 双源绿；本地重建演练完成（pgdata 清空 →
  新镜像 → up→down→up，extension 0.8.7 实证）。**wire 精度发现**：
  pgvector 文本输出是最短 float32 往返表示，float64 精确值出库带 ~1e-7
  表示误差（存储本身精确）——embedding 断言必须 `pytest.approx`，已记入
  任务文档 §7 供检索切片复用。
- **D-033 provider 政策首核完成（2026-10-02，A，`docs/d033-provider-policy-first-check`）
  ——资料摄取的硬前置解除**：核对 OpenAI（Responses API +
  text-embedding-3-small）数据政策，两页当日有效：enterprise-privacy
  （Updated Jan 8 2026）与 platform docs Data controls——API 输入输出
  默认不用于训练（2023-03-01 起，需显式 opt-in）、输入输出归用户。
  残留事实如实入档：供应商侧 ≤30 天滥用监控日志保留（含内容；ZDR 需
  审批，alpha 不适用）；实现约束 = 适配层 Responses 调用显式
  `store: false`，按课程同意文案披露供应商侧保留。结论：与决策清单第 4
  条兼容，「默认关闭」继续成立，摄取批次可开工（待 B 会签本记录）。
  记录落 `TASKS/m3-course-materials-privacy.md` §7；复核节奏 = 供应商
  政策变更或每里程碑一次。**B 双核完成（同日，两页独立重取，五项声明与残留事实逐
  一命中）——摄取批次正式解锁。**
- **A M3 第二批 = Memory 检索下限接线（2026-10-02，A，
  `feature/memory-retrieval-floor`）**：① `services/memory_retrieval.py`
  ——D-031 §5 共享检索路径落地（`retrieve_memories`：live-only + 滤
  REJECTED + 0.3 下限可提高不可绕过【clamp】+ kind/domain/level/
  subject_key 过滤 + 确定性序 + 上限 200）；文档明示**估时阶梯刻意不走
  此下限**（n=2 课程行 confidence=0.2，样本数门控独立，两路径只共享
  live/REJECTED 语义）。② `use_count` 首个冻结写入点接线（任务文档
  §8a.2）：`Estimate.memory_id` 回带支撑行 → `_generate_v2_items` 只收集
  真正落进已生成计划 basis 的行 → `record_decision_use` 每计划每行
  恰好 +1、`last_used_at` 盖章；批内去重（同课三任务读同一行 = 1 次决策
  ——`estimate_for_task` 跑三遍也不多计）；候选检索与
  `_nothing_placeable` 判定永不计数。事务内属性递增（非 bulk UPDATE），
  与计划同生共死。③ `MemoryRead.use_count` 已透出（M2 迁移列），Memory
  页可直接展示「参与过 N 次计划决策」。验证：**236 passed**（main 231，
  +6 检索/遥测，含钉子：reject 后估时回落 default 且计数恒 0、重复 id
  去重、下限 0.1 请求被 clamp 回 0.3）/pyright 0/ruff/drift 双源绿；
  无 API 面变化（openapi 零漂移）。
- **A M3 第三批 = 批末重算 + 版本语义修订（2026-10-02，A，
  `feature/batch-end-state-recompute`）——评估报告 #4 尾巴清偿**：
  ① **批末重算**：event handler 不再内联 `recompute_current_state`（4 处
  调用点改 `mark_state_dirty`，登记在 `session.info`）；单事件路径在
  `create_event` 末尾 flush，批量路径 `ingest_event_batch` 用
  `defer_state_recompute` 抑制 + 循环后 flush 一次——103 条事件同步从
  ~103 次全量重算（90 天课表重扫）降到 1 次。登记随会话回滚自然消失，
  零 schema。② **version 语义修订（重要）**：`version` 从「重算计数器」
  改为「投影内容修订号」——签名 =（current_task_id, current_plan_id,
  pending 集合, last_event_at/type, recent_event_types 排序元组），不变
  则不跳版；`version==0`（未计算）强制首跳；墙钟易变字段（current_time、
  24h 计数、breakdown）排除在签名外（跨分钟必漂，计入即回归逐次跳版）。
  `update_overrides` 对用户自有字段（context/available_minutes 覆盖）
  显式跳版。**钉子测试重写**：`test_current_state_reflects_pending_tasks`
  原断言「连读两次必跳版」改为「建任务跳、无变化读不跳」。③ **实现发现
  （due_at 教训同类）**：`last_event_at` 写入时统一 `astimezone(UTC)`——
  同一事件从线上的 Python 对象（原偏移）与从 UTC 库会话（+00:00）读回
  的 isoformat 不同，不规范化会让版本门控把「表示翻转」误判为「内容
  变化」。验证：**242 passed**（main 236：+6 批处理/版本语义，重写 1）/
  pyright 0/ruff/drift 双源绿；无 API 面变化（version 字段仍在客户端
  契约，语义注释入模块 docstring）。
- **A M3 第四批 = D-029 keyset 分页（2026-10-02，A，
  `feature/d029-keyset-pagination`）**：tasks 与 events 列表统一游标契约
  落地。① opaque cursor（base64url(JSON 键数组)），畸形 → 422；键 =
  **实际 ORDER BY**（tasks `(deadline nulls-last, created_at desc,
  id desc)`——冻结括注 `(created_at, id)` 与实际排序不符，按绑定原则
  「键序与排序一致」实现，注记入 DECISIONS；events `(timestamp desc,
  id desc)`，补 id tiebreak 防同批时间戳并列丢行/重行）。② tasks 裸数组
  形状不变，游标经 `X-Next-Cursor` 响应头（末页无头）；events 走
  `Page.next_cursor`；`Page.total` 改 `int | null`（cursor 页不 COUNT，
  D-029 冻结口径），`next_cursor` 增列。③ `cursor + offset` 并存 → 422
  （含显式 0）；offset 标记 deprecated 保留兼容。④ CORS
  `expose_headers=["X-Next-Cursor"]`（浏览器 dev 直连需要；打包客户端走
  IPC 代理，**B 侧依赖：`backend_proxy.rs` response_headers 白名单加一行
  `x-next-cursor`**——D-029 附录落地依赖，协调人已两提）。⑤ 客户端 Zod
  契约零改动（tasks 仍 `TaskSchema.array()`；events 列表不在客户端契约），
  openapi 重导 + drift 双源绿。测试：**239 passed**（+9：确定性种子含
  deadline 并列/id 并列/nulls-last 的精确翻页、422 两态、末页无头、
  CORS expose、offset 兼容）。
- **M3 五批审毕合并（2026-10-02，B 执行，协调人核验）**：#35-#41 七个
  PR 全部 review + 合并（`3daf140`/`881a65b`/`4481955`/`663914d`/
  `32dd5fb`/`52282cc`/`061c145`，均已在 main 验证可达）；交叉审方向正确
  （七 PR 均 A=rotcar07 authored、B=juefan-web APPROVED，时间戳先于合并）。
  **#40 B 侧原子件核销**：白名单行（`978efe8`）在 #40 合并 `52282cc`
  内原子落地——main `backend_proxy.rs` response_headers 已含
  `x-next-cursor` + 直测（游标透传 / Set-Cookie 仍拦），D-029 附录
  「落地依赖」关闭，未隔夜。**#41 会签义务核验**（协调人直读 main
  代码）：`store=False` 硬编码于 provider 请求体；同意门调用时重查
  （worker `tasks.py` 与 ingestion 双点）；`scanner_version` NOT NULL +
  中英注入对抗 fixture；全树无 `downloadUrl`；`storage_key` 用户前缀
  （`{user_id}/uuid`）；删除顺序按 D-033 §5（行先删、对象 best-effort +
  orphan 重试）。#41 的两类评审修订（rebase 后 openapi 重导 `f76eb43`、
  pyright typing 修复 `715517b`）随合并落地，review 正文有标注。
  main head `061c145` 双 CI 绿（CI + Client checks）；评审队列零在途。
- **B 本地 pgvector 阻塞（裁定记录）**：B 便携 PG 为 stock 16.9 无
  vector 二进制（删 pgdata 无解；WSL sudo 阻塞、无 docker），且 ORM 已
  引用 embedding 列、停旧迁移版会炸 Memory 查询——B 本地无法跑全栈。
  **裁定：E4 / 联调一律指向 A 的 compose 栈**（pgvector 镜像已切
  `pg16`）；B 本地以单测/类型检查/客户端构建为口径，不因环境阻塞
  客户端工作。
- **下一队列（2026-10-02 指派）**：A = M3 检索/grounding 切片（新任务
  文件 `TASKS/m3-grounded-answers.md`：混合检索 + 机械引用校验 + 回答
  落库 + Learning Memory 接入；HNSW 暂缓至规模实测）；B = ① 客户端
  游标循环（`getTasks`/`listPlans` 读 `X-Next-Cursor`/`Page.next_cursor`
  `while` 拉全量，退役 `limit=200` 过渡口径——验收：多页 fixtures +
  pnpm test/build 绿）→ ② Memory 页展示 `use_count`（#37 已透出，
  「这条事实参与过 N 次计划决策」）→ ③ 讲解页/引用跳转 UI，待 A 的
  `m3-grounded-answers.md` §6 接口冻结后并行。
- **#41 交付细节与竞态记录（2026-10-02，A 侧汇报，协调人核验；该汇报的
  「当前局面」一节已过期——七个 PR 实际已全部合并，A 报告时读的是合并前
  状态）**：增量声明逐项坐实——迁移 `c8f2a14d6b93`（material_chunks +
  grounding_consents + file_objects.course_name）；30s cron
  `drain_pending_extractions` 兜底丢失的 enqueue；**flagged chunk 永不
  嵌入外送**（`embed_pending_chunks` 查询仅取 `scan_status == "clean"`，
  flag 行留本地可检索、不进 provider）；同意门在 worker 与 embed 函数
  内双重调用时点复查（撤销对已入队的回填 job 同样关门）。**过程竞态
  （流程教训）**：B 合并队列期间对 #41 分支 rebase force-push，竞态丢失
  A 后推的两个修复 commit；A 对齐远端、验证 B 修复等价后让位、未推冗余
  提交——处置正确（合并树最终 3 commit：`8f888ce`/`f76eb43`/`715517b`）。
  CI drift 根因 = ci.yml 双触发（push + pull_request）的 merge 预览把两侧
  openapi.json 自动合并成任何一侧都不会导出的混合体（A 以 Docker
  Python 3.12 干净树复现，排除版本因素）。两条教训入下方流程规则。
- 流程规则不变：分支从 main 拉出；跨边界先冻结；PR 互审（A=rotcar07，
  B=juefan-web）；**并行会话各用独立 worktree**（2026-10-01 混合提交事故
  后的新规则）；**openapi.json 冲突一律 rebase 后 `--write` 重导**——CI
  双触发的 merge 预览可能自动合并出任何一侧都不会导出的混合体，勿信
  自动合并结果（#41 竞态教训）；**共享 PR 分支被 rebase force-push 后，
  author 先对齐远端并验证等价性，再决定补推或让位**（#41 竞态教训，
  A 的处置即为范本）。
