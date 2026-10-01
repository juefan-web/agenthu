# DECISIONS

Short, factual records. Add a new entry when a boundary or data contract changes.

## D-001 — Non-native enums (VARCHAR + CHECK)

Status enums use `sa.Enum(..., native_enum=False, create_constraint=True)`.

Reason: adding/removing an enum member becomes a normal migration instead of `ALTER TYPE`, and the
model works with a plain metadata `create_all` in tests. Trade-off: no native PostgreSQL enum type.

Note: Alembic autogenerate emitted duplicate CHECK constraints for these enums; the generated
migration keeps only the constraint rendered by the column type. `alembic check` confirms no drift.

## D-002 — CurrentState is a recomputed projection

`services.current_state.recompute_current_state` reads Tasks/Plans/recent Events and upserts one row
per user with an incrementing `version`. It is not an Event copy.

`current_plan` returns the **confirmed** plan only; unconfirmed proposals are visible via the Plans
API but are not the user's current plan.

## D-003 — Event dedupe via unique constraint

`events (user_id, dedupe_key)` is unique. `create_event` checks first, and a savepoint handles the
race so concurrent replays return the existing Event (HTTP 200 + `X-Deduplicated: true`).

## D-004 — Audit middleware is toggleable

Mutating requests are audited by middleware, but it can be disabled with `AUDIT_ENABLED=false`
(tests). Permission decisions are recorded in the service layer regardless, so audit infrastructure
is always exercised.

## D-005 — Storage is an interface, S3 uses path-style

`ObjectStorage` (InMemory + S3). `S3Storage` uses `addressing_style="path"` so MinIO, S3Mock and
hosted S3 all work. Buckets are created on startup (`ensure_bucket`), removing the need for a
separate bucket-init container.

## D-006 — MinIO default, s3mock fallback

Compose defaults to `minio/minio` (per the stack decision) and adds an `s3mock` profile. The MinIO
Docker Hub repository currently returns 404 upstream, so local verification can use s3mock. No code
change is needed because only the `ObjectStorage` interface is used.

## D-007 — DEVELOPMENT.md is the status document

`DEVELOPMENT.md` now holds `# Current Status` (Completed/In Progress/Blocked/Known Issues/Next
Steps/Recent Decisions). Workflow guidance moved to `AGENT_CONTEXT/` and `README.md`.

## D-008 — Deterministic planner for M0

`services.planner` is a transparent baseline (`deadline_then_priority`) so the loop is testable
without an LLM. The M1 LLM planner will reuse the same Plan model and permission layer.

---

## Review fixes (astra6 report on e715f9e)

## D-009 — The desktop client contract (`packages/contracts`) is authoritative

Status: accepted. Context: `TECH_STACK_AND_WORKPLAN.md` assumed a Flutter client generated from
OpenAPI, but the actual client on `feature/client-tauri-campus-adapter` is a React/Tauri desktop app
with hand-written Zod contracts in `packages/contracts` and `apps/desktop/src/backend/client.ts`.

Decision: for the endpoints the client consumes, the Backend serves the client's exact shapes at
`/v1`:
- `POST /v1/events/batch` (EventEnvelope + provenance, client_event_id correlation)
- `GET /v1/tasks` (bare `Task[]`, lowercase status)
- `GET /v1/current-state`
- `GET /v1/plans/today`, `POST /v1/plans/{id}/confirm`
- `POST /v1/focus-sessions`, `PATCH /v1/focus-sessions/{id}`

Additional Backend-only fields are kept (Zod strips unknown keys). The API prefix moved from
`/api/v1` to `/v1`. Contract mappers live in `backend/services/client_view.py`.

Consequence: `TECH_STACK_AND_WORKPLAN.md` was realigned to React/Tauri, and the stale Flutter
references in `AGENT_CONTEXT/` and the Backend comments were removed so the docs match this decision.

## D-010 — Event dedupe key is computed on the Backend

`source:upstream_id:semantic_version` (the client's `eventDedupeKey`) is derived server-side from the
Event provenance; a client-supplied `dedupe_key` is only an additional signal, never the trusted
boundary. Enforced by the unique `(user_id, dedupe_key)` constraint.

The three parts are escaped exactly like the client's `eventDedupeKey` (`\` -> `\\`, `:` -> `\:`
before joining) so adapter values such as `upstream_id="assignment:hw-1"` cannot create a
field-boundary collision between different triples.

## D-011 — Focus is a persisted session with an idempotent completion

New `focus_sessions` table and `running -> paused/running -> completed|abandoned` transitions.
Completion recomputes actual minutes at most once: the `focus.completed` event uses
`focus-session:{id}:completed` as its dedupe key and terminal sessions ignore further patches.

## D-012 — Sensitive Event fields are rejected at ingestion

`backend/core/sensitive.py` recursively rejects credential-like keys in `data`/`context`/
`provenance`, enforces size and depth limits, and reports only key paths (never values). Batch
ingestion returns them as per-event `rejected` entries.

## D-013 — Non-local environments must set a strong SECRET_KEY

`Settings` refuses to construct outside local/dev/test when `SECRET_KEY` is the default, empty or
shorter than 32 characters.

## D-014 — Cross-user references are rejected

Plan items, CurrentState overrides and Memory `source_event_ids` are validated against the
authenticated user; missing/foreign ids return 404.

## D-015 — Replan is restricted to non-terminal plans

Only DRAFT / PENDING_CONFIRMATION / CONFIRMED plans can be re-planned; COMPLETED / CANCELLED /
SUPERSEDED return 409.

