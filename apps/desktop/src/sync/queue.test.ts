import { describe, expect, it } from "vitest";
import { CORRUPT_QUEUE_BACKUP_KEY, createEventQueue, LocalEventQueue } from "./queue";

const event = {
  client_event_id: "event-1",
  type: "study.assignment.discovered",
  occurred_at: "2026-09-27T10:00:00+08:00",
  source: "fixture",
  data: { title: "Homework" },
  context: {},
  provenance: {
    connector: "fixture",
    connector_version: "1",
    upstream_id: "hw-1",
    semantic_version: "v1",
    fetched_at: "2026-09-27T10:00:01+08:00",
  },
} as const;

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: (key) => { values.delete(key); },
  } as Storage;
}

describe("LocalEventQueue recovery", () => {
  it("preserves valid events when only the cursor is malformed", async () => {
    const data = storage();
    data.setItem("agenthu.event-queue", JSON.stringify({ events: [event], cursor: 42 }));

    const queue = new LocalEventQueue(data);

    expect(await queue.list()).toEqual([event]);
    expect(await queue.getCursor()).toBeNull();
    expect(data.getItem(CORRUPT_QUEUE_BACKUP_KEY)).toContain("sync cursor failed schema validation");
  });

  it("quarantines a valid JSON payload with the wrong top-level shape", async () => {
    const data = storage();
    data.setItem("agenthu.event-queue", JSON.stringify([event]));

    const queue = new LocalEventQueue(data);

    expect(await queue.list()).toEqual([]);
    expect(data.getItem(CORRUPT_QUEUE_BACKUP_KEY)).toContain("queue payload is not an object");
  });
});

describe("queue boundary safety (B-3.2)", () => {
  it("rejects sensitive fields on the direct enqueue path without a configured Backend", async () => {
    // jsdom 环境走 LocalEventQueue 分支，Safety 包装在 createEventQueue 边界
    const queue = createEventQueue();
    const unsafe = {
      ...event,
      data: { ...event.data, password: "should-never-sync" },
    };
    await expect(queue.add([unsafe as never])).rejects.toThrow("敏感字段不得进入 Event");
    // 抛出前不落任何事件
    expect(await queue.list()).toEqual([]);
  });

  it("accepts normal events through the same boundary", async () => {
    const queue = createEventQueue();
    await queue.add([event as never]);
    expect(await queue.list()).toHaveLength(1);
  });
});
