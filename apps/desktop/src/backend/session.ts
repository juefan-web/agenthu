import type { User } from "@agenthu/contracts";
import { useBackendSessionStore } from "../state/backendSession";
import { BackendAuthError, BackendClient } from "./client";
import { createTokenStore, type StoredToken, type TokenStore } from "./tokenStore";

export interface BackendSessionOptions {
  baseUrl: string;
  store?: TokenStore;
  now?: () => number;
}

export interface BackendSession {
  client: BackendClient;
  token(): string | null;
  restore(): Promise<void>;
  login(email: string, password: string): Promise<void>;
  register(email: string, password: string, displayName: string): Promise<void>;
  logout(): Promise<void>;
}

export const BACKEND_SESSION_EXPIRED = "Backend 登录已过期，请重新登录";

/**
 * Owns the Backend Bearer JWT independently from the campus session. The
 * in-memory token keeps request signing synchronous; the store persists it for
 * restart recovery. A 401 from any request drops the session immediately.
 */
export function createBackendSession(options: BackendSessionOptions): BackendSession {
  const store = options.store ?? createTokenStore();
  const now = options.now ?? (() => Date.now());
  let current: StoredToken | null = null;

  const state = () => useBackendSessionStore.getState();

  const client = new BackendClient({
    baseUrl: options.baseUrl,
    getToken: () => current?.access_token ?? null,
    onUnauthorized: () => {
      current = null;
      void store.clear();
      state().setState({ status: "error", message: BACKEND_SESSION_EXPIRED });
    },
  });

  function expired(token: StoredToken): boolean {
    return Date.parse(token.expires_at) <= now();
  }

  async function adopt(token: StoredToken, user: User): Promise<void> {
    current = token;
    await store.write(token);
    state().setState({
      status: "ready",
      email: user.email,
      displayName: user.display_name,
      expiresAt: token.expires_at,
      message: null,
    });
  }

  return {
    client,
    token: () => current?.access_token ?? null,

    async restore(): Promise<void> {
      const stored = await store.read();
      if (!stored || expired(stored)) {
        if (stored) await store.clear();
        state().reset();
        return;
      }
      current = stored;
      try {
        await adopt(stored, await client.me());
      } catch (error) {
        current = null;
        await store.clear();
        if (error instanceof BackendAuthError) state().reset();
        else state().setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
      }
    },

    async login(email: string, password: string): Promise<void> {
      const token = await client.login(email, password);
      const stored: StoredToken = {
        access_token: token.access_token,
        expires_at: new Date(now() + token.expires_in * 1_000).toISOString(),
      };
      const previous = current;
      current = stored;
      try {
        await adopt(stored, await client.me());
      } catch (error) {
        current = previous;
        throw error;
      }
    },

    async register(email: string, password: string, displayName: string): Promise<void> {
      await client.register({ email, password, display_name: displayName });
    },

    async logout(): Promise<void> {
      current = null;
      await store.clear();
      state().reset();
    },
  };
}