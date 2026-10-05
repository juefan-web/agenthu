import { describe, expect, it } from "vitest";
import { LocalFocusDraftStore, type FocusDraft } from "./draft";
import { focusDraftKey, UNOWNED_OWNER } from "../sync/owner";

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
    data.setItem(focusDraftKey(UNOWNED_OWNER), JSON.stringify({ ...draft, session: { ...draft.session, status: "unknown" } }));
    expect(await new LocalFocusDraftStore(data).read()).toBeNull();
  });

  it("isolates drafts per owner and isolates the legacy key as unowned (P0-2)", async () => {
    const data = storage();
    data.setItem("agenthu.focus-draft", JSON.stringify(draft)); // P0-2 之前的历史草稿

    const a = new LocalFocusDraftStore({ storage: data, resolveOwner: () => "owner-a" });
    const b = new LocalFocusDraftStore({ storage: data, resolveOwner: () => "owner-b" });

    // 历史（无主）草稿对任何 owner 不可见，也不会被清除
    expect(await a.read()).toBeNull();
    expect(data.getItem(focusDraftKey(UNOWNED_OWNER))).toContain(draft.note);
    expect(data.getItem("agenthu.focus-draft")).toBeNull();

    await a.write(draft);
    expect(await a.read()).toEqual(draft);
    expect(await b.read()).toBeNull(); // 另一账号的草稿互不可见

    await a.write(null); // 清 a 不动 b 与无主
    expect(data.getItem(focusDraftKey(UNOWNED_OWNER))).toContain(draft.note);
  });
});
