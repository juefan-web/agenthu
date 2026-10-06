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

// Task.source 是任务来源（"manual" | "onethu" | ...）：backend-only addition
// 为派生任务徽标透出（D-028 后续 / PR #9）。optional 使缺失该字段的旧
// Backend 载荷仍可解析（undefined，按 manual 对待）。
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
  // D-027 附录 / D-031 §1：backend-only 投影诊断（breakdown 等）转正；
  // 弱类型不锁内部结构，服务端永不发 null（None 归一为对象）。
  recent_state: z.record(z.unknown()).optional(),
});

export const PlanItemSchema = z.object({
  task_id: z.string(),
  title: z.string(),
  start_at: IsoDateTime,
  end_at: IsoDateTime,
  reason: z.string(),
  // D-031 §1：结构化依据（「为什么」面板/审计用），形状可演进不锁契约；
  // reason 保留为人话渲染层。服务端 None 归一为空对象，线上永不见 null。
  basis: z.record(z.unknown()).optional(),
});

export const PlanSchema = z.object({
  id: z.string(),
  generated_at: IsoDateTime,
  items: z.array(PlanItemSchema),
  confirmation_required: z.boolean(),
  status: z.enum(["draft", "confirmed", "active", "completed", "superseded"]),
  // Plan 级弱类型依据（服务端 ClientPlan.basis 恒发对象；#59 起
  // generate_plan 写入结构化 agent_decision 子键）。与 item basis 同口径：
  // 形状可演进不锁契约，UI 经 BasisPanel 兼容层检出转交共享渲染器。
  basis: z.record(z.unknown()).optional(),
  // D-031 §2：重排建议形状。普通计划服务端序列化显式 null——必须
  // .nullable()（optional 只容缺失不容 null，B 评审修订）。
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

// ---------------------------------------------------------------------------
// M4（D-034 冻结契约）：pending actions / agent runs / chat / 通知偏好。
// 字段级依据 m4-agent-runtime-audit-contract.md v3 与
// m4-action-confirmation-chat-contract.md r3；与 A1 的 Pydantic/OpenAPI
// 对齐（drift 映射条目随对齐批登记）。

export const DecisionReferenceSchema = z.object({
  // chat_message / current_state 为 D-034 冻结裁定新增（B4①②）。
  kind: z.enum(["event", "memory", "goal", "plan", "task", "material", "chat_message", "current_state"]),
  id: z.string(),
  label: z.string(),
  state: z.enum(["available", "source_deleted", "version_mismatch"]).nullable().optional(),
  locator: z.object({
    page: z.number().int().nullable().optional(),
    quote: z.string().nullable().optional(),
    occurred_at: z.string().nullable().optional(),
    file_id: z.string().nullable().optional(),
    checksum: z.string().nullable().optional(),
    chunk_id: z.string().nullable().optional(),
    span_start: z.number().int().nullable().optional(),
    span_end: z.number().int().nullable().optional(),
    message_id: z.string().nullable().optional(),
    state_version: z.number().int().nullable().optional(),
  }).nullable().optional(),
});

export const DecisionBasisSchema = z.object({
  basis_version: z.string(),
  summary: z.string(),
  references: z.array(DecisionReferenceSchema),
  rule_versions: z.record(z.string()),
  // B1（D-034）：服务端字段，UI 不渲染；drift 双源靠它保持一致。
  selected_tool_call_ids: z.array(z.string()),
});

export const PendingActionReadSchema = z.object({
  id: z.string(),
  version: z.number().int().nonnegative(),
  status: z.enum([
    "PENDING", "CONFIRMED", "EXECUTING", "SUCCEEDED",
    "FAILED_RETRYABLE", "FAILED", "IGNORED", "EXPIRED",
  ]),
  required_level: z.union([z.literal(2), z.literal(3)]),
  tool: z.object({ name: z.string(), version: z.string(), title: z.string() }),
  display: z.object({
    summary: z.string(),
    parameters: z.array(z.object({ label: z.string(), value: z.string() })),
    impact: z.string(),
    risk_note: z.string().nullable().optional(),
  }),
  basis: DecisionBasisSchema,
  // 非空（D-034 裁定）：服务端恒有值；「确认后不再过期」是状态机行为，
  // 不以置空字段表达。
  expires_at: IsoDateTime,
  retryable: z.boolean(),
  safe_error: z.object({ code: z.string(), message: z.string() }).nullable().optional(),
  result: z.object({
    summary: z.string(),
    resource_type: z.string().nullable().optional(),
    resource_id: z.string().nullable().optional(),
  }).nullable().optional(),
  created_at: IsoDateTime,
  updated_at: IsoDateTime,
});

export const AgentRunToolCallSchema = z.object({
  call_id: z.string(),
  tool_name: z.string(),
  tool_version: z.string(),
  status: z.string(),
  started_at: IsoDateTime.nullable(),
  ended_at: IsoDateTime.nullable(),
  error_code: z.string().nullable().optional(),
});

export const AgentRunReadSchema = z.object({
  id: z.string(),
  status: z.enum(["QUEUED", "RUNNING", "WAITING_CONFIRMATION", "SUCCEEDED", "FAILED", "CANCELLED"]),
  invocation_kind: z.enum(["chat", "proactive_trigger", "pending_action_resume", "retry"]),
  trigger_ref: z.object({
    kind: z.string(),
    event_id: z.string().nullable().optional(),
    trigger_signature: z.string().nullable().optional(),
    chat_message_id: z.string().nullable().optional(),
  }),
  provider: z.object({
    name: z.string(),
    model: z.string(),
    capability: z.enum(["tools", "text_only", "none"]),
  }),
  created_at: IsoDateTime,
  updated_at: IsoDateTime,
  started_at: IsoDateTime.nullable(),
  finished_at: IsoDateTime.nullable(),
  // 评审点 6 的成立条件（D-034 裁定必修）：读面必须能 join 出工具调用
  // 序列，L0 审计降噪才不是漏洞。
  tool_calls: z.array(AgentRunToolCallSchema),
  decision_basis: DecisionBasisSchema.nullable(),
  pending_action_ids: z.array(z.string()),
  usage: z.object({
    input_tokens: z.number().int().nonnegative(),
    output_tokens: z.number().int().nonnegative(),
    tool_tokens: z.number().int().nonnegative(),
  }).nullable(),
  result: z.object({
    summary: z.string().nullable().optional(),
    degraded: z.boolean(),
    degrade_code: z.string().nullable().optional(),
  }).nullable(),
  failure: z.object({
    code: z.string(),
    retryable: z.boolean(),
    safe_message: z.string(),
  }).nullable(),
});

export const NotificationPreferencesSchema = z.object({
  version: z.number().int().nonnegative(),
  timezone: z.string(),
  enabled_categories: z.array(z.string()),
  quiet_hours_start: z.string().nullable(),
  quiet_hours_end: z.string().nullable(),
  daily_budget: z.number().int().nonnegative(),
  sent_count: z.number().int().nonnegative(),
  // server-only 只读（B2 裁定）：sent_count 的归属日 / 最近发送时间。
  budget_date: z.string(),
  last_sent_at: IsoDateTime.nullable(),
});

export const ChatSessionSchema = z.object({
  id: z.string(),
  title: z.string(),
  created_at: IsoDateTime,
  updated_at: IsoDateTime,
  archived_at: IsoDateTime.nullable(),
});

export const ChatMessageSchema = z.object({
  id: z.string(),
  // D-035：消息自带会话定位（服务端恒发必填）；检索命中与深链不再依赖
  // 带外上下文。
  session_id: z.string(),
  // 值域未在冻结文本枚举（服务端权威）；客户端不据此分支。
  role: z.string(),
  content: z.string(),
  created_at: IsoDateTime,
  // A5 裁定：经 agent_run_id join 的投影列，不落第二份存储。
  // nullable+optional：服务端 ORMModel 不带 exclude_none，None 字段以
  // 显式 null 下发（A1 评审时发现；仅 optional 会拒收 null）。
  agent_run_id: z.string().nullable().optional(),
  decision_basis: DecisionBasisSchema.nullable().optional(),
  pending_action_id: z.string().nullable().optional(),
});

/** D-035：全局检索命中 = ChatMessageRead（含 session_id）+ 扁平
 *  session_title（会话当前值）——命中行直接渲染「标题 · 时间」并深链，
 *  不取嵌套 ChatSessionRead（每行重复四个恒定字段，零收益）。 */
export const ChatSearchItemSchema = z.object({
  // 显式 z.object 而非 .extend：drift 解析器只认 z.object 字面量（与库内
  // 全部既有 schema 同风格）；字段与 ChatMessageSchema 逐一同形 + 加富。
  id: z.string(),
  session_id: z.string(),
  role: z.string(),
  content: z.string(),
  created_at: IsoDateTime,
  agent_run_id: z.string().nullable().optional(),
  decision_basis: DecisionBasisSchema.nullable().optional(),
  pending_action_id: z.string().nullable().optional(),
  session_title: z.string(),
});

/** D-029 events 口径的 cursor page：只断言 items + next_cursor（缺省/null
 *  = 末页）；Page 包装的其余字段（total/limit/offset）透传剥离。 */
export const CursorPageSchema = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), next_cursor: z.string().nullable() });

