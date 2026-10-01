// Frozen snapshot of the desktop client's authoritative Zod contract.
//
// Source: `packages/contracts/src/index.ts` on branch
// `feature/client-tauri-campus-adapter` @ c581226ca702ba66a484576547bc37bc893a2e0f.
//
// Backend-side contract freeze (2026-09-28, integration review): `title` was
// added to `PlanItemSchema` to match the served `ClientPlanItem` (OpenAPI
// already had it as required). Developer B must mirror this exact line in
// `packages/contracts/src/index.ts`; the drift check fails until both copies
// agree. `next_cursor` is deprecated server-side (D-010) and kept here for
// response compatibility (D-022).
//
// 2026-09-29 (PR #9 review): `TaskSchema.source` added to both copies —
// backend serves "manual" | "onethu" | ..., optional on the client so older
// payloads still parse.
//
// 2026-10-01 (D-031 §1/§2, M2 phase-0 freeze): three lines staged on the
// Backend side, mirroring the 2026-09-28 `title` precedent — mirrored in
// `packages/contracts/src/index.ts` the same day (`feature/contracts-d031-mirror`):
//   `PlanItemSchema.basis: z.record(z.unknown()).optional()`
//     (structured per-item explainability; `reason` stays the human string)
//   `CurrentStateSchema.recent_state: z.record(z.unknown()).optional()`
//     (D-027 appendix; backend-only field turns contractual)
//   `PlanSchema.replaces_plan_id: z.string().nullable().optional()` and
//     `PlanSchema.replan_reason: z.string().nullable().optional()`
//     (replan-suggestion shape; `.nullable()` is required — the backend
//     serializes an explicit null on plans without a replacement, which
//     `.optional()` alone would reject).
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

// Deprecated D-022: echoes the request's client_cursor; client owns sync progress.
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
  source: z.string().optional(),
});

export const CurrentStateSchema = z.object({
  version: z.number().int().nonnegative(),
  updated_at: IsoDateTime,
  now: IsoDateTime,
  context: z.string().nullable(),
  tasks: z.array(TaskSchema),
  available_minutes: z.number().int().nonnegative().nullable(),
  recent_state: z.record(z.unknown()).optional(),
});

export const PlanItemSchema = z.object({
  task_id: z.string(),
  start_at: IsoDateTime,
  end_at: IsoDateTime,
  title: z.string(),
  reason: z.string(),
  basis: z.record(z.unknown()).optional(),
});

export const PlanSchema = z.object({
  id: z.string(),
  generated_at: IsoDateTime,
  items: z.array(PlanItemSchema),
  confirmation_required: z.boolean(),
  status: z.enum(["draft", "confirmed", "active", "completed", "superseded"]),
  replaces_plan_id: z.string().nullable().optional(),
  replan_reason: z.string().nullable().optional(),
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

export const SyncCursorSchema = z.object({
  value: z.string().nullable(),
});

export type EventProvenance = z.infer<typeof EventProvenanceSchema>;
export type EventEnvelope = z.infer<typeof EventEnvelopeSchema>;
export type EventBatchRequest = z.infer<typeof EventBatchRequestSchema>;
export type EventBatchResponse = z.infer<typeof EventBatchResponseSchema>;
export type Task = z.infer<typeof TaskSchema>;
export type CurrentState = z.infer<typeof CurrentStateSchema>;
export type Plan = z.infer<typeof PlanSchema>;
export type FocusSession = z.infer<typeof FocusSessionSchema>;
export type SyncCursor = z.infer<typeof SyncCursorSchema>;

export function eventDedupeKey(event: Pick<EventEnvelope, "source" | "provenance">): string {
  const escape = (part: string): string => part.replace(/[\\:]/g, (ch) => `\\${ch}`);
  return [
    escape(event.source),
    escape(event.provenance.upstream_id),
    escape(event.provenance.semantic_version),
  ].join(":");
}

const sensitiveKey = /^(?:password|passwd|cookie|set-cookie|authorization|access[_-]?token|refresh[_-]?token|token|otp|2fa|verification[_-]?code)$/i;

export function assertSafeEvent(event: EventEnvelope): void {
  const visit = (value: unknown, path: string): void => {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${path}[${index}]`));
      return;
    }
    for (const [key, child] of Object.entries(value)) {
      if (sensitiveKey.test(key)) throw new Error(`敏感字段不得进入 Event: ${path}.${key}`);
      visit(child, `${path}.${key}`);
    }
  };
  visit(event.data, "data");
  visit(event.context, "context");
}

export const LoginRequestSchema = z.object({
  email: z.string().min(3).max(320),
  password: z.string().min(1).max(128),
});

export const RegisterRequestSchema = z.object({
  email: z.string().min(3).max(320),
  password: z.string().min(8).max(128),
  display_name: z.string().min(1).max(200),
});

export const TokenSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.string().min(1).default("bearer"),
  expires_in: z.number().int().positive(),
});

export const UserSchema = z.object({
  id: z.string().min(1),
  email: z.string().min(1),
  display_name: z.string().min(1),
  is_active: z.boolean(),
});

export type LoginRequest = z.infer<typeof LoginRequestSchema>;
export type RegisterRequest = z.infer<typeof RegisterRequestSchema>;
export type Token = z.infer<typeof TokenSchema>;
export type User = z.infer<typeof UserSchema>;
