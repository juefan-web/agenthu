import { describe, expect, it } from "vitest";
import { CORRUPT_QUEUE_BACKUP_KEY, LocalEventQueue } from "./queue";

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
