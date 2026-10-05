import { describe, expect, it, vi } from "vitest";
import type { EventEnvelope } from "@agenthu/contracts";
import { BackendAuthError } from "../backend/client";
import { EventSyncCoordinator } from "./coordinator";
import type { EventQueue } from "./queue";
import { LocalEventQueue } from "./queue";

const event: EventEnvelope = {
  client_event_id: "event-1",
  type: "study.course.discovered",
  occurred_at: "2026-09-26T10:00:00+08:00",
  source: "onethu",
  data: { course_id: "c-1" },
  context: {},
  provenance: {
    connector: "onethu",
    connector_version: "2e3455fc235719b7f91fffaf5fe35e09220dda73",
    upstream_id: "course:c-1",
    semantic_version: "v1",
    fetched_at: "2026-09-26T10:00:00+08:00",
  },
};

function queue(): EventQueue {
  let events: EventEnvelope[] = [event];
  let cursor: string | null = null;
  return {
    add: async (next) => { events = [...events, ...next]; },
    list: async () => events,
    remove: async (ids) => { events = events.filter((item) => !ids.includes(item.client_event_id)); },
    getCursor: async () => cursor,
    setCursor: async (next) => { cursor = next; },
  };
}

describe("EventSyncCoordinator", () => {
  it("removes accepted, duplicate, and rejected events and returns rejection details", async () => {
    const q = queue();
    const backend = {
      probeHealth: async () => true,
      pushEvents: async () => ({
        accepted_event_ids: [],
        duplicate_event_ids: [],
        rejected: [{ client_event_id: "event-1", reason: "data.secret is not allowed" }],
        next_cursor: "cursor-1",
      }),
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q);
    const result = await coordinator.flush();
    expect(result).toEqual({
      sent: 0,
      duplicates: 0,
      rejected: 1,
      rejections: [{ client_event_id: "event-1", reason: "data.secret is not allowed" }],
      pending: 0,
    });
  });

  it("sends at most 500 events per batch", async () => {
    const events = Array.from({ length: 501 }, (_, index) => ({ ...event, client_event_id: `event-${index}` }));
    const q = queue();
    await q.remove([event.client_event_id]);
    await q.add(events);
    const sizes: number[] = [];
    const backend = {
      probeHealth: async () => true,
      pushEvents: async (request: { events: EventEnvelope[] }) => {
        sizes.push(request.events.length);
        return {
          accepted_event_ids: request.events.map((item) => item.client_event_id),
          duplicate_event_ids: [], rejected: [], next_cursor: null,
        };
      },
    } as never;
    const result = await new EventSyncCoordinator(backend, q).flush();
    expect(sizes).toEqual([500, 1]);
    expect(result).toEqual({ sent: 501, duplicates: 0, rejected: 0, rejections: [], pending: 0 });
  });

  it("removes a mixed batch and leaves no pending events", async () => {
    const q = queue();
    await q.remove([event.client_event_id]);
    await q.add([
      { ...event, client_event_id: "accepted" },
      { ...event, client_event_id: "duplicate" },
      { ...event, client_event_id: "rejected" },
    ]);
    const backend = {
      probeHealth: async () => true,
      pushEvents: async () => ({
        accepted_event_ids: ["accepted"],
        duplicate_event_ids: ["duplicate"],
        rejected: [{ client_event_id: "rejected", reason: "payload too large" }],
        next_cursor: "cursor-2",
      }),
    } as never;

    const result = await new EventSyncCoordinator(backend, q).flush();

    expect(result.pending).toBe(0);
    expect(result.rejected).toBe(1);
    expect(result.rejections[0]?.reason).toBe("payload too large");
  });

  it("deduplicates repeated IDs within one local add", async () => {
    const storage = new Map<string, string>();
    const fakeStorage = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value); },
    } as Storage;
    const q = new LocalEventQueue(fakeStorage);
    await q.add([event, event]);
    expect(await q.list()).toHaveLength(1);
  });

  it("shares one in-flight flush across concurrent triggers", async () => {
    const q = queue();
    let releases = 0;
    const release: Promise<void> = new Promise((resolve) => { setTimeout(resolve, 10); });
    let calls = 0;
    const backend = {
      probeHealth: async () => true,
      pushEvents: async (request: { events: EventEnvelope[] }) => {
        calls += 1;
        await release;
        releases += 1;
        return {
          accepted_event_ids: request.events.map((item) => item.client_event_id),
          duplicate_event_ids: [], rejected: [], next_cursor: null,
        };
      },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q);
    const [first, second, third] = await Promise.all([coordinator.flush(), coordinator.flush(), coordinator.flush()]);
    // 三个并发入口（采集/online/手动）只产生一次真实上传，结果共享
    expect(calls).toBe(1);
    expect(releases).toBe(1);
    expect(second).toEqual(first);
    expect(third).toEqual(first);
    expect(first.sent).toBe(1);
  });

  it("stops after the per-batch retry cap and leaves the batch queued", async () => {
    const q = queue();
    let calls = 0;
    const backend = {
      probeHealth: async () => true,
      pushEvents: async () => {
        calls += 1;
        throw new Error("connection refused");
      },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q, { maxBatchAttempts: 3, retryBaseDelayMs: 1 });
    await expect(coordinator.flush()).rejects.toThrow("已重试 3 次");
    expect(calls).toBe(3);
    // 超限停发：事件保留，等待下一次触发续传
    expect(await q.list()).toHaveLength(1);
  });

  it("retries with exponential backoff between attempts", async () => {
    const q = queue();
    const delays: number[] = [];
    let calls = 0;
    const backend = {
      probeHealth: async () => true,
      pushEvents: async () => {
        calls += 1;
        if (calls < 3) throw new Error("temporarily unavailable");
        return { accepted_event_ids: ["event-1"], duplicate_event_ids: [], rejected: [], next_cursor: null };
      },
    } as never;
    const originalDelay = setTimeout;
    const coordinator = new EventSyncCoordinator(backend, q, { maxBatchAttempts: 3, retryBaseDelayMs: 5 });
    const timers: number[] = [];
    vi.stubGlobal("setTimeout", (fn: () => void, ms?: number) => {
      if (ms !== undefined && ms >= 5) delays.push(ms);
      return originalDelay(fn, ms);
    });
    try {
      await coordinator.flush();
    } finally {
      vi.unstubAllGlobals();
    }
    expect(calls).toBe(3);
    expect(delays).toEqual([5, 10]);
  });

  it("does not retry a batch rejected for authentication", async () => {
    const q = queue();
    let calls = 0;
    const backend = {
      probeHealth: async () => true,
      pushEvents: async () => {
        calls += 1;
        throw new BackendAuthError();
      },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q, { maxBatchAttempts: 3, retryBaseDelayMs: 1 });
    await expect(coordinator.flush()).rejects.toThrow(BackendAuthError);
    expect(calls).toBe(1);
  });

  it("resumes from the failed batch on the next flush", async () => {
    const q = queue();
    await q.remove([event.client_event_id]);
    await q.add([
      { ...event, client_event_id: "first-batch" },
      { ...event, client_event_id: "second-batch" },
    ]);
    let failing = true;
    const sent: string[][] = [];
    const backend = {
      probeHealth: async () => true,
      pushEvents: async (request: { events: EventEnvelope[] }) => {
        const ids = request.events.map((item) => item.client_event_id);
        sent.push(ids);
        if (ids[0] === "second-batch" && failing) throw new Error("upstream 503");
        return { accepted_event_ids: ids, duplicate_event_ids: [], rejected: [], next_cursor: null };
      },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q, { batchSize: 1, maxBatchAttempts: 2, retryBaseDelayMs: 1 });
    // 第二批失败：第一批已 remove（断点续传的进度已落账）
    await expect(coordinator.flush()).rejects.toThrow("upstream 503");
    expect(await q.list()).toEqual([{ ...event, client_event_id: "second-batch" }]);
    // 下一次 flush 只补发失败批次（首轮内该批已按上限尝试 2 次）
    failing = false;
    const result = await coordinator.flush();
    expect(result.sent).toBe(1);
    expect(sent).toEqual([["first-batch"], ["second-batch"], ["second-batch"], ["second-batch"]]);
    expect(await q.list()).toHaveLength(0);
  });

  it("fails fast without the retry ladder when the health probe says unreachable (D1)", async () => {
    const q = queue();
    let attempts = 0;
    const backend = {
      probeHealth: async () => false,
      pushEvents: async () => {
        attempts += 1;
        throw new Error("connection refused");
      },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q, { maxBatchAttempts: 3, retryBaseDelayMs: 1 });
    await expect(coordinator.flush()).rejects.toThrow("Backend 不可达（健康探测失败）");
    // 首攻快速失败后探测即放弃：不再进入重试梯（1 次尝试而非 3 次）
    expect(attempts).toBe(1);
    // 事件保留待同步
    expect(await q.list()).toHaveLength(1);
  });

  it("treats a probe timeout as unreachable", async () => {
    const q = queue();
    const backend = {
      probeHealth: async (timeoutMs: number) => {
        await new Promise((resolve) => setTimeout(resolve, timeoutMs + 5));
        return false;
      },
      pushEvents: async () => { throw new Error("connection refused"); },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q, { healthProbeTimeoutMs: 10 });
    const startedAt = Date.now();
    await expect(coordinator.flush()).rejects.toThrow("Backend 不可达");
    expect(Date.now() - startedAt).toBeLessThan(1_000);
  });

  it("still retries a healthy backend on transient failures (probe gates only reachability)", async () => {
    const q = queue();
    let attempts = 0;
    const backend = {
      probeHealth: async () => true,
      pushEvents: async () => {
        attempts += 1;
        if (attempts < 2) throw new Error("upstream 503");
        return { accepted_event_ids: [event.client_event_id], duplicate_event_ids: [], rejected: [], next_cursor: null };
      },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q, { retryBaseDelayMs: 1 });
    const result = await coordinator.flush();
    expect(result.sent).toBe(1);
    expect(attempts).toBe(2);
  });
});

