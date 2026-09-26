# M0 Handoff

Milestone: **M0 — engineering baseline + frozen core contracts**
Audience: Developer B (Flutter client), and the next Backend session.

The M0 goal was a reliable Backend foundation with contracts the client can depend on — not a
complete Agent. Everything below is implemented and covered by tests unless explicitly marked as
mock/stub.

---

## 1. What was completed

- FastAPI app with unified error envelope, request-id/audit middleware, CORS, health checks.
- PostgreSQL schema (13 tables) + Alembic initial migration, verified upgrade-from-zero,
  downgrade-to-base and no-drift (`alembic check`).
- Frozen core contracts: Event, Task, Goal, CurrentState, Memory, Plan (+ PlanItem, File, Audit,
  Permission) with DB model + Pydantic schema + API + fixtures.
- Auth: register/login/token/me with bcrypt + JWT.
- Event ingestion with per-user dedupe and an Event→domain handler registry.
- Task/Goal CRUD, task↔event linking, focus start/complete (event-driven).
- CurrentState projection with versioning.
- Memory CRUD with source/confidence/correction status.
- Deterministic baseline planner, confirm/cancel, re-planning.
- Object storage abstraction (S3/MinIO + in-memory), file upload/download/signed-url/delete.
- Permission levels 0–3, standing grants, decision service, append-only audit trail.
- Arq worker + `/jobs` enqueue/status.
- Docker Compose, GitHub Actions CI, Ruff, Pyright, pytest (unit + integration), OpenAPI export.
- OneTHU adapter contract + research stub (no data acquisition implemented).

## 2. Current API contract

OpenAPI: `openapi.json` (also served at `/openapi.json`, docs at `/docs`). 38 paths. All API routes
are under `/api/v1` and require `Authorization: Bearer <jwt>` except auth and health.

Auth
- `POST /api/v1/auth/register` → `UserRead` (201)
- `POST /api/v1/auth/login` → `Token` (JSON body)
- `POST /api/v1/auth/token` → `Token` (OAuth2 password form; for the docs Authorize button)
- `GET  /api/v1/auth/me` → `UserRead`

Events
- `POST /api/v1/events` → `EventRead` (201 new / 200 deduplicated, `X-Deduplicated` header)
- `GET  /api/v1/events` → `Page[EventRead]` (filters: `type`, `source`, `since`, `until`)
- `GET  /api/v1/events/{event_id}` → `EventRead`
- `DELETE /api/v1/events/{event_id}` → 204

Tasks
- `POST/GET /api/v1/tasks`, `GET/PATCH/DELETE /api/v1/tasks/{task_id}`
- `POST/DELETE /api/v1/tasks/{task_id}/events/{event_id}` (link/unlink source event)
- `POST /api/v1/tasks/{task_id}/focus/start` → `EventRead`
- `POST /api/v1/tasks/{task_id}/focus/complete` → `TaskRead` (body: `actual_minutes`, `completed`,
  `notes`)

Goals
- `POST/GET /api/v1/goals`, `GET/PATCH/DELETE /api/v1/goals/{goal_id}`

CurrentState
- `GET /api/v1/current-state` → `CurrentStateRead` (recomputed)
- `POST /api/v1/current-state/refresh` → `CurrentStateRead`
- `PATCH /api/v1/current-state` (override `current_context`, `current_task_id`, `available_minutes`)

Memory
- `POST/GET /api/v1/memory`, `GET/PATCH/DELETE /api/v1/memory/{memory_id}`

Plans
- `POST /api/v1/plans` → `PlanRead` (manual draft)
- `POST /api/v1/plans/generate` → `PlanRead` (deterministic planner, `PENDING_CONFIRMATION`)
- `GET /api/v1/plans`, `GET /api/v1/plans/{plan_id}`
- `POST /api/v1/plans/{plan_id}/confirm` | `/cancel` | `/replan`
- `PATCH /api/v1/plans/{plan_id}/items/{item_id}`
- `DELETE /api/v1/plans/{plan_id}` (draft/pending only)

Files
- `POST /api/v1/files` (multipart `file`) → `FileRead`
- `GET /api/v1/files`, `GET /api/v1/files/{file_id}`
- `GET /api/v1/files/{file_id}/download` (bytes), `GET /api/v1/files/{file_id}/signed-url`
- `DELETE /api/v1/files/{file_id}` → 204

Permissions / Audit / Jobs
- `GET /api/v1/permissions/policy`, `GET/POST /api/v1/permissions/grants`,
  `DELETE /api/v1/permissions/grants/{grant_id}`, `POST /api/v1/permissions/check`
- `GET /api/v1/audit`
- `POST /api/v1/jobs/ping`, `GET /api/v1/jobs/{job_id}`

Health
- `GET /health` (liveness), `GET /health/ready` (db/redis/object storage)