## D-016 — Uploads are size-limited while streaming

Uploads are read in 1 MiB chunks and rejected with 413 as soon as the limit is exceeded; a
compensating object delete removes orphans if metadata persistence fails.

## D-017 — CI runs on every pushed branch

`push` triggers cover all branches, not only `main`, so feature branches are validated before merge.

---

## Second review (astra6 report on eb1a058/e2d2841)

## D-018 — Authentication is Bearer JWT (frozen)

Decided with the reviewer. The Backend freezes:
`POST /v1/auth/register`, `POST /v1/auth/login` (and `/v1/auth/token`), `GET /v1/auth/me`, plus the
401/expiry semantics (JSON error envelope, `code: "unauthenticated"`).

The client (Developer B) implements its own Backend login, stores the token encrypted, attaches
`Authorization: Bearer <jwt>` to requests, and clears it on logout. The Backend does **not** add a
cookie session. Campus (OneTHU) accounts and Backend accounts are separate and must not be mixed.

## D-019 — `/v1/plans/today` selection rules

`/v1/plans/today` must always return a plan the client can parse, so it:
- returns the confirmed plan only if it is client-valid;
- otherwise reuses a client-valid draft/pending plan **created since the start of today** in
  `default_timezone` (default `Asia/Shanghai`);
- never reuses a cross-day draft, and never returns a task-less manual plan
  (`task_id`/`start_at`/`end_at` must be non-null for every item);
- otherwise generates a deterministic plan.

Confirmed-plan semantics: a confirmed plan is the user's **global current plan**, not a per-day
object. It is returned regardless of the local day it was created, because confirmation is an
explicit user decision that stays in force until the plan is cancelled, superseded by a re-plan, or
completed. Only *unconfirmed* proposals are day-scoped (`created since the start of today`), so a
stale draft from a previous day is never reused.

Concurrent first requests for the same user/day are serialized by a PostgreSQL transaction-level
advisory lock keyed by (user, local day) (`planner.lock_today_proposal`), so two simultaneous
`GET /v1/plans/today` calls cannot both observe "no proposal" and insert duplicates.

## D-020 — CORS uses explicit client origins

Defaults are the real client origins: Tauri `devUrl` `http://localhost:5173` (and `127.0.0.1:5173`)
plus the Tauri production webview origins (`tauri://localhost`, `http://tauri.localhost`). A
wildcard origin together with credentials is invalid in browsers, so configuring `*` automatically
disables credentials.

---

## Third review / A/B contract integration

## D-021 — Contract drift (openapi.json + client Zod) is checked in CI

Status: accepted. Context: the desktop client validates responses with the Zod
contract in `packages/contracts` (D-009), but nothing failed CI when the Backend changed a
client-consumed shape or forgot to regenerate the OpenAPI artifact.

Decision: `backend/scripts/check_contract_drift.py` runs in CI before the OpenAPI export and
fails when:
- `openapi.json` differs from the schema generated by the running app (stale artifact), or
- a field declared by the client Zod contract is missing from the matching OpenAPI component,
  or its base JSON type is incompatible.

The client contract is parsed from `packages/contracts/src/index.ts` when present; a frozen
snapshot at `tests/fixtures/client_contract.ts` (source commit recorded in the file) lets the
check run on Backend-only branches. Request schemas (`EventEnvelope`, `EventBatchRequest`,
`EventProvenance`) and response schemas (`EventBatchResponse`, client Task/CurrentState/Plan/
Focus) are compared in the matching direction. Null widening (`str | None`) is intentionally not
enforced because the Backend uses it to represent absence; runtime shapes are asserted by
`tests/integration/test_client_contract.py`.

The check is exposed as `agenthu-contract-drift`; `--write` refreshes `openapi.json`.

## D-022 — `EventBatchResponse.next_cursor` is deprecated, not implemented

Status: accepted (2026-09-28, A/B contract integration review blocking item). Context: the batch
ingestion response returned `next_cursor` as a placeholder that only echoed the request's
`client_cursor`, which looked like a real incremental sync cursor but carried no server-side state.

Decision: deprecate rather than implement. The client's sync coordinator already owns cursor
progress (it resends unacked envelopes until they are accepted/deduplicated), so a server-side
cursor would duplicate the same state the client is required to keep. The field stays in the
frozen contract (marked `deprecated: true` in OpenAPI, `z.string().nullable()` in Zod) for
response compatibility; it must not be used by new client behavior and will be removed in the
next contract version. Raising a real server-driven incremental sync cursor requires a fresh
decision (it belongs to the M1 sync work, not the M0 batch contract).

## Fourth review fixes (2026-09-28, Developer A)

## D-023 — Client-invalid plans are impossible to create or confirm

Status: accepted. Context: the integration review found that a manually created plan
without `task_id`/`planned_start`/`planned_end`, once confirmed, was served by
`GET /v1/current-state` and broke the desktop client's Zod `PlanItemSchema` parse
(non-null `task_id`/`start_at`/`end_at`). The drift check cannot catch this because null
widening is intentionally ignored there.

Decision: enforce the invariant at three layers instead of filtering one endpoint:
1. Creation (`POST /v1/plans`) rejects task-less items (the client contract has no
   task-less plan item) and backfills `planned_start`/`planned_end` from `planned_minutes`
   (default 60) so manual plans stay usable without full scheduling input.
