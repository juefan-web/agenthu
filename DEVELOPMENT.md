# Development Workflow

This document turns the project principles in `AGENTS.md` into a repeatable delivery process.

## 1. Product and delivery order

Build one complete user loop before expanding the surface area:

```text
Event -> Memory -> Current State -> Agent -> Plan/Act -> Result -> updated Memory
```

The first milestone is the Study + Time loop:

1. Capture a course event, learning material, assignment, or deadline.
2. Normalize it into the shared Event schema.
3. Store the relevant task and learning memory with traceable sources.
4. Build a plan using current state, goals, and available time.
5. Support a focused work session and record the result and actual duration.
6. Re-plan when reality differs from the original plan.

Priorities follow `AGENTS.md`: P0 establishes Event, Backend, basic Memory, Agent foundations, and the Study + Time loop; P1 adds Inbox, device sync, proactive behavior, replanning, and context switching; P2 adds Exercise and Life; P3 adds periodic reviews.

## 2. Repository and branch workflow

- `main` is always releasable and receives changes through pull requests.
- Use `feature/<short-name>` for product work, `fix/<short-name>` for defects, and `experiment/<short-name>` for disposable investigations.
- Keep a branch focused on one user-visible outcome. Do not mix unrelated refactors into the same pull request.
- Use clear imperative commits, for example `Add assignment event schema` or `Fix plan rollover on missed focus session`.
- Rebase or update the branch before review, resolve conflicts on the feature branch, and merge only after required checks pass.

## 3. Starting a task

Before changing code:

1. Read `AGENTS.md`, `PROJECT.md`, `CURRENT_STATE.md`, `ARCHITECTURE.md`, and relevant decisions or task notes.
2. Write a task note under `AGENT_CONTEXT/TASKS/` containing the goal, inputs, outputs, in-scope and out-of-scope work, and acceptance criteria.
3. Identify the Event, Memory, Current State, Agent, and permission boundaries affected by the change.
4. Search existing code and tests before introducing a new module or abstraction.

Every task must define what it will not change. A task is ready for implementation only when its acceptance criteria are testable.

## 4. Implementation rules

- Keep domain logic independent of a specific campus data provider or client platform.
- Treat the Backend as the cross-device source of truth for identity, events, memory, tasks, goals, agent state, and synchronization.
- Make data provenance explicit. Memory entries should retain their source, timestamps, confidence, and correction status.
- Assign every tool an explicit permission level from 0 (read-only) through 3 (explicitly authorized automation). High-risk, irreversible, and external-communication actions require confirmation by default.
- Prefer observable, explainable decisions: important recommendations should expose the supporting event, memory, goal, or current-state data.
- Add tests at the contract boundary: schemas, permission checks, state transitions, source citations, and replanning behavior.

## 5. Pull request checklist

A pull request should explain the user problem, the resulting behavior, and the affected boundaries. Before requesting review:

- Run the relevant unit, integration, and end-to-end tests.
- Check error handling, permission enforcement, privacy implications, and obvious regressions.
- Update architecture or decision records when a boundary or data contract changes.
- Update `CURRENT_STATE.md` and add a handoff note when work is incomplete.
- Include migration, rollout, and rollback notes for persistent data or API changes.
- Keep screenshots, logs, or example payloads for UI and data-flow changes when they clarify the review.

## 6. Completion and handoff

Work is complete when the acceptance criteria pass, documentation is current, and the change is merged or has a clear next owner. The completion report must state:

- What changed and why.
- Which files, contracts, or user flows changed.
- What checks and tests were run.
- What remains unfinished or uncertain.
- The next action, if any.

For work that spans sessions, record the current state, decisions, blockers, and next steps in `AGENT_CONTEXT/CURRENT_STATE.md`, `AGENT_CONTEXT/DECISIONS.md`, and `AGENT_CONTEXT/HANDOFF/` as appropriate. Repository files are the durable source of shared context; chat history is not.

## 7. Suggested initial work breakdown

1. Define the Event schema and persistence contract.
2. Define the minimum Current State projection for Study + Time.
3. Implement task/deadline ingestion and source tracking.
4. Implement a permission-aware planning and replanning service.
5. Add Focus execution and actual-duration events.
6. Add learning-memory updates with citations and user correction.
7. Validate the end-to-end course -> assignment -> plan -> focus -> memory loop with representative fixtures.
