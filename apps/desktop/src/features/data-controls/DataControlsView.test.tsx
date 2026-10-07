import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DataCapabilities, DataOperationOut, DataPreviewOut } from "@agenthu/contracts";
import { BackendHttpError } from "../../backend/client";
import { MemoryReceiptStore } from "../../backend/receiptStore";
import { AppServicesContext, type AppServices } from "../../app/services";
import { useBackendSessionStore } from "../../state/backendSession";
import { DataControlsView } from "./DataControlsView";

const capabilities = vi.fn();
const createPreview = vi.fn();
const confirmDeletion = vi.fn();
const getOperation = vi.fn();
const adoptUnowned = vi.fn();
const discardUnowned = vi.fn();
const adoptUnownedDraft = vi.fn();
const discardUnownedDraft = vi.fn();
const clearOwnerData = vi.fn();
const countOwnerData = vi.fn();
const logout = vi.fn();

function makeCapabilities(overrides: Partial<DataCapabilities> = {}): DataCapabilities {
  return { schema_version: "1", graph_version: "g1", export_enabled: true, deletion_enabled: true, supported_source_kinds: ["event", "file", "chat_session", "chat_message"], minimum_client_version: "0.1", ...overrides };
}

function makePreview(overrides: Partial<DataPreviewOut> = {}): DataPreviewOut {
  return {
    id: "019ddddd-0000-7000-8000-000000000001",
    target: { kind: "source" },
    graph_version: "g1",
    data_generation: 1,
    preview_digest: "d".repeat(64),
    expires_at: "2026-10-07T10:10:00+08:00",
    effects: [
      { resource_type: "chat_sessions", delete_count: 1, redact_count: 0, recompute_count: 0, retain_count: 0, reason_code: "source_whole_delete" },
      { resource_type: "chat_messages", delete_count: 2, redact_count: 0, recompute_count: 1, retain_count: 0, reason_code: "source_whole_delete" },
    ],
    limitations: [],
    ...overrides,
  };
}

function makeOperation(overrides: Partial<DataOperationOut> = {}): DataOperationOut {
  return {
    id: "019ddddd-aaaa-7000-8000-000000000002",
    kind: "DELETION",
    target: null,
    status: "COMPLETED",
    phase: null,
    version: 1,
    data_generation: 1,
    created_at: "2026-10-07T10:00:00+08:00",
    updated_at: "2026-10-07T10:00:30+08:00",
    next_retry_at: null,
    expires_at: null,
    progress: { processed: 3, total: 3, outstanding_count: 0 },
    error: null,
    receipt_id: null,
    receipt_capability: null,
    ...overrides,
  };
}

function renderView(servicesOverrides: Partial<AppServices> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const receipts = new MemoryReceiptStore();
  const services: AppServices = {
    backend: { getDataCapabilities: capabilities, createDataPreview: createPreview, confirmDataDeletion: confirmDeletion, getDataOperation: getOperation } as unknown as AppServices["backend"],
    backendSession: { logout } as unknown as AppServices["backendSession"],
    queue: { countUnowned: vi.fn().mockResolvedValue(2), adoptUnowned, discardUnowned, clearOwnerData, countOwnerData } as unknown as AppServices["queue"],
    focusDraft: { adoptUnownedDraft, discardUnownedDraft } as unknown as AppServices["focusDraft"],
    sync: null,
    receipts,
    resolveOwner: () => "owner-key-0001",
    backendUrl: "http://backend",
    buildTimeBackendUrl: "",
    ...servicesOverrides,
  };
  const view = render(<QueryClientProvider client={queryClient}><AppServicesContext.Provider value={services}><DataControlsView /></AppServicesContext.Provider></QueryClientProvider>);
  return { ...view, receipts, services };
}

