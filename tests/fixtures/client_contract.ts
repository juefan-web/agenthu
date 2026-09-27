// Frozen snapshot of the desktop client's authoritative Zod contract.
//
// Source: `packages/contracts/src/index.ts` on branch
// `feature/client-tauri-campus-adapter` @ 202e22799ec5eb1072b1d9e44bb8bb835acce674.
//
// The desktop client (Developer B) owns this contract. The Backend serves these
// exact shapes under `/v1` (DECISIONS.md D-009) and the drift check in
// `backend/scripts/check_contract_drift.py` reads this file so CI can report an
// OpenAPI/Zod drift even on a branch where `packages/contracts` is not present.
// When `packages/contracts` *is* present, both copies are checked.
//
// Do not edit to make the Backend pass: update it only together with the client
// contract and record the new source commit above.

import { z } from "zod";

const IsoDateTime = z.string().datetime({ offset: true });

export const EventProvenanceSchema = z.object({
  connector: z.string().min(1),
  connector_version: z.string().min(1),
  upstream_id: z.string().min(1),
  semantic_version: z.string().min(1),
  fetched_at: IsoDateTime,
  endpoint: z.string().optional(),
});

export const EventEnvelopeSchema = z.object({
  client_event_id: z.string().min(1),
  type: z.string().min(1),
  occurred_at: IsoDateTime,
  source: z.string().min(1),
  data: z.record(z.unknown()),
  context: z.record(z.unknown()).default({}),
  provenance: EventProvenanceSchema,
});

export const EventBatchRequestSchema = z.object({
  events: z.array(EventEnvelopeSchema).min(1).max(500),
  client_cursor: z.string().nullable(),
});

export const EventBatchResponseSchema = z.object({
  accepted_event_ids: z.array(z.string()),
  duplicate_event_ids: z.array(z.string()),
  rejected: z.array(
    z.object({
      client_event_id: z.string(),
      reason: z.string(),
    }),
  ),
  next_cursor: z.string().nullable(),
});

export const TaskSchema = z.object({
  id: z.string(),
  title: z.string(),
  due_at: IsoDateTime.nullable(),
  estimate_minutes: z.number().int().nonnegative().nullable(),
  status: z.enum(["todo", "in_progress", "done", "cancelled"]),
  source_event_ids: z.array(z.string()),
});

export const CurrentStateSchema = z.object({
  version: z.number().int().nonnegative(),
  updated_at: IsoDateTime,
  now: IsoDateTime,
  context: z.string().nullable(),
  tasks: z.array(TaskSchema),
  available_minutes: z.number().int().nonnegative().nullable(),
});

export const PlanItemSchema = z.object({
  task_id: z.string(),
  start_at: IsoDateTime,
  end_at: IsoDateTime,
  reason: z.string(),
});

export const PlanSchema = z.object({
  id: z.string(),
  generated_at: IsoDateTime,
  items: z.array(PlanItemSchema),
  confirmation_required: z.boolean(),
  status: z.enum(["draft", "confirmed", "active", "completed", "superseded"]),
});

export const FocusSessionSchema = z.object({
  id: z.string(),
  task_id: z.string(),
  started_at: IsoDateTime,
  ended_at: IsoDateTime.nullable(),
  actual_minutes: z.number().int().nonnegative().nullable(),
  status: z.enum(["running", "paused", "completed", "abandoned"]),
  deviation_note: z.string().nullable(),
});

// Kept for parity with the authoritative contract; no Backend endpoint returns
// this shape directly, so it has no ZOD_TO_OPENAPI mapping.
export const SyncCursorSchema = z.object({
  value: z.string().nullable(),
});
