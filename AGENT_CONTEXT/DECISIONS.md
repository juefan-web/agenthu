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
