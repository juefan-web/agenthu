import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PendingActionRead } from "@agenthu/contracts";
import { BackendHttpError } from "../../backend/client";
import { PendingActionsView } from "./PendingActions";

/** 契约 §3/§8：每个 action state 的呈现与可用操作、409 以服务端状态
 *  重呈现（不声称失败）、mutation 幂等重发（同一 mutation_id）、
 *  用户自致失败子码单列文案、仅 PENDING 倒计时、离线不伪造确认。 */

const baseAction: PendingActionRead = {
  id: "pa-1",
  version: 3,
  status: "PENDING",
  required_level: 2,
  tool: { name: "task.create", version: "1.0.0", title: "创建任务" },
  display: {
    summary: "把「复习第三章」加入任务列表",
    parameters: [{ label: "标题", value: "复习（旧：复习第三章要点 → 新：复习第三章）" }],
    impact: "将在任务列表新增一条 todo",
    risk_note: "不可逆程度低",
  },
  basis: {
    basis_version: "v1",
    summary: "作业临近且当前时段空闲",
    references: [{ kind: "task", id: "task-1", label: "HW1" }],
    rule_versions: { planner: "v2" },
    selected_tool_call_ids: [],
  },
  expires_at: new Date(Date.now() + 90_000).toISOString(),
  retryable: false,
  created_at: "2026-10-03T12:00:00+08:00",
  updated_at: "2026-10-03T12:00:00+08:00",
};

function actionWith(overrides: Partial<PendingActionRead>): PendingActionRead {
  return { ...baseAction, ...overrides };
}

const confirm = vi.fn();
const ignore = vi.fn();
const retry = vi.fn();
const listPendingActions = vi.fn();

function backendFixture() {
  return {
    listPendingActions,
    confirmPendingAction: confirm,
    ignorePendingAction: ignore,
    retryPendingAction: retry,
  } as unknown as Parameters<typeof PendingActionsView>[0]["backend"];
}

function renderView(actions: PendingActionRead[], backend = backendFixture()) {
  listPendingActions.mockReset().mockResolvedValue(actions);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>
    <PendingActionsView backend={backend} />
  </QueryClientProvider>);
}

beforeEach(() => {
  confirm.mockReset();
  ignore.mockReset();
  retry.mockReset();
});

