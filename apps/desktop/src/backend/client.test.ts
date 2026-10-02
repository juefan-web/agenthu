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
    // D-029：首页显式 limit；后续页经 X-Next-Cursor 跟随（见分页用例）
    expect(String(fetcher.mock.calls[0][0])).toContain("/v1/tasks?limit=200");
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

  it("probes health without auth and reports false on timeout or error (D1)", async () => {
    const ok = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ status: "ok" }, 200));
    const unhealthy = vi.fn(async () => json({ error: {} }, 503));
    const refusing = vi.fn(async () => { throw new TypeError("fetch failed"); });
    expect(await new BackendClient({ baseUrl: "http://backend", fetcher: ok }).probeHealth(500)).toBe(true);
    expect(await new BackendClient({ baseUrl: "http://backend", fetcher: unhealthy }).probeHealth(500)).toBe(false);
    expect(await new BackendClient({ baseUrl: "http://backend", fetcher: refusing }).probeHealth(500)).toBe(false);

    // 探测超时 = 不可达：fetcher 挂起，race 由计时器胜出
    const hanging = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => new Promise<Response>(() => undefined));
    const startedAt = Date.now();
    expect(await new BackendClient({ baseUrl: "http://backend", fetcher: hanging }).probeHealth(20)).toBe(false);
    expect(Date.now() - startedAt).toBeLessThan(500);
    // 无鉴权：探测请求不携带 Authorization（健康检查不消耗会话语义）
    const init = ok.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(new Headers(init?.headers ?? {}).get("Authorization")).toBeNull();
  });
});

describe("BackendClient list pagination (D-029 拉全量)", () => {
  const task = (id: string) => ({
    id,
    title: `HW ${id}`,
    due_at: null,
    estimate_minutes: null,
    status: "todo",
    source_event_ids: [],
  });
  const plan = (id: string) => ({
    id,
    generated_at: "2026-10-02T10:00:00+08:00",
    items: [],
    confirmation_required: false,
    status: "confirmed",
    replaces_plan_id: null,
    replan_reason: null,
  });
  const memory = (id: string) => ({
    id,
    user_id: "u1",
    level: 1,
    domain: "study",
    content: `记忆 ${id}`,
    source: {},
    source_event_ids: [],
    confidence: 0.9,
    correction_status: "CONFIRMED",
    evidence: [],
    kind: "episode",
    subject_key: null,
    supersedes_id: null,
    valid_from: null,
    valid_to: null,
    use_count: 0,
    last_used_at: null,
    created_at: "2026-10-02T10:00:00+08:00",
    updated_at: "2026-10-02T10:00:00+08:00",
  });
  /** 200 条整页 fixture 工厂（PAGE_SIZE = 200：整页后必须继续翻页）。 */
  const ids = (n: number, prefix: string) => Array.from({ length: n }, (_, i) => `${prefix}-${i}`);
  const pageBody = (items: unknown[]) => ({ items, total: null, limit: 200, offset: 0 });

  function clientWith(pages: Response[]) {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      const page = pages.shift();
      if (page === undefined) throw new Error("unexpected extra request");
      return page;
    });
    return { client: new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" }), fetcher };
  }

  it("drains tasks through the X-Next-Cursor header until it is absent", async () => {
    const { client, fetcher } = clientWith([
      new Response(JSON.stringify([task("task-1")]), {
        status: 200,
        headers: { "Content-Type": "application/json", "X-Next-Cursor": "cur-1" },
      }),
      json([task("task-2")]),
    ]);
    const tasks = await client.getTasks();
    expect(tasks.map((item) => item.id)).toEqual(["task-1", "task-2"]);
    // 首页不带 cursor；第二页携带（keyset 路径，禁 offset 混用）
    expect(String(fetcher.mock.calls[0][0])).toContain("/v1/tasks?limit=200");
    expect(String(fetcher.mock.calls[1][0])).toContain("cursor=cur-1");
    expect(String(fetcher.mock.calls[1][0])).not.toContain("offset=");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("aborts instead of looping forever when the cursor never ends", async () => {
    const runaway = vi.fn(async () =>
      new Response(JSON.stringify([task("task-x")]), {
        status: 200,
        headers: { "Content-Type": "application/json", "X-Next-Cursor": "loop" },
      }),
    );
    const client = new BackendClient({ baseUrl: "http://backend", fetcher: runaway, getToken: () => "jwt" });
    await expect(client.getTasks()).rejects.toThrow("任务分页异常");
    expect(runaway).toHaveBeenCalledTimes(50); // MAX_PAGES 护栏
  });

  it("drains plans by offset until an empty tail page (offset 版 Page 不铸 cursor)", async () => {
    const { client, fetcher } = clientWith([
      json(pageBody(ids(200, "plan").map(plan))),
      json(pageBody(ids(200, "plan-b").map(plan))),
      json(pageBody([])), // 恰好整页倍数：空尾页判停
    ]);
    const plans = await client.listPlans("confirmed");
    expect(plans).toHaveLength(400);
    expect(String(fetcher.mock.calls[0][0])).toContain("offset=0");
    expect(String(fetcher.mock.calls[1][0])).toContain("offset=200");
    expect(String(fetcher.mock.calls[2][0])).toContain("offset=400");
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("drains memories across pages and stops on a short page", async () => {
    const { client } = clientWith([
      json(pageBody(ids(200, "mem").map(memory))),
      json(pageBody(ids(2, "mem-tail").map(memory))),
    ]);
    const memories = await client.listMemories();
    expect(memories).toHaveLength(202);
    expect(memories.at(-1)?.id).toBe("mem-tail-1");
  });
});
