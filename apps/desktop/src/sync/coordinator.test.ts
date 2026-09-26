import { describe, expect, it } from "vitest";
import type { EventEnvelope } from "@agenthu/contracts";
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
  it("removes accepted and duplicate events but retains rejected events", async () => {
    const q = queue();
    const backend = {
      pushEvents: async () => ({
        accepted_event_ids: ["event-1"],
        duplicate_event_ids: [],
        rejected: [],
        next_cursor: "cursor-1",
      }),
    } as never;
    const coordinator = new EventSyncCoordinator(backend, q);
    const result = await coordinator.flush();
    expect(result).toEqual({ sent: 1, duplicates: 0, rejected: 0, pending: 0 });
  });

  it("sends at most 500 events per batch", async () => {
    const events = Array.from({ length: 501 }, (_, index) => ({ ...event, client_event_id: `event-${index}` }));
    const q = queue();
    await q.remove([event.client_event_id]);
    await q.add(events);
    const sizes: number[] = [];
    const backend = {
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
    expect(result).toEqual({ sent: 501, duplicates: 0, rejected: 0, pending: 0 });
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
});