describe("数据与隐私页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    capabilities.mockReset().mockResolvedValue(makeCapabilities());
    createPreview.mockReset().mockResolvedValue(makePreview());
    confirmDeletion.mockReset().mockResolvedValue(makeOperation({ status: "QUEUED" }));
    getOperation.mockReset().mockResolvedValue(makeOperation({ status: "COMPLETED" }));
    clearOwnerData.mockReset().mockResolvedValue(0);
    countOwnerData.mockReset().mockResolvedValue(0);
    logout.mockReset().mockResolvedValue(undefined);
    useBackendSessionStore.getState().setState({ status: "ready", email: "user@test.invalid", userId: "u1" });
  });
  afterEach(() => {
    useBackendSessionStore.getState().reset();
  });

  it("服务能力卡渲染契约/图谱版本；错误时显示「尚未支持」", async () => {
    renderView();
    expect(await screen.findByText(/契约版本 1 · 数据图谱 g1/)).toBeTruthy();

    capabilities.mockReset().mockRejectedValue(new Error("404"));
    renderView();
    await waitFor(() => expect(screen.getAllByText("此服务尚未支持完整导出/删除。").length).toBeGreaterThan(0));
  });

  it("source 删除全流：preview 文案 → 确认 202 → 轮询 COMPLETED 文案", async () => {
    renderView();
    fireEvent.change(await screen.findByLabelText("对象 ID"), { target: { value: "019ddddd-bbbb-7000-8000-000000000009" } });
    fireEvent.click(await screen.findByRole("button", { name: "查看删除范围" }));
    expect(await screen.findByText("将删除 3 项、清除 0 项派生内容、重算 1 项；独立编辑内容按清单保留")).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
    expect(await screen.findByText("服务端在线数据已清除")).toBeTruthy();
    expect(createPreview).toHaveBeenCalledWith({ kind: "source", source_kind: "event", ids: ["019ddddd-bbbb-7000-8000-000000000009"] });
    const request = confirmDeletion.mock.calls[0]?.[0] as { preview_digest: string; confirmed: boolean };
    expect(request.preview_digest).toBe("d".repeat(64));
    expect(request.confirmed).toBe(true);
  });

  it("账号删除两步确认：回执留存（含完整确认体）→ 本机清理 verified（VACUUM 路径）", async () => {
    confirmDeletion.mockReset().mockResolvedValue(makeOperation({
      kind: "DELETION",
      status: "QUEUED",
      receipt_id: "019ddddd-cccc-7000-8000-000000000003",
      receipt_capability: "cap-once-delivered",
    }));
    const { receipts } = renderView();

    fireEvent.change(await screen.findByLabelText("删除范围"), { target: { value: "account" } });
    fireEvent.click(await screen.findByRole("button", { name: "查看删除范围" }));
    expect(await screen.findByText(/user@test\.invalid/)).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "继续" }));
    const confirmButton = await screen.findByRole("button", { name: "永久删除账号" }) as HTMLButtonElement;
    expect(confirmButton.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "我理解此操作不可恢复" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "永久删除账号" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "永久删除账号" }));

    expect(await screen.findByText(/本机清理已核验/)).toBeTruthy();
    await waitFor(() => expect(clearOwnerData).toHaveBeenCalledWith("owner-key-0001", true));
    expect(logout).toHaveBeenCalled();
    const stored = await receipts.read("owner-key-0001");
    expect(stored?.capability).toBe("cap-once-delivered");
    expect(stored?.confirm_body).toMatchObject({ preview_id: makePreview().id, confirmed: true, client_request_id: expect.stringMatching(/^del-/) });
  });

  it("409 deletion_in_progress 显示冻结文案，不开第二个确认", async () => {
    confirmDeletion.mockReset().mockRejectedValue(new BackendHttpError("已有删除正在进行", 409, "deletion_in_progress"));
    renderView();
    fireEvent.change(await screen.findByLabelText("对象 ID"), { target: { value: "019ddddd-bbbb-7000-8000-000000000009" } });
    fireEvent.click(await screen.findByRole("button", { name: "查看删除范围" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
    expect(await screen.findByText("已有删除正在进行")).toBeTruthy();
  });

  it("无主处置：未登录时 adopt 禁用（live-session 守卫）；登录后 adopt 归当前 owner", async () => {
    useBackendSessionStore.getState().setState({ status: "idle" });
    const view = renderView();
    const adopt = await screen.findByRole("button", { name: "归入当前账号" }) as HTMLButtonElement;
    expect(adopt.disabled).toBe(true);
    view.unmount();

    useBackendSessionStore.getState().setState({ status: "ready", email: "user@test.invalid", userId: "u1" });
    adoptUnowned.mockReset().mockResolvedValue(2);
    adoptUnownedDraft.mockReset().mockResolvedValue(0);
    renderView();
    const enabled = await screen.findByRole("button", { name: "归入当前账号" }) as HTMLButtonElement;
    await waitFor(() => expect(enabled.disabled).toBe(false));
    fireEvent.click(enabled);
    await waitFor(() => expect(adoptUnowned).toHaveBeenCalledWith("owner-key-0001"));
    expect(adoptUnownedDraft).toHaveBeenCalledWith("owner-key-0001");
    await screen.findByText(/已归入当前账号：事件 2 条/);
  });
});
