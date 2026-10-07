import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { DataOperationOut } from "@agenthu/contracts";
import { POLL_INITIAL_DELAY_MS, POLL_MAX_DELAY_MS, POLL_TOTAL_CAP_MS, useOperationPoll } from "./useOperationPoll";

function makeOperation(status: DataOperationOut["status"]): DataOperationOut {
  return {
    id: "019bbbbb-0000-7000-8000-000000000001",
    kind: "DELETION",
    target: null,
    status,
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
  };
}

describe("useOperationPoll（B 稿 §2 冻结参数）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("挂载即新鲜拉取；按 5s→10s→20s→30s 梯子轮询；终态停", async () => {
    const fetchOperation = vi.fn()
      .mockResolvedValueOnce(makeOperation("QUEUED"))
      .mockResolvedValueOnce(makeOperation("RUNNING"))
      .mockResolvedValueOnce(makeOperation("RUNNING"))
      .mockResolvedValueOnce(makeOperation("COMPLETED"));
    const { result } = renderHook(() => useOperationPoll({ operationId: "op-1", fetchOperation }));

    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(fetchOperation).toHaveBeenCalledTimes(1);
    expect(result.current.operation?.status).toBe("QUEUED");

    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INITIAL_DELAY_MS); });
    expect(fetchOperation).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(fetchOperation).toHaveBeenCalledTimes(3);

    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(fetchOperation).toHaveBeenCalledTimes(4);
    expect(result.current.operation?.status).toBe("COMPLETED");

    // 终态后不再排程
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MAX_DELAY_MS * 3); });
    expect(fetchOperation).toHaveBeenCalledTimes(4);
  });

  it("后台暂停（visibilitychange hidden 清定时器），回前台立即新鲜拉取", async () => {
    const fetchOperation = vi.fn().mockResolvedValue(makeOperation("RUNNING"));
    renderHook(() => useOperationPoll({ operationId: "op-1", fetchOperation }));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(fetchOperation).toHaveBeenCalledTimes(1);

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    // 隐藏期间推进两个梯级：不再发请求
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MAX_DELAY_MS * 2); });
    expect(fetchOperation).toHaveBeenCalledTimes(1);

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchOperation).toHaveBeenCalledTimes(2);
  });

  it("30 分钟前台上限：停自动轮询并置 capped", async () => {
    const fetchOperation = vi.fn().mockResolvedValue(makeOperation("RUNNING"));
    const { result } = renderHook(() => useOperationPoll({ operationId: "op-1", fetchOperation }));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    // 30s 步进推进（阶梯 5→10→20→30s；链式排程需要逐段推进），70 步
    // 内必跨 30 分钟上限
    for (let step = 0; step < 70 && !result.current.capped; step += 1) {
      await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MAX_DELAY_MS); });
    }
    expect(result.current.capped).toBe(true);
    const callsAtCap = fetchOperation.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MAX_DELAY_MS * 5); });
    expect(fetchOperation.mock.calls.length).toBe(callsAtCap);

    // 手动刷新仍可（GET only）
    await act(async () => { await result.current.refresh(); });
    expect(fetchOperation.mock.calls.length).toBe(callsAtCap + 1);
  });
});
