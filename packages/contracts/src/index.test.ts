import { describe, expect, it } from "vitest";
import {
  assertSafeEvent,
  CurrentStateSchema,
  EventEnvelopeSchema,
  eventDedupeKey,
  PlanItemSchema,
  PlanSchema,
  TaskSchema,
  AgentRunReadSchema,
  ChatMessageSchema,
  ChatSearchItemSchema,
  CursorPageSchema,
  DecisionBasisSchema,
  NotificationPreferencesSchema,
  PendingActionReadSchema,
} from "./index";

const event = {
  client_event_id: "onethu:homework:hw-1:v1",
  type: "study.assignment.discovered",
  occurred_at: "2026-09-26T10:00:00+08:00",
  source: "onethu",
  data: { title: "HW1" },
  context: {},
  provenance: {
    connector: "onethu",
    connector_version: "2e3455f",
    upstream_id: "hw-1",
    semantic_version: "v1",
    fetched_at: "2026-09-26T10:00:01+08:00",
  },
};

describe("event contract", () => {
  it("validates and derives a stable dedupe key", () => {
    const parsed = EventEnvelopeSchema.parse(event);
    expect(eventDedupeKey(parsed)).toBe("onethu:hw-1:v1");
  });

  it("does not collide when source or upstream_id contains a colon", () => {
    const base = EventEnvelopeSchema.parse(event);
    const first = eventDedupeKey({
      ...base,
      source: "a:b",
      provenance: { ...base.provenance, upstream_id: "c" },
    });
    const second = eventDedupeKey({
      ...base,
      source: "a",
      provenance: { ...base.provenance, upstream_id: "b:c" },
    });
    expect(first).not.toBe(second);
  });

  it("rejects credentials before enqueueing", () => {
    const parsed = EventEnvelopeSchema.parse({
      ...event,
      data: { password: "secret" },
    });
    expect(() => assertSafeEvent(parsed)).toThrow("敏感字段");
  });
});

describe("task contract", () => {
  const task = {
    id: "019a2b3c-1111-7000-8000-000000000001",
    title: "Linear Algebra HW2",
    due_at: "2026-10-01T23:59:00+08:00",
    estimate_minutes: 60,
    status: "todo",
    source_event_ids: ["019a2b3c-2222-7000-8000-000000000002"],
    source: "onethu",
  };

  it("keeps the derived-task source and strips backend-only additions", () => {
    const parsed = TaskSchema.parse({ ...task, description: "backend-only", goal_id: null });
    expect(parsed.source).toBe("onethu");
    expect(parsed).not.toHaveProperty("description");
    expect(parsed).not.toHaveProperty("goal_id");
  });

  it("parses payloads from a backend predating the source field", () => {
    const { source: _omitted, ...withoutSource } = task;
    expect(TaskSchema.parse(withoutSource).source).toBeUndefined();
  });
});

describe("plan contract (D-031 mirror)", () => {
  const planItem = {
    task_id: "019a2b3c-3333-7000-8000-000000000003",
    title: "线性代数 HW2",
    start_at: "2026-10-02T14:00:00+08:00",
    end_at: "2026-10-02T15:30:00+08:00",
    reason: "周五 23:59 截止；14:00-15:30 是今天课间最长空档。",
  };
  const plan = {
    id: "019a2b3c-4444-7000-8000-000000000004",
    generated_at: "2026-10-01T09:00:00+08:00",
    items: [planItem],
    confirmation_required: true,
    status: "draft" as const,
  };

  it("keeps the structured basis and tolerates its absence (never null on the wire)", () => {
    const basis = { deadline: "2026-10-04T23:59:00+08:00", slack_minutes: -30, estimate_source: "learned:course" };
    expect(PlanItemSchema.parse({ ...planItem, basis }).basis).toEqual(basis);
    expect(PlanItemSchema.parse(planItem).basis).toBeUndefined();
  });

  it("accepts the explicit null replaces_plan_id on ordinary plans (D-031 review amendment)", () => {
    expect(PlanSchema.parse({ ...plan, replaces_plan_id: null, replan_reason: null }).replaces_plan_id).toBeNull();
    expect(PlanSchema.parse(plan).replaces_plan_id).toBeUndefined();
  });

  it("keeps the replan-suggestion shape on suggestion drafts", () => {
    const suggestion = PlanSchema.parse({
      ...plan,
      replaces_plan_id: "019a2b3c-5555-7000-8000-000000000005",
      replan_reason: "《线性代数》作业 Focus 超时 42 分钟，今日后续安排需要重排",
    });
    expect(suggestion.replan_reason).toContain("超时");
  });

  it("exposes recent_state as a weak record without locking its shape (D-027 appendix)", () => {
    const state = {
      version: 3,
      updated_at: "2026-10-01T09:00:00+08:00",
      now: "2026-10-01T09:00:00+08:00",
      context: null,
      tasks: [],
      available_minutes: 135,
      recent_state: { available_minutes_breakdown: { schedule: -180, focus: -45 } },
    };
    expect(CurrentStateSchema.parse(state).recent_state).toEqual(state.recent_state);
    expect(CurrentStateSchema.parse({ ...state, recent_state: undefined }).recent_state).toBeUndefined();
  });
});