export const PendingActionMutationSchema = z.object({
  expected_version: z.number().int().nonnegative(),
  mutation_id: z.string().min(1),
});

export const ChatSessionCreateSchema = z.object({
  title: z.string().optional(),
  client_request_id: z.string().optional(),
});

export const ChatMessageSendSchema = z.object({
  content: z.string().min(1),
  client_message_id: z.string().min(1),
});

export const ChatMessageSendResponseSchema = z.object({
  run_id: z.string(),
  user_message_id: z.string(),
});

export type DecisionReference = z.infer<typeof DecisionReferenceSchema>;
export type DecisionBasis = z.infer<typeof DecisionBasisSchema>;
export type PendingActionRead = z.infer<typeof PendingActionReadSchema>;
export type AgentRunToolCall = z.infer<typeof AgentRunToolCallSchema>;
export type AgentRunRead = z.infer<typeof AgentRunReadSchema>;
export type NotificationPreferences = z.infer<typeof NotificationPreferencesSchema>;
export type ChatSession = z.infer<typeof ChatSessionSchema>;
export type ChatMessage = z.infer<typeof ChatMessageSchema>;
export type ChatSearchItem = z.infer<typeof ChatSearchItemSchema>;
export type CursorPage<T> = { items: T[]; next_cursor: string | null };
export type PendingActionMutation = z.infer<typeof PendingActionMutationSchema>;
export type ChatSessionCreate = z.infer<typeof ChatSessionCreateSchema>;
export type ChatMessageSend = z.infer<typeof ChatMessageSendSchema>;
export type ChatMessageSendResponse = z.infer<typeof ChatMessageSendResponseSchema>;

