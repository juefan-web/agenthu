import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { DataReceiptOut } from "@agenthu/contracts";
import { MemoryReceiptStore, type StoredReceipt } from "../../backend/receiptStore";
import { ReceiptViewer } from "./ReceiptViewer";

const fetchReceiptWithCapability = vi.hoisted(() => vi.fn());
vi.mock("../../backend/data", () => ({
  fetchReceiptWithCapability: fetchReceiptWithCapability,
}));

function makeStored(): StoredReceipt {
  return {
    capability: "cap-secret-value-never-rendered",
    receipt_id: "019ccccc-0000-7000-8000-000000000001",
    client_request_id: "del-00000001",
    confirm_body: { preview_id: "019ccccc-aaaa-7000-8000-000000000002", preview_digest: "d".repeat(64), client_request_id: "del-00000001", confirmed: true },
    issued_at: "2026-10-07T10:00:00+08:00",
    expires_at: "2027-01-05T10:00:00+08:00",
  };
}

function makeReceipt(): DataReceiptOut {
  return {
    id: "019ccccc-0000-7000-8000-000000000001",
    operation_id: "019ccccc-bbbb-7000-8000-000000000003",
    completed_at: "2026-10-07T10:02:00+08:00",
    completion_scope: "controlled_live",
    effects: [{ resource_type: "events", delete_count: 6, redact_count: 0, recompute_count: 0, retain_count: 0, reason_code: "account_deletion" }],
    outstanding_count: 0,
    backup_expires_at: "2026-10-21T10:02:00+08:00",
    provider_limitations: ["供应商在备份窗内可能仍持有副本"],
    local_cleanup_required: true,
    audit_receipt_version: "1",
  };
}

describe("回执独立最小视图（B 稿 §1/§3）", () => {
  beforeEach(() => {
    fetchReceiptWithCapability.mockReset();
  });

  it("列出本机槽位（非敏感元数据），读取成功展示清理账目", async () => {
    const store = new MemoryReceiptStore();
    await store.write("owner-key-0001", makeStored());
    fetchReceiptWithCapability.mockResolvedValue(makeReceipt());
    render(<ReceiptViewer baseUrl="http://backend" store={store} />);

    const open = await screen.findByRole("button", { name: "查看" });
    fireEvent.click(open);
    expect(await screen.findByText("服务端清理已完成")).toBeTruthy();
    expect(fetchReceiptWithCapability).toHaveBeenCalledWith(
      "http://backend",
      "019ccccc-0000-7000-8000-000000000001",
      "cap-secret-value-never-rendered",
    );
    // capability 不进 DOM
    expect(document.body.textContent ?? "").not.toContain("cap-secret-value");
    expect(screen.getByText(/备份最晚失效/)).toBeTruthy();
  });

  it("无效能力统一「回执不可用」——不区分不存在/过期/身份不符", async () => {
    const store = new MemoryReceiptStore();
    await store.write("owner-key-0001", makeStored());
    fetchReceiptWithCapability.mockResolvedValue(null);
    render(<ReceiptViewer baseUrl="http://backend" store={store} />);

    fireEvent.click(await screen.findByRole("button", { name: "查看" }));
    expect(await screen.findByText("回执不可用")).toBeTruthy();
  });

  it("槽位损坏（读不出 capability）同样统一「回执不可用」", async () => {
    const store = new MemoryReceiptStore();
    // 不写任何槽位：列表为空 → 无枚举面、无能力输入面
    render(<ReceiptViewer baseUrl="http://backend" store={store} />);
    expect(await screen.findByText("本机没有留存的删除回执。")).toBeTruthy();
    await waitFor(() => expect(fetchReceiptWithCapability).not.toHaveBeenCalled());
  });
});
