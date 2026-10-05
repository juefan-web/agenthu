import { describe, expect, it } from "vitest";
import { createEventQueue, LocalEventQueue } from "./queue";
import { queueCorruptKey, queueKey, UNOWNED_OWNER } from "./owner";

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
    data.setItem(queueKey(UNOWNED_OWNER), JSON.stringify({ events: [event], cursor: 42 }));

    const queue = new LocalEventQueue(data);

    expect(await queue.list()).toEqual([event]);
    expect(await queue.getCursor()).toBeNull();
    expect(data.getItem(queueCorruptKey(UNOWNED_OWNER))).toContain("sync cursor failed schema validation");
  });

  it("quarantines a valid JSON payload with the wrong top-level shape", async () => {
    const data = storage();
    data.setItem(queueKey(UNOWNED_OWNER), JSON.stringify([event]));

    const queue = new LocalEventQueue(data);

    expect(await queue.list()).toEqual([]);
    expect(data.getItem(queueCorruptKey(UNOWNED_OWNER))).toContain("queue payload is not an object");
  });

  it("isolates legacy unowned keys instead of attributing them to the next owner", async () => {
    const data = storage();
    data.setItem("agenthu.event-queue", JSON.stringify({ events: [event], cursor: "legacy" }));

    const ownerQueue = new LocalEventQueue({ storage: data, resolveOwner: () => "owner-a" });

    // 新 owner 看不到历史键上的数据；legacy 数据只在 unowned 命名空间
    expect(await ownerQueue.list()).toEqual([]);
    expect(await ownerQueue.getCursor()).toBeNull();
    expect(data.getItem("agenthu.event-queue")).toBeNull();
    expect(await ownerQueue.countUnowned()).toBe(1);
    expect(data.getItem(queueKey(UNOWNED_OWNER))).toContain("legacy");
  });
});

describe("owner namespaces (P0-2 / D-036)", () => {
  it("isolates events, cursors, and corrupt backups per owner on one storage", async () => {
    const data = storage();
    const a = new LocalEventQueue({ storage: data, resolveOwner: () => "owner-a" });
    const b = new LocalEventQueue({ storage: data, resolveOwner: () => "owner-b" });

    const sameUpstream = { ...event, client_event_id: "same-upstream" };
    await a.add([sameUpstream as never]);
    await b.add([sameUpstream as never]); // 同 client_event_id 两 owner 都保留
    expect(await a.list()).toHaveLength(1);
    expect(await b.list()).toHaveLength(1);

    await a.setCursor("cursor-a");
    await b.setCursor("cursor-b");
    expect(await a.getCursor()).toBe("cursor-a");
    expect(await b.getCursor()).toBe("cursor-b");

    // 清 a 不动 b（「本地删除不清另一账号」）
    await a.remove(["same-upstream"]);
    await a.setCursor(null);
    expect(await a.list()).toEqual([]);
    expect(await b.list()).toHaveLength(1);
    expect(await b.getCursor()).toBe("cursor-b");

    // 损坏隔离按 owner 落键，互不覆盖
    data.setItem(queueKey("owner-a"), "{{corrupt");
    const aReloaded = new LocalEventQueue({ storage: data, resolveOwner: () => "owner-a" });
    expect(await aReloaded.list()).toEqual([]);
    expect(data.getItem(queueCorruptKey("owner-a"))).toContain("not valid JSON");
    expect(data.getItem(queueCorruptKey("owner-b"))).toBeNull();
  });

  it("treats a null owner as the unowned namespace (pre-login collection)", async () => {
    const data = storage();
    const anonymous = new LocalEventQueue({ storage: data, resolveOwner: () => null });

    await anonymous.add([event as never]);
    expect(await anonymous.list()).toHaveLength(1);
    expect(data.getItem(queueKey(UNOWNED_OWNER))).toContain(event.client_event_id);
  });

  it("adopts and discards unowned data only through explicit decisions", async () => {
    const data = storage();
    let owner: string | null = null;
    const queue = new LocalEventQueue({ storage: data, resolveOwner: () => owner });

    await queue.add([event as never]); // 未登录 → unowned
    expect(await queue.countUnowned()).toBe(1);

    owner = "owner-a";
    await queue.add([{ ...event, client_event_id: "event-2" } as never]);
    expect(await queue.list()).toHaveLength(1); // 只见自己的

    const moved = await queue.adoptUnowned("owner-a");
    expect(moved).toBe(1);
    expect(await queue.countUnowned()).toBe(0);
    expect(await queue.list()).toHaveLength(2);
    expect(data.getItem(queueKey(UNOWNED_OWNER))).toBeNull();

    // discard：显式丢弃后无主与目标都不受影响
    owner = null;
    await queue.add([{ ...event, client_event_id: "orphan" } as never]);
    const removed = await queue.discardUnowned();
    expect(removed).toBe(1);
    expect(await queue.countUnowned()).toBe(0);
    owner = "owner-a";
    expect(await queue.list()).toHaveLength(2);
  });

  it("keeps the target owner's cursor when adopting unowned state", async () => {
    const data = storage();
    let owner: string | null = null;
    const queue = new LocalEventQueue({ storage: data, resolveOwner: () => owner });

    await queue.add([event as never]);
    await queue.setCursor("unowned-cursor");

    owner = "owner-a";
    await queue.setCursor("cursor-a");
    await queue.adoptUnowned("owner-a");
    expect(await queue.getCursor()).toBe("cursor-a"); // 目标优先

    owner = "owner-b"; // 空 cursor 的目标接收无主 cursor
    await queue.add([{ ...event, client_event_id: "event-9" } as never]);
    await queue.discardUnowned();
    owner = null;
    await queue.add([{ ...event, client_event_id: "event-10" } as never]);
    await queue.setCursor("unowned-cursor-2");
    owner = "owner-b";
    await queue.adoptUnowned("owner-b");
    expect(await queue.getCursor()).toBe("unowned-cursor-2");
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
