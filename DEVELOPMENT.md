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
  Task, Goal, CurrentState, Memory, Plan. OpenAPI is exported to `openapi.json` (38 paths).
- **Auth**: register / JSON login / OAuth2-form token / me, bcrypt password hashing, HS256 JWT.
- **Event infrastructure**: `POST/GET/DELETE /events`, per-user dedupe by `dedupe_key` (unique
  constraint + `X-Deduplicated` header), provenance, filters, and an event-handler registry that
  projects Events into Task/CurrentState.
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
- `pytest` (full suite, all services up): **67 passed** in ~45s
- `pytest -m storage` (S3Storage against `s3mock`): pass
- Arq worker test (Redis → Arq → task): pass
- Migration test (upgrade from zero + downgrade + `alembic check` no drift): pass

## Blocked

- **OneTHU adapter** is a stub. The OneTHU source tree / API documentation was not accessible in
  this environment, so no endpoint, auth or schema was guessed. See
  `backend/adapters/onethu/RESEARCH.md` for the research checklist and constraints.
- **`minio/minio` image**: Docker Hub returns 404 for `minio/minio` (upstream removed/relocated the
  image) and `quay.io/minio/minio` requires auth. MinIO remains the default backend; `s3mock`
  (`docker compose --profile s3mock`) is available where MinIO cannot be pulled. This does not
  affect the code path, which depends only on the `ObjectStorage` interface.

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
4. Wire `openapi.json` into the Flutter API client generation and add a contract check to CI.
5. Decide credential storage (encryption + access control + deletion path) before any real campus
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
