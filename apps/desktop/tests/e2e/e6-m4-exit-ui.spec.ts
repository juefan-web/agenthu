import { test as base, chromium, expect, type BrowserContext, type Page } from "@playwright/test";

/**
 * E6 — M4 出口场景（构建包 + CDP，契约 §8 六场景）。场景定义见
 * AGENT_CONTEXT/TASKS/m4-b3-e6-exit.md；后端栈与 provider 假件手册见
 * tests/e2e/README.md「E6 栈」。
 *
 * 覆盖：①超时 Focus → Level 1 重排建议（应用内免费）②Chat 请求 →
 * task.create L2 卡片（安全参数/Level/到期/basis）③「为什么」展开同一份
 * basis（引用可核）④确认恰一次（UI 防双击 + API 并发只结算一个任务）
 * ⑤provider 断供 → Chat 明确失败、计划/重排/Focus 仍可操作 ⑥预算抑制 +
 * L3 grant 自动派发 + 预算耗尽如实抑制。
 *
 * 已知契约-实现缺口（任务文件「缺口矩阵」节，断言按已实现判据书写）：
 * Plan.basis.agent_decision 与 reference 失效态（source_deleted/
 * version_mismatch）暂无后端写入者——场景①的「与 Plan.basis 相同依据」
 * 以 run 级结构化 basis 核验；场景③的失效标注已有单测钉住（
 * DecisionBasisView.test），活链断言随缺口闭合后补。
 *
 * 前置：构建包以 CDP 运行；`AGENTHU_E6_UI=1`；`AGENTHU_TEST_BACKEND_URL`
 * 与构建期 `VITE_BACKEND_URL` 同源；provider = e6-replay.mjs
 * （`AGENTHU_E6_REPLAY_URL`，默认 :9099）。
 */

const backendUrl = process.env.AGENTHU_TEST_BACKEND_URL;
const backendEmail = process.env.AGENTHU_TEST_BACKEND_EMAIL;
const backendPassword = process.env.AGENTHU_TEST_BACKEND_PASSWORD;
const replayUrl = process.env.AGENTHU_E6_REPLAY_URL ?? "http://127.0.0.1:9099";

const RUN = `e6-${Date.now()}`;
const SUGGESTED_TASK = "复习第三章（E6 建议）";

const test = base.extend<{ app: { context: BrowserContext; page: Page } }>({
  app: async ({}, use) => {
    const cdpUrl = process.env.AGENTHU_CDP_URL ?? "http://127.0.0.1:9222";
    const browser = await chromium.connectOverCDP(cdpUrl);
    const context = browser.contexts()[0];
    const page = context.pages()[0];
    if (!page) throw new Error("构建包 WebView 没有可达页面：确认 CDP 端口与启动参数");
    await use({ context, page });
    await browser.close();
  },
});

test.skip(!backendUrl || !backendEmail || !backendPassword,
  "需要 AGENTHU_TEST_BACKEND_URL / EMAIL / PASSWORD");
test.skip(process.env.AGENTHU_E6_UI !== "1",
  "E6 需 AGENTHU_E6_UI=1（构建包 + CDP + E6 栈，见 tests/e2e/README.md）");

interface Api {
  get: (path: string) => Promise<any>;
  post: (path: string, body?: unknown, method?: string) => Promise<{ status: number; body: any }>;
}

/** 构建包内登录的是首个注册账号（serial 共享）；API 侧全用它核账。 */
let sharedApi: Api | null = null;

