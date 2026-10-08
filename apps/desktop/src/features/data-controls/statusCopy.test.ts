import { describe, expect, it } from "vitest";
import type { DataEffect, DataOperationOut } from "@agenthu/contracts";
import { effectSummaryLine, isTerminalStatus, knownErrorCopy, operationStatusLine, progressLine } from "./statusCopy";
import { nextPollDelayMs, POLL_INITIAL_DELAY_MS, POLL_MAX_DELAY_MS } from "./useOperationPoll";

function makeEffect(overrides: Partial<DataEffect>): DataEffect {
  return { resource_type: "events", delete_count: 0, redact_count: 0, recompute_count: 0, retain_count: 0, reason_code: "anchored_derivation", ...overrides };
}

function makeOperation(overrides: Partial<DataOperationOut>): DataOperationOut {
  return {
    id: "019aaaaa-0000-7000-8000-000000000001",
    kind: "DELETION",
    target: null,
    status: "QUEUED",
    phase: null,
    version: 1,
    data_generation: 1,
    created_at: "2026-10-07T10:00:00+08:00",
    updated_at: "2026-10-07T10:00:00+08:00",
    next_retry_at: null,
    expires_at: null,
    progress: { processed: 0, total: null, outstanding_count: 0 },
    error: null,
    receipt_id: null,
    receipt_capability: null,
    ...overrides,
  };
}

describe("B 稿 §2 状态文案表", () => {
  it("preview 行只加总服务端计数，不推断级联", () => {
    const line = effectSummaryLine([
      makeEffect({ resource_type: "events", delete_count: 3, redact_count: 1 }),
      makeEffect({ resource_type: "tasks", delete_count: 2, recompute_count: 4 }),
    ]);
    expect(line).toBe("将删除 5 项、清除 1 项派生内容、重算 4 项；独立编辑内容按清单保留");
  });

  it("QUEUED/RUNNING 用服务端进度，无虚构百分比", () => {
    const operation = makeOperation({ status: "RUNNING", progress: { processed: 7, total: 12, outstanding_count: 5 } });
    expect(operationStatusLine(operation)).toBe("删除已提交，正在清理");
    expect(progressLine(operation)).toBe("已处理 7 项（共 12 项，剩余 5 项）");
  });

  it("RETRY_WAIT 显示重试时间与剩余数", () => {
    const operation = makeOperation({ status: "RETRY_WAIT", next_retry_at: "2026-10-07T10:05:00+08:00", progress: { processed: 1, total: null, outstanding_count: 2 } });
    expect(operationStatusLine(operation)).toContain("部分清理尚未完成");
    expect(operationStatusLine(operation)).toContain("剩余 2 项");
  });

  it("FAILED/COMPLETED/READY/EXPIRED 各按冻结文案", () => {
    expect(operationStatusLine(makeOperation({ status: "FAILED", error: { code: "x", message: "S3 不可用", retryable: true } }))).toContain("删除未完成");
    expect(operationStatusLine(makeOperation({ status: "COMPLETED" }))).toBe("服务端在线数据已清除");
    expect(operationStatusLine(makeOperation({ status: "READY", expires_at: "2026-10-08T10:00:00+08:00" }))).toMatch(/^可下载至/);
    expect(operationStatusLine(makeOperation({ status: "EXPIRED" }))).toBe("导出包已到期");
  });

  it("未知状态停危险操作并提示升级", () => {
    expect(operationStatusLine(makeOperation({ status: "WEIRD" as DataOperationOut["status"] }))).toContain("未知状态");
  });

  it("终态集合与 409 等已知错误码文案", () => {
    expect(isTerminalStatus("READY")).toBe(true);
    expect(isTerminalStatus("RETRY_WAIT")).toBe(false);
    expect(knownErrorCopy("deletion_in_progress")).toBe("已有删除正在进行");
    expect(knownErrorCopy("preview_expired")).toBe("数据已变化，请重新查看删除范围");
    expect(knownErrorCopy("something_else")).toBeNull();
  });
});

describe("poll 退避梯（5s→30s 封顶）", () => {
  it("梯子：5→10→20→30→30", () => {
    expect(nextPollDelayMs(POLL_INITIAL_DELAY_MS)).toBe(10_000);
    expect(nextPollDelayMs(10_000)).toBe(20_000);
    expect(nextPollDelayMs(20_000)).toBe(POLL_MAX_DELAY_MS);
    expect(nextPollDelayMs(POLL_MAX_DELAY_MS)).toBe(POLL_MAX_DELAY_MS);
  });
});
