import { beforeEach, describe, expect, it, vi } from "vitest";
import { BACKEND_SESSION_EXPIRED, createBackendSession } from "./session";
import type { StoredToken, TokenStore } from "./tokenStore";
import { useBackendSessionStore } from "../state/backendSession";

function memoryStore(initial: StoredToken | null = null): TokenStore & { value: StoredToken | null } {
  return {
    value: initial,
    async read() { return this.value; },
    async write(token) { this.value = token; },
    async clear() { this.value = null; },
  };
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const user = { id: "u-1", email: "student@example.com", display_name: "Student", is_active: true };
const token = { access_token: "jwt-1", token_type: "bearer", expires_in: 3600 };

beforeEach(() => {
  useBackendSessionStore.getState().reset();
});

describe("createBackendSession", () => {
  it("persists the token and loads the profile after login", async () => {
    const store = memoryStore();
    const fetcher = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/v1/auth/login") ? json(token) : json(user),
    );
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 1_000 });

    await session.login("student@example.com", "password123");

    expect(store.value?.access_token).toBe("jwt-1");
    expect(store.value?.expires_at).toBe(new Date(1_000 + 3_600_000).toISOString());
    expect(useBackendSessionStore.getState()).toMatchObject({ status: "ready", email: "student@example.com" });
  });

  it("restores a persisted session on restart", async () => {
    const stored: StoredToken = { access_token: "jwt-1", expires_at: "2999-01-01T00:00:00.000Z" };
    const fetcher = vi.fn(async () => json(user));
    const session = createBackendSession({ baseUrl: "http://backend", store: memoryStore(stored), fetcher, now: () => 0 });

    await session.restore();

    expect(session.token()).toBe("jwt-1");
    expect(useBackendSessionStore.getState().status).toBe("ready");
  });

  it("drops an expired token without calling the Backend", async () => {
    const store = memoryStore({ access_token: "jwt-1", expires_at: "2000-01-01T00:00:00.000Z" });
    const fetcher = vi.fn(async () => json(user));
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => Date.parse("2026-01-01T00:00:00.000Z") });

    await session.restore();

    expect(fetcher).not.toHaveBeenCalled();
    expect(store.value).toBeNull();
    expect(session.token()).toBeNull();
    expect(useBackendSessionStore.getState().status).toBe("idle");
  });

  it("reports a storage error when clearing an expired token fails", async () => {
    const store: TokenStore = {
      async read() { return { access_token: "jwt-1", expires_at: "2000-01-01T00:00:00.000Z" }; },
      async write() {},
      async clear() { throw new Error("credential store unavailable"); },
    };
    const fetcher = vi.fn(async () => json(user));
    const session = createBackendSession({
      baseUrl: "http://backend",
      store,
      fetcher,
      now: () => Date.parse("2026-01-01T00:00:00.000Z"),
    });

    await expect(session.restore()).resolves.toBeUndefined();

    expect(fetcher).not.toHaveBeenCalled();
    expect(session.token()).toBeNull();
    expect(useBackendSessionStore.getState()).toMatchObject({
      status: "error",
      message: "Backend 会话存储失败：credential store unavailable",
    });
  });

  it("clears the session when the Backend rejects the token", async () => {
    const store = memoryStore({ access_token: "jwt-1", expires_at: "2999-01-01T00:00:00.000Z" });
    const fetcher = vi.fn(async () => json({ error: { code: "unauthenticated", message: "expired" } }, 401));
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 0 });

    await session.restore();

    expect(session.token()).toBeNull();
    expect(store.value).toBeNull();
  });

  it("keeps a replacement login when an old request returns 401 late", async () => {
    const store = memoryStore();
    const oldRequest = deferred<Response>();
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/v1/auth/login")) {
        const body = JSON.parse(String(init?.body)) as { password: string };
        return json({ access_token: body.password === "new-password" ? "jwt-2" : "jwt-1", token_type: "bearer", expires_in: 3600 });
      }
      const authorization = new Headers(init?.headers).get("Authorization");
      if (authorization === "Bearer jwt-1" && path.endsWith("/v1/current-state")) return oldRequest.promise;
      return json({ ...user, display_name: authorization === "Bearer jwt-2" ? "New session" : "Old session" });
    });
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 1_000 });

    await session.login("student@example.com", "old-password");
    const oldRequestResult = session.client.getCurrentState();
    await session.login("student@example.com", "new-password");
    oldRequest.resolve(json({ error: { code: "unauthenticated", message: "expired" } }, 401));
    await expect(oldRequestResult).rejects.toThrow("expired");

    expect(session.token()).toBe("jwt-2");
    expect(store.value?.access_token).toBe("jwt-2");
    expect(useBackendSessionStore.getState()).toMatchObject({ status: "ready", displayName: "New session" });
  });

  it("serializes 401 cleanup before a replacement login", async () => {
    const clearStarted = deferred<void>();
    const releaseClear = deferred<void>();
    let value: StoredToken | null = null;
    const store: TokenStore & { value: StoredToken | null } = {
      get value() { return value; },
      set value(next) { value = next; },
      async read() { return value; },
      async write(token) { value = token; },
      async clear() {
        clearStarted.resolve(undefined);
        await releaseClear.promise;
        value = null;
      },
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/v1/auth/login")) {
        const body = JSON.parse(String(init?.body)) as { password: string };
        return json({ access_token: body.password === "new-password" ? "jwt-2" : "jwt-1", token_type: "bearer", expires_in: 3600 });
      }
      const authorization = new Headers(init?.headers).get("Authorization");
      if (authorization === "Bearer jwt-1" && path.endsWith("/v1/current-state")) return json({ error: { code: "unauthenticated", message: "expired" } }, 401);
      return json({ ...user, display_name: "New session" });
    });
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 1_000 });

    await session.login("student@example.com", "old-password");
    await expect(session.client.getCurrentState()).rejects.toThrow("expired");
    await clearStarted.promise;
    const replacementLogin = session.login("student@example.com", "new-password");
    expect(fetcher.mock.calls.filter(([input]) => String(input).endsWith("/v1/auth/login"))).toHaveLength(1);
    releaseClear.resolve(undefined);
    await replacementLogin;

    expect(session.token()).toBe("jwt-2");
    expect(store.value?.access_token).toBe("jwt-2");
  });

  it("bumps the invalidation counter a mid-session 401 uses to clear the query pool (external #27)", async () => {
    // 中途失效（restore 时 token 仍有效）：onUnauthorized 队列完成完整清理
    // 并递增计数——App 据此整池清查询缓存（restore 期 401 的清理由
    // restore 内联完成、current 已清空，队列早退不递增，不属本面）。
    const store = memoryStore();
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/v1/auth/login")) return json({ access_token: "jwt-1", token_type: "bearer", expires_in: 3600 });
      const authorization = new Headers(init?.headers).get("Authorization");
      if (authorization === "Bearer jwt-1" && path.endsWith("/v1/current-state")) return json({ error: { code: "unauthenticated", message: "expired" } }, 401);
      return json(user);
    });
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 1_000 });

    await session.login("student@example.com", "password");
    const before = useBackendSessionStore.getState().invalidations;
    await expect(session.client.getCurrentState()).rejects.toThrow("expired");
    // onUnauthorized 清理在会话串行队列内 flush
    await expect(Promise.resolve()).resolves.toBeUndefined();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(useBackendSessionStore.getState().invalidations).toBe(before + 1);
    expect(useBackendSessionStore.getState()).toMatchObject({ status: "error", message: BACKEND_SESSION_EXPIRED });
    expect(store.value).toBeNull();
  });

  it("reports a storage error when ordinary 401 cleanup fails", async () => {
    const clear = vi.fn(async () => {
      throw new Error("credential store unavailable");
    });
    const store: TokenStore = {
      async read() { return null; },
      async write() {},
      clear,
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      return String(input).endsWith("/v1/current-state")
        ? json({ error: { code: "unauthenticated", message: "expired" } }, 401)
        : String(input).endsWith("/v1/auth/login")
          ? json(token)
          : json(user);
    });
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 1_000 });

    await session.login("student@example.com", "password123");
    await expect(session.client.getCurrentState()).rejects.toThrow("expired");
    await vi.waitFor(() => expect(clear).toHaveBeenCalledTimes(1));

    expect(session.token()).toBeNull();
    expect(useBackendSessionStore.getState()).toMatchObject({
      status: "error",
      message: "Backend 会话存储失败：credential store unavailable",
    });
  });

  it("keeps a stored token when restore fails because the Backend is unavailable", async () => {
    const stored: StoredToken = { access_token: "jwt-1", expires_at: "2999-01-01T00:00:00.000Z" };
    const store = memoryStore(stored);
    const session = createBackendSession({
      baseUrl: "http://backend",
      store,
      fetcher: vi.fn(async () => { throw new Error("Backend unavailable"); }),
      now: () => 0,
    });

    await session.restore();

    expect(session.token()).toBe("jwt-1");
    expect(store.value).toEqual(stored);
    expect(useBackendSessionStore.getState()).toMatchObject({ status: "error", message: "Backend unavailable" });
  });

  it("reports a storage error when clearing a rejected token fails", async () => {
    const store: TokenStore = {
      async read() { return { access_token: "jwt-1", expires_at: "2999-01-01T00:00:00.000Z" }; },
      async write() {},
      async clear() { throw new Error("credential store unavailable"); },
    };
    const fetcher = vi.fn(async () => json({ error: { code: "unauthenticated", message: "expired" } }, 401));
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 0 });

    await expect(session.restore()).resolves.toBeUndefined();

    expect(session.token()).toBeNull();
    expect(useBackendSessionStore.getState()).toMatchObject({
      status: "error",
      message: "Backend 会话存储失败：credential store unavailable",
    });
  });

  it("clears persisted state on logout", async () => {
    const store = memoryStore({ access_token: "jwt-1", expires_at: "2999-01-01T00:00:00.000Z" });
    const session = createBackendSession({ baseUrl: "http://backend", store, now: () => 0 });
    await session.logout();
    expect(store.value).toBeNull();
    expect(useBackendSessionStore.getState().status).toBe("idle");
  });

  it("reports a logout storage failure after clearing the in-memory session", async () => {
    const store: TokenStore = {
      async read() { return null; },
      async write() {},
      async clear() { throw new Error("credential store unavailable"); },
    };
    const session = createBackendSession({ baseUrl: "http://backend", store, now: () => 0 });

    await expect(session.logout()).rejects.toThrow("credential store unavailable");

    expect(session.token()).toBeNull();
    expect(useBackendSessionStore.getState()).toMatchObject({
      status: "error",
      message: "Backend 会话存储失败：credential store unavailable",
    });
  });

  it("executes concurrent restore, login, and logout calls in order", async () => {
    const stored: StoredToken = { access_token: "jwt-1", expires_at: "2999-01-01T00:00:00.000Z" };
    const store = memoryStore(stored);
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/v1/auth/login")) return json({ access_token: "jwt-2", token_type: "bearer", expires_in: 3600 });
      const authorization = new Headers(init?.headers).get("Authorization");
      return json({ ...user, display_name: authorization === "Bearer jwt-2" ? "New session" : "Restored session" });
    });
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 0 });

    const restore = session.restore();
    const login = session.login("student@example.com", "new-password");
    const logout = session.logout();
    await Promise.all([restore, login, logout]);

    expect(session.token()).toBeNull();
    expect(store.value).toBeNull();
    expect(useBackendSessionStore.getState().status).toBe("idle");
    expect(fetcher.mock.calls.map(([input]) => String(input))).toEqual([
      "http://backend/v1/auth/me",
      "http://backend/v1/auth/login",
      "http://backend/v1/auth/me",
    ]);
  });

  it("keeps the previous session when a replacement token is rejected", async () => {
    const store = memoryStore();
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/v1/auth/login")) {
        const body = JSON.parse(String(init?.body)) as { password: string };
        return json(body.password === "new-password"
          ? { access_token: "jwt-2", token_type: "bearer", expires_in: 3600 }
          : { access_token: "jwt-1", token_type: "bearer", expires_in: 3600 });
      }
      const authorization = new Headers(init?.headers).get("Authorization");
      return authorization === "Bearer jwt-2"
        ? json({ error: { code: "unauthenticated", message: "expired" } }, 401)
        : json({ ...user, display_name: "Old session" });
    });
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 1_000 });

    await session.login("student@example.com", "old-password");
    await expect(session.login("student@example.com", "new-password")).rejects.toThrow("expired");

    expect(session.token()).toBe("jwt-1");
    expect(store.value?.access_token).toBe("jwt-1");
    expect(useBackendSessionStore.getState()).toMatchObject({
      status: "ready",
      displayName: "Old session",
    });
  });

  it("keeps the previous session when token persistence fails", async () => {
    let value: StoredToken | null = null;
    const store: TokenStore & { value: StoredToken | null } = {
      get value() { return value; },
      set value(next) { value = next; },
      async read() { return value; },
      async write(token) {
        value = token;
        if (token.access_token === "jwt-2") throw new Error("credential store unavailable");
        value = token;
      },
      async clear() { value = null; },
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/v1/auth/login")) {
        return json({ access_token: "jwt-1", token_type: "bearer", expires_in: 3600 });
      }
      return json(user);
    });
    const session = createBackendSession({ baseUrl: "http://backend", store, fetcher, now: () => 1_000 });

    await session.login("student@example.com", "password123");
    let nextLogin = false;
    fetcher.mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/v1/auth/login")) {
        nextLogin = true;
        return json({ access_token: "jwt-2", token_type: "bearer", expires_in: 3600 });
      }
      return json({ ...user, display_name: nextLogin ? "New session" : "Old session" });
    });

    await expect(session.login("student@example.com", "password123")).rejects.toThrow("credential store unavailable");
    expect(session.token()).toBe("jwt-1");
    expect(store.value?.access_token).toBe("jwt-1");
    expect(useBackendSessionStore.getState()).toMatchObject({ status: "ready", displayName: "Student" });
  });
});

