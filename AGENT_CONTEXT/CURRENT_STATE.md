# CURRENT_STATE

**当前队列（2026-10-05 深夜，P0-1 切片 1 送审）**：#67 已合并（main
`95858ee`），**D-036 生效、P0-1/P0-2 并行开工**。A 侧 **P0-1 切片 1
已实现待审**（[任务书](TASKS/m5-p0-1-live-predicate.md)，分支
`feature/m5-p0-1-live-predicate`）：统一 live 谓词
`live_memory_conditions` 接入五处（四读者 + keyed upsert 写侧）、
`MemoryCreate/Update` 移除 validity（D-036 §6，Create 侧为原则完足的
解释步）、唯一索引窄化 `valid_to IS NULL`（迁移 `45b7db4cb2cb` 升降级
往返 + autogenerate 零漂移已验）、OpenAPI −48 行无漂移、新 5 例集成
测试 + 旧往返测试改钉新契约；全量测试/ruff/pyright 绿。待 B head-bound
互审 → 协调人对库实测后合并。P0-1 后续（持久账本/屏障/代际/依赖矩阵）
与 B 侧 P0-2（三层 owner 命名空间）并行。运营尾巴全闭合（E6 dump 验读
拆栈、volume 保）。入口：[规划指导](TASKS/m5-planning-guidance.md)、
[双草任务](TASKS/m5-phase0-prereq-docs.md)。

Updated: 2026-10-05 · Milestone: **M4（Agent 运行时、Chat 与主动 Agent）——已收口（2026-10-05，D-030 双证齐：E6 六用例两轮绿 + B 核账账实相符；main `058c512` 复绿；实施链 #50–#65 全合，见 2026-10-05 收口条目）**。M5 phase-0 已冻结（D-036，2026-10-05，双契约 @`de8f5c0`；P0-1/P0-2 开工）。M3 已收口（main `5b381fd`，D-030 口径出口判据「代码 + 真机双证」达成，见 2026-10-03 收口条目）。M2 已关闭（main `e2a80e6`，出口判据「四绿三窗口双人」达成，见 2026-10-02 条目）。M0/M1 已合并（PR #1-#15，round-5 数据闭环验收通过 + e2e 首跑解锁）；对概念基线的完整差距评估见 `HANDOFF/2026-09-30-implementation-evaluation.md`（§8 七子句：4 达成 + 1 部分 + 2 缺失），M2 出口判据即该报告末节的场景化 §8 全句。路线大纲（M2–M8）已经 A/B 确认采纳（**D-030 accepted**，含三处修订：M3 同步产出删除/依赖图设计、TECH_STACK 依赖方已注取代、m2-breakdown 已对齐大纲口径）。
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
- **检索/grounding 切片开出（2026-10-02 深夜，A @ `feature/m3-grounded-answers`，
  待 B review）**：按协调人新立的 `TASKS/m3-grounded-answers.md` 执行——
  §6 接口**已冻结**（POST/GET/DELETE `/v1/material/answers`；403 fail-closed、
  503 不降级、citations 快照元组），B 的讲解页可并行。迁移 `e3a7c59f21b8`
  （material_answers：内容 + citations + chunk_ids + memory_ids + 模型/prompt
  版本，引用无 FK——删文件软失效不毁回答史）；混合检索（pgvector cosine +
  关键词 CJK-bigram/ASCII 词，RRF 融合；**检索资格 clean-only**，flagged
  两路皆排除）；**机械引用校验与 scanner 共用 `normalize_text`**（伪造
  quote/越界编号删引用剥标记，全伪造 → grounded=false）；Learning Memory
  经 `retrieve_memories` 共享路径接入（level 1/2），删除后同问不再体现
  （M3 出口句后端半边达成）；provider `generate()` 复用 `store=False`
  builder。HNSW 未建，检索延迟/候选数入日志（规模实测后单独决策）。
  验证：**297 tests**（对抗 fixture + 隔离 + 级联 + fail-closed spy）、
  ruff/pyright/drift 全绿、迁移 up→down→up；**§7.6 联调在 A 的 compose
  栈通过（录制回放口径**——真实 key 401 由 fail-closed 正确暴露，本地
  wire-format 回放端点跑通 上传→抽取→consent 回填嵌→问答 grounded=true
  （page/span 校验过）→历史 全链；详见任务文件当日记录）。**A 队列余项**：
  HNSW 决策（攒规模数据）、prompt 调优迭代、多课程混问（M3 末再议）。
  **B review（2026-10-02，PR #43）**：四个重点核过——校验纯机械
  （regex+子串查找，无模型判真）、同意门单源（import
  `material_ingestion.consent_enabled`，`provider.calls == []` 断言坐实
  零调用）、503 重试有界（≤4 次、退避 2/4/8s、60s/次超时、非 429 4xx
  不重试）、迁移纯 DDL 降级逆序。**一处评审修订（B 落于分支）**：
  `verify_citations` 原只归一化引文侧，块侧未过共享 `normalize_text`，
  与冻结 §3.4/§6「被引 chunk 的归一化文本」坐标系不符——分解式重音
  （PDF 抽取常见）会把真引用误杀；已改为块侧同样归一化（span 落归一化
  坐标系，§6 本就不依赖 span 精确渲染），补分解重音回归用例。分支
  rebase 上 #42 合并后的 main（CURRENT_STATE 两侧条目不同段，自然并存）。

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
- **B ①② 落地（2026-10-02，PR #42）**：游标循环已实现——`getTasks`
  走 X-Next-Cursor 头跟随（keyset 路径）；`listPlans`/`listMemories`
  所在端点仍是 offset 版 Page（不铸 `next_cursor`），按短页/空尾页
  判停逐页 offset 拉全量（两端点迁移 keyset 后改为跟随 `next_cursor`
  即可）。MAX_PAGES=50 防失控护栏（中止并报错，不静默截断）。多页
  fixtures 4 例 + 全量 116 测试 / build 绿。② 经核**已由 M2 Memory 页
  落地**：`memory.ts` schema 含 `use_count`/`last_used_at`，
  `MemoryView` telemetryText 渲染「参与决策 N 次 · 最近使用 …」且
  MemoryView.test 已断言（零遥测行不显示）——无需新增改动。
- **B ③ 讲解页落地（2026-10-02，PR #44，待 A review）**：§6 冻结形状的
  客户端半边——新增「讲解」主视图（导航第 5 项）。课程选择（文件列表
  distinct course_name + 手输 datalist）；同意门展示后端下发的
  consent_text 并以「同意并开启」回显 `consent_text_version`（PUT）；
  提问走 POST `/v1/material/answers`，403/503 经 `BackendHttpError`
  （新增错误类携带状态码）分流提示（503 明示「不会降级为无引用回答」）；
  回答正文把存活 「quote」[n] 标记渲染为可点击引用点，与引用卡
  （quote + page + 文件名，§6 口径不依赖 span）双向跳转高亮；文件
  已删/已换版本（checksum 不匹配）→ 失效锚点标注；历史（offset 拉全量
  + 删除入口）。课件上传 UI 不在本切片（后续项）。127 测试（+11）/
  build 绿；E1 主视图正则扩入「讲解」。
