import { describe, expect, it, vi } from "vitest";
import { MemoryReceiptStore } from "../../backend/receiptStore";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AppServicesContext, type AppServices } from "../../app/services";
import { PlanView } from "./PlanView";

const confirmPlan = vi.fn();
const backend = { confirmPlan } as unknown as AppServices["backend"];

function renderWithServices(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const services = { backend, backendSession: null, queue: {} as never, focusDraft: {} as never, sync: null, receipts: new MemoryReceiptStore(), backendUrl: "http://backend", buildTimeBackendUrl: "" };
  return render(<QueryClientProvider client={queryClient}><AppServicesContext.Provider value={services}>{ui}</AppServicesContext.Provider></QueryClientProvider>);
}

const plan = {
  id: "plan-1",
  generated_at: "2026-10-01T09:00:00+08:00",
  items: [{
    task_id: "task-1",
    title: "线性代数 HW2",
    start_at: "2026-10-02T14:00:00+08:00",
    end_at: "2026-10-02T15:30:00+08:00",
    reason: "周五 23:59 截止；预计 75 分钟（按你近几次同课程作业实际用时）。",
    basis: { estimate_minutes: 75, estimate_source: "learned:course" },
  }],
  confirmation_required: true,
  status: "draft" as const,
  replaces_plan_id: null,
  replan_reason: null,
};

describe("PlanView（app 拆分后的服务注入可测性）", () => {
  it("渲染 reason 人话并挂载「为什么」面板（D-031 双层解释契约）", () => {
    renderWithServices(<PlanView plan={plan} loading={false} error={null} onChanged={() => undefined} />);
    expect(screen.getByText("线性代数 HW2")).toBeTruthy();
    expect(screen.getByText(/按你近几次同课程作业实际用时/)).toBeTruthy();
    expect(screen.getByText("为什么")).toBeTruthy();
  });

  it("无 basis 的旧载荷不渲染面板，计划照常展示", () => {
    const legacy = { ...plan, items: [{ ...plan.items[0]!, basis: undefined }] };
    renderWithServices(<PlanView plan={legacy} loading={false} error={null} onChanged={() => undefined} />);
    expect(screen.getByText("线性代数 HW2")).toBeTruthy();
    expect(screen.queryByText("为什么")).toBeNull();
  });

  it("draft 且 confirmation_required 时提供确认按钮", () => {
    renderWithServices(<PlanView plan={plan} loading={false} error={null} onChanged={() => undefined} />);
    expect(screen.getByRole("button", { name: "确认计划" })).toBeTruthy();
  });
});
