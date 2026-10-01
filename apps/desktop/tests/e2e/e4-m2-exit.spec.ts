import { test, expect } from "@playwright/test";

/**
 * E4 — M2 出口判据（AGENTS §8 场景化全句，见 TASKS/m2-phase0-contract-freeze.md）。
 *
 * 两个用例：
 * - **e4-seed（常开）**：真实管线预置——事件 → 派生（课程前缀标题 + source）→
 *   Focus 完成（actual 由 PATCH 载荷提供，无需真实等待）→ 课表事件。这是
 *   「seed 走真实管线可以先行」的部分，A 侧写入者上线前即可持续验证管线。
 * - **e4（门控 AGENTHU_E4_FULL=1）**：出口判据全链断言——依赖 planner v2
 *   （basis/estimate_source）、估时学习、触发引擎、接受即取代、L1 写入者
 *   （A 侧批次）。全绿 = M2 出口达成。
 *
 * 对 m2-phase0 草案的两处已核修偏：① 草案 ×3 作业中课程 X 的 A/B 完成后无
 * 待办可入计划——补第四份同课程**待办**作业 D 承接 learned 估时（中位数仍
 * 由 A/B 的 60/90 决定）；② 「删除（DELETE）」按已落地语义改为 reject
 * （REJECTED live 占位，#23 端点无 delete）。
 */

const backendUrl = process.env.AGENTHU_TEST_BACKEND_URL;
const backendEmail = process.env.AGENTHU_TEST_BACKEND_EMAIL;
const backendPassword = process.env.AGENTHU_TEST_BACKEND_PASSWORD;
test.skip(!backendUrl || !backendEmail || !backendPassword,
  "需要 AGENTHU_TEST_BACKEND_URL / AGENTHU_TEST_BACKEND_EMAIL / AGENTHU_TEST_BACKEND_PASSWORD");

interface Api {
  token: string;
  get: (path: string) => Promise<unknown>;
  post: (path: string, body?: unknown, method?: string) => Promise<unknown>;
}

async function login(): Promise<Api> {
  const response = await fetch(`${backendUrl}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: backendEmail, password: backendPassword }),
  });
  if (!response.ok) throw new Error(`Backend 登录失败：HTTP ${response.status}`);
  const token = ((await response.json()) as { access_token: string }).access_token;
  const headers = () => ({ Authorization: `Bearer ${token}`, "Content-Type": "application/json" });
  const get = async (path: string) => {
    const res = await fetch(`${backendUrl}${path}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
    return res.json();
  };
  const post = async (path: string, body?: unknown, method = "POST") => {
    const res = await fetch(`${backendUrl}${path}`, { method, headers: headers(), body: body === undefined ? undefined : JSON.stringify(body) });
    if (!res.ok) throw new Error(`${method} ${path} → ${res.status}：${(await res.text()).slice(0, 200)}`);
    return res.status === 204 ? null : res.json();
  };
  return { token, get, post };
}

interface Seed {
  api: Api;
  run: string;
  courseX: string;
  courseY: string;
  taskA: { id: string; title: string };
  taskB: { id: string; title: string };
  taskD: { id: string; title: string };
  taskC: { id: string; title: string };
  planDId?: string;
}

function assignmentEnvelope(run: string, course: string, courseName: string, homework: string, deadline: string) {
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "+08:00");
  return {
    client_event_id: `e2e:${run}:hw:${homework}`,
    type: "study.assignment.discovered",
    occurred_at: now,
    source: "onethu",
    data: {
      assignment_id: `${run}-${homework}`,
      course_id: course,
      course_name: courseName,
      title: `作业${homework}`,
      content: "E2E seed",
      publish_time: now,
      deadline,
      deadline_raw: deadline,
      submitted: false,
      graded: false,
      url: "https://learn.example.com/e2e",
    },
    context: {},
    provenance: { connector: "onethu", connector_version: "e2e", upstream_id: `e2e:${run}:${homework}`, semantic_version: "v1", fetched_at: now },
  };
}

async function postEvents(api: Api, events: unknown[]): Promise<void> {
  const result = (await api.post("/v1/events/batch", { events, client_cursor: null })) as { rejected: unknown[] };
  if (result.rejected.length > 0) throw new Error(`seed 事件被拒：${JSON.stringify(result.rejected).slice(0, 300)}`);
}

async function findTaskByTitle(api: Api, title: string): Promise<{ id: string; title: string; status: string; actual_duration_minutes: number | null }> {
  const tasks = (await api.get("/v1/tasks?limit=200")) as Array<{ id: string; title: string; status: string; actual_duration_minutes: number | null }>;
  const match = tasks.filter((task) => task.title === title);
  if (match.length === 0) throw new Error(`派生任务未出现：${title}`);
  return match[match.length - 1]!;
}

