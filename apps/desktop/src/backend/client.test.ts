import { describe, expect, it, vi } from "vitest";
import { BackendAuthError, BackendClient, BackendHttpError } from "./client";

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

describe("BackendClient grounding endpoints (M3 §6)", () => {
  const consent = {
    course_name: "信号与系统",
    enabled: true,
    consent_text: "开启后，当你在此课程中提问，系统会把与问题最相关的课程资料片段……",
    consent_text_version: "v1",
    consented_at: "2026-10-02T09:00:00+08:00",
  };
  const answer = {
    id: "ans-1",
    course_name: "信号与系统",
    question: "什么是采样定理",
    answer: "约束：「采样率至少为最高频率的两倍」[2]。",
    grounded: true,
    citations: [{
      file_id: "file-1",
      checksum: "chk-1",
      page: 2,
      span_start: 0,
      span_end: 13,
      quote: "采样率至少为最高频率的两倍",
    }],
    chunk_ids: ["chunk-1"],
    memory_ids: [],
    model_version: "fake-model",
    prompt_version: "v1",
    created_at: "2026-10-02T10:00:00+08:00",
  };
  const file = { id: "file-1", filename: "lecture1.pdf", checksum_sha256: "chk-1", course_name: "信号与系统", status: "ready" };

  it("asks a grounded question via POST with course and question body", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(answer));
    const client = new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" });
    const result = await client.askGroundedQuestion("信号与系统", "什么是采样定理");
    expect(result.grounded).toBe(true);
    expect(result.citations[0]?.quote).toBe("采样率至少为最高频率的两倍");
    expect(String(fetcher.mock.calls[0][0])).toContain("/v1/material/answers");
    const init = fetcher.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ course_name: "信号与系统", question: "什么是采样定理" });
  });

  it("carries 403/503 status on BackendHttpError for the view to branch on", async () => {
    const denied = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ error: { code: "permission_denied", message: "not enabled" } }, 403));
    const unavailable = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ error: { code: "service_unavailable", message: "provider down" } }, 503));
    const statuses = await Promise.all([
      new BackendClient({ baseUrl: "http://backend", fetcher: denied, getToken: () => "jwt" })
        .askGroundedQuestion("c", "q").catch((error) => error),
      new BackendClient({ baseUrl: "http://backend", fetcher: unavailable, getToken: () => "jwt" })
        .askGroundedQuestion("c", "q").catch((error) => error),
    ]);
    expect(statuses[0]).toBeInstanceOf(BackendHttpError);
    expect((statuses[0] as BackendHttpError).status).toBe(403);
    expect((statuses[1] as BackendHttpError).status).toBe(503);
  });

  it("enables consent echoing the served consent_text_version", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ ...consent, enabled: true }));
    const client = new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" });
    await client.setGroundingConsent("信号与系统", true, "v1");
    const init = fetcher.mock.calls[0][1] as RequestInit;
    expect(String(fetcher.mock.calls[0][0])).toContain("/v1/grounding-consent");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({ course_name: "信号与系统", enabled: true, consent_text_version: "v1" });
  });

  it("reads consent state and deletes answers (204)", async () => {
    const reader = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(consent));
    await new BackendClient({ baseUrl: "http://backend", fetcher: reader, getToken: () => "jwt" }).getGroundingConsent("信号与系统");
    expect(String(reader.mock.calls[0][0])).toContain("/v1/grounding-consent?course_name=");

    const deleter = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(null, { status: 204 }));
    await new BackendClient({ baseUrl: "http://backend", fetcher: deleter, getToken: () => "jwt" }).deleteGroundedAnswer("ans-1");
    expect(String(deleter.mock.calls[0][0])).toContain("/v1/material/answers/ans-1");
    expect((deleter.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
  });

  it("drains grounded answers and files by offset until short pages", async () => {
    const answerPages = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ items: [answer, { ...answer, id: "ans-2" }], total: 2, limit: 200, offset: 0 }));
    const answers = await new BackendClient({ baseUrl: "http://backend", fetcher: answerPages, getToken: () => "jwt" }).listGroundedAnswers("信号与系统");
    expect(answers.map((item) => item.id)).toEqual(["ans-1", "ans-2"]);
    expect(answerPages).toHaveBeenCalledTimes(1); // 短页即停

    const filePages = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ items: [file], total: 1, limit: 200, offset: 0 }));
    const files = await new BackendClient({ baseUrl: "http://backend", fetcher: filePages, getToken: () => "jwt" }).listFiles();
    expect(files[0]?.filename).toBe("lecture1.pdf");
    expect(String(filePages.mock.calls[0][0])).toContain("/v1/files?limit=200&offset=0");
  });
});

