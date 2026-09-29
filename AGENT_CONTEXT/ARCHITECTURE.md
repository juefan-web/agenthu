# ARCHITECTURE

## Runtime topology

```
Android ──┐
          ├── Backend (FastAPI) ── PostgreSQL
Windows ──┘        │              ── Redis + Arq worker
                   │              ── S3-compatible object storage
                   └── Model providers (later, via adapter)
```

Clients only call the HTTP API. The Backend owns identity, permissions, events, tasks, goals,
current state, memory, plans and files.

## Backend layout

```
backend/
├── main.py            FastAPI app factory (middleware, routers, OpenAPI)
├── config.py          pydantic-settings (env-driven)
├── middleware.py      request-id + best-effort audit middleware
├── core/              errors (envelope), security (bcrypt/JWT), logging
├── db/                declarative Base, mixins, engine/session
├── models/            SQLAlchemy domain models + enums
├── schemas/           Pydantic contracts (client-facing)
├── services/          events, event_handlers, current_state, planner, focus,
│                      permissions, audit, storage, lookup
├── api/
│   ├── deps.py        auth/session/pagination dependencies
│   ├── health.py      /health, /health/ready
│   └── v1/            resource routers + router aggregation
├── adapters/          SourceAdapter contract + onethu stub
├── worker/            Arq tasks, settings, pool
└── scripts/           export_openapi
```

## Data flow

1. A fact enters as an **Event** (`POST /events` or an adapter), with `dedupe_key` for idempotency.
2. `services.events.create_event` persists it and runs registered **event handlers**.
3. Handlers project Events into domain state (Task status/duration, CurrentState). They never lose
   the raw Event on failure — failures are logged and audited.
4. **CurrentState** is *recomputed* from Tasks/Plans/recent Events, not copied from Events; it has a
   monotonically increasing `version`.
5. **Plans** reference tasks and store `basis` (explainability), `permission_level`, confirmation
   state and `replan_reason`.
6. **Memory** stores traceable, correctable entries (source, confidence, correction status).

## Key invariants

- Every query is scoped by `user_id`; ownership helpers raise `NotFoundError` (no existence leak).
- Event dedupe is enforced by a DB unique constraint `(user_id, dedupe_key)`.
- Enums are `VARCHAR` + CHECK (`native_enum=False`) for cheap evolution.
- Time is always timezone-aware UTC (`timestamptz`).
- Object bytes live in S3-compatible storage; only metadata is relational.
- Permission decisions and mutating requests are auditable, with secret/ PII redaction.

## Extension points for later milestones

- **Planner**: replace/augment `services.planner` with an LLM planner that writes the same `Plan`
  model and calls `services.permissions` before acting.
- **Adapters**: implement `SourceAdapter.fetch()` per provider; only emit `NormalizedEvent`.
- **Memory**: add pgvector + citations; keep `source_event_ids`, confidence, correction status.
- **Agent runtime**: wrap observe/retrieve/decide/plan/act, reusing `current_state`, `memory`,
  permissions and audit.