- **B ④ 课件上传入口（2026-10-02，PR #46，叠置 #44 之上，待 review）**：
  按 `TASKS/m3-materials-upload-ui.md` 落地。**§5 三预埋点实测先行**：
  ① vendor 字段口径——`learn/getFileList` 已有实测归一化映射
  （wjid/bt/wjlx/scsj/fileSize，含「文件消失」根因注记），Zod 按
  `CourseFile` 镜像不发明第二套；② Windows 临时句柄——探针证明
  写→读流后 drop 可删，实现用 `tempfile::tempfile()` 仅句柄 RAII（无
  路径、含 panic 全失败路径无残留）；③ 大 POST body——**字节不走
  WebView IPC**（§3.3），Rust reqwest multipart 流式实测 12MB loopback
  8KB 块 10.7s / 1MB BufReader+ReaderStream 5.3s → 256MB 上限 ≈2min，
  600s 传输预算 5 倍余量，无需分块（两处 API 实测修正：
  `Part::stream_with_length(Body)`；`From<tokio::fs::File>` 而非
  std File）。**实现**：列表 = 既有 `campus_request`+cookie jar（D8
  路径，`getCourseFiles` 走 read() 自动重登）；下载+上传 = 新 Rust 单
  命令 `material_upload`（campus 下载客户端无总时限共享 jar；Backend
  上传长时限客户端 + B-4 origin 谓词；multipart 表单带 course_name）；
  UI = 讲解页课件面板（按需拉取 gcTime 0 不缓存、单文件显式上传、
  §3.5 同意门双态如实标注、status 生命周期按文件名对应透出、校园/
  Backend 失败显式透出不静默空列表）。验收 2（临时无残留）/3（React
  零字节）由构造保证；打包端到端（验收 1/4）待真机联调。cargo 17
  测试 + vitest 139（+12：adapter 3 + wrapper 3 + panel 6）/build 绿。
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
- **#43 grounding 切片审毕合并（2026-10-02，B 评审 + 合并 `872c8b3`，
  协调人核验）**：B 四个重点全过（纯机械校验、同意门单源 import
  `consent_enabled` 且测试钉死零调用、503 重试上限 4 次/退避 2/4/8s/
  单次 60s 超时、迁移纯 DDL 可逆）；**评审修订 `669f53a` + format
  `00c6c28` 已核**——haystack 侧补过共享 `normalize_text`（原实现只
  归一化 quote 侧，PDF 分解重音序列会误杀真引用；修复与 §6「span 索引
  归一化文本」文档语义对齐），分解重音回归用例在库
  （`test_decomposed_accent_chunk_matches_composed_quote`）；A 的交叉
  核验评论在案（13:10Z，含 rebase 核验/299 passed 补测/让位说明）。
  合并后 main 双 CI 绿。第三次推送竞争按既定协议让位，无冗余提交。
- **B ③ 讲解页 PR #44 核验（2026-10-02，`6b9416c`，待 A review，
  协调人代码核验通过）**：六项声明坐实——`BackendHttpError` 携带状态
  码、403/503 分流；consent PUT 回显 `consent_text_version`（测试断言
  请求体）；失效锚点两态（文件已删 / checksum 不匹配）；历史 offset
  拉全 + 删除；E1 正则扩入「讲解」；12/12 检查绿。
- **下一队列（2026-10-02 指派，第二轮）**：A = ① review #44（小 PR，
  就近批）→ ② 起草 **E5（M3 出口 e2e 场景）**：讲解页全链——上传 →
  同意 → 提问 → 引用机械校验成立 → 删除 Learning Memory 后回答不再
  体现（M2 的 E4 模式沿用；B 上传 UI 合并前可先以 API 造数路径写后端
  半边）；HNSW 继续等检索延迟数据。B = #44 合并后开工 **④ 课件上传
  入口**（新任务文件 `TASKS/m3-materials-upload-ui.md`，含文件列表
  来源裁定：按需拉取、不进采集循环——见 DECISIONS D-033 §1 实现注记）。
- **#45/#46 审毕合并，M3 主体落地（2026-10-02，A/B 互审 + 协调人核验
  与合并）**：#45（A 的 E5 后端半边 + 回放 provider + 标记序不变式，
  B approve 16:21Z）合 `55169c1`；#46（B 的课件上传链路，A approve
  16:46Z）合 `8f9c04b`——A 评审三重点全过（双 URL 闸 + 重定向策略
  对称性、无总时限下载客户端的非对称有理性、downloadUrl 会话态全链
  路不落地），§5 三预埋点固化为常驻回归（12MB loopback multipart、
  Windows 句柄探针），§6 验收 2-5 由构造与测试覆盖。**协调人事故
  记录（转正 A 的记忆条目）**：合并 #44 时带 `--delete-branch` 删掉
  叠置 base 分支，连带关闭 #46——已重建指针、重开、改基 main 完整
  恢复；教训：**叠置 PR 链的底层合并勿带 `--delete-branch`，等上层
  改基后再清分支**。
- **下一队列（2026-10-02 指派，第三轮）——M3 验收轮**：A = 执行
  **M3 验收**（compose 栈 + 打包客户端）：E5 全链升级为真实上传链
  （A 自述将 API 造数换成真实上传）+ 上传 → 同意 → 提问 → 引用跳转
  → 删 Learning Memory 复验；`m3-materials-upload-ui.md` 验收 1
  （打包端到端）在此闭环；HNSW 决策看检索延迟日志。B = A 评审的两条
  非阻塞跟进（小 PR）：① 下载端补 `read_timeout(30s)`——现状连接
  僵死会让 invoke 无限挂起、按钮停在「转送中…」，**建议验收轮前
  落地**；② status 徽标建图按课程过滤（`backendStatusByName` 仅按
  filename，跨课程同名串标签，纯外观）。
- **B 跟进落地（2026-10-02，PR #48，①② 同批）**：① 下载客户端
  `read_timeout(30s)`（无总时限语义不变——慢而流动的传输不受影响，
  30s 无字节进展即中止）；回归测试用 1s 缩时验证僵死源在时限内报错
  （reqwest 源码核实 timer 在等响应头阶段同样武装）。**测试过程发现**
  ：客户端超时中止后 Windows 对端不一定 FIN，测试服务端需自带读超时
  才能 join——已注释在测试内。② `backendStatusByName` 先按
  `course_name === courseName` 过滤再建图，补跨课程同名用例（另一门课
  的 extracted 不串到本课的「抽取进行中」）。cargo 18（+1）/
  vitest 140（+1）/build 绿。
- 流程规则不变：分支从 main 拉出；跨边界先冻结；PR 互审（A=rotcar07，
- **M3 收口（2026-10-03，协调人，main `5b381fd`）**：#47（keyword
  lane ANY-token 修复 + `scan_ms`/`embed_ms` 拆分，B approve）合
  `41b9e96`、#49（E5 UI 半边 + 验收记录 + B 评审修订 `4411bb5` DOM id
  命名空间）合 `5b381fd`；#48（read_timeout + 徽标课程过滤）此前已合
  `7c677b7`。**D-030 口径 M3 出口判据达成，代码 + 真机双证**：E5
  backend 半边合并后 main 复跑绿 + E5 UI 打包客户端全链 1 passed +
  campus 真机链闭环（105 事件同步、36.3MB 真实课件 → 167 chunks 全
  clean → 回填嵌入、第 74 页引用机械校验通过且服务端核验）——证据链
  见 `HANDOFF/2026-10-03-m3-acceptance-round.md` §4。**backlog（检索
  重做桶，B #47 评审观察）**：OR 通道内候选按文件序截断 32、无命中
  计数排序——语料增大后可能把真命中挤出前 32；命中计数排序/BM25 化
  与 HNSW 决策同桶，触发条件 = 语料规模数据。首组 HNSW 数据结论 =
  不建索引（2→167 chunk 混计延迟同数量级、DB 扫描非瓶颈）。
  **M3 全程 PR 链**：#33-#49（Memory 迁移/检索下限/批末重算/分页/
  摄取/grounding/讲解页/上传链/E5/三笔修复），A/B 互审全部在案。