// --- M5 /v1/data lifecycle contract (P0-4, D-035 client-side batch) ----------
// Mirrors the /v1/data OpenAPI components field-for-field. Mirror discipline
// (B-draft §1, M4 lessons codified): explicit z.object everywhere; the frozen
// contract's `?` marks mean "key always present, may be null" -> required
// `.nullable()` keys, never `.optional()` — the server emits these keys with
// null, and a required mirror is what catches a silently stripped field.
// `include_files` is the one documented omit-ok request field (default true).

// Enum value arrays are the single source (inlined into the DTOs below —
// the drift parser reads z.enum literals, not schema references; types are
// derived from the arrays so values and TS types cannot diverge).
const DATA_OPERATION_KINDS = ["EXPORT", "DELETION"] as const;
const DATA_OPERATION_STATUSES = [
  "QUEUED",
  "RUNNING",
  "RETRY_WAIT",
  "READY",
  "COMPLETED",
  "EXPIRED",
  "FAILED",
] as const;
const DATA_OPERATION_PHASES = [
  "EXPORT_COLLECT",
  "EXPORT_PACKAGE",
  "EXPORT_VERIFY",
  "DELETE_FENCE",
  "DELETE_RELATIONAL",
  "DELETE_OBJECTS",
  "DELETE_VERIFY",
] as const;

export const AccountTargetSchema = z.object({
  kind: z.literal("account"),
});
export const SourceTargetSchema = z.object({
  kind: z.literal("source"),
  source_kind: z.enum(["event", "file", "chat_session", "chat_message"]),
  ids: z.array(z.string().uuid()).min(1).max(100),
});
export const MemoryTargetSchema = z.object({
  kind: z.literal("memory"),
  ids: z.array(z.string().uuid()).min(1).max(100),
  include_history: z.literal(true),
});
export type DeleteTarget =
  | z.infer<typeof AccountTargetSchema>
  | z.infer<typeof SourceTargetSchema>
  | z.infer<typeof MemoryTargetSchema>;

export const DeletionConfirmRequestSchema = z.object({
  preview_id: z.string().uuid(),
  // Opaque server echo: submitted verbatim, never rendered or recomputed.
  preview_digest: z.string().length(64),
  client_request_id: z.string().min(8).max(128),
  confirmed: z.literal(true),
});
export const ExportCreateRequestSchema = z.object({
  client_request_id: z.string().min(8).max(128),
  // The only omit-ok field on this face (server default: true).
  include_files: z.boolean().optional(),
});
export const OperationRetryRequestSchema = z.object({
  // Single field (frozen @A-r2 delta): a 409 version_conflict is the natural
  // idempotency — same shape as the M4 confirm expected_version pattern.
  expected_version: z.number().int().min(1),
});
export const DeletionRecoverRequestSchema = z.object({
  client_request_id: z.string().min(8).max(128),
  request_digest: z.string().length(64),
});

