# CURRENT_STATE

Updated: 2026-09-26 · Milestone: **M0 (engineering baseline + frozen contracts)** +
astra6 review fixes

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
- OpenAPI exported to `openapi.json` (40 paths, prefix `/v1`).
- Docs: `README.md`, `DEVELOPMENT.md` (status + review fixes), `M0_HANDOFF.md`, `AGENT_CONTEXT/`.

## Verification snapshot

- `ruff check` / `ruff format --check`: pass
- `pyright`: 0 errors
- `pytest` full suite with db/redis/s3mock up: **95 passed**
- S3Storage round-trip against `s3mock`: pass
- Arq worker (Redis → Arq → task): pass
- Migration from zero + downgrade + `alembic check` (no drift): pass

## In progress / pending

- Nothing blocking. M1 work not started.

## Blockers / decisions needed

- OneTHU source/API not accessible → adapter is a deliberate stub.
- `minio/minio` Docker Hub image returns 404 upstream; `s3mock` profile used for local verification.
- `TECH_STACK_AND_WORKPLAN.md` still describes a Flutter client; reality is React/Tauri. Needs a
  coordinated doc update with Developer B (see DECISIONS D-009).

## Next

- M1: real (manual-first) adapters and idempotent ingestion, richer CurrentState, LLM planner behind
  the permission layer, OpenAPI/contract drift check in CI.