- **M4 先决文档阶段分派（2026-10-03，协调人）**：任务文件
  `TASKS/m4-phase0-prereq-docs.md`——A 草拟《Agent 运行时与审计契约》
  （agent_runs schema、工具注册表 ACTION_POLICY、pending_actions
  生命周期、上下文装配快照格式、provider 工具调用接口缺口），B 草拟
  《动作确认与 Chat 交互契约》（pending_actions 确认 UI、Chat 视图
  与 basis 渲染复用、主动提醒呈现与打扰预算）。双文档互审 → 冻结 →
  拆实施任务（沿用 M2/M3 phase-0 模式）。
- **A 的《Agent 运行时与审计契约》草案已交（2026-10-03 @
  `feature/m4-phase0-runtime-contract`，worktree `D:\agenthu-wt-m4`）**：
  `TASKS/m4-agent-runtime-audit-contract.md`。**v2（同日晚）**：以重写稿
  为基并入 A 首稿（PR #50）更优部分——attempt/operation_key/client_request_id
  幂等与 lease/watchdog 恢复、权限账本同事务 + 递归脱敏（redact 顶层过滤
  已核实）、**grant 等级收紧**（fnmatch 通配 + granted>=required 越级漏洞
  已核实：L3 grant 只自动执行 L3 动作）、grant 软撤销、**全局「Agent 模型
  上下文」同意缺口**（M3 同意只覆盖 chunk，不授权 CurrentState/Memory/chat
  外发）、`content_revision` 前缀排序（updated_at 受 use 遥测扰动已核实）；
  并回的部分：pg_trgm FTS 决定（tsvector 对 CJK 无分词）、materials.answer
  工具、会话近史段入前缀、chat/pending API 形状与默认值。
- **M4 互审轮闭环（2026-10-03 晚，PR #50 分支）**：协调人补推 B 草案
  （`f8ef58a`）并出具裁定表（A1-A5/B1-B4①② + 附加两项）；B 随即落 r2
  （`564f68a`：B1/B2/B3/A3/A5、B4①②、AgentRunRead 字段级、路径对齐
  `/v1/agent/runs`、A1/A2/A4 引用，且完成对 A v2 的 delta 复核——12 项
  承重语义在位）。**A 落 v3**（同分支）：A1（CONFIRMED 起不过期）、A2
  （`chat:{session_id}:{client_message_id}` 映射 + §8 字段名统一）、B4②
  （`current_state` kind + version）、B4① 确认、A4 终裁执行（pg_trgm +
  <3 字符降级 + conftest 预装两条件）、跨契约吸收四项（chat/search、
  消息级 DELETE、title 可选+回退、`pending_actions.result` 按 B1 三元组）。
  **A 对 B 草案 r2 的正式评审已交：Approve 无阻塞**
  （`HANDOFF/2026-10-03-a-review-m4-b-contract.md`，对 head `564f68a`
  文本；§9 四问逐答；唯一互审要求 = AgentRunRead 补 `tool_calls[]`——
  评审点 6 成立条件；小修 expires_at 非空；非阻塞建议「旧 → 新」渲染
  约定与 A2 重发断言）。**待 B 补 tool_calls[] 镜像 + expires_at 非空后，
  双稿具备冻结候选条件**（head 文本各持对方 approve）。
- 流程规则追加：**开 PR 一律两步走——先 `gh pr create` 拿真实编号、
  再单独 `--add-reviewer`，挂完回读 `reviewRequests` 确认生效**
  （三起 reviewer 误挂/静默失败教训：#46/#47/#48 号段竞争 + 命令成功
  返回 ≠ 挂载生效）。
- **M4 phase-0 闭环与冻结（2026-10-03，协调人终审）**：双契约互审完成
  ——A 契约 v3（`92e2c24`）持 B 的 head 绑定 approve（PR #50，
  10:08Z，附「50b86f7 处逐字节不变」声明，协调人 diff 验证属实）；
  B 契约 r3（`50b86f7`）持 A 的 approve（HANDOFF + PR 评论 09:38Z）。
  终审核验：四项代码断言（fnmatch 越级 / 硬删 / redact 顶层 /
  onupdate 扰动）三方独立复核一致；协调人裁定 A1/A2/B4①② 全部落文；
  r3 三修（`AgentRunRead.tool_calls[]` 逐字段镜像、`expires_at` 非空、
  旧→新渲染）在库。**PR #50 合并 `05330f3`，12/12 绿**；冻结条目
  **D-034**（含 pg_trgm 取代 §1.8 预设、grant 收紧、全局模型上下文
  同意 = 切片 2 门禁、8 态 + CONFIRMED 不过期、content_revision 排序、
  审计降噪成立条件）。**实施分派 = `TASKS/m4-implementation-slices.md`**
  （B1/A1 契约代码化同批先行 → A2 运行时含同意门禁 → A3/B2 并行 →
  B3 = E6 出口 e2e）。
- **B1 交付（2026-10-03，PR 见分支 `feature/m4-b1-contract-zod`）**：M4
  冻结契约代码化——`@agenthu/contracts` 新增 M4 块（`DecisionBasis`/
  `DecisionReference` 含 `chat_message`/`current_state` 两 kind、
  `PendingActionRead`（`expires_at` 必填非空）、`AgentRunRead` 含
  `tool_calls[]` 镜像、`NotificationPreferences`（budget_date/last_sent_at
  server-only）、chat session/message、`CursorPage` 工厂与 mutation/send
  请求形状）；`tests/fixtures/client_contract.ts` 同块镜像（头注记变更）。
  BackendClient 新增 12 方法（pending-actions 拉/确认/忽略/重试、
  agent run、chat 会话/消息/202 发送/两删除、通知偏好 GET/PATCH），共享
  `drainCursorPages`（D-029 events 口径）。验证：contracts 14 测试、
  desktop 145 测试（+5）、build、drift 双源本地绿（带 SECRET_KEY/S3_SECRET_KEY
  环境变量跑通——worktree 无 .env 的本地口径）。**两点留待对齐批**：
  ① `ZOD_TO_OPENAPI` 映射条目随 A1 登记（现在加会因组件缺失红 CI）；
  ② `searchChat` 未实现——搜索结果形状未在冻结文本字段级定义，归
  B2 与 A1 OpenAPI 对齐时补。
- **A1 迁移与契约代码化已交付（2026-10-03 深夜 @
  `feature/m4-a1-contract-codification`，worktree `D:\agenthu-wt-m4`）**：
  迁移 `b8d3e57a21c4`（5 新表 agent_runs/pending_actions/chat_sessions/
  chat_messages/notification_preferences + **grant 唯一约束改部分唯一
  `WHERE revoked_at IS NULL`**——原全量唯一与「再授权铸新行」冲突，
  属软撤销的完整 DDL 面 + memories.content_revision 列 sha256 回填，
  before_insert 监听器单点覆盖全部写入方）；ACTION_POLICY +4 行
  （memory.retrieve/goal.read/replan.evaluate/materials.answer）+
  **focus.start 校正 L2**；grant DELETE 改软撤销、POST 不复用已撤销行；
  Pydantic 契约面（PendingActionRead/AgentRunRead 含 tool_calls[]/
  DecisionBasis/chat/偏好，严格镜像 B r3）+ 8 个读面端点（D-029 游标）；
  drift 检查器注册 6 新映射 + **anyOf[$ref,null] 下钻**（首个含可空
  嵌套对象的契约 schema）。快照 staged 块**已按协调人裁定整块删除**
  （B1 已在库落镜像段，暂存副本成冗余且会制造 rebase 冲突——映射键
  亦已对齐 B1 实际导出名 `89d29ed`）；CI 保持红至 #51 合入 +
  本分支 rebase（合并序列见 PR #52 披露评论）。验证：
  ruff/format/pyright 干净；**309 passed** 1 skipped（S3 env 既有跳过），
  含迁移 up→down→up + alembic check 与 9 个新测试（隔离 P0/分页/
  软撤销/修订号不可变/偏好 409 与成对校验）。**待 B1 同批合入后
  drift 双源全绿 → A2 开工**。