async function registerAndLogin(): Promise<Api> {
  if (sharedApi) return sharedApi;
  const email = `${RUN}@e6.test`;
  const password = "e6-pass-123456";
  const register = await fetch(`${backendUrl}/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: `E6 ${RUN}` }),
  });
  if (register.status !== 201) throw new Error(`注册失败：HTTP ${register.status}`);
  const login = await fetch(`${backendUrl}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!login.ok) throw new Error(`登录失败：HTTP ${login.status}`);
  const token = ((await login.json()) as { access_token: string }).access_token;
  const auth = () => ({ Authorization: `Bearer ${token}` });
  sharedApi = {
    get: async (path) => {
      const res = await fetch(`${backendUrl}${path}`, { headers: auth() });
      if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
      return res.json();
    },
    post: async (path, body, method = "POST") => {
      const res = await fetch(`${backendUrl}${path}`, {
        method,
        headers: { ...auth(), "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!res.ok && res.status !== 409) {
        throw new Error(`${method} ${path} → ${res.status}：${(await res.text()).slice(0, 200)}`);
      }
      return { status: res.status, body: res.status === 204 ? null : await res.json().catch(() => null) };
    },
  };
  return sharedApi;
}

async function waitFor<T>(label: string, probe: () => Promise<T>, done: (value: T) => boolean, timeoutMs = 150_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await probe();
    if (done(value)) return value;
    if (Date.now() > deadline) throw new Error(`等待超时：${label}`);
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
}

async function setReplayMode(mode: "grounding" | "chat-tools" | "unavailable") {
  const res = await fetch(`${replayUrl}/__mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) throw new Error(`replay 模式切换失败（${replayUrl}）：HTTP ${res.status}`);
}

/** 已过期 pending 任务：deadline at-risk 豁免触发引擎 30 分钟限流（D-031
 *  §2）——六场景的多次 overrun 全在同一 30 分钟窗内，无豁免则 s6 的后续
 *  触发被限流饿死。须在首个计划 confirm 之前种（created_at ≤ confirmed_at，
 *  不抢跑 new_task 触发器；overrun 判据优先级更高，双保险）。 */
async function seedDeadlineExemption(api: Api) {
  await api.post("/v1/tasks", {
    title: "已过期豁免项（E6）",
    deadline: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  });
}

/** 触发一次真实的计划项 overrun（D-030 出口句原文路径：超时 Focus → 重排
 *  建议）：任务（75）→ 计划脚手架（items + confirm，触发引擎先取已确认
 *  计划）→ 真实 focus 完成链收尾——focus.completed Event 同请求内同步跑
 *  handler 并 SADD 脏标（SADD 在终态之后，SPOP 竞态窗口闭合），
 *  `_mark_confirmed_plan_items` 把确认计划项置 COMPLETED、actual 累计 100
 *  > planned 75 → focus_overrun。手工 PATCH 计划项是 A 上轮的简化捷径，
 *  已按二轮裁定（修法 A）移除。 */
async function seedOverrun(api: Api, title: string): Promise<string> {
  const task = (await api.post("/v1/tasks", { title, estimated_duration_minutes: 75 })).body;
  const plan = (await api.post("/v1/plans", {
    title: `计划 · ${title}`,
    items: [{ title, task_id: task.id, order_index: 0, planned_minutes: 75 }],
  })).body;
  await api.post(`/v1/plans/${plan.id}/confirm`);
  const focus = (await api.post("/v1/focus-sessions", { task_id: task.id })).body;
  await api.post(`/v1/focus-sessions/${focus.id}`, { status: "completed", actual_minutes: 100, deviation_note: "超时" }, "PATCH");
  return task.id as string;
}

async function countSuggestedTasks(api: Api): Promise<number> {
  const tasks = (await api.get("/v1/tasks?limit=200")) as Array<{ title: string }>;
  return tasks.filter((task) => task.title === SUGGESTED_TASK).length;
}

async function loginInApp(page: Page) {
  const backendLogout = page.getByRole("button", { name: "退出 Backend" });
  if (await backendLogout.isVisible()) {
    await backendLogout.click();
    await expect(backendLogout).toBeHidden({ timeout: 10_000 });
  }
  await page.getByLabel("Backend 邮箱").fill(`${RUN}@e6.test`);
  await page.getByLabel("Backend 密码").fill("e6-pass-123456");
  await page.getByRole("button", { name: "登录 Backend" }).click();
  await expect(page.getByRole("button", { name: "登录 Backend" })).toBeHidden({ timeout: 30_000 });
}

test.describe.configure({ mode: "serial" });

test("e6-s1: 超时 Focus → Level 1 重排建议（依据活链：agent_decision 引用超时任务）", async ({ app }) => {
  const { page } = app;
  const api = await registerAndLogin();
  await seedDeadlineExemption(api); // 首个计划 confirm 之前种（限流豁免）
  const seededTaskId = await seedOverrun(api, "线性代数作业");

  // 触发引擎经 worker cron（≤30s）产出 DRAFT 建议；UI 60s 轮询——上界内等
  const drafts = await waitFor("重排建议落库", async () =>
    (await api.get("/v1/plans?status=draft&limit=10&offset=0")) as { items: Array<{ id: string; replaces_plan_id: string | null; basis?: Record<string, unknown> }> },
    (body) => body.items.some((plan) => plan.replaces_plan_id !== null));
  const suggestion = drafts.items.find((plan) => plan.replaces_plan_id !== null)!;

  // 活链（#59 缺口闭合后摘锚）：建议 plan 级 basis.agent_decision 引用超时任务
  const agentDecision = suggestion.basis?.["agent_decision"] as { references?: Array<{ kind: string; id: string }> } | undefined;
  expect(agentDecision).toBeTruthy();
  expect(agentDecision!.references?.some((reference) => reference.kind === "task" && reference.id === seededTaskId)).toBe(true);

  await loginInApp(page);
  const suggestionBox = page.locator(".replan-suggestion").first();
  await expect(suggestionBox).toBeVisible({ timeout: 120_000 });
  expect(/超时|超了|overrun|重排|调整/i.test((await suggestionBox.textContent()) ?? "")).toBeTruthy();

  // UI 腿：建议的「为什么」展开共享 DecisionBasisView（§8-1「客户端显示
  // 与 Plan.basis 相同的 Event / Task 依据」）
  await suggestionBox.getByText("为什么").click(); // <details><summary>：点 summary 切换 open
  const basis = suggestionBox.locator(".decision-basis").first();
  await expect(basis).toBeVisible();
  expect((await basis.textContent()) ?? "").toContain("线性代数作业");
});

test("e6-s2: Chat 请求「把作业加入日程」→ task.create Level 2 卡片", async ({ app }) => {
  const { page } = app;
  page.on("dialog", (dialog) => void dialog.accept());
  await setReplayMode("chat-tools");

  await page.getByRole("button", { name: "对话" }).click();
  // 全局模型上下文同意门（默认关）：先读文案，开启回显版本
  await expect(page.getByText(/开启前请阅读授权说明/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "同意并开启" }).click();
  await expect(page.getByRole("button", { name: "新会话" })).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "新会话" }).click();
  await page.getByLabel("消息").fill("把线性代数作业加入今天日程");
  await page.getByRole("button", { name: "发送" }).click();

  // run 结算（202 + 客户端 3s×≤40 轮询）：助手回复 + 待确认动作行
  await expect(page.getByText("已为你创建待确认任务，请在「确认」里查看。").first()).toBeVisible({ timeout: 130_000 });
  await expect(page.getByText("这条回复提出了一个待确认动作").first()).toBeVisible();
  await page.getByRole("button", { name: "查看确认卡片" }).first().click();

  // 卡片（深链落「确认」视图）：安全参数 + Level 2 + 绝对到期时间 + basis
  await expect(page.getByText(SUGGESTED_TASK).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Level 2 · 需要确认").first()).toBeVisible();
  await expect(page.getByText("标题").first()).toBeVisible();
  await expect(page.getByText(/到期：/).first()).toBeVisible();
  await page.getByRole("button", { name: "为什么" }).first().click();
  await expect(page.locator(".decision-basis").first()).toBeVisible();
});

test("e6-s3: Chat「为什么」同一份 basis + 删被引用消息 → 活链失效标注", async ({ app }) => {
  const { page } = app;
  const api = await registerAndLogin();
  await page.getByRole("button", { name: "对话" }).click();
  const whyButtons = page.getByRole("button", { name: "为什么" });
  await expect(whyButtons.first()).toBeVisible({ timeout: 15_000 });
  await whyButtons.first().click();
  const basis = page.locator(".decision-basis").first();
  await expect(basis).toBeVisible();
  // 判据：引用真实存在、可定位（kind 标签渲染，定位不是正文）——chat run
  // 引用触发消息（#59 起 chat_message kind 产出者），basis 与确认卡同一 run
  expect((await basis.textContent()) ?? "").toContain("对话消息");

  // 活链（#59 失效传播闭合后摘锚）：删除被引用的触发消息（API，同事务翻转
  // run/卡片 basis 的 chat_message 引用）→ 重新进对话视图取新鲜投影 →
  // 「为什么」里的该引用显示失效标注，不改指同名对象（契约 §4/§5）
  const sessions = await api.get("/v1/chat/sessions?limit=10&offset=0") as { items: Array<{ id: string }> };
  const sessionId = sessions.items[0]!.id;
  const messages = await api.get(`/v1/chat/sessions/${sessionId}/messages?limit=50&offset=0`) as { items: Array<{ id: string; role: string }> };
  const triggerMessage = messages.items.find((message) => message.role === "user")!;
  await api.post(`/v1/chat/messages/${triggerMessage.id}`, undefined, "DELETE");
  // 服务端核账：读面投影已翻 source_deleted
  await waitFor("引用翻转", async () =>
    (await api.get(`/v1/chat/sessions/${sessionId}/messages?limit=50&offset=0`)) as { items: Array<{ decision_basis?: { references?: Array<{ kind: string; state?: string }> } | null }> },
    (body) => body.items.some((message) => message.decision_basis?.references?.some((reference) => reference.kind === "chat_message" && reference.state === "source_deleted")));
  // UI 腿：remount 重取投影，展开「为什么」见失效标注
  await page.getByRole("button", { name: "今天", exact: true }).click();
  await page.getByRole("button", { name: "对话" }).click();
  await page.getByRole("button", { name: "为什么" }).first().click();
  await expect(page.getByText(/来源已删除或不可用/).first()).toBeVisible();
});

test("e6-s4: 确认恰一次（UI 防双击 + API 并发只结算一个任务）", async ({ app }) => {
  const { page } = app;
  const api = await registerAndLogin();

  // UI：s2 卡片确认，紧接第二次点击被防双击挡掉（先进「确认」视图挂载卡片）
  await page.getByRole("button", { name: "确认", exact: true }).click();
  const confirm = page.getByRole("button", { name: /确认：/ }).first();
  await confirm.click();
  await confirm.click().catch(() => undefined);
  await expect(page.getByText("已完成").first()).toBeVisible({ timeout: 30_000 });

  // 计数快照移到 UI 确认之后：s2/s3 只到卡片可见未确认（L2 PENDING 不产
  // 任务），before=1 的语义 = 「UI 确认路径恰产一条」
  const before = await countSuggestedTasks(api);
  expect(before).toBe(1);

  // API 并发恰一次：再造一个 chat 动作，两个不同 mutation_id 同时 confirm
  await setReplayMode("chat-tools");
  const session = (await api.post("/v1/chat/sessions", {})).body;
  await api.post(`/v1/chat/sessions/${session.id}/messages`, {
    content: "再建一个同样的任务", client_message_id: `e6-conc-${Date.now()}`,
  });
  const action = await waitFor("第二个动作入队", async () =>
    (await api.get("/v1/pending-actions?status=active&limit=10&offset=0")) as { items: Array<{ id: string; version: number; tool_name: string; status: string }> },
    (body) => body.items.some((item) => item.status === "PENDING" && item.tool_name === "task.create"));
  const target = action.items.find((item) => item.status === "PENDING" && item.tool_name === "task.create")!;
  const [first, second] = await Promise.all([
    api.post(`/v1/pending-actions/${target.id}/confirm`, { expected_version: target.version, mutation_id: "e6-conc-a" }),
    api.post(`/v1/pending-actions/${target.id}/confirm`, { expected_version: target.version, mutation_id: "e6-conc-b" }),
  ]);
  // 两次都以服务端状态收口（200：先结算 / 后到重入返回当前行），无 5xx
  expect([first.status, second.status]).toEqual([200, 200]);
  const after = await waitFor("并发结算后任务数稳定", () => countSuggestedTasks(api), (count) => count === before + 1);
  expect(after).toBe(before + 1); // 恰一次：并发双 confirm 只再多一条任务
});

test("e6-s5: provider 断供 → Chat 明确失败；计划/重排/Focus 仍可操作", async ({ app }) => {
  const { page } = app;
  await setReplayMode("unavailable");

  await page.getByRole("button", { name: "对话" }).click();
  await page.getByLabel("消息").fill("再帮我看一下今天的安排");
  await page.getByRole("button", { name: "发送" }).click();
  // 断供判定（§7 表）：明确失败面，不生成无依据的平滑回答
  await expect(page.getByText(/模型暂不可用|本轮失败/).first()).toBeVisible({ timeout: 130_000 });

  // 必须继续可用的路径：确定性计划 / 重排建议 / Focus
  await page.getByRole("button", { name: "今天" }).click();
  await expect(page.getByText("今日计划")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "专注" }).click();
  await expect(page.getByRole("heading", { name: "专注" })).toBeVisible();
});

test("e6-s6: 预算抑制 + L3 grant 自动派发 + 预算耗尽如实抑制", async ({ app }) => {
  const { page } = app;
  page.on("dialog", (dialog) => void dialog.accept());
  const api = await registerAndLogin();

  // 清 s1 遗留的 notify.push PENDING（工厂态偏好 → 确认即抑制，不占预算）
  await page.getByRole("button", { name: "确认", exact: true }).click();
  const stale = page.locator(".pending-action-card", { hasText: "通知" }).first();
  if (await stale.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await stale.getByRole("button", { name: /确认：/ }).click();
    await expect(stale.getByText("已完成").first()).toBeVisible({ timeout: 30_000 });
  }

  // UI 偏好面：类别 replan + 每日上限 2
  await page.getByRole("button", { name: "提醒" }).click();
  await expect(page.getByText(/今天已发送/)).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("新增类别").fill("replan");
  await page.getByRole("button", { name: "添加类别" }).click();
  await page.getByLabel(/条\/天/).fill("2");
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("已保存。")).toBeVisible({ timeout: 15_000 });

  // 触发 #1（无 grant）：notify.push PENDING（不自动、不耗预算）；确认 → 送达 1/2
  await seedOverrun(api, "概率论作业");
  await waitFor("触发 #1 动作入队", async () =>
    (await api.get("/v1/pending-actions?status=active&limit=10&offset=0")) as { items: Array<{ tool_name: string; status: string }> },
    (body) => body.items.some((item) => item.tool_name === "notify.push" && item.status === "PENDING"));
  await page.getByRole("button", { name: "确认", exact: true }).click();
  const card = page.locator(".pending-action-card", { hasText: "通知" }).first();
  await expect(card).toBeVisible({ timeout: 15_000 });
  await card.getByRole("button", { name: /确认：/ }).click();
  await expect(card.getByText("已完成").first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "提醒" }).click();
  await expect(page.getByText(/今天已发送 1 条 \/ 上限 2 条/)).toBeVisible({ timeout: 15_000 });

  // L3 grant（scope 值级 categories=["replan"]）→ 触发 #2 自动派发送达 2/2
  // （DOM 不自刷新：先 API 等落账，再进视图取新鲜渲染）
  await api.post("/v1/permissions/grants", { action: "notify.push", level: 3, scope: { categories: ["replan"] }, note: "e6" });
  await seedOverrun(api, "随机过程作业");
  await waitFor("grant 自动送达", async () =>
    (await api.get("/v1/notification-preferences")) as { sent_count: number },
    (prefs) => prefs.sent_count === 2);
  await page.getByRole("button", { name: "提醒" }).click();
  await expect(page.getByText(/今天已发送 2 条 \/ 上限 2 条/)).toBeVisible({ timeout: 15_000 });

  // 触发 #3：预算耗尽 → 不发送，如实抑制入历史账本（应用内建议仍在计划面）
  await seedOverrun(api, "数字逻辑作业");
  await waitFor("预算耗尽抑制落账", async () =>
    (await api.get("/v1/pending-actions?status=history&limit=10&offset=0")) as { items: Array<{ result: { summary?: string } | null }> },
    (body) => body.items.some((item) => /budget exhausted/i.test(item.result?.summary ?? "")));
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await page.getByRole("button", { name: "历史账本" }).click();
  await expect(page.getByText(/budget exhausted/i).first()).toBeVisible({ timeout: 15_000 });
});
