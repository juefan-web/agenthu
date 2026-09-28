# CURRENT_STATE

Updated: 2026-09-28 · Milestone: **M0 (engineering baseline + frozen contracts)**
· 集成分支 `integration/study-time-m0` 已合并 Backend（`61fcf82`）与客户端
（`a2693e9`），冲突已解决，双侧 CI 与联合 drift check 全绿（draft PR #1）。
· **Merge-1 Windows 构建包人工测试结论：不建议转正合并**（见
`HANDOFF/2026-09-28-merge1-manual-test-report.md`，D1-D7 七项缺陷经代码复核全部
属实）。修复任务已立项：A 见 `TASKS/backend-merge1-review-fixes.md`（D5/D7），
B 见 `TASKS/client-merge1-review-fixes.md`（D1/D2/D3/D4/D6）。登录链修复参照上游
OneTHU dev3 实现，要求一次登录不重复认证。

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
  2FA 等待期密码驻留不修：vendored info-lib 的 id roam 需重放明文密码，属上游约束。
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

## Next

1. 集成分支（本分支）跑双侧完整检查 + `check_contract_drift --require-zod --zod
   packages/contracts/src/index.ts` 联检，推送并开 draft PR 进 main。
2. Windows 构建包完成上面的人工验收项后，PR 转正合并。
3. M1：真实（手动优先）导入适配层与幂等摄取、更丰富的 CurrentState、权限层后的
   LLM planner、带真实调用方的 CurrentState 重算。
