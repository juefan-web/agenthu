import { describe, expect, it } from "vitest";
import { assertSafeEvent, EventEnvelopeSchema, eventDedupeKey } from "./index";

const event = {
  client_event_id: "onethu:homework:hw-1:v1",
  type: "study.assignment.discovered",
  occurred_at: "2026-09-26T10:00:00+08:00",
  source: "onethu",
  data: { title: "HW1" },
  context: {},
  provenance: {
    connector: "onethu",
    connector_version: "2e3455f",
    upstream_id: "hw-1",
    semantic_version: "v1",
    fetched_at: "2026-09-26T10:00:01+08:00",
  },
};

describe("event contract", () => {
  it("validates and derives a stable dedupe key", () => {
    const parsed = EventEnvelopeSchema.parse(event);
    expect(eventDedupeKey(parsed)).toBe("onethu:hw-1:v1");
  });

  it("does not collide when source or upstream_id contains a colon", () => {
    const base = EventEnvelopeSchema.parse(event);
    const first = eventDedupeKey({
      ...base,
      source: "a:b",
      provenance: { ...base.provenance, upstream_id: "c" },
    });
    const second = eventDedupeKey({
      ...base,
      source: "a",
      provenance: { ...base.provenance, upstream_id: "b:c" },
    });
    expect(first).not.toBe(second);
  });

  it("rejects credentials before enqueueing", () => {
    const parsed = EventEnvelopeSchema.parse({
      ...event,
      data: { password: "secret" },
    });
    expect(() => assertSafeEvent(parsed)).toThrow("敏感字段");
  });
});
