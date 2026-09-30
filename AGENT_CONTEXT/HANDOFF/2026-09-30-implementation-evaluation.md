# Implementation evaluation against the original concept (2026-09-30)

Scope: `main` at `f4afc09` ("Archive the e2e first-run report and unlock M2 acceptance tooling"). The local working copy is on `feature/backend-request-proxy`, which has diverged from `origin` and still carries an older `CURRENT_STATE.md`. Everything below was read from an export of `main`, and the working tree was not modified. The baselines are `GOALS.md` (the product concept), `AGENTS.md` (the invariants and the phase-one acceptance sentence), `TECH_STACK_AND_WORKPLAN.md` (milestones M0–M4) and `DECISIONS.md` (D-001 to D-029).

## Verdict in one paragraph

The *data plumbing* is faithful to the concept and is well built. It has a unified Event envelope with provenance, server-side dedupe keys, a trusted `user_id`, rejection of sensitive fields, strong cookie and credential custody, permission levels and audit. The *intelligence half* of the concept has not started yet. The loop is meant to be "see → remember → understand → plan → act → learn", but it currently stops after "act". Focus results update Task and CurrentState and are never learned from. Plans ignore the class schedule that CurrentState already knows about. The "why" shown to the user is the literal string `deadline_then_priority`. Measured against the phase-one acceptance sentence in `AGENTS.md` §8, four of seven clauses are met, one is partly met and two are missing (see the table below). The biggest risk is not code quality but sequencing: five acceptance rounds have gone into login/sync plumbing, while the P0 items "Memory foundation" and "Agent basic framework" have no code.

## 1. Where the implementation deviates from the concept

### 1.1 Phase-one acceptance scorecard

| AGENTS.md §8 clause | Status on `main` | Evidence |
| --- | --- | --- |
| Import courses and assignments | Met | Client collects four domains (`study.course.discovered`, `study.assignment.discovered/updated`, `time.schedule.entry`, `time.academic_calendar.updated`); 103 events / 50 derived tasks in round 5 |
| Record Events and deadlines | Met | Dedupe, provenance, `+08:00` deadlines verified end-to-end (D-028) |
| Generate an **explainable**, properly authorised plan | Partly met | Authorisation works (draft → confirm). Explanation does not: `client_view.py:75-83` falls back to `basis["strategy"]`, so every item's `reason` is `"deadline_then_priority"` |
| Complete one Focus | Met | `focus.py` start/pause/complete, idempotent completion (D-011) |
| Record actual duration | Met | `actual_duration_minutes` accumulated by the `focus.completed` handler |
| Detect deviation and **re-plan** | Missing | `planner.replan` exists but is API-only; no trigger, no client button. Round 5 re-planned by manual cancel |
| Write sourced learning results into **correctable Learning Memory** | Missing | Memory table and CRUD exist, but no code path writes Memory (`event_handlers.py` only mentions it in the module docstring as "later") |

### 1.2 Structural deviations (these change what the product *is*)

**The loop has no "learn" step.** `AGENTS.md` §2.1 makes `Observe Result -> Update State / Memory -> Re-plan` an invariant. Today `focus.completed` updates Task status, plan-item completion and CurrentState, and then the information goes nowhere. The user's `deviation_note` is stored and forwarded as `notes` in the event payload (`focus.py:195`), but nothing reads it. Estimates are never learned either: derived tasks carry no estimate, so the planner assigns every task `DEFAULT_TASK_MINUTES = 60` (`planner.py:34,113`) no matter how long past work took. Of all the deviations, this one most directly contradicts the concept, because the product was defined as something that gets to know you over time.

**The planner is blind to the state it depends on.** `current_state.py` already builds today's class schedule (`_today_schedule_entries`) and a careful `available_minutes` (D-027). `generate_plan` uses neither. It lays tasks back-to-back from "now" with a fixed 240-minute horizon (`planner.py:110-127`), and the first task is placed even if it overruns. A plan generated at 09:50 can therefore put homework on top of a 10:00 lecture that the context badge is announcing at that very moment. The two halves of M1 were built by different developers against different decisions, and nothing joins them.

