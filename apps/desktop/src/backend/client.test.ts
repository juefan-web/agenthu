import { describe, expect, it, vi } from "vitest";
import { BackendAuthError, BackendClient } from "./client";

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("BackendClient authentication", () => {
  it("adds a bearer token and omits cookies on authenticated requests", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      json([
        {
          id: "task-1",
          title: "HW1",
          due_at: null,
          estimate_minutes: null,
          status: "todo",
          source_event_ids: [],
        },
      ]),
    );
    const client = new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" });
    await client.getTasks();
    const init = fetcher.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("omit");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer jwt");
  });

  it("reports and clears an expired session on 401", async () => {
    const onUnauthorized = vi.fn();
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ error: { code: "unauthenticated", message: "expired" } }, 401));
    const client = new BackendClient({
      baseUrl: "http://backend",
      fetcher,
      getToken: () => "expired",
      onUnauthorized,
    });
    await expect(client.getCurrentState()).rejects.toBeInstanceOf(BackendAuthError);
    expect(onUnauthorized).toHaveBeenCalledWith("expired");
  });

  it("refuses to call protected endpoints without a token", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const client = new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => null });
    await expect(client.getTasks()).rejects.toBeInstanceOf(BackendAuthError);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("uses the Backend error message for failed logins", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ error: { code: "unauthenticated", message: "Invalid email or password" } }, 401));
    const client = new BackendClient({ baseUrl: "http://backend", fetcher });
    await expect(client.login("student@example.com", "wrong-password")).rejects.toThrow("Invalid email or password");
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).has("Authorization")).toBe(false);
  });

  it("sends only fields supported by the Focus PATCH contract", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({
      id: "focus-1",
      task_id: "task-1",
      started_at: "2026-09-28T10:00:00+08:00",
      ended_at: null,
      actual_minutes: null,
      status: "paused",
      deviation_note: "Interrupted by a meeting",
    }));
    const client = new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" });

    await client.updateFocus("focus-1", {
      status: "paused",
      deviation_note: "Interrupted by a meeting",
    });

    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      status: "paused",
      deviation_note: "Interrupted by a meeting",
    });
  });
});