2. `POST /v1/plans/{id}/confirm` rejects client-invalid plans (422) — a confirmed plan
   becomes the current plan, which is served through the client contract.
3. `current_plan_for` filters client-invalid confirmed plans in SQL (shared
   `backend/services/plan_validity.py`, home of both the Python and SQL forms) as
   belt-and-braces for legacy rows written before this change.

Rollback: revert the commit; no data migration is involved. Existing legacy plans keep
their shape (they are simply no longer confirmable).

## D-024 — `recompute_user_current_state` worker task removed

Status: accepted. Context: the Arq task had no caller (dead code) and its semantics were
underspecified (no trigger, no debouncing).

Decision: delete it; `WorkerSettings.functions` now only registers `ping`. CurrentState is
recomputed synchronously on the request path today. An off-request recompute belongs to M1
and must arrive with a real caller and a decision about trigger points.

## D-025 — Auth rate limiting and secrets fail closed

Status: accepted. Context: the review flagged (a) `SECRET_KEY` strength only enforced when
`ENVIRONMENT != "local"`, so a deployment that forgot to set `ENVIRONMENT` silently
accepted the dev key and JWTs could be forged; (b) `/auth/register|login|token` had no
brute-force throttle and leaked user existence through timing; (c) `GET /v1/jobs/{id}`
returned any job's status/result to any authenticated user.

Decision:
- `ENVIRONMENT` now defaults to `production` (fail closed): without explicit
  `local`/`dev`/`test`, weak `SECRET_KEY` **and** weak `S3_SECRET_KEY` (was the hardcoded
  `agenthu123` default) are rejected at settings load. Local dev opts in via
  `.env.example` / `docker-compose.yml` (`ENVIRONMENT=local`), CI sets `ENVIRONMENT=test`.
- Auth endpoints share an in-process sliding-window limiter (10 req/min per client IP by
  default, `AUTH_RATE_LIMIT_MAX=0` disables; tests disable). Over-limit returns the frozen
  429 `rate_limited` envelope plus `Retry-After`. Login paths burn a bcrypt comparison
  against a cached dummy hash for unknown emails so response timing does not reveal
  account existence.
- Arq job ids are prefixed with the owning user id (`{user_id}:...`); `GET /v1/jobs/{id}`
  checks the prefix before any Redis round-trip and answers other users with 404.
- The rate limiter is per-process (single uvicorn worker in M0); swapping in a
  Redis-backed limiter is the documented seam for multi-worker deployments.

## D-026 — zhjw.cic.tsinghua.edu.cn 单 host http:80 窄口（D9，明文 cookie 边界）

Status: accepted（2026-09-29 补录；实现 `6a72dfd`，A 联合 review 通过）。Context：
merge-3 发现 vendor 教务课表直连 `http://zhjw.cic.tsinghua.edu.cn:80`（`info/urls.ts`
`ZHJW_PREFIX` + `http.ts` `PUBLIC_DIRECT_HOSTS` 直连注释），而 Rust 白名单
`allowed_campus_url` 仅放行 https:443，入口与重定向策略双处拒绝，采集确定性失败
（D9）。

Decision：为该**单个精确 host** 开 `http:80` 窄口，不做子域通配、不放开其他
http host、不允许 username/password 形式的凭据注入；重定向策略复用同一谓词，
窄口语义自然继承到每一跳。备选 b 案（改走 webvpn `/http/` 包装）被 vendor 自己
的加白注释证伪——教务 host 的 wengine 票从未建立（包装路径撞引导壳），上游
2026-09-19 起教务访问统一直连 JSONP，b 案等于重走已被上游实测失败的路径。

**接受的残余风险**：该 host 的教务会话 cookie 以明文 http 传输（JSONP 的固有
属性，上游如此），风险面为同网段嗅探与 DNS 欺骗冒充该 host——无 TLS 即无证书
验证，客户端侧不可缓解，只能把范围压到最小（单 host、单端口）。与 D8 cookie
镜像的交互已核对：zhjw 的明文 cookie 进入 Rust 权威仓与 TS 镜像的粒度与其他
campus cookie 相同（host/name/value/hostOnly），host-only 域隔离保证它只回发
该 host，无跨域放大。

**Revisit 条件**（非阻塞）：上游 ZHJW_PREFIX 改为 https 的当天，同步删除此
例外并恢复全 https 白名单。

A 的联合 review（范围最小性 / 重定向继承 / 伪造测试覆盖逐项核对）全文见
`TASKS/client-merge3-d9-and-residuals.md` 末节。

## D-027 — CurrentState 投影语义：available_minutes 口径与 context 派生

Status: accepted（2026-09-29，M1-2）。Context：round-4 观察到投影
`available_minutes`/`context` 恒为 null/空而 version 空转；M1-1 落地后真实任务
与课表事件进入 Event 流，投影需要给出语义。

Decision：`available_minutes` = **用户 override 优先，否则**
`max(0, 本地日剩余分钟 − 今日课表重叠分钟 − 当前任务剩余估时)`（休息扣除
显式为 0，魔法扣除不做）。课表取自 `time.schedule.entry` 事件，条目按
`DEFAULT_TIMEZONE` 组合 naive date/时刻串，同 `provenance.upstream_id` 只取
最新版本（semantic_version 变更产生的新行天然取代旧行，变更/移课不双计）。
derived 不落列：override 的持久化位置不变，derived 是纯函数输出、Event 流是
事实源，可观测性经 `recent_state.available_minutes_breakdown` 补齐——同时避免
与 M1-1 并行的 alembic multi-head 合并。`context` 派生优先级：override >
在课 > 专注中 > 进行中任务 > 即将上课（≤30min）> 空闲（有待办）> None，
经内部 `context_label` 传递，客户端契约不变。完整口径与 B 对齐清单见
`TASKS/m1-2-currentstate-projection.md`；口径调整必须走 DECISIONS 变更。