**"Why" is not implemented.** The concept (GOALS "为什么这样安排", AGENTS §2.1 "重要建议应给出原因以及相关 Event、数据、Memory 或 Goal") treats explanation as a core feature. The data for an explanation partly exists in `plan.basis`: task ids, the CurrentState version and the horizon. However, the client contract's `PlanItemSchema.reason` is a single string, and the backend fills it with an internal identifier.

**Goals have no effect.** The `Goal` model and API exist, and tasks can carry a `goal_id`. However, `pending_tasks` orders tasks only by `deadline, priority, created_at` (`current_state.py:84-88`), and neither CurrentState nor the planner reads goals. GOALS.md positions goals as one of the three inputs to every decision ("Current State + Relevant Memory + Goals").

**There is no Agent or LLM layer at all.** D-008 described the deterministic planner as an M0 baseline and said "the M1 LLM planner will reuse the same Plan model". M1 is now closed without it. `pyproject.toml` has no model SDK, no LangGraph and no pgvector. There is also no chat entry point, proactive behaviour, prompt/version logging or evaluation fixture. The deterministic-first approach is sensible, but it should be recorded as a decision ("LLM planner deferred to M3+") rather than left to drift silently.

### 1.3 Scope deviations (reasonable deferrals that should be written down)

On the Study side, collection stops at metadata. The vendored OneTHU core already exposes `getFileList`, `getAllNotifications`, `getHomeworkDetail`, `getExams` and `getDeadlines`. None of these are collected, so the concept's "materials → grounded explanation → citations" chain has no input yet. The Time module has no "开始摆" rest state, no Now view and no Deadline Radar. `ACTION_POLICY` in `permissions.py` is complete, but for a user actor it never blocks: `plans.py:190-194` proceeds when `allowed or requires_confirmation`. That is semantically correct for a human confirming their own plan. It does mean the permission layer has not yet been exercised against its real subject, an agent proposing an action. The Arq worker registers only `ping` (`worker/settings.py:21`), so Redis and the worker containers are maintained without doing any work. Observability (OpenTelemetry/Sentry in the stack doc, and AGENTS §7's "可观测记录" for external calls) is absent.

These are acceptable deferrals for an alpha. They are listed here so that the next milestone plan names them explicitly.

### 1.4 What is on-concept and should be protected

Several parts match the concept well and should be kept as they are. Event provenance and the server-computed dedupe key (D-010) are right. Credentials stay in Rust and Stronghold, with only a read-only cookie mirror (D-008 review) and a narrow zhjw exception documented with a revisit condition (D-026). The client–backend contract is authoritative and checked for drift in CI (D-009, D-021). Derived tasks keep their provenance, and the `(user_id, source, source_upstream_id)` identity is enforced by a unique constraint. The team has also held the line of "no LLM until the deterministic loop is testable", which is the right call. The deviations above are about what comes next, not about undoing any of this.

## 2. Areas for improvement in the current implementation

The table is ordered by impact on the M2 goal. Items marked **correctness** produce wrong user-visible behaviour today.