- **B1 自修 + A1（#52）交叉评审（2026-10-03）**：评审 A1 时发现 B1 缺陷
  ——`ORMModel` 不带 exclude_none，None 投影列以显式 null 下发，仅
  `.optional()` 会拒收；`2e484c0` 改三投影列为 `.nullable().optional()`
  （包 + 镜像 + 回归测试，145/14/tsc/drift 全绿）。**A 评审 #51 又出
  同类五处（chat 三列 + safe_error/result），且"其余可空字段写法正确"
  的断言不成立——嵌套面同样发 null（trigger_ref 三列、locator 全列、
  state、risk_note、resource_type/id、error_code、summary/degrade_code），
  B 做了全类清扫（累计 26 处字段实例，含 A 的五处），补显式 null
  全覆盖回归测试。**#52 内容核验通过
  （schemas 与 B1 逐字段一致、迁移/软撤销/政策行/读面路径全对），但
  request-changes：除映射键改名外，**A1 写入 fixture 的整份 staged 副本
  （+203 行）须删除**——与 B1 镜像同锚点，rebase 必冲突且四个同名
  schema 双声明；title 先例不适用于 B1 已在库的批次。正式 approve 按
  序列落 rebase 后绿 head（head 绑定）。
- **#51 合并 + #52 rebase 收口 + B 绑定 approve（2026-10-03 晚）**：
  #51 增量（`88f786b` 全量 nullable 清扫）复审 **APPROVE**（绑定 head，
  12:06Z）；**#51 合并 `9ffe10c`**；#52 rebase 到新 main，head `523023a`
  （快照零 diff——staged 块删除后冲突源整体消失；drift `--require-zod`
  绿；12/12 CI 全绿）；**B 于 12:24Z 在 `523023a` 出绑定 APPROVE**——
  闸门解除，待协调人执行合并。#53 节流 PR 已关闭（仓库转 public 后
  Actions 免费无限额；双触发与 12/12 口径维持原样）。
- **A2 运行时与同意门禁已交付（2026-10-03 深夜 @
  `feature/m4-a2-agent-runtime`，自 `523023a` 拉出，worktree
  `D:\agenthu-wt-m4`；边界 = `HANDOFF/2026-10-03-a2-agent-runtime.md`）**：
  ①**全局模型上下文同意门禁**（`model_context_consents` 表 + GET/PUT
  `/v1/model-context-consent`，形状镜像 grounding_consents、版本回显、
  默认关）——双层强制（装配层裁剪 + runner 层零调用），同意关 ⇒ fake
  provider 计数恰为 0 且确定性路径照常出计划（degraded=
  model_consent_missing）；②权限收紧落地（L3 grant 仅自动执行 L3 声明
  动作、L2 永远逐次确认、通配不再越级、空 scope/通配 scope/过期/撤销
  全 deny——`_matching_grants` 只做候选匹配）；③工具注册表 16 项
  （server-side 版本化代码配置、schema→权限→display 三道顺序、启动
  校验与 ACTION_POLICY 对齐；calendar.write/message.send/file.delete/
  data.delete 诚实 `tool_not_implemented`）；④确定性 runner（原子
  claim/lease/heartbeat、watchdog 先查可见副作用再结算 + attempt+1、
  同事务审计账本）；⑤pending 8 态 mutation 面（confirm/ignore/retry、
  expected_version 409、mutation 响应缓存表、CONFIRMED 不过期、
  FOR UPDATE SKIP LOCKED 原子派发、EXECUTING 租约回收→同 key
  FAILED_RETRYABLE）；⑥上下文装配 manifest（固定前缀序、
  content_revision 排序、token 预算整段丢弃计数、逐字节
  rendered_context_hash、untrusted 边界、N=10 近史段）；⑦redact 递归化
  （嵌套键全禁 + 白名单变体 + 200 字符截断）；⑧provider 能力协商
  （capabilities/generate_with_tools/continue_with_tool_results，
  OpenAI Responses tools 实现，store=False 维持）；⑨chat 发送入口
  （POST sessions/messages 202、消息级幂等、client_request_id 公式派生、
  assistant 消息随终态落行）+ worker `execute_agent_run`/
  `sweep_agent_runtime` cron（30s）。**验证：329 passed 1 skipped（含
  20 个新 A2 回归 = §9 之 A2 面）、ruff/format/pyright 0 错、迁移
  up/down/up + alembic check 绿、drift 双源绿（+ChatMessageSendResponse
  映射）**。**未落地（留 A3/B2）**：pg_trgm/搜索、触发器接线、打扰预算
  结算、消息删除、通知投递通道。分支叠在 #52 上，待 #52 合并后 rebase
  到 main 再开 PR。
- 流程规则不变：分支从 main 拉出；跨边界先冻结；PR 互审（A=rotcar07，
  B=juefan-web）；**并行会话各用独立 worktree**（2026-10-01 混合提交事故
  后的新规则）；**openapi.json 冲突一律 rebase 后 `--write` 重导**——CI
  双触发的 merge 预览可能自动合并出任何一侧都不会导出的混合体，勿信
  自动合并结果（#41 竞态教训）；**共享 PR 分支被 rebase force-push 后，
  author 先对齐远端并验证等价性，再决定补推或让位**（#41 竞态教训，
  A 的处置即为范本）。
- **B1/A1 契约代码化批次合并（2026-10-03，协调人核验与执行）**：#51
  （B1 共享 Zod + 12 客户端方法；A 评审抓 5 处 nullable 欠缺 → B 全类
  清扫 26 处 `88f786b`，交叉互查双向起效）合 `9ffe10c`；#52（A1 迁移/
  政策行/读面；映射键改名对齐 + 206 行 staged 块删除 + rebase `523023a`，
  B approve 12:24Z）合 `1bdae73`。drift 双源绿闭环（六映射全命中 B1
  在库导出）；main 双 CI 绿。**流程新规经此批次立起来**：远端 CI 非
  绿必须披露；同批 PR 名字对齐先于任一侧合并；nullability 缺陷类靠
  字段级人工互查（drift 对 null 加宽不可见）。**仓库可见性变更记录**：
  仓库由私有转 public（2026-10-03，Actions 计费封锁后持有人的解决
  方案；节流 PR #53 据此关闭）——**原排 M5 合规章的 OneTHU BSL 1.1 /
  LearnX 许可审查因「公开分发」实际已触发，建议提前正式审查**；脱敏
  纪律（合成 fixtures、验收数据不出本机）继续有效。
- **A2 已交付在分支（2026-10-03，`feature/m4-a2-agent-runtime` @
  `fc1a5dc`，31 文件 +5283/−146，未开 PR）**：同意门禁双层强制且测试
  钉死（`test_m4_runtime.py:301` 同意关 ⇒ provider 零调用）；16 工具
  注册表（4 个诚实 `tool_not_implemented`）；runner/watchdog/mutations/
  逐字节装配/递归 redact/chat 202；迁移 `a7d1c93f4e20`。本地 329
  passed + drift 双源绿；**远端 CI 未跑（无 PR），按披露规则如实记录**。
  下一步：A rebase 到 `1bdae73` 开 PR（两步挂 reviewer）→ B 交叉审；
  **B2 依赖面已齐（pending mutations / chat 202 / 偏好 / 同意 GET/PUT），
  B 可即刻开工**。