## D-028 — M1-1 契约冻结：assignment 事件派生 Task

Status: accepted（2026-09-29，M1-1 阶段 0，A 产出、B 评审）。Context：D10 裁定后，
campus 作业事件（`study.assignment.discovered|updated`）需要服务端派生 Task，
驱动 Study + Time 主线进入真实数据。本条冻结四组语义，双方据此并行。

### 1. 派生规则

- `study.assignment.discovered` → 创建 Task（title、deadline、late_deadline、
  description 按 event `data` 映射；`estimated_duration_minutes` 暂不猜，留空由
  用户/后续 planner 补）。
- `study.assignment.updated` → 幂等更新：deadline/标题变更刷新既有 Task；
  `data.status` 为 submitted/graded → Task `COMPLETED` + `completed_at` =
  event `occurred_at`。已 COMPLETED 的任务不回退（与 focus 完成语义一致，C2）。
- 派生在 `process_event` 的 SAVEPOINT 内运行（C1 语义：handler 失败不丢原始
  Event，失败审计为 `event.handler_failed`）。

### 2. Task 上游身份与幂等键

- `tasks` 新列 `source_upstream_id TEXT NULL` + 唯一约束
  `(user_id, source, source_upstream_id)`（`uq_tasks_user_source_upstream`）；
  手动任务该列为 NULL（PostgreSQL 唯一约束天然放行多 NULL）。
- Task upsert 键 = `(user_id, source, source_upstream_id)`；其中 `source` 取
  event `source` 字段（如 `campus`），`source_upstream_id` 取 event
  `provenance.upstream_id`。**与 Event dedupe 键的关系**：dedupe 键含
  `semantic_version`（同 upstream 新版本 = 新 Event 行），Task 键不含——
  semantic_version 变化触发的是**更新既有 Task**而非新建，这是幂等的来源。
- API 面：`source_upstream_id` 不进 `TaskCreate`（派生是服务端行为，客户端不
  造上游身份）；`TaskRead` 暴露该列（Backend-only addition，客户端 Zod
  strip，契约无破坏）。Task 标题冲突时后端不加后缀——最新事件赢（见上）。

### 3. deadline 时区规则（冻结 a 案）

- **客户端必须发 `+08:00`（或任意显式偏移）tz-aware ISO**；vendor 原始串保留
  在 `deadline_raw` / `late_deadline_raw` 溯源。
- **Backend 对 naive deadline 拒收**，作用点在两个边界：
  a) `POST /v1/events` 与 `/v1/events/batch` 中 `study.assignment.*` 事件的
     `data.deadline` / `data.late_deadline` 若为无偏移 ISO → 该 envelope 进
     `rejected`（reason 注明 naive deadline），**不入库**——naive 串入库后没有
     正确解释途径，只会成为永远无法正确派生的死数据。
     **[勘误 2026-09-29，B 的 PR #4 审查备注 #1]** 原文「留在客户端队列等 B
     修复后重发」与客户端实际行为不符：协调器对 `rejected` 的既有（且有回归
     测试的）语义是**移出队列并把 reason 透出 UI**——naive 事件留在队列只会
     反复被拒。正确的恢复路径是**重新采集**：被拒事件从未入库，服务端
     dedupe 无记录；修复后的采集以同一 upstream 身份重新生成（新的
     semantic_version → 新 client_event_id），正常派生，无锁死。不得按原文
     字面实现「保留重发」的特殊分支。
  b) `TaskCreate` / `TaskUpdate` 的 `deadline` naive → 422。这是对 C4「全部
     datetime naive→UTC」的**定向收紧**：deadline 是排序核心字段，静默 +8h
     偏移比拒收更危险。C4 的 naive→UTC 对 `GoalCreate.target_date`、
     `PlanItemCreate.planned_*`、`PlanGenerateRequest.start_at` **维持不变**
     （非本轮范围，待真实数据验证后再评估是否同样收紧）。
- 已存的 naive 历史数据：M0 阶段无 campus 事件入库（D10 事实），无历史清洗
  需求。

### 4. 不派生清单（本轮冻结）

`study.course.discovered`、`time.schedule.entry`、
`time.academic_calendar.updated` 不派生 Task：课表已进入 CurrentState 投影
（D-027），课程主数据与日历的领域化（Goal/Course 实体）属 M1 后段。新增派生
类型必须先补 DECISIONS。

### 兼容与回滚

- 迁移 up/down 完整（加列 + 唯一约束；down 删列）。fixtures、OpenAPI、drift
  基线随实现同步。回滚 = revert 迁移与 handler，Event 流不受影响（派生是
  投影，事实层不回滚）。

## D-028 附录 — Round-5 遗留裁定（L3/L4/L5，2026-09-29）

**L5 哨兵作业**：上游对无截止作业用 `2099-09-30 23:59` 占位。裁定：**Event 层如实
入库（事实层不改写上游数据），派生层排除**——`data.deadline` 距事件时刻超过
**2 年**视为哨兵，不派生 Task（真实课程作业不超过一学期，2 年是保守界）。
无论 submitted/graded 状态，哨兵一律不派生。回归测试覆盖哨兵入库无任务 +
正常 deadline 对照派生。