// Component name DataSafeError = the frozen contract's SafeError DTO
// (avoids the agent-domain {code,message} component collision).
export const DataSafeErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  retryable: z.boolean(),
});
export const OperationProgressSchema = z.object({
  processed: z.number().int().nonnegative(),
  total: z.number().int().nonnegative().nullable(),
  outstanding_count: z.number().int().nonnegative(),
});
export const DataEffectSchema = z.object({
  resource_type: z.string(),
  delete_count: z.number().int().nonnegative(),
  redact_count: z.number().int().nonnegative(),
  recompute_count: z.number().int().nonnegative(),
  retain_count: z.number().int().nonnegative(),
  reason_code: z.string(),
});
export const DataCapabilitiesSchema = z.object({
  schema_version: z.string(),
  graph_version: z.string(),
  export_enabled: z.boolean(),
  deletion_enabled: z.boolean(),
  supported_source_kinds: z.array(z.string()),
  minimum_client_version: z.string(),
});
export const DataPreviewOutSchema = z.object({
  id: z.string().uuid(),
  // Server-side loose echo of the accepted target dict.
  target: z.record(z.unknown()),
  graph_version: z.string(),
  data_generation: z.number().int(),
  preview_digest: z.string().length(64),
  expires_at: IsoDateTime,
  effects: z.array(DataEffectSchema),
  limitations: z.array(z.string()),
});
export const DataOperationOutSchema = z.object({
  id: z.string().uuid(),
  kind: z.enum(DATA_OPERATION_KINDS),
  target: z.record(z.unknown()).nullable(),
  status: z.enum(DATA_OPERATION_STATUSES),
  phase: z.enum(DATA_OPERATION_PHASES).nullable(),
  version: z.number().int().min(1),
  data_generation: z.number().int(),
  created_at: IsoDateTime,
  updated_at: IsoDateTime,
  next_retry_at: IsoDateTime.nullable(),
  expires_at: IsoDateTime.nullable(),
  progress: OperationProgressSchema,
  error: DataSafeErrorSchema.nullable(),
  receipt_id: z.string().uuid().nullable(),
  // Delivered exactly once on creation/recovery; always null on plain reads.
  receipt_capability: z.string().nullable(),
});
export const DataReceiptOutSchema = z.object({
  id: z.string().uuid(),
  operation_id: z.string().uuid(),
  completed_at: IsoDateTime.nullable(),
  completion_scope: z.string(),
  effects: z.array(DataEffectSchema),
  outstanding_count: z.number().int().nonnegative(),
  backup_expires_at: IsoDateTime.nullable(),
  provider_limitations: z.array(z.string()),
  local_cleanup_required: z.boolean(),
  audit_receipt_version: z.string(),
});

export type DataOperationKind = (typeof DATA_OPERATION_KINDS)[number];
export type DataOperationStatus = (typeof DATA_OPERATION_STATUSES)[number];
export type DataOperationPhase = (typeof DATA_OPERATION_PHASES)[number];
export type AccountTarget = z.infer<typeof AccountTargetSchema>;
export type SourceTarget = z.infer<typeof SourceTargetSchema>;
export type MemoryTarget = z.infer<typeof MemoryTargetSchema>;
export type DeletionConfirmRequest = z.infer<typeof DeletionConfirmRequestSchema>;
export type ExportCreateRequest = z.infer<typeof ExportCreateRequestSchema>;
export type OperationRetryRequest = z.infer<typeof OperationRetryRequestSchema>;
export type DeletionRecoverRequest = z.infer<typeof DeletionRecoverRequestSchema>;
export type DataSafeError = z.infer<typeof DataSafeErrorSchema>;
export type OperationProgress = z.infer<typeof OperationProgressSchema>;
export type DataEffect = z.infer<typeof DataEffectSchema>;
export type DataCapabilities = z.infer<typeof DataCapabilitiesSchema>;
export type DataPreviewOut = z.infer<typeof DataPreviewOutSchema>;
export type DataOperationOut = z.infer<typeof DataOperationOutSchema>;
export type DataReceiptOut = z.infer<typeof DataReceiptOutSchema>;
