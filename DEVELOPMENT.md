# Current Status

Last updated: 2026-09-26 · Milestone: **M0 — engineering baseline + frozen core contracts**

This document reflects the real state of the code. It is not a design document; product and
architecture invariants live in `AGENTS.md` and `TECH_STACK_AND_WORKPLAN.md`. Cross-session
context lives under `AGENT_CONTEXT/`.

## Completed

- **Engineering skeleton**: FastAPI app factory, Pydantic v2 settings, structured logging, unified
  error envelope, request-id and audit middleware, CORS, `/health` + `/health/ready`.
- **Database**: SQLAlchemy 2 models for User, Event, Task, Goal, CurrentState, Memory, Plan,
  PlanItem, FileObject, AuditLog, PermissionGrant and the `task_events` link table. Initial Alembic
  migration creates 13 tables with explicit foreign keys, indexes and CHECK constraints.
- **Core contracts (frozen)**: database model + Pydantic schema + API + test fixtures for Event,
  Task, Goal, CurrentState, Memory, Plan. OpenAPI is exported to `openapi.json` (40 paths).
- **Desktop client contract** (`/v1`, aligned to `packages/contracts`): `POST /v1/events/batch`,
  `GET /v1/tasks` (bare `Task[]`), `GET /v1/current-state`, `GET /v1/plans/today`,
  `POST /v1/plans/{id}/confirm`, `POST /v1/focus-sessions`, `PATCH /v1/focus-sessions/{id}`.
  Mappers live in `backend/services/client_view.py`.
- **Focus sessions**: persisted `focus_sessions` with a `running/paused/completed/abandoned` state
  machine and idempotent completion (no double-counted actual minutes).
- **Auth**: register / JSON login / OAuth2-form token / me, bcrypt password hashing, HS256 JWT.
- **Event infrastructure**: `POST/GET/DELETE /events`, backend-computed dedupe
  (`source:upstream_id:semantic_version`) plus optional `dedupe_key`, unique constraint,
  `X-Deduplicated` header, provenance, filters, batch ingestion and an event-handler registry that
  projects Events into Task/CurrentState.
- **Ingestion safety**: recursive sensitive-field rejection (password/cookie/token/OTP), JSON size
  and depth limits, and a non-local `SECRET_KEY` startup guard.
- **Task / Goal**: CRUD, goal ownership validation, task↔event linking, status transitions with
  `completed_at`.
- **CurrentState**: recomputed projection (never a copy of Events) with `version`, pending tasks,
  current task, current plan, recent-event summary, and user overrides.
- **Memory**: reliable CRUD with level, domain, source, source events, confidence and correction
  status. No automatic extraction or vector retrieval in M0.
- **Plan**: manual create/read/confirm/cancel, deterministic baseline planner (`/plans/generate`),
  item updates and re-planning (`/plans/{id}/replan`) with `basis`, permission level and
  `replan_reason`.
- **Focus loop**: `focus.started` / `focus.completed` events drive Task status, actual duration and
  the CurrentState projection — the full Study + Time loop is covered by an integration test.
- **Permissions / Audit**: Level 0–3 model, action policy, standing `PermissionGrant`s, a shared
  decision service, and an append-only audit trail with redaction.
- **Object storage**: `ObjectStorage` abstraction with `InMemoryStorage` and `S3Storage`
  (MinIO/S3-compatible), upload/download/signed-url/metadata/delete.
- **Worker**: Arq on Redis (`ping`, `recompute_user_current_state`) plus `/jobs` enqueue/status.
- **Adapters**: provider-agnostic `SourceAdapter` contract and an explicit OneTHU research stub.
- **Tooling**: Docker Compose (db/redis/minio + s3mock profile + api + worker), GitHub Actions CI,
  Ruff, Pyright (0 errors), pytest (unit + integration), `M0_HANDOFF.md`.

## Verification snapshot (latest)

- `ruff check` + `ruff format --check`: pass
- `pyright`: 0 errors
- `pytest` (full suite, all services up): **95 passed** in ~52s
- `pytest -m storage` (S3Storage against `s3mock`): pass
- Arq worker test (Redis → Arq → task): pass
- Migration test (upgrade from zero + downgrade + `alembic check` no drift): pass
- `openapi.json` regenerated: 40 paths, prefix `/v1`

## Blocked

- **OneTHU adapter** is a stub. The OneTHU source tree / API documentation was not accessible in
  this environment, so no endpoint, auth or schema was guessed. See
  `backend/adapters/onethu/RESEARCH.md` for the research checklist and constraints.
- **`minio/minio` image**: Docker Hub returns 404 for `minio/minio` (upstream removed/relocated the
  image) and `quay.io/minio/minio` requires auth. MinIO remains the default backend; `s3mock`
  (`docker compose --profile s3mock`) is available where MinIO cannot be pulled. This does not
  affect the code path, which depends only on the `ObjectStorage` interface.
  s3mock specifics: image is **pinned** (`adobe/s3mock:5.2.3`, not `latest`) so CI does not drift;
  the healthcheck uses **`wget`** (the image has no `curl`) against **`/favicon.ico`** (the root path
  is an unauthenticated ListBuckets that may return 403). CI mirrors the same readiness probe.
- **Documentation mismatch (needs a coordinated decision)**: `TECH_STACK_AND_WORKPLAN.md` states the
  client is Flutter generated from OpenAPI, but the real client is React/Tauri with hand-written Zod
  contracts (`packages/contracts`). The Backend now conforms to the real client (see D-009), but the
  project doc should be updated with Developer B.

## Resolved review items (astra6 report on e715f9e)