**L3 派生标题**：vendor 作业标题是裸作业名（"Homework 2"），跨课程同名不可
辨识（round-5 抽样 3 中 1 个可对上的根因；`CampusAssignment` 适配层类型当前
未携带 vendor 已有的 `courseName`）。裁定：派生标题规则 = **`{course_name}：
{title}`**（course_name 存在时），缺省纯 title，title 缺省回退 course_name 或
upstream id。`course_name` 同时进 `task.extra` 溯源。**B 侧协作项**：适配层
`CampusAssignment` 补 `courseName` 并在事件 `data.course_name` 透传（vendor
`dsa.ts` 载荷已含该字段）；透传落地前旧载荷按缺省分支渲染，向后兼容。

**L4 当日含项草稿不吸收新任务**：确认为 **D-019/D-023/D-028 的预期行为**。
`latest_open_plan` 复用「items 非空」的当日草稿/已确认计划，是对用户已确认
结构的保护——静默吸收新任务等于破坏确认语义（AGENTS.md 权限模型：计划变更
应可解释、可拒绝）。新任务入计划的显式路径 = cancel → 重排（round-5 B7 实测
路径，998ms 确认）。M2 planner 议题：新任务到达时的「建议重排」提示（Level 1
建议，不自动执行）。

## D-027 附录 — breakdown 出口裁定（Round-5 L1，2026-09-29）

`available_minutes_breakdown` 当前仅在 `recent_state`（backend-only dict）内，
客户端契约不可见，B6 分量合理性无法外部观测。裁定：**入契约而非独立诊断
端点**——B 侧 `CurrentStateSchema` 增加可选 `recent_state:
z.record(z.unknown())`（一行，不锁定内部结构，breakdown 演进无契约摩擦）。
理由：① 可解释性数据与投影同生命周期，属投影本体（AGENTS.md「重要建议应
给出原因」）；② 不新增端点即不膨胀 API 面与权限模型；③ record(unknown) 的
弱类型恰当地表达"内部诊断、结构可演进"。M2 实现（B 侧 Zod 一行 + drift
基线同步）；**不建独立诊断端点**。

## D-029 — 列表 keyset 分页契约（Round-5 L2，冻结设计、M2 实现）

Status: accepted（2026-09-29 冻结设计；实现排 M2）。Context：`/v1/tasks` 默认
`limit=50`（上限 200）且客户端无分页，79 条任务 UI 只见 50 条；events 列表同
为 offset 分页且事件量随采集增长（A-3 backlog 同族问题）。短期过渡：客户端
请求 `limit=200`（B 侧，一行）。

Decision：tasks 与 events 列表统一 keyset 分页契约：
- 查询参数：可选 `cursor`（不传 = 首页，语义同今天的无参请求）；`limit` 语义
  不变。**offset 参数保留但标记 deprecated**（兼容期一个 M 阶段后移除）。
- 响应：现有 `Page` 契约增加可选 `next_cursor: string | null`——**null 表示
  没有更多页**。注意与 D-022 的区别：D-022 弃用的是 `events/batch` 摄取响应
  里的游标回显（客户端自有状态），本条是列表查询的**服务端游标**，语义不同、
  不冲突；命名评审时确认 Zod 侧同步。
- cursor 编码：opaque base64（含排序键），tasks 以 `(created_at, id)` 为键、
  events 以 `(timestamp, id)` 为键（timestamp 非唯一，必须复合）；键序与现有
  排序一致，保证 cursor 翻页与直接查询同一顺序。
- 客户端职责：循环 `while next_cursor != null` 拉全量或按需增量；不估算
  total（`total` 字段保留但 keyset 路径下可为 null——冻结时定为"cursor 请求
  时不返回 total"以避免每页 COUNT）。
- 契约变更走冻结流程：OpenAPI + 双侧 Zod + drift 基线 + fixtures 一次同步。

## D-029 附录 — tasks 裸数组形状的游标裁定（PR #13 review 备注 1，2026-09-30）

B 的 review 抓到冻结设计的真实遗漏：`GET /v1/tasks` 是**裸数组**响应
（`response_model=list[ClientTask]`，客户端 `TaskSchema.array()` 消费），
「现有 Page 契约增加 `next_cursor`」只对 events（Page 包装）成立；tasks 若
改为 Page 形状属破坏性响应变更，D-029 原文未覆盖。补充裁定：

- **统一原则**：游标语义两端点同构（opaque cursor、`null`/缺省 = 末页、
  复合排序键），**载体按端点现有形状最小侵入**：
  - events（已 Page 包装）：`Page.next_cursor` 字段，同 D-029 原文。
  - tasks（裸数组）：**保持裸数组**，游标经响应头 **`X-Next-Cursor`** 携带
    （缺省头 = 末页）。Zod 契约不变（客户端照旧 parse 数组，分页消费者
    读 header）；fetch 侧 `response.headers.get()` 可达。
- **cursor/offset 优先级**：同一请求同时携带 `cursor` 与 `offset` → **422
  拒绝**（不静默忽略，避免歧义）。
- **不采用**：改 Page 形状（breaking，客户端与 e2e 同步改造成本不成比例）、
  新增分页端点（膨胀 API 面）、Link header（多值解析复杂度不值）。
