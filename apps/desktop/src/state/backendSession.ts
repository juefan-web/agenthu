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
  setState: (state: {
    status: BackendSessionState;
    email?: string | null;
    displayName?: string | null;
    userId?: string | null;
    message?: string | null;
    expiresAt?: string | null;
  }) => void;
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
  setState: (state) => set({
    status: state.status,
    email: state.email ?? null,
    displayName: state.displayName ?? null,
    userId: state.userId ?? null,
    message: state.message ?? null,
    expiresAt: state.expiresAt ?? null,
  }),
  reset: () => set(EMPTY),
}));