const basis = {
  basis_version: "v1",
  summary: "作业临近且当前时段空闲",
  references: [
    { kind: "task", id: "task-1", label: "HW1", state: "available" },
    { kind: "chat_message", id: "msg-9", label: "昨天的讨论", locator: { message_id: "msg-9", occurred_at: "2026-10-02T21:00:00+08:00" } },
    { kind: "current_state", id: "state-42", label: "当前状态 v42", locator: { state_version: 42 } },
    { kind: "material", id: "file-1", label: "lecture1.pdf", state: "version_mismatch", locator: { page: 3, checksum: "chk-old" } },
  ],
  rule_versions: { planner: "v2" },
  selected_tool_call_ids: ["call-1"],
};

const pendingAction = {
  id: "pa-1",
  version: 3,
  status: "PENDING",
  required_level: 2,
  tool: { name: "task.create", version: "1.0.0", title: "创建任务" },
  display: {
    summary: "把「复习第三章」加入任务列表",
    parameters: [{ label: "标题", value: "复习第三章（旧：复习 → 新：复习第三章）" }],
    impact: "将在任务列表新增一条 todo",
    risk_note: "不可逆程度低",
  },
  basis,
  expires_at: "2026-10-04T12:00:00+08:00",
  retryable: true,
  created_at: "2026-10-03T12:00:00+08:00",
  updated_at: "2026-10-03T12:00:00+08:00",
};

