# CURRENT_STATE

Updated: 2026-09-28 · Milestone: **M0 (engineering baseline + frozen contracts)** +
astra6 review fixes + A/B contract integration + merge-gate hardening +
integration-review Developer-A fixes (fourth review)

## Done

- Full Backend skeleton: FastAPI, PostgreSQL/SQLAlchemy/Alembic, Redis/Arq, S3-compatible storage,
  Docker Compose, CI, Ruff, Pyright, pytest.
- Frozen contracts and APIs for Auth, Event, Task, Goal, CurrentState, Memory, Plan, Focus, File,
  Permission, Audit, Jobs, Health.
- Two migrations (13 → 14 tables) verified from zero + no drift.
- Desktop client contract aligned to `packages/contracts` under `/v1`: `events/batch`,
  client-shaped tasks/current-state/plans, `plans/today`, persisted `focus-sessions`.
- Deterministic planner and the full Study + Time loop integration test.
- Ingestion safety: sensitive-field rejection, JSON limits, non-local secret guard,
  cross-user reference validation.
- OpenAPI exported to `openapi.json` (40 paths, prefix `/v1`); OAuth2 `tokenUrl` is `/v1/auth/token`.
- Auth contract fixtures (`/register`, `/login`, `/token`, `/me`, expired JWT) and 401 envelope
  tests (missing / invalid / expired, `WWW-Authenticate: Bearer`).
- Repeatable Event -> Task -> CurrentState -> Plan -> Focus main-chain API test
  (`tests/integration/test_client_main_chain.py`).
- OpenAPI/Zod drift check (`backend/scripts/check_contract_drift.py`) wired into CI (**with
  `--require-zod`**) before the OpenAPI export; frozen client Zod snapshot in
  `tests/fixtures/client_contract.ts` (D-021).
- Event dedupe key escaping matches the client's `eventDedupeKey` (`\`/`:`, D-010).
- `GET /v1/plans/today` concurrency-idempotent via advisory lock (D-019); Focus start race
  serialized by an advisory lock keyed by (user, task) (`cbe30f7`).
- **Integration-review fixes (2026-09-28, fourth review, Developer A):**
  - **K1 contract hole**: client-invalid plans can no longer be created (task-less items
    rejected, times backfilled from `planned_minutes`) nor confirmed; `current_plan_for`
    filters them in SQL via the shared `backend/services/plan_validity.py` (D-023).
    Regression: manual/legacy invalid plan -> confirm -> current-state stays parseable.
  - **C1 handler failure path**: every event handler runs inside a SAVEPOINT; a DB-level
    handler failure (verified with a real PostgreSQL error) no longer rolls back the raw
    Event. `safe_record_audit` uses a savepoint instead of a destructive rollback.
  - **S1 fail-closed secrets + auth hardening**: `ENVIRONMENT` defaults to `production`
    (weak `SECRET_KEY`/`S3_SECRET_KEY` rejected at load); auth endpoints rate-limited
    (429 `rate_limited` + `Retry-After`, `AUTH_RATE_LIMIT_MAX=0` disables); login timing
    equalized with a dummy-hash comparison; job ids user-scoped, foreign jobs 404 (D-025).
  - **C2 multi-session accounting**: every focus completion emits `focus.completed`
    (`completed` flag marks the session that finished the task); task and plan-item actual
    minutes accumulate across sessions; COMPLETED status is sticky, `completed_at` never
    rewritten. Regression test covers 30 + 25 minutes across two sessions.
  - **C4 naive datetimes**: all datetime inputs (`TaskCreate/Update`, `GoalCreate/Update`,
    `PlanItemCreate`, `PlanGenerateRequest`, events `since`/`until` query params) share
    `EventCreate`'s naive->UTC rule via `UTCDatetime` (`schemas/common.py`).
  - Audit middleware DB write moved off the event loop (`asyncio.to_thread`);
    dead `recompute_user_current_state` worker task removed (D-024);
    README Quick start no longer references the removed `createbuckets` service.
- Docs: `README.md`, `DEVELOPMENT.md`, `M0_HANDOFF.md`, `AGENT_CONTEXT/` (D-009).

## Verification snapshot (after fourth-review fixes)

- `ruff check` / `ruff format --check`: pass; `pyright`: 0 errors
- `pytest` full suite with db/redis (+ s3mock for the storage test): **182 passed**, 1 skipped
  (S3 test without `S3_ENDPOINT_URL`), including 15 new regression tests for the fixes above
- OpenAPI/Zod drift check with `--require-zod`: pass
- Migration up -> down -> up + `alembic check` (no drift): pass
- Local docker stack: db / redis / s3mock running; `ENVIRONMENT` handling documented in
  README / `.env.example` / `docker-compose.yml`

## In progress / pending

- Joint acceptance with Developer B (integration review): plan loading, duplicate
  confirmation, Focus start/complete, `actual_minutes=0`, offline retry, Windows build
  package. Merge to `main` waits on it.
- `packages/contracts` on `feature/client-tauri-campus-adapter` must mirror the frozen
  `PlanItem.title` (see the header note in `tests/fixtures/client_contract.ts`).

## Blockers / decisions needed

- OneTHU source/API not accessible → adapter is a deliberate stub.
- `minio/minio` Docker Hub image returns 404 upstream; `s3mock` profile used for local
  verification.
- Joint A+B CI should run the authoritative `packages/contracts` Vitest/typecheck; the
  Backend branch only has the frozen Zod snapshot stand-in (D-021).

## Next

- Integration branch with Developer B's client branch; end-to-end main-chain rehearsal on
  a Windows build package (Study + Time loop acceptance).
- M1: real (manual-first) adapters and idempotent ingestion, richer CurrentState, LLM
  planner behind the permission layer, off-request CurrentState recompute with a real
  caller.