- **勘误（协调人，2026-10-03）**：上条「B2 依赖面已齐……全在 main」
  **不成立**——pending mutations / chat 202 / 同意 GET/PUT 在 A2 未合并
  分支上，main 实际只有读面 + 偏好 PATCH + M3 同意门（B 开工前独立
  核实并纠正，PR #55 声明在案）。教训：**宣布依赖就绪前必须对 main
  实测**，协调人口径不得凭记忆（本类第二起，前一起为 §6/#43 滞后）。
- **在途双 PR（2026-10-03）**：**#54 = A2**（`47bce4d`，base `b01c9ae`，
  31 文件，12/12，B 已挂评审；同意门禁零调用钉死 + 全量运行时）；
  **#55 = B2**（`769df09`，base `b01c9ae`，15 文件 +1442，12/12，A 已
  挂评审；四视图族 + App 接线，按 D-034 冻结形状实现，A2 未合前的
  诚实失败态——同意面加载失败 / mutation 404 不伪造成功；**A2 改形状
  需在对齐批同步 `backend/modelConsent.ts`**）。B 交叉审 #54 的三个
  预埋关注点：同意门双层单源性 / watchdog 幂等键覆盖面 / chat 202
  `client_request_id` 公式与 A2 裁定逐字一致。合序建议：#54 先、#55
  rebase 对齐后合（或若零冲突按便利序）。
- **B2 视图族交付（2026-10-03，`feature/m4-b2-view-family`，base `b01c9ae`）**：
  ①`DecisionBasisView` 共享渲染器（8 kind 定位渲染、失效标注、`parseDecisionBasis`
  弱类型入口；`BasisPanel` 检出 `basis.agent_decision` 子键转交，形状不符退回
  JSON 透出）→ ②`PendingActionsView/Card`（8 态 × 操作矩阵、仅 PENDING 倒计时、
  409 静默 refetch、防双击、用户自致失败子码单列文案、结果三元组、深链滚动）→
  ③`ChatView`（模型上下文同意门 = 文案下发 + 版本回显开启/撤销；会话/消息
  cursor 流；发送 202 + 3s 有限轮询封顶 40 次；断供「模型暂不可用」不伪造
  兜底；消息/会话删除；「为什么」同一渲染器；pending action 深链到确认卡；
  网络失败同一 client_message_id 幂等重发）→ ④`NotificationPreferencesView`
  （类别 chips + 免打扰起止（跨午夜）/每日上限数值控件、server-only 用量
  只读、PATCH expected_version、409 重填不静默覆盖）。App 加 确认/对话/提醒
  三视图 + 待确认徽标（与视图共用 query key）。新增本地 schema
  `backend/modelConsent.ts` + 两个 client 方法（镜像 A2 冻结形状：GET 带
  consent_text/version，PUT 回显）。测试 +31（共 176 绿）、tsc/build 绿。
  `searchChat` 继续等 A3（结果形状未字段级冻结）。
- **#55 rebase 轮（2026-10-03，base 新 main `8d47781` = #54 合入）**：诚实
  失败态翻真实读写（mutation/202/同意端点已在 main，同意门成活接口）。
  四条裁定落地：①客户端自致失败码**超集**——实发码 `permission_denied`/
  `grounding_consent_missing` 入集合，原三词（`permission_revoked`/
  `consent_revoked`/`source_deleted`）注释为 A3/B3 前向词汇保留；②Chat
  删除入口补 onError 错误呈现、按钮保留（A3 同波交付 DELETE，「确认后
  静默无结果」消除）；③L3 标签按状态分词——PENDING 上的 L3 = 「自动执行
  未获授权，需你处理」，历史已授权派发 = 「已授权自动执行」；④不可达
  403 分支防御性保留。同意门两 client 方法对 main openapi 现端面补
  path/body/解析用例。A 于新 head 重新出绑定 approve 后合入。
- **A2 已合 + A3 交付在分支（2026-10-03 深夜）**：#54 合并 `8d47781`
  （B 绑定 approve 14:47Z，四关注点带行号坐实）；#55 等 B rebase 轮
  （A 的 APPROVED 绑 `769df09` + 四条非阻塞裁定意见在案，新 head 需
  A 重新绑定）。**A3 = `feature/m4-a3-retrieval-wiring`**（自 `8d47781`）：
  pg_trgm 迁移 `c4f2a8e01d73` + conftest 预装；chat DELETE 双端点
  （幂等 204；会话归档级联消息软删，检索资格同事务丧失）+ 会话内
  搜索（ILIKE 子串 + trgm GIN，<3 字符无 trigram 退化为无索引过滤
  结果仍正确，通配符字面化，newest-first keyset）；触发引擎接线主动
  run（`trigger:{signature}` 永久去重 + `uq_agent_runs_active_trigger`
  双保险；drain 后直接 enqueue，sweep 兜底）；主动结算确定性无
  provider 调用（L1 建议免费走计划面，L3 notify.push 消耗预算——分流
  落地）；打扰预算结算 `notification_delivery.settle_and_deliver`
  （类别→免打扰→本地日预算三重门，跨午夜窗口合法，抑制=SUCCEEDED
  如实文案 + 审计记因，无 prefs 行=工厂态全关且不为此建行）。**修复
  A2 缝隙一处**：dispatch 的 L3 grant 复验现仅作用于 grant 确认路径
  （`grant_snapshot` 非空），用户逐次确认的 L3 动作不再被错误拒绝
  （A3 回归钉死：无 grant PENDING→确认→真实投递结算）。验证：331
  passed / 8 skipped（7 深夜窗 + 1 S3）、ruff/format/pyright 0、迁移
  up/down/up + alembic check 绿、OpenAPI 61 路径重导 + drift 双源绿。
  遗留观察（非阻塞）：L3 grant 的 scope 只做形状校验（categories 列
  表非空即过），未与本次调用的 category 做包含性比对——A2 冻结语义如
  此，预算门仍在，是否收紧待裁定。服务端细分码（可选项）未做：客户
  端超集方案已覆盖今天的诚实呈现。
- **#54/#55/#56 合并收口，M4 实施完毕（2026-10-04，协调人核验与执行）**：
  #54（A2 运行时 + 同意门禁）合 `8d47781`；#55（B2 视图族 + 四裁定
  rebase 轮 `83c24e9`）合 `baf3667`；#56（A3 + scope 值级匹配
  `2abe56c`）合 `e4fc297`。**上条的「遗留观察」已裁定并落地**：值级
  匹配 = D-034 §5.3 冻结语义补齐（非 A2 变更），双闸注册强制 +
  三执行点收口 + 端到端用例，详见 **DECISIONS D-034 §5.3 实现注记**
  （含 grant 面文案挂起条件）。**批准延续协议首次实践**：rebase 零
  代码 delta + CURRENT_STATE 并集 + 12/12，评审人自执核验后 approve
  延续（issuecomment-5975655100）——head 绑定纪律与例行 rebase 的
  兼容路径就此定型。main `e4fc297` 双 CI 绿。
- **下一队列（2026-10-04 指派）**：B = **B3（E6 出口 e2e）**：契约
  §8 六场景（重排建议依据 → Chat 建议任务 → Level 2 卡片 →「为什么」
  basis → 并发确认恰一次 → 断供降级 → 预算/免打扰 + L3 grant），构建包
  /CDP 口径（E5 手册），从 `e4fc297` 拉分支；E6 全绿 = M4 按 D-030
  口径收口。A = 起草**跨会话搜索契约演进冻结稿**（`ChatMessageRead` +
  `session_id` + 结果形状，与 B 同批冻结后实施——A3 主动延后项）；
  grant 面文案要求随 B 侧 grant 管理面 backlog 挂起。