Error envelope (frozen):

```json
{"error": {"code": "not_found", "message": "...", "details": {}}}
```

Codes: `bad_request`, `unauthenticated`, `permission_denied`, `not_found`, `conflict`,
`validation_error`, `storage_error`, `service_unavailable`, `internal_error`.

## 3. Current database structure

All tables use UUID primary keys and timezone-aware timestamps. Every user-owned table has
`user_id` FK (cascade) and is always queried scoped by user.

- `users` — email (unique, lowercased), display_name, hashed_password, is_active
- `events` — type, timestamp, source, data/context/provenance (JSONB), dedupe_key
  (unique per user), ingested_at
- `tasks` — title, description, source, status, deadline, estimated/actual minutes, priority,
  goal_id, completed_at, extra (JSONB)
- `task_events` — task↔event many-to-many
- `goals` — title, description, category, status, priority, target_date
- `current_states` — one row per user, version, current_time, current_context,
  current_task_id, current_plan_id, pending_task_ids, recent_state, available_minutes
- `memories` — level (0–3), domain, content, source (JSONB), source_event_ids, confidence,
  correction_status
- `plans` — title, status, basis, permission_level, generated_by, replan_reason,
  execution_result, replaces_plan_id, confirmed/cancelled/completed_at
- `plan_items` — plan_id, task_id, order_index, planned window/minutes, status, actual_minutes,
  result
- `file_objects` — storage_key (unique), backend, filename, content_type, size, checksum,
  metadata (JSONB)
- `audit_logs` — actor, action, resource, method/path, status, duration, permission_level,
  decision, details (JSONB, redacted), ip/user_agent
- `permission_grants` — action (unique per user), level, scope, granted/expires/revoked

## 4. What is mock / baseline (not real intelligence)

- **Planner is deterministic**, not an LLM. `strategy = "deadline_then_priority"`. The Plan model and
  permission layer are designed to be reused by the M1 LLM planner.
- **No automatic Memory extraction**, no embeddings, no vector search.
- **No OneTHU or other real campus data**. Event sources used in M0 are `manual`, `test`, `mock`,
  `system`, `backend`.
- **Focus** is event-driven state tracking, not a timer UI.
- Object storage tests default to `InMemoryStorage`; the S3 path is the real implementation and is
  exercised separately with `-m storage`.

## 5. Not implemented yet

- LLM planner, Agent runtime/state machine, tools, Chat, proactive behavior.
- Real adapters (OneTHU, WeChat, mail, exercise, life) and PDF/PPT/audio parsing or transcription.
- pgvector / retrieval / citations / grounding.
- Notifications, scheduling, offline sync, device pairing.
- Complex authorization policies beyond the Level 0–3 + grant model.
- Credential storage (needs encryption, access control, deletion path — deferred decision).

## 6. OneTHU / external data source research

Status: **blocked on source access**. The OneTHU source tree/API docs were not available in this
environment, so no endpoint or schema was guessed. `backend/adapters/onethu/RESEARCH.md` records the
full checklist (data sources, auth/cookie/session, pagination, error handling, time fields, update
frequency, official API, authorization boundary) and hard constraints (no committed secrets, no
auth bypass, normalize to Event only). `OneTHUAdapter.fetch()` raises `ServiceUnavailableError`.

Architecture rule enforced: `External Source → Adapter → Normalized Event → Backend → Agent`. The
Backend never imports provider types.

## 7. What Developer B can use now

- Generate the Flutter API client from `openapi.json` (or `/openapi.json`). Do not read the DB.
- Implement: register/login/token storage, course & assignment import (via `POST /events` and/or
  `POST /tasks`), task list, current-state page, plan confirm, focus start/complete, and error
  handling using the envelope + codes above.
- Local backend: `docker compose up -d` then `http://localhost:8000`.
- Stable identifiers: all IDs are UUIDs; all timestamps are ISO-8601 with timezone.
- Pagination is `limit`/`offset` with `{items,total,limit,offset}`.
- Permissions: call `GET /permissions/policy` for the action→level map; show confirmation for
  Level 2 actions and manage Level 3 grants via `/permissions/grants`.

## 8. Where M1 should start

1. **Adapters + ingestion**: implement the first real normalized adapter (manual/markdown first),
   idempotent ingestion, and link events to tasks.
2. **CurrentState enrichment**: available-time calculation, deadline risk inputs, context switching.
3. **Planner**: LLM planner behind `permissions.evaluate_permission`, persisting `basis` and
   citations; deviation-driven `replan`.
4. **Memory**: extraction with sources, pgvector retrieval, correction/delete paths.
5. **Contract check in CI**: regenerate `openapi.json` and fail on diff to protect the client.

Runbook: `alembic upgrade head`, `uvicorn backend.main:app`, `arq backend.worker.settings.WorkerSettings`.
