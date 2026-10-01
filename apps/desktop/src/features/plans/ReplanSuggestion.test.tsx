import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Plan } from "@agenthu/contracts";
import { AppServicesContext, type AppServices } from "../../app/services";
import { diffPlans, ReplanSuggestion } from "./ReplanSuggestion";

const listPlans = vi.fn();
const confirmPlan = vi.fn();
const cancelPlan = vi.fn();

function makePlan(overrides: Partial<Plan>): Plan {
  return {
    id: "plan-1",
    generated_at: "2026-10-01T09:00:00+08:00",
    items: [{
      task_id: "task-1",
      title: "线性代数 HW2",
      start_at: "2026-10-02T14:00:00+08:00",
      end_at: "2026-10-02T15:30:00+08:00",
      reason: "周五截止。",
      basis: undefined,
    }],
    confirmation_required: true,
    status: "confirmed",
    replaces_plan_id: null,
    replan_reason: null,
    ...overrides,
  };
}

const currentPlan = makePlan({
  id: "plan-current",
  status: "confirmed",
  items: [
    { task_id: "task-1", title: "线性代数 HW2", start_at: "2026-10-02T14:00:00+08:00", end_at: "2026-10-02T15:30:00+08:00", reason: "r", basis: undefined },
    { task_id: "task-2", title: "人工智能作业", start_at: "2026-10-02T19:00:00+08:00", end_at: "2026-10-02T20:00:00+08:00", reason: "r", basis: undefined },
  ],
});

const suggestion = makePlan({
  id: "plan-suggestion",
  generated_at: "2026-10-01T12:00:00+08:00",
  status: "draft",
  replaces_plan_id: "plan-current",
  replan_reason: "《线性代数》作业 Focus 超时 42 分钟，今日后续安排需要重排",
  items: [
    { task_id: "task-1", title: "线性代数 HW2", start_at: "2026-10-02T16:00:00+08:00", end_at: "2026-10-02T17:30:00+08:00", reason: "r", basis: undefined },
    { task_id: "task-3", title: "数据结构实验", start_at: "2026-10-02T19:00:00+08:00", end_at: "2026-10-02T20:00:00+08:00", reason: "r", basis: undefined },
  ],
});

function renderSuggestion(current: Plan | undefined) {
  listPlans.mockReset().mockResolvedValue([suggestion, makePlan({ id: "plain-draft", status: "draft" })]);
  confirmPlan.mockReset().mockResolvedValue(suggestion);
  cancelPlan.mockReset().mockResolvedValue(suggestion);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const services = { backend: { listPlans, confirmPlan, cancelPlan } as unknown as AppServices["backend"], backendSession: null, queue: {} as never, focusDraft: {} as never, sync: null, backendUrl: "http://backend", buildTimeBackendUrl: "" };
  return render(<QueryClientProvider client={queryClient}><AppServicesContext.Provider value={services}><ReplanSuggestion currentPlan={current} /></AppServicesContext.Provider></QueryClientProvider>);
}

describe("diffPlans", () => {
  it("按 task_id 归类 moved/added/dropped", () => {
    const diff = diffPlans(currentPlan, suggestion);
    const fmt = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    expect(diff.moved).toEqual([{ title: "线性代数 HW2", from: fmt(currentPlan.items[0]!.start_at), to: fmt(suggestion.items[0]!.start_at) }]);
    expect(diff.added.map((item) => item.title)).toEqual(["数据结构实验"]);
    expect(diff.droppedTitles).toEqual(["人工智能作业"]);
  });
});

describe("ReplanSuggestion（D-031 §2 Level 1 建议 UI）", () => {
  it("发现 replaces_plan_id 非空的最新草稿并展示理由与 diff", async () => {
    renderSuggestion(currentPlan);
    expect(await screen.findByText(/Focus 超时 42 分钟/)).toBeTruthy();
    const fmt = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    expect(screen.getByText(new RegExp(`调整 线性代数 HW2：${fmt(currentPlan.items[0]!.start_at).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} →`))).toBeTruthy();
    expect(screen.getByText(/新增 数据结构实验/)).toBeTruthy();
    expect(screen.getByText(/移出 人工智能作业/)).toBeTruthy();
    expect(screen.getByText(/Level 1 · 不会改动当前计划/)).toBeTruthy();
  });

  it("无建议草稿时不渲染", async () => {
    listPlans.mockReset().mockResolvedValue([makePlan({ id: "plain-draft", status: "draft" })]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const services = { backend: { listPlans } as unknown as AppServices["backend"], backendSession: null, queue: {} as never, focusDraft: {} as never, sync: null, backendUrl: "http://backend", buildTimeBackendUrl: "" };
    const { container } = render(<QueryClientProvider client={queryClient}><AppServicesContext.Provider value={services}><ReplanSuggestion currentPlan={currentPlan} /></AppServicesContext.Provider></QueryClientProvider>);
    await waitFor(() => expect(listPlans).toHaveBeenCalled());
    expect(container.childElementCount).toBe(0);
  });

  it("接受走既有 confirm、忽略走既有 cancel", async () => {
    renderSuggestion(currentPlan);
    fireEvent.click(await screen.findByRole("button", { name: "接受建议" }));
    await waitFor(() => expect(confirmPlan).toHaveBeenCalledWith("plan-suggestion"));
    fireEvent.click(screen.getByRole("button", { name: "忽略" }));
    await waitFor(() => expect(cancelPlan).toHaveBeenCalledWith("plan-suggestion"));
  });
});
