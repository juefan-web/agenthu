import { describe, expect, it } from "vitest";
import { LocalFocusDraftStore, type FocusDraft } from "./draft";

const draft: FocusDraft = {
  session: {
    id: "focus-1",
    task_id: "task-1",
    started_at: "2026-09-26T10:00:00+08:00",
    ended_at: null,
    actual_minutes: null,
    status: "paused",
    deviation_note: null,
  },
  note: "需要继续核对习题",
};

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: (key) => { values.delete(key); },
  } as Storage;
}

describe("LocalFocusDraftStore", () => {
  it("restores a validated unfinished session and clears it on completion", async () => {
    const store = new LocalFocusDraftStore(storage());
    await store.write(draft);
    expect(await store.read()).toEqual(draft);
    await store.write(null);
    expect(await store.read()).toBeNull();
  });

  it("does not restore malformed persisted data", async () => {
    const data = storage();
    data.setItem("agenthu.focus-draft", JSON.stringify({ ...draft, session: { ...draft.session, status: "unknown" } }));
    expect(await new LocalFocusDraftStore(data).read()).toBeNull();
  });
});