- **落地依赖（B 补记，09-30）**：Tauri 包内 Backend 流量经 B-4 的
  `backend_request` IPC 代理，其响应头白名单（`backend_proxy.rs
  response_headers`：content-type/retry-after/location）**会剥掉
  `X-Next-Cursor`**——M2 实现时必须把该头加入白名单（TS 侧
  `backendFetch` 的 headers 通道已就绪，仅 Rust 一行）；浏览器 dev 模式
  直连 fetch 还需 Backend 侧 CORS `Exposed-Headers` 包含该头（次要路径，
  打包客户端不受 CORS 约束）。
- 实现仍排 M2；OpenAPI 需为两端的 cursor 参数与响应头出文档（header 在
  OpenAPI 用 `Header` 参数对象描述）。

## D-028 附录补充 — 哨兵残留与空标题边角的处置（PR #13 review 备注 2/3）

- **备注 2（哨兵 early-return 跳过更新）**：已派生任务随后续事件把 deadline
  改为哨兵值时，任务以旧 deadline 残留。裁定：**保持现状**——「哨兵不触碰
  已派生任务」与「哨兵不派生」语义一致；真实场景（作业截止被改为 2099 占位）
  出现时由 M2 议显式关闭（task cancel 语义），不在派生层隐式改写用户可见数据。
- **备注 3（标题无条件赋值）**：空 title 事件会把已派生任务标题重置为回退值。
  裁定：接受——客户端映射恒发非空 title（`String(...)`），空 title 事件本身
  即上游异常，回退标题（course/upstream）比残留旧标题更可追溯；不加 if 守卫
  换取派生路径的赋值一致性。

## D-030 — 路线图 M2-M8 采纳（插入独立 Agent 阶段；M2 硬出口 = 确定性闭环）

Status: **accepted**（2026-09-30 协调人提交；A/B 对大纲及三处修订均无异议，
当日确认采纳）。

输入：`HANDOFF/2026-09-30-roadmap-outline.md`（基于
`2026-09-30-implementation-evaluation.md` 与 GOALS/AGENTS/TECH_STACK）。

Decision（两处结构变化 + 一组原则）：

1. 在 Memory/Grounding（M3）与 Alpha 加固之间**插入独立 Agent 阶段（新 M4）**：
   Provider 适配、显式 Agent 循环、agent_runs 审计、pending_actions 确认、
   Chat 与主动 Agent；确定性 planner 保留为工具与降级路径。原 M4（加固）
   顺延为 M5，后续 M6 多端/Inbox、M7 Exercise/Life、M8 Review（与 AGENTS
   P1-P3 优先级一一对应）。
2. **M2 出口 = 确定性闭环**（AGENTS §8 全句在无 LLM 前提下过 e2e 新场景
   E4），作为硬门槛；LLM/Agent 推迟至 M3/M4（消除评估指出的静默漂移）。
3. 总体原则：确定性优先且规则版永为降级路径；一切建议带结构化 basis；
   写入分级（模型产出默认 UNREVIEWED）；契约先行；出口场景一律 e2e 化。

修订要求（协调人审阅附加，采纳时一并生效）：

- M3 Memory schema 设计**必须同步产出删除/依赖图设计**（评估 §3.7 的告诫
  不能在阶段顺延中丢失）：evidence 与 subject_key 血缘要使 M5 的级联删除
  是机械遍历而非考古。
- 采纳后按 AGENTS §4 更新依赖方：`TECH_STACK_AND_WORKPLAN.md` 的 M0-M4
  里程碑节需注明被本路线取代（先记录决策、再改依赖文档）。
- `TASKS/m2-breakdown.md` 以大纲 M2 节为准对齐（分页归 A；补 CurrentState
  goals 摘要与摆状态），避免双源漂移。
- 大纲 §5.4（CURRENT_STATE 头刷新）已随 `9b4b1d2` 完成。

Rollback：纯文档决策，回滚 = 废弃本条并恢复 TECH_STACK 原里程碑节；各阶段
实现不受已合并历史影响。

## D-031 — M2 阶段 0 契约冻结：PlanItem.basis、recent_state、重排建议形状与 Memory 扩展

Status: **accepted**（2026-09-30 产出、2026-10-01 B 评审通过；两处评审修订
随合并落盘——§2 客户端 `replaces_plan_id` 补 `.nullable()`、§3 live 唯一索引
M2 直接建版本感知部分索引，均标注「B 评审修订」可追溯。双方按
`TASKS/m2-breakdown.md` 并行，场景草案与 E4 fixture 冷启动注意见
`TASKS/m2-phase0-contract-freeze.md`）。

Context：`TASKS/m2-breakdown.md`「冻结先行」四项中的三项尚无裁定；第四项
（LLM/Agent 推迟）**已由 D-030 第 2 点覆盖**，不再另立条目。本条冻结其余
三组的语义，全部为增量 optional 字段或既有列的语义化，无破坏性响应变更。

### 1. PlanItem.basis（optional、弱类型）与 recent_state 入契约

- 客户端 Zod：`PlanItemSchema` 增加 `basis: z.record(z.unknown()).optional()`，
  与 D-027 附录 `recent_state` 同一模式。**双层解释契约**：`reason: z.string()`
  保留，是服务端由 basis 渲染出的中文人话（直接显示）；`basis` 是结构化依据
  （「为什么」面板与审计用），形状可演进、不锁契约。M2 客户端优先渲染
  `reason`，`basis` 做展开面板。
- 服务端存储：`plan_items` 新列 `basis JSONB NULL`（**不**塞进 plan 级
  `basis` 的嵌套 dict——按项检索干净，plan.basis 不随任务数膨胀，只保留
  `strategy` 版本标签等全局项）。旧行 NULL → 客户端 `basis` 缺省。