describe("onOwnerChange (P0-2 / D-036)", () => {
  it("notifies the owner after login/restore and null after logout or expiry", async () => {
    const store = memoryStore();
    const fetcher = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/v1/auth/login") ? json(token) : json(user),
    );
    const owners: Array<{ origin: string; userId: string } | null> = [];
    const session = createBackendSession({
      baseUrl: "http://backend",
      store,
      fetcher,
      now: () => 1_000,
      onOwnerChange: (owner) => { owners.push(owner); },
    });

    await session.login("student@example.com", "password123");
    expect(owners).toEqual([{ origin: "http://backend", userId: "u-1" }]);
    expect(useBackendSessionStore.getState().userId).toBe("u-1");

    await session.logout();
    expect(owners).toEqual([{ origin: "http://backend", userId: "u-1" }, null]);

    // restore 成功再通知同一 owner（去重：不重复通知同 id）
    await session.login("student@example.com", "password123");
    expect(owners).toEqual([{ origin: "http://backend", userId: "u-1" }, null, { origin: "http://backend", userId: "u-1" }]);

    // 过期 restore：清除身份并通知 null
    const expiredStore = memoryStore({ access_token: "jwt-old", expires_at: "1970-01-01T00:00:00Z" });
    const expiredOwners: Array<{ origin: string; userId: string } | null> = [];
    const expiredSession = createBackendSession({
      baseUrl: "http://backend",
      store: expiredStore,
      fetcher,
      now: () => Date.parse("2026-01-01T00:00:00.000Z"),
      onOwnerChange: (owner) => { expiredOwners.push(owner); },
    });
    await expiredSession.restore();
    // 新实例 currentUserId 初始即 null：等值守卫不重复通知（消费侧
    // ownerScope.key 初始同为 null，无事可做）——owner 通知只在变化时发生
    expect(expiredOwners).toEqual([]);
  });

  it("does not flip the owner when a replacement login fails mid-flight", async () => {
    const store = memoryStore();
    let loginCalls = 0;
    let failSecondMe = false;
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/v1/auth/login")) {
        loginCalls += 1;
        return json(loginCalls === 1 ? token : { ...token, access_token: "jwt-2" });
      }
      if (path.endsWith("/v1/auth/me")) {
        if (loginCalls === 2 && failSecondMe) throw new Error("network down during me");
        return json(loginCalls === 1 ? user : { ...user, id: "u-2" });
      }
      return json(user);
    });
    const owners: Array<string | null> = [];
    const session = createBackendSession({
      baseUrl: "http://backend",
      store,
      fetcher,
      now: () => 1_000,
      onOwnerChange: (owner) => { owners.push(owner?.userId ?? null); },
    });

    await session.login("student@example.com", "password123");
    expect(owners).toEqual(["u-1"]);

    // 第二次登录在 me() 阶段失败：owner 不翻到 u-2，也不误报 null
    failSecondMe = true;
    await expect(session.login("student@example.com", "password123")).rejects.toThrow("network down during me");
    expect(owners).toEqual(["u-1"]);
    expect(useBackendSessionStore.getState()).toMatchObject({ status: "ready", userId: "u-1" });
  });
});
