# Backend fixes from 2026-09-28 merge-1 manual test

负责人：开发者 A。上游输入：`HANDOFF/2026-09-28-merge1-manual-test-report.md`（D5、D7）。
以下根因已经过代码复核，可直接定位修复，不必重新诊断。

## D5（P1）current-state 并发首请求 500

- 根因：`backend/services/current_state.py` `get_or_create_state()` 是无锁的先查后插
  （`select` → `session.add` → `flush`）。两个并发首请求同时判空 → 双 INSERT →
  `uq_current_states_user` 唯一约束冲突 → 未捕获 IntegrityError → 500。人工测试
  5 并发复现 2/5，与该模式一致。
- 次生问题：未处理异常由 ServerErrorMiddleware 生成（在 CORSMiddleware 之外），
  500 响应不带 CORS 头，WebView 端表现为 CORS 错误，掩盖真实 5xx。
- 修复方向：`INSERT ... ON CONFLICT (user_id) DO NOTHING` 后重查，或对齐 D-019
  的 advisory lock 模式；同时注册 app 级 `Exception` handler（FastAPI
  exception handler 在 CORS 中间件之内），让未处理异常也返回约定 error envelope
  并携带 CORS 头。
- 验收：新增并发首请求回归测试（多线程/多连接同时 GET `/v1/current-state`，
  参考 plans today 的既有并发测试写法）全部 200；人为抛出的未处理异常响应带
  CORS 头且为约定 envelope。

## D7（P2）当日空草稿计划吸收不了新任务

- 根因：`backend/services/planner.py` `resolve_today_plan()` 里
  `latest_open_plan(since=day_start)` 会复用当日已存在的空 items 草稿；
  `is_client_valid_plan` 对空 items 返回 `all([]) == True`（client-valid），
  因此新建任务后 today 永远返回旧空草稿，用户必须手动 cancel 才重排。
- 修复方向：`resolve_today_plan` 复用当日 open plan 前增加「items 非空 或 无待排
  任务」的条件；空草稿且存在 pending tasks 时重新生成（原草稿转 superseded 或
  按 D-019 语义处理），不改变 K1/D-023 的 client-valid 定义（空计划在契约上仍
  valid，只是不再被 today 复用）。
- 验收：回归测试覆盖「生成空计划 → 创建任务 → GET /v1/plans/today 返回含新任务
  的计划」；既有 plans/today 契约与并发测试不回归。

## 协作项（D4 title 的 Backend 侧）

- B 将在 `packages/contracts` 的 `PlanItemSchema` 增加 `title: z.string()`。请确认
  `backend/schemas/client_contract.py` 中 `title` 是否需从 "Backend-only additions"
  移入核心对齐集合，并共同跑
  `python -m backend.scripts.check_contract_drift --require-zod --zod packages/contracts/src/index.ts`
  无漂移；冻结快照 `tests/fixtures/client_contract.ts` 同步。

## 不负责

- D1/D2/D3/D6 属客户端（见 `client-merge1-review-fixes.md`）。
- 不改变 Event 契约与 2FA/校园认证职责边界。

## 完成标准

- CI 全绿（含新增回归测试）；与本任务文件一起更新 `CURRENT_STATE.md`；
  提交推送后在完成报告中附可 fetch 的 commit hash。