- planner v2 写入的 basis 字段集（目标形状，弱类型下实现期可增补）：
  `deadline`、`slack_minutes`、`estimate_minutes`、`estimate_source`（§4）、
  `goal_id`、`slot_reason`、`score`（分量 dict）、`at_risk`（负 slack 标记）。
  plan 级 `basis.strategy = "slots_v2"` 作为版本标签，便于同一批 fixture 与
  `deadline_then_priority` 对比评估。`reason` 渲染模板从 basis 生成；旧计划
  无 basis 时回退现状（notes → strategy → replan_reason → "planned"）。
- `recent_state`：语义已由 **D-027 附录**冻结（`z.record(z.unknown())`、不建
  诊断端点），本条仅将其排入 M2 落地清单（B 侧 Zod 一行 + drift 基线同步），
  使 M2 契约变更一次冻结、一次同步。

### 2. 重排建议契约（Level 1 语义）

- 载体 = 既有 `plans` 表与状态机，**零迁移**：`replaces_plan_id`/
  `replan_reason` 列自 M0 已存在。一条重排建议 = `status=DRAFT` +
  `replaces_plan_id` 指向被替代计划 + `replan_reason`（中文人话，引用触发
  事实，如「《XX》作业 Focus 超时 42 分钟，今日后续安排需要重排」）。
- **Level 1 语义**（对照 AGENTS §3 权限等级）：触发评估（读事件模式）为
  Level 0 自动；建议创建（新 DRAFT）为 Level 1 自动且**绝不修改被替代
  计划**（D-028 附录 L4 的确认保护不变）；接受 = 用户走既有
  `POST /v1/plans/{id}/confirm`（复用 `plan.confirm` 权限审计路径）；忽略 =
  既有 `POST /v1/plans/{id}/cancel`。**无新端点、无新权限动作**。
- **接受即取代（本条唯一的新行为规则）**：confirm 一个 `replaces_plan_id`
  非空的计划时，若被替代计划仍为 CONFIRMED，则**同事务**置 SUPERSEDED
  （幂等：已非 CONFIRMED 则跳过）。现状缺口：confirm 不触碰旧计划，旧计划
  残留 CONFIRMED，仅靠 `current_plan_for` 的 `confirmed_at desc` 排序压住，
  语义上是脏状态。触发引擎**不得**调用 `replan()`——它会在用户接受前就把
  原计划置 SUPERSEDED（违反 L4 保护）；引擎直接
  `generate_plan(status=DRAFT, replaces_plan_id=…, replan_reason=…)`。
- 发现路径：客户端经既有 `GET /v1/plans?status=DRAFT` 发现建议
  （`replaces_plan_id` 非空者即建议；列表分页随 D-029 落地）。`GET
  /v1/plans/today` 语义不变（D-019：confirmed 优先，建议草稿不劫持 today
  视图；无 confirmed 时 `latest_open_plan` 自然取到最新草稿——对「新任务
  到达」触发器而言，含新任务的建议草稿成为 today 提案正是 L4 的显式路径）。
- 客户端 Zod：`PlanSchema` 增加 `replaces_plan_id:
  z.string().nullable().optional()`、`replan_reason:
  z.string().nullable().optional()`（**B 评审修订 2026-10-01**：原案
  `replaces_plan_id` 只写 `.optional()`——服务端未设
  `response_model_exclude_none`，普通计划会序列化 `"replaces_plan_id": null`，
  而 Zod 的 optional 只容缺失不容 null，缺 `.nullable()` 会让客户端解析
  **每一个**无替代的计划时失败）。服务端 `ClientPlan` 补
  `replaces_plan_id` 映射（该列目前根本没进 client view，顺带修复），
  `replan_reason` 从 backend-only 转正。
- 去抖（约 30s/用户）与限频（无 deadline at-risk 豁免时 ≤1 条/30 分钟）是
  触发引擎的实现参数，进任务文件验收，不入契约。

### 3. Memory 五项扩展（形状冻结；迁移、写入者语义与删除/依赖图详见 `TASKS/m3-memory-schema-migration.md`）

目标形状（五项）：

| 字段 | 类型/约束 | 语义 |
| --- | --- | --- |
| `subject_key` | `TEXT NULL` | 聚合 upsert 稳定键（如 `estimate:course:<course_key>`、`estimate_ratio:user`）；L1 episode 追加式，键为 NULL |
| `valid_from` / `valid_to` | `TIMESTAMPTZ NULL` | 适用时间窗（信息性，由写入者设置；被取代时旧行补 `valid_to`） |
| `supersedes_id` | `UUID NULL → memories(id)` | 版本链；**live 行 = `supersedes_id IS NULL`** |
| `kind` | `VARCHAR(32)` + CHECK（episode/fact/habit/preference/model，D-001 非 native） | 记忆种类，与 `level` 正交 |
| `evidence` | `JSONB` | 通用证据列表：`{type:"event", id}` 或 `{type:"document", file_id, checksum, page, span_start, span_end}` |
| `embedding` | `vector(1536) NULL`（M3 落列） | pgvector；维度对应 text-embedding-3-small，换供应商 = 迁移 + 重嵌 |