| # | Area | Problem | Recommendation |
| --- | --- | --- | --- |
| 1 | Planner (correctness) | Ignores class schedule, `available_minutes`, goals; first item can overrun the horizon | Slot-based planner v2 (see §3.1) |
| 2 | Plan explanation (correctness) | `reason` = `"deadline_then_priority"` for every item | Deterministic per-item reason template from a structured basis (§3.1) |
| 3 | Overdue tasks (correctness) | `deadline ASC` puts long-overdue unsubmitted assignments at the top of every plan forever | Explicit overdue policy: separate "overdue" bucket, planner excludes by default past N days, UI lets the user dismiss/cancel |
| 4 | Batch ingest cost | `ingest_event_batch` → `create_event` → `process_event` per envelope (`events.py:138,225`); each handler ends in `_recompute` (`event_handlers.py:260`), which rescans 90 days of schedule events (`current_state.py:40`) and bumps `version` (`:138`). A 103-event sync means ~103 full recomputes and 103 version bumps | Handlers mark the user dirty; recompute once at the end of the batch (and later debounced in the worker). Skip the version bump when the projection hash is unchanged |
| 5 | Estimates | Always 60 min for derived tasks; actuals never feed back | Estimate learning (§3.2) |
| 6 | Deviation data | `deviation_note` stored, never used | Feed into L1 episode memory (§3.4) |
| 7 | Same-day draft reuse (round-5 L4) | New tasks arriving after a non-empty draft are not absorbed until manual cancel | Replan-suggestion trigger on `task` creation with near deadline (§3.3) |
| 8 | Pagination | `limit` capped at 200 (`deps.py:66`, default 50); e2e relies on 200 as a stopgap | Implement D-029 keyset. Note that `backend_proxy.rs:138` whitelists only `content-type/retry-after/location`, so `x-next-cursor` must be added there or the cursor is silently dropped in Tauri |
| 9 | Offline fast-fail | 15.2 s to enqueue when the backend is down (round-5 D1) | Probe `/health` with a ~2 s timeout before flushing; skip the retry ladder when the probe fails |
| 10 | Observability of CurrentState | `available_minutes_breakdown` lives only in `recent_state`, and the client schema has no `recent_state` (round-5 L1) | Land the D-027 appendix (`recent_state: z.record(z.unknown())`) in M2 as planned |
| 11 | Sentinel handling | "No deadline" is detected relative to event time (`event_handlers.py:215`); if upstream later changes a real deadline to the 2099 placeholder, the existing task keeps a stale deadline | On an `updated` event that turns into a sentinel, clear `deadline` on the existing task rather than skipping |
| 12 | Worker | Only `ping`; infrastructure is paid for without work | Give it its first real jobs: debounced recompute and replan-trigger evaluation (D-024 said it needs "a real caller"; this is it) |
| 13 | Rate limiting | Per-process (D-025) | Redis limiter before any multi-worker deployment |
| 14 | e2e robustness | E1 view assumption, E2 `getByLabel('密码')` ambiguity | Small PR as proposed in the first-run report |
| 15 | Client structure | `App.tsx` (338 lines) holds module-level singletons, three views and two sub-components | Before M2 UI grows (replan diff, why panel, memory page), split into feature folders and inject the backend/sync singletons via context so views are testable |
| 16 | Documentation hygiene | `CURRENT_STATE.md` header still says "2026-09-28 · M0"; the "安全加固" bullet is duplicated; "尚未满足的验收项（合并 main 的前置门槛）" is obsolete since PR #1 merged | Refresh the header and prune merged gates. The document is the cross-session memory for both developers and any agent, so its staleness has a real cost |
| 17 | Process | Five acceptance rounds, 29 decisions, and zero lines of Memory/Agent code | Make the M2 exit criterion literally the AGENTS §8 sentence, and time-box plumbing work |

## 3. The most important implementation details for unimplemented phases

These are ordered by dependency. Each builds on the one before, and §3.1–§3.3 can ship in M2 without any LLM.

### 3.1 Planner v2: slot-based, state-aware, explainable (finish M2)

Build the free-slot list first, and only then assign tasks. Compute free intervals for the local day as `[max(now, day_start), day_end)`. Subtract today's schedule entries, reusing `_today_schedule_entries` so the planner and CurrentState read the same schedule, with a small transit buffer (about 10 minutes) on each side. Also subtract an active rest/"摆" block and any user-declared busy blocks. Cap the total placed minutes at `available_minutes` so that the badge and the plan cannot disagree. Score each pending task deterministically, for example `urgency(slack) + goal_weight + priority`, where `slack = time_to_deadline − remaining_estimate`. Split tasks longer than about 90 minutes into blocks. Mark tasks whose slack is negative as **at risk** instead of silently dropping them. That flag is the seed of a Deadline Radar.

