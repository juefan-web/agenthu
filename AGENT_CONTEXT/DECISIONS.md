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

Consequence: `TECH_STACK_AND_WORKPLAN.md` still says Flutter; that needs a coordinated doc update
(it is a project-level decision, not a Backend-only change).

## D-010 — Event dedupe key is computed on the Backend

`source:upstream_id:semantic_version` (the client's `eventDedupeKey`) is derived server-side from the
Event provenance; a client-supplied `dedupe_key` is only an additional signal, never the trusted
boundary. Enforced by the unique `(user_id, dedupe_key)` constraint.

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
