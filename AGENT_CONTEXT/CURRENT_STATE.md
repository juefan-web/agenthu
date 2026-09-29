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

## 尚未满足的验收项（合并 main 的前置门槛）

- **Windows 构建包人工端到端演练**（两位开发者共同）：校园登录/2FA → 采集 →
  Event 同步 → Task/Plan（显示 `title`）→ 确认计划 → Focus 完成 → 断网重试与冲突处理；
  DevTools 无 CSP violation，拒绝 Event 可见原因且不重复上传。
- 客户端开放项：`flush` single-flight 与重试上限、SQLite 连接 `busy_timeout`/复用、
  `campus_restore` 版本不兼容自清理、`assertSafeEvent` 无条件执行、Testing Library/
  Playwright 用户流程测试、`backendUrl` 运行时配置、Android 凭据存储/通知。
- 发布前完成 OneTHU BSL 1.1、LearnX 及依赖许可的逐文件分发审查。

## Blockers / decisions needed

- OneTHU 源/API 不可达 → 服务端 adapter 保持显式 stub。
- `minio/minio` 镜像上游 404 → 本地用 `s3mock` profile 验证。
- 联合 CI 应跑真实的 `packages/contracts` Vitest/typecheck；Backend 分支只有冻结
  快照替身（D-021）。

## Next（2026-09-29 更新：PR #1 已转正合并进 main `c2b58c8`，A/B 均已回归）

1. **M1-1（最高优先，A/B 并行）**：campus 作业事件派生 Task——先由 A 冻结
   契约（派生规则、Task 上游身份唯一约束、deadline 时区规则、不派生清单），
   再 A 做 Backend handler/迁移、B 做事件载荷时区修复与派生任务展示；见
   `TASKS/m1-1-assignment-event-derivation.md`。round-5 共同验收真实数据
   全链（采集→任务→计划→Focus→完成）。
2. **A**：`TASKS/backend-m1-tasks.md`——D9 明文 cookie 边界 review 补录与
   DECISIONS 编号（快速还债）、CurrentState 投影语义（M1-2）、backlog
   （events keyset 分页、多 worker 限流、M3 Memory/Grounding 预研）。
3. **B**：`TASKS/client-m1-hardening.md`——flush single-flight + 重试上限、
   SQLite busy_timeout/WAL、restore 自清理与 assertSafeEvent 无条件化、
   backendUrl 运行时配置、Testing Library/Playwright 测试纵深。
4. 后续分支一律从 main 拉出（`feature/*`）；集成分支仅作存档。