- **A 的冻结稿已交（2026-10-04，`feature/m4-chat-search-contract` 自
  `e537068`）**：**DECISIONS D-035（proposed，待 B 签字 + 协调人采纳）**——
  ①`ChatMessageRead` += `session_id`（必发，一切出现处）；②全局检索面
  `GET /v1/chat/search?q=&session_id?=&cursor=` 字段级冻结：结果项
  `ChatSearchItem` = `ChatMessageRead` + `session_title`（扁平加富，不取
  嵌套 ChatSessionRead）、A3 同款 keyset/可见性/降级语义、限域 404 纪律
  与消息流一致；③**端点收口**：A3 会话内子路径被 `?session_id=` 取代并
  移除——零消费窗口内唯一非加法项，**需 B 在 PR 评审中显式确认**；④零
  schema 变更（trgm/资格模型已在 main）；⑤纯加法可 revert；⑥实施分侧
  A=后端+OpenAPI+测试，B=Zod 镜像+客户端方法+UI。非目标：跨域统一检索、
  相关性排序、服务端分组聚合。冻结前不开实施。
- **D-035 采纳 + M4 收口三线并行（2026-10-04，协调人）**：#57 合并
  `46e8bb5`，**D-035 → accepted**（B 两点确认与「已映射 schema 必填字段
  变更须 OpenAPI 侧同批在后」排序规则记入 DECISIONS）。#58（E6 工件）
  待 A 评审。**三线**：① A = D-035 后端切片（OpenAPI 重导先行，供 B
  同批配对）+ **结构化 basis 缺口切片**（`agent_decision` 写入者 /
  删除失效传播 / chat 触发 run 引用消息——M4 收口前必落）+ **E6 栈上
  首跑**（#58 合后，E5 手册 + B 的 E6 手册）；② B = D-035 客户端切片
  （按排序规则与 A 同批）+ E6 核账报告（镜像 M3 角色对账）；③ 缺口
  切片合 → S1/S3 活链断言 → E6 全绿 → **M4 按 D-030 收口**。
- **A 的缺口切片交付（2026-10-04，`feature/m4-basis-gap-slice` 自
  `e537068`，协调人裁定 1 三件合一）**：①`generate_plan` 写
  `Plan.basis.agent_decision`（冻结 DecisionBasis 外层；引用排入任务/
  goal/当日课表事件/估时 Memory/CurrentState locator.state_version；
  legacy 键原位不动；全部调用方一次覆盖）；②新服务
  `reference_invalidation`：删消息/归档会话同事务翻转
  `agent_runs.decision_basis` 与 `pending_actions.basis` 中的
  `chat_message` 引用为 `source_deleted`（幂等，flag_modified）；③
  chat run basis 引用触发消息（id+occurred_at locator 不带正文，L2
  action 继承引用）+ current_state 的 version 挪进 locator（B4② 形状）。
  **附带修复 A2 真缝隙**：`_chat_context` 按消息主键查
  `client_message_id` 恒查空——消息正文从未经该路径进上下文（此前靠
  会话近史段兜住）；改按 (session_id, client_message_id) 查。验证：
  新增 7 用例 + 全量 346 passed/1 skipped、ruff/format/pyright 0、
  drift 绿、无 schema/迁移/OpenAPI 变更。合并后 B 可摘 S1/S3 注释锚
  （agent_decision 活链 + source_deleted 活链，见
  `HANDOFF/2026-10-04-a-basis-gap-slice.md`）。
- **D-035 后端切片已交付（2026-10-04，A，`feature/m4-d035-chat-search`
  自 `72d42a3`）**：`ChatMessageRead` += `session_id`（必发）；全局检索面
  `GET /v1/chat/search`（`ChatSearchItem` = 消息 + 扁平 `session_title`，
  限域走 `_session_or_404` 纪律，全局域 = 未归档会话子查询 IN 保持
  user_id 无 join 隔离）；**A3 会话内子路径移除**（端点收口，B 已 ack）。
  A3 检索测试全部迁移到全局面并新增跨会话排序/title 加富/未知限域 404/
  跨用户全局隔离/子路径 404 断言。`openapi.json` 重导（A 先行，
  drift 为 Zod→OpenAPI 单向故保绿——按 D-035 排序规则，B 的
  `ChatMessageSchema.session_id` + `ChatSearchItemSchema` + 映射登记
  同批在后）。本地全量 342 passed / ruff·format·pyright 0 / drift
  `--require-zod` 绿；零 schema/迁移。**#58 复核注记**：B 的三必改
  （`c6dfac2`）全对码核实修对，但发现新必改 4——seeding 终点
  （PATCH 计划项）不打脏标，worker cron SPOP 消费脏集存在竞态窗口
  （s1+s6 四个暴露点，单跑 ≈5-7% 假红），修法 A（focus 事件路径，
  `create_event` 同请求 SADD + `_mark_confirmed_plan_items`）/ B
  （无 deadline touch 任务重打脏标）二选一，CHANGES_REQUESTED 已出。
- **B3 工件交付（2026-10-04，`feature/m4-b3-e6-exit`，任务文件
  `TASKS/m4-b3-e6-exit.md`）**：`e6-m4-exit-ui.spec.ts` 六场景 serial
  （门控 `AGENTHU_E6_UI=1`，playwright --list 过、tsc 绿）+ `e6-replay.mjs`
  三模式 provider 假件（grounding 兼容 E5 / chat-tools 首
  轮 function_call→续轮文本 / unavailable 503；`POST /__mode` 控制，
  本地自测三模式过）+ README「E6 栈」手册。**两件事如实上报**：
  ① **首跑环境受阻**——B 机无 docker/PostgreSQL/Redis（多路径核实），
  E6 栈拉不起来；运行手册已沉淀，首跑待栈机（A 的 E5 栈先例）或本地
  安装决策。② **缺口矩阵三件（B3 准备期确诊，均 A 侧产出面）**：
  Plan.basis.agent_decision 无写入者（A 契约 §7 说 planner/replan 写
  references——建议 basis 仍是 legacy 弱类型）；reference 失效态
  （source_deleted/version_mismatch）全后端无发射点（B 契约 §5 删消息
  置失效未实现）；chat_message kind 无运行时产出者。S1/S3 已按实现现实
  断言（run 级 basis 核验 + 单测钉 UI 路径），缺口闭合后补两处活链断言
  （spec 留有注释锚点）。

- **B 双笔交付（2026-10-04，协调人三线 GO）**：① **E6 S1/S3 摘锚**（PR
  #61，`8b577ef`）——`PlanSchema` += 弱类型 plan 级 `basis`（服务端
  `ClientPlan.basis` 恒发、#59 起含 agent_decision，客户端此前 strip）+
  ReplanSuggestion/PlanView 挂「为什么」（agent_decision 检出转交共享
  渲染器）+ spec 活链升级（S1 API/UI 双腿断言任务引用；S3 删被引用消息 →
  读面翻转核验 → UI 失效标注）；desktop 182 绿、drift 即加即绿（OpenAPI
  属性已在，不触排序规则）。② **D-035 客户端切片**（本笔，
  `feature/m4-b-d035-chat-search-client`）——`ChatMessageSchema` += 必填
  `session_id`（排序规则执行：OpenAPI 已先行于 main，同批在后配对）+
  `ChatSearchItemSchema`（显式 z.object——drift 解析器不认 `.extend`）+
  双表映射登记（此时两侧俱在，双源绿）+ `searchChatMessages({q, sessionId?},
  cursor?)`（单页 + next_cursor 加载更多）+ ChatView 检索 UI（命中行
  「标题 · 时间」+ 原文、深链进入会话、失败面不伪造空结果）。desktop 184
  绿、contracts 16、tsc/build/drift 双源全绿。