describe("BackendClient M4 methods (D-034)", () => {
  const basis = {
    basis_version: "v1",
    summary: "作业临近且当前时段空闲",
    references: [{ kind: "task", id: "task-1", label: "HW1" }],
    rule_versions: { planner: "v2" },
    selected_tool_call_ids: ["call-1"],
  };
  const action = {
    id: "pa-1",
    version: 3,
    status: "PENDING",
    required_level: 2,
    tool: { name: "task.create", version: "1.0.0", title: "创建任务" },
    display: {
      summary: "把「复习第三章」加入任务列表",
      parameters: [{ label: "标题", value: "复习第三章" }],
      impact: "任务列表新增一条 todo",
    },
    basis,
    expires_at: "2026-10-04T12:00:00+08:00",
    retryable: true,
    created_at: "2026-10-03T12:00:00+08:00",
    updated_at: "2026-10-03T12:00:00+08:00",
  };
  const run = {
    id: "run-1",
    status: "SUCCEEDED",
    invocation_kind: "chat",
    trigger_ref: { kind: "chat", chat_message_id: "msg-1" },
    provider: { name: "openai", model: "gpt-x", capability: "none" },
    created_at: "2026-10-03T12:00:00+08:00",
    updated_at: "2026-10-03T12:00:05+08:00",
    started_at: null,
    finished_at: null,
    tool_calls: [],
    decision_basis: null,
    pending_action_ids: [],
    usage: null,
    result: { degraded: true, degrade_code: "provider_unavailable" },
    failure: null,
  };

  it("drains pending actions through next_cursor pages", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      json({ items: [action], total: null, limit: 200, offset: 0, next_cursor: "cur-1" }));
    const second = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      json({ items: [{ ...action, id: "pa-2", status: "SUCCEEDED" }], next_cursor: null }));
    let call = 0;
    const fetcher2 = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      call += 1;
      return call === 1 ? fetcher(input, init) : second(input, init);
    });
    const client = new BackendClient({ baseUrl: "http://backend", fetcher: fetcher2, getToken: () => "jwt" });
    const actions = await client.listPendingActions("active");
    expect(actions.map((item) => item.id)).toEqual(["pa-1", "pa-2"]);
    expect(String(fetcher2.mock.calls[0][0])).toContain("/v1/pending-actions?status=active&limit=200");
    expect(String(fetcher2.mock.calls[1][0])).toContain("cursor=cur-1");
  });

  it("sends expected_version and mutation_id on confirm; 409 carries status", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ ...action, status: "CONFIRMED" }));
    const client = new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" });
    await client.confirmPendingAction("pa-1", 3, "mut-1");
    const init = fetcher.mock.calls[0][1] as RequestInit;
    expect(String(fetcher.mock.calls[0][0])).toContain("/v1/pending-actions/pa-1/confirm");
    expect(JSON.parse(String(init.body))).toEqual({ expected_version: 3, mutation_id: "mut-1" });

    const conflict = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ error: { code: "conflict", message: "已被结算" } }, 409));
    const rejected = await new BackendClient({ baseUrl: "http://backend", fetcher: conflict, getToken: () => "jwt" })
      .confirmPendingAction("pa-1", 3, "mut-1").catch((error) => error);
    expect(rejected).toBeInstanceOf(BackendHttpError);
    expect((rejected as BackendHttpError).status).toBe(409);
  });

  it("reads agent runs with the tool_calls mirror", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(run));
    const parsed = await new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" }).getAgentRun("run-1");
    expect(parsed.result?.degraded).toBe(true);
    expect(String(fetcher.mock.calls[0][0])).toContain("/v1/agent/runs/run-1");
  });

  it("creates sessions, sends messages (202), deletes messages and sessions (204)", async () => {
    const session = { id: "s-1", title: "会话", created_at: "2026-10-03T10:00:00+08:00", updated_at: "2026-10-03T10:00:00+08:00", archived_at: null };
    const creator = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(session));
    const client = new BackendClient({ baseUrl: "http://backend", fetcher: creator, getToken: () => "jwt" });
    await client.createChatSession({ title: "会话", clientRequestId: "req-1" });
    const createInit = creator.mock.calls[0][1] as RequestInit;
    expect(String(creator.mock.calls[0][0])).toContain("/v1/chat/sessions");
    expect(JSON.parse(String(createInit.body))).toEqual({ title: "会话", client_request_id: "req-1" });

    const sender = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ run_id: "run-9", user_message_id: "msg-9" }, 202));
    await new BackendClient({ baseUrl: "http://backend", fetcher: sender, getToken: () => "jwt" })
      .sendChatMessage("s-1", "把作业加进日程", "cmsg-1");
    const sendInit = sender.mock.calls[0][1] as RequestInit;
    expect(String(sender.mock.calls[0][0])).toContain("/v1/chat/sessions/s-1/messages");
    expect(JSON.parse(String(sendInit.body))).toEqual({ content: "把作业加进日程", client_message_id: "cmsg-1" });

    const deleter = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(null, { status: 204 }));
    await new BackendClient({ baseUrl: "http://backend", fetcher: deleter, getToken: () => "jwt" }).deleteChatMessage("msg-9");
    await new BackendClient({ baseUrl: "http://backend", fetcher: deleter, getToken: () => "jwt" }).deleteChatSession("s-1");
    expect(String(deleter.mock.calls[0][0])).toContain("/v1/chat/messages/msg-9");
    expect(String(deleter.mock.calls[1][0])).toContain("/v1/chat/sessions/s-1");
  });

  it("patches notification preferences with expected_version", async () => {
    const preferences = {
      version: 5, timezone: "Asia/Shanghai", enabled_categories: ["deadline"],
      quiet_hours_start: "22:00", quiet_hours_end: "07:00", daily_budget: 3,
      sent_count: 1, budget_date: "2026-10-03", last_sent_at: null,
    };
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(preferences));
    await new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" })
      .updateNotificationPreferences({ daily_budget: 5 }, 5);
    const init = fetcher.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(String(fetcher.mock.calls[0][0])).toContain("/v1/notification-preferences");
    expect(JSON.parse(String(init.body))).toEqual({ daily_budget: 5, expected_version: 5 });
  });
});