- **live 行不变式**：每 `(user_id, subject_key)` 至多一个 `supersedes_id IS
  NULL` 的行，以部分唯一索引 `WHERE subject_key IS NOT NULL AND supersedes_id
  IS NULL` 表达。**B 评审修订 2026-10-01：直接在 M2 迁移建该部分唯一索引**
  （原案「M2 普通唯一索引 + M3 降级」两步走与本条 §4 写入者语义矛盾：
  CORRECTED-supersedes 与 L2 聚合 supersede 均为 M2 范围（m2-breakdown
  A-4/本条 M2 切片理由），第一次 keyed supersede 写入即撞普通唯一索引；
  部分索引在尚无写入者时同样成立，且省去 M3 的索引换装步骤）。
- **REJECTED 阻断再派生**：聚合器写 `subject_key` 前必须查 live 行，遇
  REJECTED 跳过并审计——否则下一轮聚合会悄悄重建用户刚删的事实。
  **CORRECTED 生成新版本**（新行 `supersedes_id` 指旧行）而非原地改写，
  审计史保留。检索层默认过滤 REJECTED 并设置信度下限（默认 0.3）。
- `source_event_ids` **保留**：作为事件 id 证据的反范式子集（D-014 跨用户
  校验与既有 API 面不动）；`evidence` 是唯一权威的通用证据表，写入者保持
  两者一致（事件类证据同时进两处）。
- **M2 切片**（六列，除 embedding 外全部）：`subject_key`/`kind`/`evidence`
  /`supersedes_id`/`valid_from`/`valid_to`。理由：估时学习（L2 upsert）、
  L1 episode 证据、以及 m2-breakdown A-4 已排入 M2 的「CORRECTED 走
  supersedes」都需要版本链；本切片无新基础设施依赖。
- **M3 切片**：`embedding` 列 + `CREATE EXTENSION vector` + compose 镜像
  `postgres:16-alpine` → `pgvector/pgvector:16`（现镜像无 pgvector，把镜像
  替换拖进 M2 不成比例）；「预留」以形状冻结与维度记录兑现。
- 模型产出（未来）只能以 `UNREVIEWED` + 置信度封顶（≤0.5）进入；晋升 =
  用户确认或 ≥2 次独立的确定性证据（AGENTS §2.3）。
- 删除/依赖图设计随迁移文档产出（D-030 修订要求）。

### 4. 估时来源语义（`estimate_source`，E4 断言依赖）

- 取值枚举冻结：`default | user | learned:course | learned:ratio`。
- 分组键 = `task.extra.course_name`（D-028 附录 L3 已写入；缺失组 = 手动/
  无课程任务，只用 ratio/default 路径）。
- 采用阶梯（自上而下，第一个可用者生效）：① 任务显式估时 → `user`；
  ② 同课程已完成任务 n≥2 → 近 20 次实际分钟**中位数**（四舍五入取整）→
  `learned:course`（中位数已是实际尺度，**不**再乘校准比——校准比只修正
  基于计划的估计，叠乘会重复修正）；③ 用户级校准比 n≥3 →
  `default(60) × ratio` → `learned:ratio`；④ 都不满足 → 60 → `default`。
  校准比 = 各已完成任务 `actual ÷ planned`（planned 取执行该任务的计划项
  `planned_minutes`，缺失按 60）的截尾均值（n≥4 时去最高最低 10%）。
- 置信度 = `min(0.9, n/10)`；低于激活阈值时回退并在 `estimate_source`
  **如实标注**（E4 对 learned 与 default 双向断言）。

### 5. 契约同步清单（一次性）与兼容回滚

- 同步：`openapi.json` 刷新、`packages/contracts` Zod（B）、
  `tests/fixtures/client_contract.ts` 冻结快照（A 侧）、drift check 双源、
  e2e fixtures（E4）。新增字段全部 optional，旧 Backend 载荷必须仍可解析。
- 回滚：revert 两条迁移（`plan_items.basis`；memories 六列）与映射即可，
  无数据依赖；Event 流不动（计划与 Memory 均为投影）。

## D-032 — 不基于 Hermes agent 构建，采设计不采底座

Status: **A 已签认**（2026-10-01，rotcar07：六条不采依据与可迁移机制清单
核验无异议，「采设计不采底座」与既有冻结边界一致；随签认在
`TASKS/m3-memory-schema-migration.md` §8 提交两项待 B 会签裁定——
supersedes_id 链方向勘误、correction_status 语义端点化）。待 B 签认后转
accepted。

Context：NousResearch/hermes-agent（MIT）作为成熟对话 Agent harness 被评估
为潜在底座（预研全文与逐条技术事实见
`HANDOFF/2026-10-01-hermes-memory-prestudy.md`）。其单机单 home、平面文件
记忆、进程级权限与本项目冻结边界冲突。

Decision：维持现架构；采纳其可迁移机制（冻结快照与前缀稳定排序、写入前
注入扫描、使用遥测、provenance 即政策——前两项已分别补进 M4 设计输入与
M3 先决文档）；Hermes 仅可作为 M4 后的可选 chat surface 实验（经 MCP 调
`/v1` API，不承重、不进主线）。不采纳其底座的六条依据见预研 §5（单机
硬边界/权限无法数据化/记忆模型冲突/交互面映射不了/凭据 custody 退化/
fork 维护成本）。

Revisit：产品转向单机优先（放弃多用户与多端同步），或 M4 provider/agent
工作连续两个里程碑停滞。

附注：预研报告原编 D-031 与 M2 契约冻结决策撞号，登记时改为 D-032；预研
的文档增量已由协调人调和移植进 main 现行版（详见报告归档注记）。
