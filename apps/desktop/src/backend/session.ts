import type { User } from "@agenthu/contracts";
import { useBackendSessionStore } from "../state/backendSession";
import { BackendAuthError, BackendClient } from "./client";
import { createTokenStore, type StoredToken, type TokenStore } from "./tokenStore";

export interface BackendSessionOptions {
  baseUrl: string;
  store?: TokenStore;
  fetcher?: typeof fetch;
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

type SessionSnapshot = {
  status: ReturnType<typeof useBackendSessionStore.getState>["status"];
  email: string | null;
  displayName: string | null;
  message: string | null;
  expiresAt: string | null;
};

/**
 * Owns the Backend Bearer JWT independently from the campus session. The
 * in-memory token keeps request signing synchronous; the store persists it for
 * restart recovery. Session mutations are serialized so an old request cannot
 * race a replacement login or logout.
 */
export function createBackendSession(options: BackendSessionOptions): BackendSession {
  const store = options.store ?? createTokenStore();
  const now = options.now ?? (() => Date.now());
  let current: StoredToken | null = null;
  let validatingToken: string | null = null;
  let operationTail: Promise<void> = Promise.resolve();

  const state = () => useBackendSessionStore.getState();

  function snapshotState(): SessionSnapshot {
    const currentState = state();
    return {
      status: currentState.status,
      email: currentState.email,
      displayName: currentState.displayName,
      message: currentState.message,
      expiresAt: currentState.expiresAt,
    };
  }

  function restoreState(snapshot: SessionSnapshot): void {
    state().setState(snapshot);
  }

  function storageError(error: unknown): string {
    return error instanceof Error
      ? `Backend 会话存储失败：${error.message}`
      : `Backend 会话存储失败：${String(error)}`;
  }

  function enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const next = operationTail.then(() => operation());
    operationTail = next.then(() => undefined, () => undefined);
    return next;
  }

  const client = new BackendClient({
    baseUrl: options.baseUrl,
    fetcher: options.fetcher,
    getToken: () => current?.access_token ?? null,
    onUnauthorized: (token) => {
      // Login validation handles its own rollback. The callback runs while
      // client.me() is still inside the queued login operation.
      if (validatingToken === token) return;

      // This is deliberately queued: a 401 may arrive just before a new
      // login, and an unawaited clear could otherwise delete the new token.
      void enqueue(async () => {
        if (current?.access_token !== token) return;
        current = null;
        state().setState({ status: "error", message: BACKEND_SESSION_EXPIRED });
        try {
          await store.clear();
        } catch (error) {
          state().setState({ status: "error", message: storageError(error) });
        }
      }).catch(() => undefined);
    },
  });

  function expired(token: StoredToken): boolean {
    return Date.parse(token.expires_at) <= now();
  }

  function markReady(token: StoredToken, user: User): void {
    current = token;
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

    restore(): Promise<void> {
      return enqueue(async () => {
        let stored: StoredToken | null;
        try {
          stored = await store.read();
        } catch (error) {
          current = null;
          state().setState({ status: "error", message: storageError(error) });
          return;
        }
        if (!stored || expired(stored)) {
          current = null;
          if (stored) {
            try {
              await store.clear();
            } catch (error) {
              current = null;
              state().setState({ status: "error", message: storageError(error) });
              return;
            }
          }
          state().reset();
          return;
        }
        current = stored;
        try {
          markReady(stored, await client.me());
        } catch (error) {
          if (!(error instanceof BackendAuthError)) {
            // Network and server failures do not prove that the credential is
            // invalid. Keep it available for a later retry and preserve it in
            // the store.
            state().setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
            return;
          }
          current = null;
          try {
            await store.clear();
          } catch (clearError) {
            state().setState({ status: "error", message: storageError(clearError) });
            return;
          }
          state().reset();
        }
      });
    },

    login(email: string, password: string): Promise<void> {
      return enqueue(async () => {
        const token = await client.login(email, password);
        const stored: StoredToken = {
          access_token: token.access_token,
          expires_at: new Date(now() + token.expires_in * 1_000).toISOString(),
        };
        const previous = current;
        const previousState = snapshotState();
        current = stored;
        validatingToken = stored.access_token;
        let user: User;
        try {
          user = await client.me();
        } catch (error) {
          current = previous;
          restoreState(previousState);
          throw error;
        } finally {
          validatingToken = null;
        }

        try {
          await store.write(stored);
        } catch (error) {
          current = previous;
          restoreState(previousState);
          try {
            if (previous) await store.write(previous);
            else await store.clear();
          } catch (restoreError) {
            state().setState({ status: "error", message: storageError(restoreError) });
          }
          throw error;
        }
        markReady(stored, user);
      });
    },

    register(email: string, password: string, displayName: string): Promise<void> {
      return enqueue(async () => {
        await client.register({ email, password, display_name: displayName });
      });
    },

    logout(): Promise<void> {
      return enqueue(async () => {
        current = null;
        state().reset();
        try {
          await store.clear();
        } catch (error) {
          state().setState({ status: "error", message: storageError(error) });
          throw error;
        }
      });
    },
  };
}
