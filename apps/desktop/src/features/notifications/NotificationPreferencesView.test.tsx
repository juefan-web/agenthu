import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { NotificationPreferences } from "@agenthu/contracts";
import { BackendHttpError } from "../../backend/client";
import { NotificationPreferencesView } from "./NotificationPreferencesView";

/** 契约 §6：数值控件（类别/免打扰起止/每日上限）+ server-only 只读展示；
 *  PATCH 携带 expected_version；409 加载最新值重填不静默覆盖；禁用免打扰
 *  送 null/null；跨午夜合法；不声称「绝不会提醒」。 */

const getNotificationPreferences = vi.fn();
const updateNotificationPreferences = vi.fn();

function backendFixture() {
  return { getNotificationPreferences, updateNotificationPreferences } as unknown as Parameters<typeof NotificationPreferencesView>[0]["backend"];
}

const base: NotificationPreferences = {
  version: 5,
  timezone: "Asia/Shanghai",
  enabled_categories: ["deadline_risk"],
  quiet_hours_start: null,
  quiet_hours_end: null,
  daily_budget: 3,
  sent_count: 1,
  budget_date: "2026-10-03",
  last_sent_at: "2026-10-03T08:00:00+08:00",
};

function renderView() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>
    <NotificationPreferencesView backend={backendFixture()} />
  </QueryClientProvider>);
}

beforeEach(() => {
  getNotificationPreferences.mockReset().mockResolvedValue(base);
  updateNotificationPreferences.mockReset();
});

describe("NotificationPreferencesView（契约 §6 控制面）", () => {
  it("展示服务端值与只读用量（含 server-only 字段），不承诺绝不提醒", async () => {
    renderView();
    expect(await screen.findByText(/今天已发送 1 条 \/ 上限 3 条/)).toBeTruthy();
    expect(screen.getByText(/时区 Asia\/Shanghai/)).toBeTruthy();
    expect(screen.getByText(/最近发送/)).toBeTruthy();
    expect(screen.getByText(/提醒规则以服务端为准/)).toBeTruthy();
    expect(screen.getByText("deadline_risk")).toBeTruthy();
  });

  it("编辑免打扰（跨午夜）与上限后保存：PATCH 携带 expected_version", async () => {
    updateNotificationPreferences.mockResolvedValue({ ...base, quiet_hours_start: "22:00", quiet_hours_end: "07:00", daily_budget: 5, version: 6 });
    renderView();
    fireEvent.click(await screen.findByLabelText(/启用免打扰/));
    fireEvent.change(screen.getByLabelText("开始"), { target: { value: "22:00" } });
    fireEvent.change(screen.getByLabelText("结束"), { target: { value: "07:00" } });
    const budget = screen.getByLabelText(/条\/天/);
    fireEvent.change(budget, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(updateNotificationPreferences).toHaveBeenCalledTimes(1));
    const [patch, version] = updateNotificationPreferences.mock.calls[0];
    expect(version).toBe(5);
    expect(patch).toEqual(expect.objectContaining({
      quiet_hours_start: "22:00", quiet_hours_end: "07:00", daily_budget: 5,
      enabled_categories: ["deadline_risk"], timezone: "Asia/Shanghai",
    }));
    expect(await screen.findByText("已保存。")).toBeTruthy();
  });

  it("禁用免打扰保存送 null/null（改配对约束为服务端校验）", async () => {
    getNotificationPreferences.mockResolvedValue({ ...base, quiet_hours_start: "22:00", quiet_hours_end: "07:00" });
    updateNotificationPreferences.mockResolvedValue(base);
    renderView();
    fireEvent.click(await screen.findByLabelText(/启用免打扰/));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(updateNotificationPreferences).toHaveBeenCalledTimes(1));
    const [patch] = updateNotificationPreferences.mock.calls[0];
    expect(patch.quiet_hours_start).toBeNull();
    expect(patch.quiet_hours_end).toBeNull();
  });

  it("409：冲突提示 + 以最新值重填，不静默覆盖", async () => {
    getNotificationPreferences.mockResolvedValueOnce(base)
      .mockResolvedValue({ ...base, version: 9, daily_budget: 8, enabled_categories: ["plan_deviation"] });
    updateNotificationPreferences.mockRejectedValue(new BackendHttpError("版本冲突", 409));
    renderView();
    fireEvent.change(await screen.findByLabelText(/条\/天/), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText(/已在其他设备修改/)).toBeTruthy();
    await waitFor(() => expect(getNotificationPreferences.mock.calls.length).toBeGreaterThanOrEqual(2));
    // 表单以服务端最新值重填（daily_budget=8），不是用户被拒的 4
    expect((screen.getByLabelText(/条\/天/) as HTMLInputElement).value).toBe("8");
    expect(screen.getByText("plan_deviation")).toBeTruthy();
  });

  it("类别增删进入 PATCH；非法上限阻止提交", async () => {
    updateNotificationPreferences.mockResolvedValue(base);
    renderView();
    fireEvent.click((await screen.findAllByTitle("移除类别"))[0]);
    fireEvent.change(screen.getByLabelText("新增类别"), { target: { value: "plan_deviation" } });
    fireEvent.click(screen.getByRole("button", { name: "添加类别" }));
    fireEvent.change(screen.getByLabelText(/条\/天/), { target: { value: "-1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText(/上限必须是不小于 0 的整数/)).toBeTruthy();
    expect(updateNotificationPreferences).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/条\/天/), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(updateNotificationPreferences).toHaveBeenCalledTimes(1));
    expect(updateNotificationPreferences.mock.calls[0][0].enabled_categories).toEqual(["plan_deviation"]);
  });

  it("离线：明确失败面", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}>
      <NotificationPreferencesView backend={null} />
    </QueryClientProvider>);
    expect(screen.getByText(/未连接 Backend/)).toBeTruthy();
  });
});