describe("M4 frozen contract (D-034)", () => {
  it("parses a pending action with the full basis, including the new reference kinds", () => {
    const parsed = PendingActionReadSchema.parse(pendingAction);
    expect(parsed.basis.references.map((reference) => reference.kind)).toEqual([
      "task", "chat_message", "current_state", "material",
    ]);
    expect(parsed.basis.selected_tool_call_ids).toEqual(["call-1"]);
    expect(parsed.expires_at).toBe("2026-10-04T12:00:00+08:00");
  });

  it("requires a non-null expires_at (post-confirmation no-expiry is state-machine behaviour)", () => {
    const { expires_at: _ignored, ...withoutExpiry } = pendingAction;
    expect(() => PendingActionReadSchema.parse(withoutExpiry)).toThrow();
    expect(() => PendingActionReadSchema.parse({ ...pendingAction, expires_at: null })).toThrow();
  });

  it("parses an agent run with the tool_calls mirror and the degraded result", () => {
    const parsed = AgentRunReadSchema.parse({
      id: "run-1",
      status: "SUCCEEDED",
      invocation_kind: "chat",
      trigger_ref: { kind: "chat", chat_message_id: "msg-1" },
      provider: { name: "openai", model: "gpt-x", capability: "none" },
      created_at: "2026-10-03T12:00:00+08:00",
      updated_at: "2026-10-03T12:00:05+08:00",
      started_at: "2026-10-03T12:00:01+08:00",
      finished_at: "2026-10-03T12:00:05+08:00",
      tool_calls: [{ call_id: "call-1", tool_name: "plan.suggest", tool_version: "1.0.0", status: "succeeded", started_at: null, ended_at: null }],
      decision_basis: basis,
      pending_action_ids: [],
      usage: null,
      result: { degraded: true, degrade_code: "provider_unavailable" },
      failure: null,
    });
    expect(parsed.tool_calls).toHaveLength(1);
    expect(parsed.result?.degraded).toBe(true);
  });

  it("parses chat messages with optional join projections and notification server-only fields", () => {
    const message = ChatMessageSchema.parse({
      id: "msg-1", session_id: "sess-1", role: "user", content: "把作业加进日程", created_at: "2026-10-03T12:00:00+08:00",
    });
    expect(message.decision_basis).toBeUndefined();
    expect(() => ChatMessageSchema.parse({ ...message, decision_basis: basis, pending_action_id: "pa-1" })).toBeTruthy();
    // 服务端 ORMModel 不 exclude_none：无 run 关联的消息以显式 null 下发
    // 投影列，仅 .optional() 会拒收（A1 评审发现的回归点）。
    const nulled = ChatMessageSchema.parse({
      ...message, agent_run_id: null, decision_basis: null, pending_action_id: null,
    });
    expect(nulled.agent_run_id).toBeNull();

    const preferences = NotificationPreferencesSchema.parse({
      version: 2, timezone: "Asia/Shanghai", enabled_categories: ["deadline"],
      quiet_hours_start: "22:00", quiet_hours_end: "07:00", daily_budget: 3,
      sent_count: 1, budget_date: "2026-10-03", last_sent_at: "2026-10-03T08:00:00+08:00",
    });
    expect(preferences.budget_date).toBe("2026-10-03");
  });

  it("requires session_id on chat messages and parses search hits with the flat title (D-035)", () => {
    expect(() => ChatMessageSchema.parse({ id: "m", role: "user", content: "c", created_at: "2026-10-04T10:00:00+08:00" })).toThrow();
    const hit = ChatSearchItemSchema.parse({
      id: "msg-9", session_id: "sess-2", role: "assistant", content: "命中原文",
      created_at: "2026-10-04T10:00:00+08:00", session_title: "第一条",
    });
    expect(hit.session_title).toBe("第一条");
    expect(() => ChatSearchItemSchema.parse({ id: "m", session_id: "s", role: "user", content: "c", created_at: "2026-10-04T10:00:00+08:00" })).toThrow();
  });

  it("cursor pages assert items + next_cursor only (null = last page)", () => {
    const page = CursorPageSchema(ChatMessageSchema).parse({
      items: [], next_cursor: null, total: 7, limit: 50, offset: 0,
    });
    expect(page.items).toEqual([]);
    expect(page.next_cursor).toBeNull();
  });

  it("accepts explicit nulls on every backend-emitted nullable field (no exclude_none)", () => {
    // 服务端 ORMModel/嵌套 Pydantic 均不带 exclude_none：X | None 字段以
    // 显式 null 下发（顶层与嵌套同理）。仅 .optional() 拒收 null——本测试
    // 固化全量清扫：safe_error/result、trigger_ref 三列、locator 全列、
    // state、risk_note、resource_type/id、error_code、summary/degrade_code。
    const action = PendingActionReadSchema.parse({
      ...pendingAction,
      display: { ...pendingAction.display, risk_note: null },
      safe_error: null,
      result: null,
    });
    expect(action.safe_error).toBeNull();
    expect(action.result).toBeNull();

    const run = AgentRunReadSchema.parse({
      id: "run-2", status: "FAILED", invocation_kind: "chat",
      trigger_ref: { kind: "chat", event_id: null, trigger_signature: null, chat_message_id: "msg-2" },
      provider: { name: "openai", model: "gpt-x", capability: "none" },
      created_at: "2026-10-03T12:00:00+08:00", updated_at: "2026-10-03T12:00:05+08:00",
      started_at: null, finished_at: null,
      tool_calls: [{ call_id: "call-2", tool_name: "memory.retrieve", tool_version: "1.0.0", status: "succeeded", started_at: null, ended_at: null, error_code: null }],
      decision_basis: null, pending_action_ids: [], usage: null,
      result: { summary: null, degraded: true, degrade_code: null },
      failure: { code: "provider_unavailable", retryable: true, safe_message: "模型暂不可用" },
    });
    expect(run.trigger_ref.event_id).toBeNull();
    expect(run.tool_calls[0].error_code).toBeNull();
    expect(run.result?.summary).toBeNull();

    const withNullReferenceBasis = DecisionBasisSchema.parse({
      ...basis,
      references: [
        { kind: "goal", id: "goal-1", label: "绩点", state: null, locator: null },
        { kind: "memory", id: "mem-1", label: "偏好", locator: { page: null, quote: null, span_start: null, span_end: null } },
      ],
    });
    expect(withNullReferenceBasis.references[0].state).toBeNull();
    expect(withNullReferenceBasis.references[1].locator?.page).toBeNull();
  });
});