async function completeFocus(api: Api, taskId: string, actualMinutes: number, note: string): Promise<void> {
  const session = (await api.post("/v1/focus-sessions", { task_id: taskId })) as { id: string };
  await api.post(`/v1/focus-sessions/${session.id}`, { status: "completed", actual_minutes: actualMinutes, deviation_note: note }, "PATCH");
}

/** 真实管线 seed：课程 X（A/B 完成 actual 60/90 + 待办 D）+ 对照课程 Y（待办 C）
 *  + 今日 14:00-15:40 的课表事件。课程名带 run 后缀隔离估时分组。 */
async function seedRealPipeline(): Promise<Seed> {
  const api = await login();
  const run = `${Date.now()}`;
  const courseX = `E2E课程X-${run.slice(-6)}`;
  const courseY = `E2E课程Y-${run.slice(-6)}`;
  const tomorrow = new Date(Date.now() + 24 * 3600_000).toISOString().slice(0, 10);
  const deadline = `${tomorrow}T23:59:00+08:00`;
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "+08:00");
  const today = new Date().toISOString().slice(0, 10);
  await postEvents(api, [
    assignmentEnvelope(run, "course-x", courseX, "A", deadline),
    assignmentEnvelope(run, "course-x", courseX, "B", deadline),
    assignmentEnvelope(run, "course-x", courseX, "D", deadline),
    assignmentEnvelope(run, "course-y", courseY, "C", deadline),
    {
      client_event_id: `e2e:${run}:schedule`,
      type: "time.schedule.entry",
      occurred_at: now,
      source: "onethu",
      data: { course_name: courseX, teacher: null, date: today, day_of_week: null, start_section: null, end_section: null, location: "六教", week_text: null, category: null, start_time: "14:00", end_time: "15:40" },
      context: {},
      provenance: { connector: "onethu", connector_version: "e2e", upstream_id: `e2e:${run}:schedule`, semantic_version: "v1", fetched_at: now },
    },
  ]);
  const [taskA, taskB, taskD, taskC] = await Promise.all([
    findTaskByTitle(api, `${courseX}：作业A`),
    findTaskByTitle(api, `${courseX}：作业B`),
    findTaskByTitle(api, `${courseX}：作业D`),
    findTaskByTitle(api, `${courseY}：作业C`),
  ]);
  await completeFocus(api, taskA.id, 60, "E4 seed：计划口径");
  await completeFocus(api, taskB.id, 90, "E4 seed：计划口径");
  return { api, run, courseX, courseY, taskA, taskB, taskD, taskC };
}