Make the explanation structural. Extend each plan item's basis with `deadline`, `slack_minutes`, `estimate_minutes`, `estimate_source` (`default`, `user`, `learned:course`, `learned:ratio`), `goal_id`, `slot_reason` (for example "longest gap between classes") and the score components. Render `reason` from that basis with a Chinese template, for example "周五 23:59 截止；预计 90 分钟（按你近 3 次同课程作业实际用时）；14:00–15:30 是今天课间最长空档。" If the client should show the structured form too, add an optional `basis` object to `PlanItemSchema`. That change needs a new D-entry and a drift-check update, because the client contract is authoritative (D-009).

Keep `strategy` in `plan.basis` as a version tag (for example `slots_v2`). This allows later evaluation of the new strategy against `deadline_then_priority` on the same fixtures.

### 3.2 Estimate learning (the first real "learn" step)

When `focus.completed` closes a task, the task has an actual duration. Keep a per-user estimate model with two layers: a per-course prior (median actual minutes of completed assignments in the same course) and a per-user calibration ratio (actual ÷ planned, as a trimmed mean). Store these as **L2 Memory rows**, not in a side table. The planner then reads them through the same retrieval path the Agent will use later, and every learned number is traceable to its source events and correctable by the user. Confidence should be a function of sample count, for example `min(0.9, n/10)`. Below a threshold, the planner falls back to the default and says so in `estimate_source`.

### 3.3 Deviation → re-plan suggestions

Define the triggers explicitly, as event patterns evaluated in the worker and debounced per user (about 30 s). The triggers are:

- `focus.completed` where actual time is more than about 1.3× planned, or the task finished early;
- a newly derived task with a deadline within 48 h, which also resolves round-5 L4;
- a confirmed plan item whose slot has passed without a `focus.started`;
- a `time.schedule.entry` change affecting today;
- the user entering or leaving the rest state.

When a trigger fires, the system must never mutate a confirmed plan. It creates a new DRAFT with `replaces_plan_id` and a human-readable `replan_reason`, which is a Level 1 suggestion. The client shows a diff (moved, added and dropped items) with Accept, which goes through the existing confirm path, or Dismiss. Rate-limit suggestions, for example to one per 30 minutes unless a deadline is at risk, so the proactive feature does not become noise. This is the smallest honest implementation of "proactive Agent" and "dynamic re-planning", both P1 in `AGENTS.md`, and it needs no LLM.

### 3.4 Memory pipeline (M3 core)

The current `memories` table (level, domain, content, `source`, `source_event_ids`, confidence, `correction_status`) is a reasonable start, but it lacks five things a real pipeline needs:

- a stable `subject_key`, for example `estimate_ratio:user` or `course:<id>:estimate`, so that aggregators *upsert* instead of appending duplicates;
- `valid_from`/`valid_to` plus `supersedes_id` for versioning;
- a `kind` (episode, fact, habit, preference, model);
- an `evidence` list that can point at events *or* document anchors, not only event ids;
- a nullable `embedding vector(n)` once pgvector is enabled.

The writers should be deterministic first:

- **L1 episodes** are written directly by the `focus.completed` handler: task, course, planned vs actual minutes, time of day and `deviation_note`, with evidence set to the focus and task events.
- **L2 facts** come from a worker aggregation job over L1 (estimate priors, productive hours, typical overrun per course). Their confidence comes from sample size.
- **LLM-generated summaries**, when they arrive, enter as `UNREVIEWED` with capped confidence. Only user confirmation or repeated deterministic evidence promotes them. This implements the AGENTS §2.3 rule that unverified model summaries must not become permanent facts.