describe("PendingActionsView（契约 §3 待确认面）", () => {
  it("PENDING：标题/Level/影响/参数（旧→新按行渲染）/倒计时/确认与忽略", async () => {
    renderView([baseAction]);
    expect(await screen.findByText("创建任务")).toBeTruthy();
    expect(screen.getByText("Level 2 · 需要确认")).toBeTruthy();
    expect(screen.getByText("影响：将在任务列表新增一条 todo")).toBeTruthy();
    expect(screen.getByText("风险：不可逆程度低")).toBeTruthy();
    expect(screen.getByText("复习（旧：复习第三章要点 → 新：复习第三章）")).toBeTruthy();
    expect(screen.getByText(/后到期/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "确认：把「复习第三章」加入任务列表" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "忽略" })).toBeTruthy();
  });

  it("仅 PENDING 显示倒计时；其余状态不渲染到期行", async () => {
    const { unmount } = renderView([actionWith({ status: "CONFIRMED" })]);
    await screen.findByText("已确认，等待执行");
    expect(screen.queryByText(/后到期/)).toBeNull();
    unmount();
    renderView([actionWith({ status: "SUCCEEDED", result: { summary: "已创建任务", resource_type: "task", resource_id: "task-9" } })]);
    await screen.findByText("已完成");
    expect(screen.queryByText(/后到期/)).toBeNull();
    expect(screen.getByText(/已创建任务（task task-9）/)).toBeTruthy();
  });

  it("CONFIRMED/EXECUTING 只有刷新，没有第二次确认入口", async () => {
    renderView([actionWith({ status: "EXECUTING" })]);
    await screen.findByText("正在执行");
    // 卡片级刷新 + 工具条刷新并存
    expect(screen.getAllByRole("button", { name: "刷新" }).length).toBe(2);
    expect(screen.queryByRole("button", { name: /确认/ })).toBeNull();
  });

  it("FAILED_RETRYABLE 且 retryable=true：显示服务端安全错误 + 原参数重试 + 忽略", async () => {
    renderView([actionWith({ status: "FAILED_RETRYABLE", retryable: true, safe_error: { code: "backend_unavailable", message: "任务服务暂时不可用" } })]);
    await screen.findByText("执行失败（可原参数重试）");
    expect(screen.getByText("backend_unavailable：任务服务暂时不可用")).toBeTruthy();
    expect(screen.getByRole("button", { name: "按原参数重试" })).toBeTruthy();
  });

  it("FAILED 用户自致子码：单列文案，不显示为系统故障、无重试", async () => {
    renderView([actionWith({ status: "FAILED", retryable: false, safe_error: { code: "permission_revoked", message: "grant 已撤销" } })]);
    expect(await screen.findByText("你撤销了授权/同意（或来源已删除），动作已失效")).toBeTruthy();
    expect(screen.queryByText(/grant 已撤销/)).toBeNull();
    expect(screen.queryByRole("button", { name: "按原参数重试" })).toBeNull();
  });

  it("IGNORED / EXPIRED：终态文案，无执行按钮", async () => {
    renderView([
      actionWith({ id: "pa-2", status: "IGNORED" }),
      actionWith({ id: "pa-3", status: "EXPIRED" }),
    ]);
    await screen.findByText("已忽略");
    expect(screen.getByText("已过期（未确认）")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /确认/ })).toBeNull();
  });

  it("为什么：展开共享 DecisionBasisView（同一份渲染器）", async () => {
    renderView([baseAction]);
    fireEvent.click(await screen.findByRole("button", { name: "为什么" }));
    expect(await screen.findByText("作业临近且当前时段空闲")).toBeTruthy();
    expect(screen.getByText(/规则版本：planner v2/)).toBeTruthy();
  });

  it("confirm 成功：以 expected_version + mutation_id 调用，按钮防双击后复位", async () => {
    confirm.mockResolvedValue(actionWith({ status: "CONFIRMED" }));
    renderView([baseAction]);
    const button = await screen.findByRole("button", { name: /确认：/ });
    fireEvent.click(button);
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(confirm).toHaveBeenCalledWith("pa-1", 3, expect.any(String) satisfies string);
    await waitFor(() => expect((screen.getByRole("button", { name: /确认：/ }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("409：静默 refetch 以服务端状态重呈现，不向用户声称失败", async () => {
    confirm.mockRejectedValue(new BackendHttpError("已被忽略", 409));
    renderView([baseAction]);
    fireEvent.click(await screen.findByRole("button", { name: /确认：/ }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    // invalidate → 重新拉列表；无 unknown-outcome 告警
    await waitFor(() => expect(listPendingActions.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("网络失败：结果未知的如实文案 + 同一 mutation_id 重发 + 刷新入口", async () => {
    confirm.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    confirm.mockResolvedValueOnce(actionWith({ status: "CONFIRMED" }));
    renderView([baseAction]);
    fireEvent.click(await screen.findByRole("button", { name: /确认：/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("请求未确认送达");
    expect(alert.textContent).toContain("以服务端为准");
    const firstMutationId = confirm.mock.calls[0][2];
    fireEvent.click(screen.getByRole("button", { name: "重发同一请求" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2));
    // 幂等：同一 intent 重发携带同一 mutation_id（服务端返回前次结算）
    expect(confirm.mock.calls[1][2]).toBe(firstMutationId);
  });

  it("离线（无 Backend）：明确失败面，不渲染卡片、不伪造本地确认", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(<QueryClientProvider client={queryClient}>
      <PendingActionsView backend={null} />
    </QueryClientProvider>);
    expect(screen.getByText(/未连接 Backend/)).toBeTruthy();
    expect(container.querySelector(".pending-action-card")).toBeNull();
  });
});
