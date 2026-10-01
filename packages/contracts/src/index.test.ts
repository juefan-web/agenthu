import { describe, expect, it } from "vitest";
import {
  assertSafeEvent,
  CurrentStateSchema,
  EventEnvelopeSchema,
  eventDedupeKey,
  PlanItemSchema,
  PlanSchema,
  TaskSchema,
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