One detail is easy to miss. A `REJECTED` memory must also *block re-derivation* of the same `subject_key`, otherwise the next aggregation run will quietly recreate the fact the user just deleted. `CORRECTED` should create a new version that supersedes the old one rather than editing it in place, so audit history survives. Retrieval for planning or the Agent filters out `REJECTED` rows and applies a confidence floor. The client needs a Memory page that shows each memory with its evidence and offers confirm, correct and delete. That page is the "可修正" half of the acceptance sentence.

### 3.5 Materials and grounded answers (M3 grounding)

Collect material *metadata* as events through the existing CampusAdapter (`getFileList` → `study.material.discovered`, and `getAllNotifications` → an Inbox-ready event type). Download a file only on explicit user action, through Tauri, and upload it to object storage using the existing `FileObject`/`ObjectStorage`. A worker job then extracts text per page or slide into a `material_chunks(file_id, checksum, page, span_start, span_end, text, embedding)` table.

A citation is the tuple `(file_id, checksum, page, span)`. The checksum pins the citation to the exact version that was read. Verification should be mechanical: after generation, every quoted span must be found (after normalisation) in the cited chunk. Any citation that fails is removed and the answer is flagged, never shown as grounded. Store each answer with its citations and the model/prompt version so that "citation correctness" can be measured. Before any of this ships, write the §3 privacy decision that AGENTS.md requires for this data class. Course files are third-party copyrighted material, so the decision must cover upload scope, retention, deletion, and whether page text may be sent to a model provider.

### 3.6 Agent runtime (after 3.1–3.4, not before)

The pieces that matter most are boring ones:

- **Provider adapter.** A single interface for completion, structured output and tool calls, with timeouts and retry caps.
- **`agent_runs` table.** It records model, prompt version, context snapshot (CurrentState version plus memory ids), tools called, tokens, latency and outcome. This is what makes answers auditable.
- **Tool registry.** Each tool declares its `ACTION_POLICY` action, so its permission level is data and not convention.
- **`pending_actions` table and confirm endpoint.** Level 2 tools create a row here (proposed arguments, why, expiry) instead of executing. Level 3 requires an explicit `PermissionGrant`.

The deterministic planner stays as a *tool* the Agent calls, and it is also the fallback when no model is available. It should not be replaced. Context assembly is "CurrentState + top-k relevant memory + active goals" under a token budget. Start with a small evaluation set of fixtures (plan explanations, citation checks, memory-respecting answers) before any prompt tuning. LangGraph is listed in the stack doc, but a plain loop is enough at first. Adopt a framework only when it removes real complexity, and record that choice as a decision either way.

### 3.7 Alpha hardening (M4)

The deletion path is the hardest M4 item and should be designed early. Deleting data must cascade: events → derived tasks' `source_event_ids` → memory evidence (with dependent L2 facts recomputed or invalidated) → material chunks and embeddings → object-storage blobs. Export should follow the same graph. The rest of M4 is more familiar work: a Redis rate limiter, OpenTelemetry traces on external calls and agent runs, sanitised error reporting, and the OneTHU BSL 1.1 / LearnX licence review, which is already a listed blocker for any distribution.

### 3.8 Later domains

Adding Inbox, Life and Exercise later will cost little, because the vendored core already exposes notifications, news, card transactions, electricity balance, sports bookings and library seats. Each is "one adapter method → one event type → optional handler". This is exactly why they should *not* be added until the loop in §3.1–§3.4 is closed. Otherwise they become display features that do not serve the loop, which AGENTS §1 says to defer.

## Suggested M2 exit criterion

Using a real account, the tester collects data, gets a plan that avoids class time and explains each item in human words, completes one Focus that overruns, receives a re-plan suggestion that cites the overrun, accepts it, and sees a new L1 memory with its evidence that can be corrected or deleted. Once this passes on the e2e suite, the phase-one acceptance sentence in `AGENTS.md` §8 is met, and the Agent/LLM work in §3.6 can start on a loop that already learns.
