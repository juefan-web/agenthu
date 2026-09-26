# CURRENT_STATE

Updated: 2026-09-26 · Milestone: **M0 (engineering baseline + frozen contracts)**

## Done

- Full Backend skeleton: FastAPI, PostgreSQL/SQLAlchemy/Alembic, Redis/Arq, S3-compatible storage,
  Docker Compose, CI, Ruff, Pyright, pytest.
- Frozen contracts and APIs for Auth, Event, Task, Goal, CurrentState, Memory, Plan, File,
  Permission, Audit, Jobs, Health.
- Initial migration (13 tables) verified from zero + no drift.
- Deterministic planner & full Study + Time loop integration test (event → task → plan → confirm →
  focus → actual duration → current state → replan).
- OpenAPI exported to `openapi.json` (38 paths).
- Docs: `README.md`, `DEVELOPMENT.md` (status), `M0_HANDOFF.md`, `AGENT_CONTEXT/`.

## Verification snapshot

- `ruff check` / `ruff format --check`: pass
- `pyright`: 0 errors
- `pytest` full suite with db/redis/s3mock up: **67 passed**
- S3Storage round-trip against `s3mock`: pass
- Arq worker (Redis → Arq → task): pass
- Migration from zero + downgrade + `alembic check` (no drift): pass

## In progress / pending

- Nothing blocking M0. M1 work not started.

## Blockers

- OneTHU source/API not accessible → adapter is a deliberate stub.
- `minio/minio` Docker Hub image returns 404 upstream; `s3mock` profile used for local verification.

## Next

- M1: real (manual-first) adapters and idempotent ingestion, richer CurrentState, LLM planner behind
  the permission layer, OpenAPI contract check in CI.
