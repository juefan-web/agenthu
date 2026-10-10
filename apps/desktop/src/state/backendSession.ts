import { create } from "zustand";

export type BackendSessionState = "idle" | "ready" | "error";

interface BackendSessionStore {
  status: BackendSessionState;
  email: string | null;
  displayName: string | null;
  /** P0-2（D-036）：本地 owner 命名空间的依据（与 origin 一起派生 ownerKey）。 */
  userId: string | null;
  message: string | null;
  expiresAt: string | null;
  /** 401 失效轮次（外审 #27）：单调递增、不随 reset 归零——App 据此整池清
   *  查询缓存（与显式 logout 的整池清空同语义）。 */
  invalidations: number;
  setState: (state: {
    status: BackendSessionState;
    email?: string | null;
    displayName?: string | null;
    userId?: string | null;
    message?: string | null;
    expiresAt?: string | null;
  }) => void;
  invalidate: () => void;
  reset: () => void;
}

const EMPTY = {
  status: "idle" as BackendSessionState,
  email: null,
  displayName: null,
  userId: null,
  message: null,
  expiresAt: null,
};

export const useBackendSessionStore = create<BackendSessionStore>((set) => ({
  ...EMPTY,
  invalidations: 0,
  setState: (state) => set({
    status: state.status,
    email: state.email ?? null,
    displayName: state.displayName ?? null,
    userId: state.userId ?? null,
    message: state.message ?? null,
    expiresAt: state.expiresAt ?? null,
  }),
  // 计数单调（不进 EMPTY/reset）：0→N 每次变化都是一次失效事件
  invalidate: () => set((state) => ({ invalidations: state.invalidations + 1 })),
  reset: () => set(EMPTY),
}));