test.describe("E4 — M2 出口判据", () => {
  test("e4-seed：真实管线预置（事件→派生→Focus 实际用时→课表）", async () => {
    const seed = await seedRealPipeline();
    const recheckA = await findTaskByTitle(seed.api, `${seed.courseX}：作业A`);
    const recheckB = await findTaskByTitle(seed.api, `${seed.courseX}：作业B`);
    // 派生标题 = {course_name}：{title}（L3 合成 + #14 透传），actual 覆盖值入账
    expect(recheckA.title).toContain("作业A");
    expect(recheckA.status).toBe("done");
    expect(recheckA.actual_duration_minutes).toBe(60);
    expect(recheckB.actual_duration_minutes).toBe(90);
  });

  test("e4：出口判据全链（依赖 A 侧 planner v2/估时/触发/L1 写入者）", async ({ }) => {
    test.skip(!process.env.AGENTHU_E4_FULL, "AGENTHU_E4_FULL=1 时运行——依赖 A 侧 M2 写入者批次");
    const seed = await seedRealPipeline();
    const api = seed.api;

    // 当日已有确认计划则先取消，保证「生成受验计划」从干净状态开始（D-019）
    const existing = (await api.get("/v1/plans/today")) as { id: string; status: string };
    if (existing.status === "confirmed" || existing.status === "active") {
      await api.post(`/v1/plans/${existing.id}/cancel`);
    }
    const plan = (await api.get("/v1/plans/today")) as {
      id: string; status: string; items: Array<{ task_id: string; title: string; start_at: string; end_at: string; reason: string; basis?: Record<string, unknown> }>;
    };

    // (a) 无计划项与今日 14:00-15:40 课表重叠（含缓冲由 planner 内部处理）
    const classStart = Date.parse(`${new Date().toISOString().slice(0, 10)}T14:00:00+08:00`);
    const classEnd = Date.parse(`${new Date().toISOString().slice(0, 10)}T15:40:00+08:00`);
    for (const item of plan.items) {
      expect(Date.parse(item.start_at) >= classEnd || Date.parse(item.end_at) <= classStart,
        `计划项 ${item.title}（${item.start_at} ~ ${item.end_at}）与课表 14:00-15:40 重叠`).toBe(true);
    }
    // (b) reason 是人话，不含内部策略标识
    for (const item of plan.items) {
      expect(item.reason, `reason 含内部标识：${item.reason}`).not.toMatch(/deadline_then_priority|slots_v2/);
    }
    // (c)/(d) 估时来源双向断言：课程 X（60/90 → 中位 75）learned，对照 Y default
    const itemD = plan.items.find((item) => item.title.includes("作业D"));
    const itemC = plan.items.find((item) => item.title.includes("作业C"));
    expect(itemD, "课程 X 待办作业 D 应入计划").toBeTruthy();
    expect(itemC, "对照课程 Y 作业 C 应入计划").toBeTruthy();
    expect(String(itemD!.basis?.["estimate_source"])).toBe("learned:course");
    expect(itemD!.basis?.["estimate_minutes"]).toBe(75); // seed 数与 n≥2 阈值对齐（D-031 §4）
    expect(String(itemC!.basis?.["estimate_source"])).toBe("default");

    // 确认计划 → 超时 Focus（planned 75 → actual 100 ≥ 1.3×）→ 触发建议
    await api.post(`/v1/plans/${plan.id}/confirm`);
    const note = "比预计多用了 25 分钟";
    await completeFocus(api, seed.taskD.id, 100, note);

    let suggestion: { id: string; replaces_plan_id: string | null; replan_reason: string | null } | undefined;
    const deadlineAt = Date.now() + 90_000;
    while (Date.now() < deadlineAt && !suggestion) {
      const drafts = (await api.get("/v1/plans?status=draft&limit=200")) as { items: Array<{ id: string; replaces_plan_id: string | null; replan_reason: string | null }> };
      suggestion = drafts.items.find((item) => item.replaces_plan_id === plan.id);
      if (!suggestion) await new Promise((resolve) => setTimeout(resolve, 5_000));
    }
    expect(suggestion, "90s 内应出现指向被替代计划的重排建议（触发引擎 30s 去抖）").toBeTruthy();
    expect(suggestion!.replan_reason).toContain("100");
    // L4 保护：接受前被替代计划仍是 CONFIRMED
    const replacedBefore = (await api.get(`/v1/plans/${plan.id}`)) as { status: string };
    expect(replacedBefore.status).toBe("confirmed");

    // 接受即取代（#23）：新计划 CONFIRMED、旧计划同事务 SUPERSEDED
    const accepted = (await api.post(`/v1/plans/${suggestion!.id}/confirm`)) as { status: string };
    expect(accepted.status).toBe("confirmed");
    const replacedAfter = (await api.get(`/v1/plans/${plan.id}`)) as { status: string };
    expect(replacedAfter.status).toBe("superseded");

    // L1 记忆：kind=episode、evidence 指向事件、deviation_note 入内容
    const memories = (await api.get("/v1/memory?limit=200")) as { items: Array<{ id: string; kind: string | null; level: number; content: string; evidence: Array<Record<string, unknown>>; correction_status: string; supersedes_id: string | null }> };
    const episode = memories.items.find((item) => item.kind === "episode" && item.content.includes(note));
    expect(episode, "应出现含偏差说明的 L1 episode").toBeTruthy();
    expect(episode!.evidence.some((entry) => entry["type"] === "event")).toBe(true);

    // 可修正（superseded-by 版本链端到端）：correct → 201 新 live、旧行 CORRECTED 且指针指向新行
    const corrected = (await api.post(`/v1/memory/${episode!.id}/correct`, { content: `${episode!.content}（用户修正版）`, confidence: 0.95 })) as { id: string; correction_status: string; supersedes_id: string | null };
    expect(corrected.correction_status).toBe("CONFIRMED");
    expect(corrected.supersedes_id).toBeNull();
    const afterCorrect = (await api.get("/v1/memory?limit=200")) as { items: Array<{ id: string; correction_status: string; supersedes_id: string | null }> };
    const refreshedOld = afterCorrect.items.find((item) => item.id === episode!.id);
    expect(refreshedOld!.correction_status).toBe("CORRECTED");
    expect(refreshedOld!.supersedes_id).toBe(corrected.id);

    // 拒绝（REJECTED live 占位阻断再派生——#23 语义，草案的「DELETE」按落地语义替换）
    const rejected = (await api.post(`/v1/memory/${corrected.id}/reject`)) as { correction_status: string };
    expect(rejected.correction_status).toBe("REJECTED");
  });
});
