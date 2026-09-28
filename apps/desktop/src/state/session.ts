import { create } from "zustand";

export type SessionState = "idle" | "need-2fa" | "ready" | "error";

interface SessionStore {
  status: SessionState;
  username: string | null;
  message: string | null;
  methods: string[];
  codeSent: boolean;
  selectedMethod: string;
  notice: string | null;
  setTwoFactor: (methods: string[], codeSent: boolean, selectedMethod?: string, notice?: string | null) => void;
  setStatus: (status: SessionState, username?: string | null, message?: string | null) => void;
  reset: () => void;
}

export const useSessionStore = create<SessionStore>((set) => ({
  status: "idle",
  username: null,
  message: null,
  methods: [],
  codeSent: false,
  selectedMethod: "",
  notice: null,
  setTwoFactor: (methods, codeSent, selectedMethod = "", notice = null) => set({ methods, codeSent, selectedMethod, notice }),
  setStatus: (status, username = null, message = null) => set({ status, username, message }),
  reset: () => set({ status: "idle", username: null, message: null, methods: [], codeSent: false, selectedMethod: "", notice: null }),
}));
