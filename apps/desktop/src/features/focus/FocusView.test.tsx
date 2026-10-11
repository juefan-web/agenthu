import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { FocusDraftStore } from "../../focus/draft";
import { AppServicesContext, type AppServices } from "../../app/services";
import { FocusView } from "./FocusView";

/** 外审 #26 的钉子：专注草稿存储按 owner 命名空间（D-036），残留的是
 *  mount 时读入的组件态——App 以账号 key 重挂载后，新 mount 必须读当前
 *  owner 的草稿，而不是把前一账号的会话留在屏上。 */
function servicesWith(draft: FocusDraftStore): AppServices {
  // 视图只消费 focusDraft；其余槽位给空实现（整对象一次断言转换）
  return {
    buildTimeBackendUrl: "",
    backendUrl: "",
    backendSession: null,
    backend: null,
    queue: draft,
    focusDraft: draft,
    sync: null,
    receipts: null,
    resolveOwner: () => null,
  } as unknown as AppServices;
}

const sessionA = {
  id: "focus-a",
  task_id: "task-a",
  status: "running",
  started_at: "2026-10-10T09:00:00Z",
  deviation_note: null,
} as const;

function draftStore(reads: Array<{ session: typeof sessionA | null }>): FocusDraftStore {
  let call = 0;
  return {
    read: async () => {
      const item = reads[Math.min(call, reads.length - 1)];
      call += 1;
      return item ? { session: item.session, note: "" } : null;
    },
    write: vi.fn(async () => undefined),
    clear: vi.fn(async () => undefined),
    adoptUnownedDraft: vi.fn(async () => 0),
    discardUnownedDraft: vi.fn(async () => 0),
  } as unknown as FocusDraftStore;
}

describe("FocusView account-scoped view state (external #26)", () => {
  it("restores the previous account's draft on first mount, and a remount reads fresh state", async () => {
    // mount 1（账号 A 在场）：恢复 A 的进行中专注
    const store = draftStore([{ session: sessionA }]);
    const first = render(
      <AppServicesContext.Provider value={servicesWith(store)}>
        <FocusView key="user-a" tasks={[]} />
      </AppServicesContext.Provider>,
    );
    await waitFor(() => expect(screen.getByText("running")).toBeTruthy());
    // App 的换号路径 = key 变化重挂载（key="anonymous" 表示已登出）
    first.unmount();
    const loggedOut = draftStore([{ session: null }]);
    render(
      <AppServicesContext.Provider value={servicesWith(loggedOut)}>
        <FocusView key="anonymous" tasks={[]} />
      </AppServicesContext.Provider>,
    );
    await waitFor(() => expect(screen.getByText("未开始")).toBeTruthy());
    expect(screen.queryByText("running")).toBeNull();
  });
});