| ID | Issue | Resolution |
| --- | --- | --- |
| P1-1 | Client contract mismatch | `/api/v1` → `/v1`; client-shaped tasks/current-state/plans; added `events/batch`, `plans/today`, `focus-sessions` (D-009) |
| P1-2 | Event dedupe not business-keyed | Backend computes `source:upstream_id:semantic_version` (D-010) |
| P1-3 | Focus completion not idempotent | Persisted `focus_sessions` + state machine + dedupe-keyed completion (D-011) |
| P1-4 | Plan can reference another user's task | Ownership validation for plan items / current-state overrides (D-014) |
| P1-5 | No sensitive Event interception | Recursive sensitive-field rejection + size/depth limits (D-012) |
| P1-6 | Default JWT secret in production | Non-local strong-secret startup guard (D-013) |
| P2-1 | Replan without status check | Replan restricted to non-terminal plans (D-015) |
| P2-2 | Memory source_event_ids unverified | Ownership validation on create/update (D-014) |
| P2-3 | Upload buffered before size check | Chunked size limit (413) + orphan cleanup (D-016) |
| P2-4 | CI only on `main` push | Push triggers cover all branches (D-017) |
| — | Trailing whitespace in migration | Fixed in `339f5d1471c9_initial_schema.py` |

## Self-check (latest)

Method: lint/type/test, `alembic check`, OpenAPI drift, `git diff --check`, plus a **live-server
contract smoke** against `/v1` (12/12 checks pass).

### Fixed in this round

- `GET /v1/plans/today` generated a new plan on every read; it now reuses the latest
  **client-valid, same-day** draft/pending plan (`planner.latest_open_plan(since=start_of_today())`)
  and never returns a task-less manual plan (`planner.is_client_valid_plan`).
- CORS defaults corrected to the real client origin `http://localhost:5173`
  (`tauri.conf.json` `devUrl`); wildcard + credentials still auto-disables credentials.
- `TaskCreate`/`TaskUpdate` accept the client status values (`todo`, `in_progress`, `done`,
  `cancelled`) in addition to the internal enum names.
- Contract smoke test frozen in the repo (`tests/integration/test_client_contract.py`) plus
  `tests/integration/test_cors.py` (real 5173 origin) and cross-day / manual-plan coverage in
  `tests/integration/test_plans.py`.
- OpenAPI OAuth2 `tokenUrl` was hardcoded to `/api/v1/auth/token`; it is now derived from
  `api_v1_prefix` (`/v1/auth/token`) and asserted by `tests/unit/test_openapi.py`.
- `is_client_valid_plan` documents that `reason` is guaranteed non-empty by `plan_to_client`
  (item notes -> strategy -> replan reason -> "planned"), covered by `tests/unit/test_client_view.py`.

### Resolved decisions

- **Auth is Bearer JWT** (D-018): the Backend freezes register/login/me and the 401/expiry
  semantics; the client stores the token and sends `Authorization: Bearer`. No cookie session is
  added. Campus and Backend accounts stay separate.

### Open (needs a decision or another owner)

- **MinIO healthcheck** still uses `curl` and is unverified (the image cannot be pulled here);
  s3mock is pinned/verified.
- No rate limiting or request-size limit at the proxy layer (M4 hardening).
- The 8 client-side performance findings (reqwest client reuse, extra auth probes, duplicate
  semester requests, serial assignment/calendar fetch, timeout propagation) belong to Developer B.

## Known Issues

- On Windows, use `127.0.0.1` (not `localhost`) for Redis/Postgres/S3 in local `.env`: async Redis
  resolves `localhost` to `::1` while Docker maps IPv4 only. Defaults and `.env.example` already
  use `127.0.0.1`.
- arq 0.28's `Worker.close()` references POSIX-only `signal.SIGUSR1` when `handle_signals=False`;
  the worker test keeps signals enabled (registration degrades gracefully on Windows). Production
  workers run in Linux containers anyway.
- Docker Desktop in the development sandbox stops intermittently, which causes DB/Redis-dependent
  tests to skip. Tests skip cleanly rather than fail.
- `TestClient` + a shared savepoint Session works with PostgreSQL but is not thread-safe by design;
  if flakiness appears, move to a per-request session with table truncation.

## Next Steps

1. **M1 — Event / Task / Current State**: normalizing adapters for manual import, richer projection,
   deadline radar inputs, and concurrency-safe idempotent ingestion.
2. **M2 — Planner**: LLM planner behind the existing permission layer, execution results and
   deviation-driven re-planning.
3. **M3 — Memory / Grounding**: material indexing (pgvector), citations, user correction flow.
4. Add a contract test that fails CI when `openapi.json` drifts from the client's `packages/contracts`.
5. Update `TECH_STACK_AND_WORKPLAN.md` (Flutter → React/Tauri) with Developer B.
6. Decide credential storage (encryption + access control + deletion path) before any real campus
   data source is enabled.

## Recent Decisions

- Enums are stored as `VARCHAR` + CHECK (`native_enum=False`) so adding a member is a normal
  migration.
- `CurrentState.current_plan` is the **confirmed** plan only; unconfirmed proposals are not the
  user's current plan.
- Audit middleware can be disabled with `AUDIT_ENABLED=false`; explicit permission decisions are
  still recorded through the service layer.
- `S3Storage` uses path-style addressing so MinIO, S3Mock and hosted S3 all work.
- S3 object storage keeps bytes out of PostgreSQL; only metadata is relational.
- `DEVELOPMENT.md` is the current-status document; workflow guidance moved to `AGENT_CONTEXT/`.

## Development Workflow

- Branching, PR checklist and completion/reporting rules: `AGENT_CONTEXT/PROJECT.md` and
  `AGENTS.md` §5–7.
- Local setup and commands: `README.md`.
- Architecture and data flow: `AGENT_CONTEXT/ARCHITECTURE.md`.
- M0 contract handoff for the client developer: `M0_HANDOFF.md`.