- **E6 首跑完成（2026-10-04 晚，A 栈，21 轮迭代全绿）**：六用例 serial
  1.9m 全过（真实栈：uvicorn :8010 + arq + e6-replay :9099 + CDP 9222
  构建包，agenthu_e6 库）。**产品修复四件（客户端，e2e 实证驱动）**：
  ① ChatView run 结算追加 `["pending-actions"]` 失效——助手回复行就提供
  「查看确认卡片」深链，不失效则 staleTime 窗口内深链端出旧收件箱（s2）；
  ② PendingActionsView `refetchOnMount: "always"`——收件箱是「现在待我
  决定」面，worker 随时入队且无推送失效链（s6）；③ 提醒面同款
  `refetchOnMount: "always"`——「今天已发送 n/上限 m」是异步落账的当下
  读数（s6）；④ 退出 Backend 由 invalidate 改 `queryClient.clear()`——
  查询缓存无用户维度，失效只会拿死 token 重取且错误态保留旧 data，换
  用户后未重挂载视图会端出前一账号数据（s1，跨账号缓存泄漏）。
  **spec 修订（全部带库内实证注释）**：s1 断言改为引用实际重排任务 +
  CurrentState（真实 focus 链会把超时任务置 COMPLETED，不进 placement
  references）+ 等新账号特有任务名（登录后失效重取竞态）+ 先进今天视图；
  s3 删消息走 UI 真实路径（API 删 + 立即 remount 命中 <30s 旧缓存）；
  s4 双击圈定卡片（不圈定的 .first() 会重解析误点下一卡）+ 第二击
  5s 有界超时（disabled 点击无默认 action 超时会悬到测试超时）+ 终态断
  历史账本（确认即离场）+ 探针 tool.name 嵌套形（读面无扁平 tool_name）；
  s5/s6 精确匹配（导航「确认 1」徽标计入可访问名）+ grant scope 补
  channels（§5.3 fail-closed 双必填，A3 同款形状）+ 已激活视图先离再进
  （重复点击不重取）。**运行注意**：`pnpm --filter @agenthu/desktop exec
  playwright test` 的 cwd 在 apps/desktop，配置在 tests/e2e/ 不会被加
  载——必须 `--config tests/e2e/playwright.config.ts`（否则默认 30s 测试
  超时与 spec 内 60-130s 等待矛盾）。首跑第 2 轮失败后有人工桌面交互
  污染一次（已披露，run 产物不受影响）。产物：e6-logs/（uvicorn/worker/
  replay/playwright 双跑）+ agenthu_e6 库保留不清（最终绿跑账号为审计
  面），待 B 核账。

- **#63 docs 补丁（2026-10-04 深夜，协调人裁定 docs-only 必修）**：三处
  裸 `exec playwright test` 命令改 `test:e2e` 形（manual §4 / README
  E5+E6，命令形已 `--list` 实测解析出 6 用例）+ spec 头「前置」节补
  config 必载注记（使迭代账第 4-5 轮「命令修正进 spec 注释」成真）+
  HANDOFF 审计面贴执行态铁证（`66af4d3` + tracked 树干净，B 焦点①收口
  件）。纯文档 delta，绿跑绑定不受影响；③ 核账查询待 B 的 SQL 清单后在
  保留栈上执行。

- **#63 已合（main `28c58c4`）→ 核账 SQL 已执行回贴（2026-10-04 深夜）**：
  B 的 head-bound approve（@ `4f60ee8`）附四段 SQL 清单，A 在保留栈
  `agenthu_e6` 逐段执行 1a–4c 十查（全部 rc=0，未修数未筛行），psql 原始
  输出按段号贴入 HANDOFF「产物与审计面」节；docs-only PR 已开待 B 机械核。
  两处与清单旁注预期不符已如实标注、不裁决：**1b 任务全量实际 7 行**（B
  预期 7 / 协调人清点 6，第 4 条 overrun = 数字逻辑作业，s6 第三个触发位）、
  **1c draft 重排实际 4 条**（旁注「S1 恰 1」系查询未按场景过滤，s1×1 +
  s6×3 各产一条）。其余各段与预期全符（1a 恰 2、2a 2/2、2b 恰 1 抑制、
  2c 恰 1 L3 grant、3 总计 96、4a/4b/4c 谱全对）。下一步：B 机械核 +
  核账报告 → M4 按 D-030 收口。

- **main 墙钟红修复（2026-10-04 深夜，墙钟类第三例，PR
  `fix/m4-basis-gaps-late-night-guard`）**：`422545f` 合并跑挂
  `test_m4_basis_gaps.py::test_replan_suggestion_carries_agent_decision`
  （北京 23:44：D-027 剩余分钟封顶下「英语听力」30min 单块当日放不进 →
  task 引用空；#63 合并跑 23:1x 绿、#64 PR 侧 23:2x 惊险绿的时间线吻合，
  `28c58c4→422545f` delta 纯 markdown 零代码差异）。该测试走
  `evaluate_replan_triggers`→`generate_plan` 无调用方 start
  （replan_triggers.py:108），placement 窗口由引擎内部
  `max(now, 08:00)`+当日剩余封顶，锚不了只能守卫——补
  `skip_late_night(minutes_needed=45)`（30min 单块 + 建种/求值余量；
  `_split_blocks` 30≤90 不分块）。**本地 23:56:25+08 复验：恰该用例
  SKIPPED、其余 6 过**（与案发同时段）。全文件 7 测试 + 1 共享 helper
  的审计表进 PR 正文（锚定 2 / 免疫 4 / 守卫 1），`422545f` 红跑记录
  保留为证据、不做午夜后刷绿。

- **M4 正式收口（2026-10-05，D-030 出口判据达成）**：E6 六用例两轮绿
  （spec @`66af4d3`，执行态铁证 = tracked 树零改动）→ 十查账面（A 于
  2026-10-04T23:09:41+08:00 保留栈执行，原文入档 #64）→ B 核账报告
  （`HANDOFF/2026-10-05-b-e6-audit-report.md`：十查全符、两处预登记
  对账闭合、confirm 请求 6/结算 4 恰一次指纹、无未解释残差）→ main
  复绿 @`058c512`（#65 墙钟守卫修复，案发到复绿 34 分钟）。实施合并链
  （收口前 git log 逐 SHA 对照）：

  ```text
  #50 05330f3 (D-034 冻结) → #51 9ffe10c → #52 1bdae73 → #54 8d47781 →
  #55 baf3667 → #56 e4fc297 → #57 46e8bb5 (D-035 冻结) → #59 b7250f8 →
  #60 a21b7e3 → #58 85858e5 → #61 cae2ff0 → #62 8d41a0b → #63 28c58c4 →
  #64 422545f → #65 058c512   （#53 关闭未合：billing 节流案，仓库转 public 后撤销）
  ```

  E6 证据链一行：spec @`66af4d3` 两轮绿（6 passed 1.9m + 2.4m）→ 铁证
  （tracked 零改动）→ 十查 @#64 `9d5e614` → 核账「账实相符、无未解释
  残差」（审计 96、run 谱、预算三态、恰一次指纹全落账）。收口 docs PR
  （本 PR，`docs/m4-closure-d030`）归档三件套：核账报告原文（经协调人
  中继 2026-10-05 落档）+ 本条目 + DECISIONS 补记（D-030 附录收口记录 /
  D-035 实现注记 / 墙钟守卫惯例 / 预登记对账惯例 / 延续协议实践 /
  协调人勘误三笔 / 遗留清单结转 M5）。此后队列进入 M5 规划起草（按
  TECH_STACK_AND_WORKPLAN 对齐）。

