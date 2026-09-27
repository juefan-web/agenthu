# M0 Handoff

Milestone: **M0 — engineering baseline + frozen core contracts**
Audience: Developer B (desktop client), and the next Backend session.

The M0 goal was a reliable Backend foundation with contracts the client can depend on — not a
complete Agent. Everything below is implemented and covered by tests unless explicitly marked as
mock/stub.

---

## 1. What was completed

- FastAPI app with unified error envelope, request-id/audit middleware, CORS, health checks.
- PostgreSQL schema (14 tables) + Alembic migrations, verified upgrade-from-zero, downgrade-to-base
  and no-drift (`alembic check`).
- Frozen core contracts: Event, Task, Goal, CurrentState, Memory, Plan (+ PlanItem, File, Audit,
  Permission) with DB model + Pydantic schema + API + fixtures.
- Desktop client contract under `/v1` (see §2), including batch event ingestion, client-shaped
  tasks/current-state/plans and persisted focus sessions.
- Auth: register/login/token/me with bcrypt + JWT.
- Event ingestion with backend-computed dedupe and an Event→domain handler registry.
- Task/Goal CRUD, task↔event linking, focus sessions (event-driven, idempotent).
- CurrentState projection with versioning.
- Memory CRUD with source/confidence/correction status.
- Deterministic baseline planner, confirm/cancel, re-planning (restricted to non-terminal plans).
- Object storage abstraction (S3/MinIO + in-memory), streaming size-limited uploads.
- Permission levels 0–3, standing grants, decision service, append-only audit trail.
- Ingestion safety: recursive sensitive-field rejection, JSON size/depth limits, non-local
  `SECRET_KEY` startup guard.
- Arq worker + `/jobs` enqueue/status.
- Docker Compose, GitHub Actions CI (all branches), Ruff, Pyright, pytest, OpenAPI export.
- OneTHU adapter contract + research stub (no data acquisition implemented).

## 2. Current API contract

OpenAPI: `openapi.json` (also served at `/openapi.json`, docs at `/docs`). 40 paths. All API routes
are under **`/v1`** and require `Authorization: Bearer <jwt>` except auth and health.

### Desktop client contract (authoritative — see DECISIONS.md D-009)

The React/Tauri client validates responses with Zod from `packages/contracts`. These endpoints serve
its exact shapes:

- `POST /v1/events/batch` — body `{events:[EventEnvelope], client_cursor}`; returns
  `{accepted_event_ids, duplicate_event_ids, rejected:[{client_event_id, reason}], next_cursor}`.
  The accepted/duplicate arrays contain **client_event_id** values (the client uses them to clear
  its local queue). Dedupe key is `source:upstream_id:semantic_version`.
- `GET /v1/tasks` — bare array: `{id, title, due_at, estimate_minutes, status, source_event_ids}`
  with status `todo|in_progress|done|cancelled`.
- `GET /v1/current-state` — `{version, updated_at, now, context, tasks, available_minutes}`.
- `GET /v1/plans/today` — the confirmed plan, or a freshly generated deterministic draft.
- `POST /v1/plans/{plan_id}/confirm` — client plan
  `{id, generated_at, items:[{task_id, start_at, end_at, reason}], confirmation_required, status}`.
- `POST /v1/focus-sessions` — body `{task_id}`; returns a focus session.
- `PATCH /v1/focus-sessions/{session_id}` — body `{status, actual_minutes, deviation_note}`;
  completion is idempotent.

Additional Backend-only fields are returned and stripped by Zod.

### Full endpoint list

Auth
- `POST /v1/auth/register` → `UserRead` (201)
- `POST /v1/auth/login` → `Token` (JSON body)
- `POST /v1/auth/token` → `Token` (OAuth2 password form; for the docs Authorize button)
- `GET  /v1/auth/me` → `UserRead`

Events
- `POST /v1/events` → `EventRead` (201 new / 200 deduplicated, `X-Deduplicated` header)
- `POST /v1/events/batch` → `EventBatchResponse`
- `GET  /v1/events` → `Page[EventRead]` (filters: `type`, `source`, `since`, `until`)
- `GET  /v1/events/{event_id}` → `EventRead`
- `DELETE /v1/events/{event_id}` → 204

Tasks
- `POST/GET /v1/tasks` (GET returns a bare array), `GET/PATCH/DELETE /v1/tasks/{task_id}`
- `POST/DELETE /v1/tasks/{task_id}/events/{event_id}` (link/unlink source event)

Focus
- `POST /v1/focus-sessions`, `GET /v1/focus-sessions/{session_id}`,
  `PATCH /v1/focus-sessions/{session_id}`

Goals
- `POST/GET /v1/goals`, `GET/PATCH/DELETE /v1/goals/{goal_id}`

CurrentState
- `GET /v1/current-state`, `POST /v1/current-state/refresh`, `PATCH /v1/current-state`

Memory
- `POST/GET /v1/memory`, `GET/PATCH/DELETE /v1/memory/{memory_id}`

