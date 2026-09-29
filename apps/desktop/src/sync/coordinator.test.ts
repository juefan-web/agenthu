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
  it("removes accepted, duplicate, and rejected events and returns rejection details", async () => {
    const q = queue();
    const backend = {
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
});