describe("owner switch guard (P0-2 / D-036)", () => {
  it("does not push the unowned queue before login", async () => {
    const q = queue(); // 预置 event-1（未登录 → unowned）
    let calls = 0;
    const backend = {
      probeHealth: async () => true,
      pushEvents: async () => {
        calls += 1;
        return { accepted_event_ids: [], duplicate_event_ids: [], rejected: [], next_cursor: null };
      },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q, { resolveOwner: () => null });
    const result = await coordinator.flush();
    expect(calls).toBe(0);
    expect(result).toEqual({ sent: 0, duplicates: 0, rejected: 0, rejections: [], pending: 1 });
  });

  it("aborts the flush when the account switches mid-flight", async () => {
    const q = queue();
    let owner: string | null = "owner-a";
    const backend = {
      probeHealth: async () => true,
      pushEvents: async () => {
        // 服务端响应返回的瞬间完成换号：结算若继续会写进新 owner 命名空间
        owner = "owner-b";
        return {
          accepted_event_ids: [event.client_event_id],
          duplicate_event_ids: [],
          rejected: [],
          next_cursor: "cursor-1",
        };
      },
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q, { resolveOwner: () => owner });
    await expect(coordinator.flush()).rejects.toThrow("账号已切换");
    // 结算未落库：事件与 cursor 都保留给原 owner（服务端幂等兜底重发）
    expect(await q.list()).toHaveLength(1);
    expect(await q.getCursor()).toBeNull();
  });
});