- **M5 phase-0 冻结（D-036，2026-10-05，协调人裁定）**：双契约
  @`de8f5c0` 冻结（A 稿 = `581606a`；B 稿 = 同步后版本），八项裁定全文
  见 DECISIONS D-036（B 逐字转录登记）：①统一 live 谓词（四读者 + 写侧
  + partial unique index 同谓词，共享查询片段）+ L2 样本不足整链清理；
  ②期限冻结（receipt 90d/logs 14d/staging 24h/备份 30d/隐藏 Chat 7d 硬清）
  + B 的 recover 摘要定义采纳（canonical JSON SHA-256，双端 fixture 钉住）；
  ③A-r2 §4 矩阵冻结（retry = expected_version 单字段），旧 DELETE 原语义
  保留至 E7 通过；④GrantScopeCatalog 派生 + catalog_version 纪律 +
  local_time_window M5 禁止；⑤E7 报告分离；⑥validity 移出 MemoryUpdate
  可写面；⑦五项结转门参数（HNSW/SSE/daily_budget/许可 + key 轮换 =
  P0-6 硬发布门）；⑧实施令 P0-1/P0-2 即刻并行。延续终检：B 稿 +31/−7
  恰为「采纳 A 五建议 + 字段重镜像 + 留裁项 + 措辞区分」，机械延续规则
  第三次适用（A approve `293d7ca`→`de8f5c0`；B→A 直接绑定 `581606a`）。
  B-r2 作者身份确认在案（报告 §1 + PR 评论）。本提交 = #67 最后一提交，
  待 A 转录忠实性 head-bound approve → CI 绿转 ready → 协调人合并，
  P0-1（A）/ P0-2（B）随即开工。

- **P0-2 切片一开工（B，2026-10-05 深夜，分支
  `feature/m5-p0-2-owner-namespace`）**：本地存储 owner 命名空间落前两层
  ——TS localStorage（LocalEventQueue/LocalFocusDraftStore，键
  `agenthu.event-queue:{owner}`/`{owner}:corrupt`/`agenthu.focus-draft:
  {owner}`）+ Rust `offline.sqlite3`（pending_events/sync_state/focus_draft
  三表迁移入 owner 维度，重建 PK 为 (owner, client_event_id)/(owner,key)/
  (owner)——两账号同上游事件不再被全局唯一键静默丢弃；历史行全归
  'unowned'）。ownerKey = SHA-256(origin+"
  "+userId) 前 16 hex（自包含
  同步实现，跨环境确定性优先）。会话层 onOwnerChange（login/restore→
  owner、logout/过期→null，等值守卫）驱动 services 的单一 ownerScope；
  coordinator 换号守卫（未登录不推无主队列；flush 中途换号即中止）。
  无主处置面 countUnowned/adoptUnowned/discardUnowned（目标 cursor
  优先；legacy 键一次性隔离到 unowned，禁自动归户）。Stronghold 分槽
  延后至 receipt 需要（P0-4）：现单槽 token 登录即覆写、无残留。
  证据：desktop vitest 200/200 + typecheck 绿；cargo test 20/20
  （含 owner 隔离/legacy 迁移/adopt-discard 新例）。待 A head-bound
  互审 → 协调人实测合并。
- **P0-1 切片 1 落地 + 切片 2 交审（A，2026-10-05，main `3f023ca` =
  #68 合并）**：切片 1（统一 live 谓词 + validity 移出可写面 + 索引
  窄化 45b7db4cb2cb）经 B approve @`e617ae2` 合并；合并前远端红一次
  （ruff format --check 与本地检查不同形），教训已入任务书 §3 流程
  注记（交付前本地必须跑 CI 同形命令）。切片 2 开工即交审：持久操作/
  清理账本（三表，owner_handle 不透明键控、无 users FK，幂等键 + 代际
  快照）+ 屏障/代际原语（raise/lock/check/release，FAILED 不解除、
  account 不自动解除，退避梯 5/30/120/300/900s + 24h 窗 + 5min 租约）
  + 依赖清单矩阵（26 表全登记 + Redis 字面量 AST 扫描，存在但未登记
  即失败）+ 迁移 e6d496a26f09（显式回填，server_default 规范化假漂移
  已绕开；往返 + autogenerate 零漂移双轮验证）。378 passed/1 skipped、
  ruff 同形双绿、pyright 0、OpenAPI 零变更（D-035 不触发）。三处
  实现期判断（幂等比较不含代际 / 5min 租约 / enqueue 重复 no-op）见
  任务书 §5 待 B 核。#69（B 的 P0-2 切片 1）A 已 RC：换号守卫窗口
  一项必改（多批循环顶部无 assert，A→B 直切可致 A 事件带 B token
  上推）+ 四 advisory；待 B 修复后新头复核。

- **P0-3 开工（A，2026-10-05，基线 main `824ab5a` = #70 合并头）**：#70
  经 B head-bound approve 合并（B 互审三条 P0-3 携带项 + memories.embedding
  should-fix + enums 名=值 advisory，产出并入任务书）；#69 修复头
  `3b97927` A 复核 approve（三道守卫 + 多批测试 + 补交 session 测试），
  待协调人合并。P0-3 = 删除/导出 API 与执行，切片计划与六项强制携带
  清单见 TASKS/m5-p0-3-data-api.md；首提交落：embedding 补录、
  matching_barrier fail-closed、N1 全谓词升级、enums 名=值对齐（零迁移）、
  DECISIONS 回填范式注记、N2/N3 档位记录。

- **P0-3 切片 1 主体交审（A，2026-10-05，分支 feature/m5-p0-3-data-api）**：
  /v1/data 四路由（capabilities/previews/deletions/operations + 
  X-Data-Generation 响应头）+ 闭包枚举一图（五 source kind + memory 整链
  + account 全 registry 扫描，所有权 404）+ preview 10min digest 绑定
  （graph_version=REGISTRY 摘要）+ confirm 事务（幂等重放优先/preview_stale/
  deletion_in_progress/users 行锁串行化 + savepoint IntegrityError 收敛=
  B 携带①/屏障/清理项 payload ids/account 停用+撤权+receipt 能力一次
  吐出摘要落账/source 抑制 HMAC）+ 迁移 a9c41f7d2e83（三新表，
  receipts/suppressions 值键控无 FK）+ registry 三新表登记（inventory
  开发期自证一次）。OpenAPI 65 路径重生、漂移绿；DataSafeError 组件名
  避让 agent 域 SafeError。四条实现期判断见任务书 §5（败者 bump 多耗/
  抑制上游锚点/audit redact 复用枚举/ChatMessage 版本戳）。待 B 互审。

- **P0-3 切片 1 RC 修复（A，2026-10-06）**：B 互审 @ `77c38e1` 全签
  （四判断 + 五核点）唯一必改 = 核点 4 组合测试缺失——已补
  "过期 preview × 幂等命中 → 202 同 op"（source 域；account 域首次
  confirm 即停用无法测该组合）。切片 2 强携两条（executor 先读
  payload 再分派、多事件派生 task 部分源删除语义正面裁定）、切片 3
  强携三条（upstream_id 前置纪律入任务书、E7-7 seed 带 upstream_id、
  assert_writable/孤儿流/抑制解除）已录入任务队列。
