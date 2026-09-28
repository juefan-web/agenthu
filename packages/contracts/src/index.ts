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