Plans
- `POST /v1/plans` (manual draft), `POST /v1/plans/generate`, `GET /v1/plans/today`
- `GET /v1/plans`, `GET /v1/plans/{plan_id}`
- `POST /v1/plans/{plan_id}/confirm` | `/cancel` | `/replan`
- `PATCH /v1/plans/{plan_id}/items/{item_id}`, `DELETE /v1/plans/{plan_id}`

Files
- `POST /v1/files` (multipart `file`), `GET /v1/files`, `GET /v1/files/{file_id}`
- `GET /v1/files/{file_id}/download`, `GET /v1/files/{file_id}/signed-url`
- `DELETE /v1/files/{file_id}`

Permissions / Audit / Jobs
- `GET /v1/permissions/policy`, `GET/POST /v1/permissions/grants`,
  `DELETE /v1/permissions/grants/{grant_id}`, `POST /v1/permissions/check`
- `GET /v1/audit`
- `POST /v1/jobs/ping`, `GET /v1/jobs/{job_id}`

Health
- `GET /health` (liveness), `GET /health/ready` (db/redis/object storage)

Error envelope (frozen):

```json
{"error": {"code": "not_found", "message": "...", "details": {}}}
```

Codes: `bad_request`, `unauthenticated`, `permission_denied`, `not_found`, `conflict`,
`validation_error`, `payload_too_large`, `storage_error`, `service_unavailable`, `internal_error`.

Auth contract fixtures and the missing / invalid / expired `401` semantics are covered by
`tests/integration/test_auth.py`; the Event -> Task -> CurrentState -> Plan -> Focus main chain is
covered by `tests/integration/test_client_main_chain.py`. OpenAPI/Zod drift is enforced in CI by
`backend/scripts/check_contract_drift.py` (D-021).

## 3. Current database structure

All tables use UUID primary keys and timezone-aware timestamps. Every user-owned table has
`user_id` FK (cascade) and is always queried scoped by user.

- `users` — email (unique, lowercased), display_name, hashed_password, is_active
- `events` — type, timestamp, source, data/context/provenance (JSONB), dedupe_key (unique per user),
  client_event_id (batch correlation), ingested_at
- `tasks` — title, description, source, status, deadline, estimated/actual minutes, priority,
  goal_id, completed_at, extra (JSONB)
- `task_events` — task↔event many-to-many
- `focus_sessions` — user_id, task_id, status (running/paused/completed/abandoned), started_at,
  ended_at, actual_minutes, deviation_note
- `goals` — title, description, category, status, priority, target_date
- `current_states` — one row per user, version, current_time, current_context, current_task_id,
  current_plan_id, pending_task_ids, recent_state, available_minutes
- `memories` — level (0–3), domain, content, source (JSONB), source_event_ids, confidence,
  correction_status
- `plans` — title, status, basis, permission_level, generated_by, replan_reason, execution_result,
  replaces_plan_id, confirmed/cancelled/completed_at
- `plan_items` — plan_id, task_id, order_index, planned window/minutes, status, actual_minutes,
  result
- `file_objects` — storage_key (unique), backend, filename, content_type, size, checksum,
  metadata (JSONB)
- `audit_logs` — actor, action, resource, method/path, status, duration, permission_level, decision,
  details (JSONB, redacted), ip/user_agent
- `permission_grants` — action (unique per user), level, scope, granted/expires/revoked

## 4. What is mock / baseline (not real intelligence)

- **Planner is deterministic**, not an LLM. `strategy = "deadline_then_priority"`. The Plan model and
  permission layer are designed to be reused by the M1 LLM planner.
- **No automatic Memory extraction**, no embeddings, no vector search.
- **No OneTHU or other real campus data**. M0 event sources are `manual`, `test`, `mock`, `system`,
  `backend`.
- **Focus** is persisted session + event tracking; there is no timer UI in the Backend.
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

- Consume `packages/contracts` shapes directly; the Backend serves them under `/v1`.
- Implement: auth/token handling, course & assignment sync via `POST /v1/events/batch`, task list,
  current-state page, today plan + confirm, focus session start/pause/resume/complete.
- Local backend: `docker compose up -d` then `http://localhost:8000`.
- Stable identifiers: all IDs are UUIDs; all timestamps are ISO-8601 with timezone.
- Permissions: `GET /v1/permissions/policy` for the action→level map; manage Level 3 grants via
  `/v1/permissions/grants`.

## 8. Where M1 should start

1. **Adapters + ingestion**: implement the first real normalized adapter (manual/markdown first),
   idempotent batch ingestion, and link events to tasks.
2. **CurrentState enrichment**: available-time calculation, deadline risk inputs, context switching.
3. **Planner**: LLM planner behind `permissions.evaluate_permission`, persisting `basis` and
   citations; deviation-driven `replan`.
4. **Memory**: extraction with sources, pgvector retrieval, correction/delete paths.
5. **Contract check in CI** (done, D-021): `python -m backend.scripts.check_contract_drift` fails CI
   when `openapi.json` is stale or the client's `packages/contracts` Zod contract drifts from the
   OpenAPI components. It also runs as `tests/unit/test_contract_drift.py`.

Runbook: `alembic upgrade head`, `uvicorn backend.main:app`, `arq backend.worker.settings.WorkerSettings`.
