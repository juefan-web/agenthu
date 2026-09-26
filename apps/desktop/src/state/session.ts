import { create } from "zustand";

export type SessionState = "idle" | "need-2fa" | "ready" | "error";

interface SessionStore {
  status: SessionState;
  username: string | null;
  message: string | null;
  setStatus: (status: SessionState, username?: string | null, message?: string | null) => void;
  reset: () => void;
}

export const useSessionStore = create<SessionStore>((set) => ({
  status: "idle",
  username: null,
  message: null,
  setStatus: (status, username = null, message = null) => set({ status, username, message }),
  reset: () => set({ status: "idle", username: null, message: null }),
}));
