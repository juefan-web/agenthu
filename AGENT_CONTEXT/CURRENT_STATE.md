# CURRENT_STATE

Updated: 2026-09-28 · Milestone: **M0 (engineering baseline + frozen contracts)**
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

## Next（2026-09-29 更新：**M1-1 验收通过，正式收口**）

- **Round-5 验收（2026-09-29，main `aa9773e`）：A/B/C/D 四组全部通过，无
  P0/P1 缺陷**（报告：`HANDOFF/2026-09-29-round5-acceptance-report.md`，三处
  计划修订已按修订口径执行）。真实采集 103 条 → rejected 0（+08:00 判据）→
  50 个派生任务（徽标/标题/分钟级截止一致）→ 幂等不翻倍 → D-027 投影首次
  实测（「在课」context + 2h15m 徽标）→ 换源免重构建（8001 独立库证伪式
  验证）→ 断网队列重放不翻倍 → 全程 0 CSP violation。**Study + Time 真实
  数据闭环（AGENTS.md §8 首阶段验收主链）达成。**
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
- 流程规则不变：分支从 main 拉出；跨边界先冻结；PR 互审（A=rotcar07，
  B=juefan-web）。
