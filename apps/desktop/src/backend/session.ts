import type { User } from "@agenthu/contracts";
import { useBackendSessionStore } from "../state/backendSession";
import { BackendAuthError, BackendClient } from "./client";
import { createTokenStore, type StoredToken, type TokenStore } from "./tokenStore";

export interface BackendSessionOptions {
  baseUrl: string;
  store?: TokenStore;
  fetcher?: typeof fetch;
  now?: () => number;
  /** P0-2（D-036）：身份落定/清除时回调（login/restore 成功 → owner；
   *  logout/过期/失效 → null）。services 层据此切换本地存储的 owner
   *  命名空间；回调在会话串行队列内 await，切号先于任何后续操作完成。 */
  onOwnerChange?: (owner: { origin: string; userId: string } | null) => void | Promise<void>;
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
  userId: string | null;
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
  const canonicalOrigin = new URL(options.baseUrl).origin;
  let current: StoredToken | null = null;
  let currentUserId: string | null = null;
  let validatingToken: string | null = null;
  let operationTail: Promise<void> = Promise.resolve();

  const state = () => useBackendSessionStore.getState();

  function snapshotState(): SessionSnapshot {
    const currentState = state();
    return {
      status: currentState.status,
      email: currentState.email,
      displayName: currentState.displayName,
      userId: currentState.userId,
      message: currentState.message,
      expiresAt: currentState.expiresAt,
    };
  }

  function restoreState(snapshot: SessionSnapshot): void {
    state().setState(snapshot);
  }

  /** owner 通知在会话串行队列内执行；同一 userId 不重复通知。 */
  async function setOwner(userId: string | null): Promise<void> {
    if (userId === currentUserId) return;
    currentUserId = userId;
    await options.onOwnerChange?.(userId ? { origin: canonicalOrigin, userId } : null);
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
        await setOwner(null);
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

  async function markReady(token: StoredToken, user: User): Promise<void> {
    current = token;
    state().setState({
      status: "ready",
      email: user.email,
      displayName: user.display_name,
      userId: user.id,
      expiresAt: token.expires_at,
      message: null,
    });
    await setOwner(user.id);
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
          await setOwner(null);
          return;
        }
        current = stored;
        try {
          await markReady(stored, await client.me());
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
          await setOwner(null);
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
          await setOwner(previousState.userId);
          throw error;
        } finally {
          validatingToken = null;
        }

        try {
          await store.write(stored);
        } catch (error) {
          current = previous;
          restoreState(previousState);
          await setOwner(previousState.userId);
          try {
            if (previous) await store.write(previous);
            else await store.clear();
          } catch (restoreError) {
            state().setState({ status: "error", message: storageError(restoreError) });
          }
          throw error;
        }
        await markReady(stored, user);
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
        await setOwner(null);
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
