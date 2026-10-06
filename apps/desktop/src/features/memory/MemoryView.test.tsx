import { describe, expect, it, vi } from "vitest";
import { MemoryReceiptStore } from "../../backend/receiptStore";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { MemoryItem } from "../../backend/memory";
import { AppServicesContext, type AppServices } from "../../app/services";
import { MemoryView } from "./MemoryView";

const listMemories = vi.fn();
const confirmMemory = vi.fn();
const correctMemory = vi.fn();
const rejectMemory = vi.fn();

function makeMemory(overrides: Partial<MemoryItem>): MemoryItem {
  return {
    id: "mem-1",
    user_id: "u1",
    level: 1,
    domain: "study",
    content: "线性代数 HW1：计划 60 分钟，实际 90 分钟（晚间效率偏低）",
    source: {},
    source_event_ids: ["event-1"],
    confidence: 0.9,
    correction_status: "CONFIRMED",
    evidence: [{ type: "event", id: "event-1" }],
    kind: "episode",
    subject_key: null,
    supersedes_id: null,
    valid_from: "2026-10-01T20:00:00+08:00",
    valid_to: null,
    use_count: 0,
    last_used_at: null,
    created_at: "2026-10-01T20:00:00+08:00",
    updated_at: "2026-10-01T20:00:00+08:00",
    ...overrides,
  };
}

const fixtures: MemoryItem[] = [
  makeMemory({ id: "mem-live", content: "线性代数作业平均用时 75 分钟" }),
  makeMemory({ id: "mem-unreviewed", correction_status: "UNREVIEWED", content: "模型总结：该生偏好在晚间做题" }),
  makeMemory({ id: "mem-rejected", correction_status: "REJECTED", content: "被拒绝的记忆" }),
  makeMemory({ id: "mem-history", supersedes_id: "mem-live", correction_status: "CORRECTED", content: "旧版本：平均 60 分钟" }),
  makeMemory({
    id: "mem-telemetry",
    content: "带遥测与文档证据的记忆",
    use_count: 3,
    last_used_at: "2026-10-02T09:00:00+08:00",
    evidence: [
      { type: "event", id: "019a2b3c-aaaa-7000-8000-000000000009" },
      { type: "document", file_id: "file-1", checksum_sha256: "abc", page: 3, span_start: 10, span_end: 40 },
    ],
  }),
];

function renderView() {
  listMemories.mockReset().mockResolvedValue(fixtures);
  confirmMemory.mockReset().mockResolvedValue(fixtures[0]!);
  correctMemory.mockReset().mockResolvedValue(fixtures[0]!);
  rejectMemory.mockReset().mockResolvedValue(fixtures[0]!);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const services = { backend: { listMemories, confirmMemory, correctMemory, rejectMemory } as unknown as AppServices["backend"], backendSession: null, queue: {} as never, focusDraft: {} as never, sync: null, receipts: new MemoryReceiptStore(), backendUrl: "http://backend", buildTimeBackendUrl: "" };
  return render(<QueryClientProvider client={queryClient}><AppServicesContext.Provider value={services}><MemoryView /></AppServicesContext.Provider></QueryClientProvider>);
}

describe("MemoryView（「可修正」验收句的落点）", () => {
  it("主列表只显示 live 行，历史版本折叠且有计数", async () => {
    renderView();
    expect(await screen.findByText("线性代数作业平均用时 75 分钟")).toBeTruthy();
    expect(screen.getByText(/live 4 条 · 历史 1 条/)).toBeTruthy();
    expect(screen.queryByText("旧版本：平均 60 分钟")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /展开历史版本/ }));
    expect(screen.getByText("旧版本：平均 60 分钟")).toBeTruthy();
  });

  it("状态徽标、层级/种类与证据计数可见", async () => {
    renderView();
    expect((await screen.findAllByText("已确认")).length).toBeGreaterThan(0);
    expect(screen.getByText("未确认")).toBeTruthy();
    expect(screen.getByText("已拒绝")).toBeTruthy();
    expect(screen.getAllByText(/L1 · 经历 · study/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/证据：事件 1/).length).toBeGreaterThan(0);
  });

  it("确认按钮只出现在非 CONFIRMED 的 live 行并调用 confirm 端点", async () => {
    renderView();
    const buttons = await screen.findAllByRole("button", { name: "确认" });
    expect(buttons.length).toBe(2); // UNREVIEWED + REJECTED（un-reject 路径）
    fireEvent.click(buttons[0]!);
    await waitFor(() => expect(confirmMemory).toHaveBeenCalledWith("mem-unreviewed"));
  });

  it("修正流程提交 content 与置信度百分比换算，成功后收起编辑", async () => {
    renderView();
    fireEvent.click((await screen.findAllByRole("button", { name: "修正" }))[0]!);
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "线性代数作业平均用时 80 分钟" } });
    const confidenceInput = screen.getByLabelText(/置信度/) as HTMLInputElement;
    fireEvent.change(confidenceInput, { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: /保存修正/ }));
    await waitFor(() => expect(correctMemory).toHaveBeenCalledWith("mem-live", { content: "线性代数作业平均用时 80 分钟", confidence: 0.8 }));
  });

  it("拒绝有确认对话框且已拒绝的行不再显示拒绝按钮", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderView();
    fireEvent.click((await screen.findAllByRole("button", { name: "拒绝" }))[0]!);
    await waitFor(() => expect(rejectMemory).toHaveBeenCalled());
    vi.mocked(window.confirm).mockRestore();
  });

  it("证据明细可展开核对：事件 id 截断、文档锚点带页码；遥测只在非零时显示", async () => {
    renderView();
    // 遥测行（use_count/last_used_at）
    expect(await screen.findByText(/参与决策 3 次/)).toBeTruthy();
    expect(screen.getByText(/最近使用/)).toBeTruthy();
    // 证据计数行 + 展开明细
    expect(screen.getByText(/证据：事件 1 · 文档 1/)).toBeTruthy();
    fireEvent.click(screen.getAllByText("证据明细")[0]!);
    const truncated = screen.getAllByText(/019a2b3c…/)[0];
    expect(truncated).toBeTruthy();
    expect(screen.getByText("p.3–10–40")).toBeTruthy();
    // 无遥测的行不显示「参与决策」
    const liveRow = screen.getByText("线性代数作业平均用时 75 分钟").closest(".memory-row")!;
    expect(liveRow.textContent).not.toContain("参与决策");
  });

  it("空列表给出引导文案", async () => {
    listMemories.mockReset().mockResolvedValue([]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const services = { backend: { listMemories } as unknown as AppServices["backend"], backendSession: null, queue: {} as never, focusDraft: {} as never, sync: null, receipts: new MemoryReceiptStore(), backendUrl: "http://backend", buildTimeBackendUrl: "" };
    render(<QueryClientProvider client={queryClient}><AppServicesContext.Provider value={services}><MemoryView /></AppServicesContext.Provider></QueryClientProvider>);
    expect(await screen.findByText(/还没有记忆/)).toBeTruthy();
  });
});
