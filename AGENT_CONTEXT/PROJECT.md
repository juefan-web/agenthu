# PROJECT

Goal: a Personal AI / Student Life OS for Tsinghua students that observes the student's reality,
builds traceable memory, understands the present state, and helps plan and act.

Core loop: `Reality -> Event -> Memory / CurrentState -> Agent -> Plan/Act -> Result Event ->
update state/memory -> Re-plan`.

First vertical slice (P0): Study + Time —
`course/assignment/deadline -> plan -> focus -> result -> learning memory`.

Non-negotiables (from `AGENTS.md`):
- Backend is the single source of truth; clients never touch the DB or campus APIs directly.
- All external sources normalize into one Event contract; no business logic binds to a provider.
- External sources go through adapters: `Source → Adapter → Normalized Event → Backend → Agent`.
- Memory is layered and traceable; wrong memory is correctable/deletable.
- Permission levels are fixed 0–3; irreversible actions need confirmation.
- Prune: a feature must serve "see → remember → understand → plan → act → learn".

Two-developer split (from `TECH_STACK_AND_WORKPLAN.md`):
- Developer A: Backend, data, contracts, worker, Agent foundations, permissions, storage, tests/CI.
- Developer B: React/Tauri Android/Windows client (`packages/contracts` Zod schemas), Study + Time
  UX, offline drafts.
- Shared: Event/Memory/CurrentState/permission contracts; cross-boundary changes need a short ADR.

Collaboration:
- Branches `feature/*`, `fix/*`, `experiment/*`; `main` via PR.
- Every task declares goal, inputs, outputs, in-scope, out-of-scope, testable acceptance criteria.
- Contract changes update schema + migration + fixtures + OpenAPI + client generation together.
- Docs are the durable shared context; chat history is not.
