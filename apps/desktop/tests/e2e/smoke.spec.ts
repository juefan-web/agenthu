import { test as base, chromium, expect, type BrowserContext, type Page } from "@playwright/test";
import { restartAppWithFreshCampusSession } from "./appProcess";

/**
 * 经 CDP 附着到构建包的 WebView2。连接地址可用 AGENTHU_CDP_URL 覆盖
 * （默认 http://127.0.0.1:9222，见 README 的启动命令）。
 */
const test = base.extend<{ app: { context: BrowserContext; page: Page }; freshApp: { context: BrowserContext; page: Page } }>({
  app: async ({}, use) => {
    const cdpUrl = process.env.AGENTHU_CDP_URL ?? "http://127.0.0.1:9222";
    const browser = await chromium.connectOverCDP(cdpUrl);
    const context = browser.contexts()[0];
    const page = context.pages()[0];
    if (!page) throw new Error("构建包 WebView 没有可达页面：确认 CDP 端口与启动参数");
    await use({ context, page });
    await browser.close();
  },
  // E2 前置态（round5 E 组修订）：清 campus.hold → 重启包，保证登录表单存在。
  // 仅在带凭据运行时执行重启；无凭据运行（E1）不动测试者手上的包。
  freshApp: async ({}, use) => {
    const cdpUrl = process.env.AGENTHU_CDP_URL ?? "http://127.0.0.1:9222";
    if (process.env.AGENTHU_TEST_USERNAME && process.env.AGENTHU_TEST_PASSWORD) {
      await restartAppWithFreshCampusSession(cdpUrl);
    }
    const browser = await chromium.connectOverCDP(cdpUrl);
    const context = browser.contexts()[0];
    const page = context.pages()[0];
    if (!page) throw new Error("构建包 WebView 没有可达页面：确认 CDP 端口与启动参数");
    await use({ context, page });
    await browser.close();
  },
});

const testUsername = process.env.AGENTHU_TEST_USERNAME;
const testPassword = process.env.AGENTHU_TEST_PASSWORD;
const backendUrl = process.env.AGENTHU_TEST_BACKEND_URL;
const backendEmail = process.env.AGENTHU_TEST_BACKEND_EMAIL;
const backendPassword = process.env.AGENTHU_TEST_BACKEND_PASSWORD;

test.describe("构建包主链冒烟", () => {
  test("应用启动并渲染外壳与校园登录表单", async ({ app }) => {
    const { page } = app;
    await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
    // 首跑修订：旧实例可能停在任务/专注/记忆视图（人工组遗留），标题放宽为
    // 任一主视图；「密码」加 exact——getByLabel 默认子串匹配会同时命中
    // 「Backend 密码」（Backend 登录表单同屏时 strict-mode 双匹配）。
    await expect(page.getByRole("heading", { name: /^(今天|任务|专注|记忆|讲解)$/ })).toBeVisible();
    await expect(page.getByText("校园未连接").or(page.getByText("已连接"))).toBeVisible();
    await expect(page.getByLabel("学号")).toBeVisible();
    await expect(page.getByLabel("密码", { exact: true })).toBeVisible();
  });

  test("登录进入 2FA 并按凭据完成主链", async ({ freshApp }) => {
    test.skip(!testUsername || !testPassword, "需要 AGENTHU_TEST_USERNAME / AGENTHU_TEST_PASSWORD");
    // 验证码由人工输入（≤5 分钟），加上前置态重启，整体放宽到 10 分钟
    test.setTimeout(10 * 60_000);
    const { page } = freshApp;

    // 重启后是全新校园会话：登录表单必须存在（缺失说明前置态未生效）
    await expect(page.getByLabel("学号")).toBeVisible({ timeout: 30_000 });

    await page.getByLabel("学号").fill(testUsername!);
    await page.getByLabel("密码", { exact: true }).fill(testPassword!);
    await page.getByRole("button", { name: "登录" }).click();

    // 未受信设备会出现方式选择；受信设备直接就绪——两分支都接受
    await expect(
      page.getByText("校园会话已连接").or(page.getByRole("combobox", { name: /验证方式/ })),
    ).toBeVisible({ timeout: 60_000 });

    const methodSelect = page.getByRole("combobox", { name: /验证方式/ });
    if (await methodSelect.isVisible({ timeout: 1_000 }).catch(() => false)) {
      // 2FA（round5 E 组修订）：不硬编码方式——从 combobox 实际可选项里选
      // （本账号只有企业微信/短信；TOTP 仅在真实存在时作为兜底）。验证码
      // 仍人工输入（密钥不出客户端），README 记录了半自动口径。
      const options = await methodSelect.locator("option").evaluateAll((elements) =>
        elements.map((element) => (element as HTMLOptionElement).value).filter(Boolean),
      );
      const method = options.find((value) => value !== "totp") ?? options[0];
      await methodSelect.selectOption(method);
      // 按钮文案随方式变化（totp=使用验证器，其余=发送验证码）
      await page.getByRole("button", { name: /使用验证器|发送验证码/ }).click();
      await page.getByLabel("验证码").waitFor({ timeout: 300_000 });
      test.info().annotations.push({ type: "note", description: `验证方式 ${method}：等待人工输入验证码（≤5 分钟）` });
      await expect(page.getByText("校园会话已连接")).toBeVisible({ timeout: 300_000 });
    }

    // 采集 → 同步 → 待同步计数归零
    await page.getByRole("button", { name: /采集并同步/ }).click();
    await expect(page.getByText(/上传 \d+ 条/)).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText("条待同步")).toBeHidden({ timeout: 60_000 });

    // 计划与专注入口可达（Backend 已配置时）
    await page.getByRole("button", { name: "专注", exact: true }).click();
    await expect(page.getByRole("heading", { name: "专注记录" })).toBeVisible();
  });

  // E3（round5 新增）：依赖 E2 的采集/同步状态，串行跑在完整链之后。
  test("派生任务出现且截止时间无偏移", async ({ app }) => {
    test.skip(!backendUrl || !backendEmail || !backendPassword,
      "需要 AGENTHU_TEST_BACKEND_URL / AGENTHU_TEST_BACKEND_EMAIL / AGENTHU_TEST_BACKEND_PASSWORD");
    const { page } = app;

    // Backend 未登录时从 UI 登录（backend.hold 持久，通常重启后仍就绪）
    const backendEmailField = page.getByLabel("Backend 邮箱");
    if (await backendEmailField.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await backendEmailField.fill(backendEmail!);
      await page.getByLabel("Backend 密码").fill(backendPassword!);
      await page.getByRole("button", { name: "登录 Backend" }).click();
    }
    await expect(page.getByRole("button", { name: "退出 Backend" })).toBeVisible({ timeout: 30_000 });

    // UI：存在带「校园采集」徽标的派生任务行，标题非空且不裸露 UUID
    await page.getByRole("button", { name: "任务", exact: true }).click();
    const badgeRow = page.locator(".task-row", { has: page.locator(".source-badge", { hasText: "校园采集" }) }).first();
    await expect(badgeRow).toBeVisible({ timeout: 30_000 });
    const badgeTitle = ((await badgeRow.locator("strong").textContent()) ?? "").trim();
    expect(badgeTitle.length, "派生任务标题非空").toBeGreaterThan(0);
    expect(badgeTitle, "派生任务标题不得裸露 UUID").not.toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );

    // 数据级（round5 B4 判据，时区无关形态——A review 修订）：due_at 的序列化
    // 偏移随 db 会话时区走（docker UTC 库返回 Z 形态，绝对时刻正确），断言
    // 偏移串会环境耦合地误报。改为绝对时刻配对：事件 data 是客户端载荷
    // 原样入库的 JSONB（+08:00 串恒定），派生任务的 due_at 时刻必须命中
    // 某条作业事件 data.deadline 的时刻——历史 8 小时偏移 bug（naive 被按
    // UTC 解释）下任务时刻 = 事件时刻 ±8h，必不命中。经 Node 直连读取
    // （页面 fetch 受 CSP 限制不经 IPC）。
    const loginResponse = await fetch(`${backendUrl}/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: backendEmail, password: backendPassword }),
    });
    if (!loginResponse.ok) throw new Error(`Backend 登录失败：HTTP ${loginResponse.status}`);
    const token = (await loginResponse.json()) as { access_token: string };
    const authHeaders = { Authorization: `Bearer ${token.access_token}` };
    // limit=200：默认 50 会截断真实作业量（round5 L2 短期过渡口径）
    const tasksResponse = await fetch(`${backendUrl}/v1/tasks?limit=200`, { headers: authHeaders });
    if (!tasksResponse.ok) throw new Error(`读取任务失败：HTTP ${tasksResponse.status}`);
    const tasks = (await tasksResponse.json()) as Array<{ title: string; due_at: string | null; source?: string }>;
    const derived = tasks.filter((task) => task.source === "onethu");
    expect(derived.length, "存在派生任务（source=onethu）").toBeGreaterThan(0);
    const withDeadline = derived.filter((task) => task.due_at !== null);
    expect(withDeadline.length, "存在带截止时间的派生任务").toBeGreaterThan(0);

    type EventPage = { items: Array<{ data: Record<string, unknown> }> };
    const eventDeadlines = new Set<number>();
    for (const type of ["study.assignment.discovered", "study.assignment.updated"] as const) {
      const eventsResponse = await fetch(`${backendUrl}/v1/events?type=${encodeURIComponent(type)}&limit=200`, {
        headers: authHeaders,
      });
      if (!eventsResponse.ok) throw new Error(`读取 ${type} 事件失败：HTTP ${eventsResponse.status}`);
      const page = (await eventsResponse.json()) as EventPage;
      for (const event of page.items) {
        const deadline = event.data["deadline"];
        if (typeof deadline !== "string" || !deadline) continue;
        // 事件侧是客户端原样载荷：+08:00 形态是本客户端的序列化不变量
        expect(deadline, `事件 data.deadline=${deadline} 应为客户端 +08:00 形态`).toMatch(/\+08:00$/);
        eventDeadlines.add(new Date(deadline).getTime());
      }
    }
    expect(eventDeadlines.size, "存在带截止时间的作业事件").toBeGreaterThan(0);
    for (const task of withDeadline) {
      const instant = new Date(task.due_at!).getTime();
      expect(
        eventDeadlines.has(instant),
        `任务「${task.title}」due_at=${task.due_at} 的时刻须与某条作业事件 data.deadline 一致（8 小时偏移判定）`,
      ).toBe(true);
    }

    // UI 与数据一致：抽样标题的任务行，「截止 …」应等于页面引擎对同一
    // due_at 的本地化渲染（同引擎同 Intl，避免 Node/Chromium 格式差异）。
    const sample = withDeadline.find((task) => task.title === badgeTitle) ?? withDeadline[0];
    const candidates = withDeadline.filter((task) => task.title === sample.title);
    const expectedLocals = await Promise.all(
      candidates.map((task) => page.evaluate((iso) => new Date(iso).toLocaleString(), task.due_at!)),
    );
    const sampleRows = page.locator(".task-row").filter({ hasText: sample.title });
    const rowCount = await sampleRows.count();
    expect(rowCount, `标题「${sample.title}」的任务行存在`).toBeGreaterThan(0);
    let matched = false;
    for (let index = 0; index < rowCount; index += 1) {
      const text = (await sampleRows.nth(index).textContent()) ?? "";
      if (expectedLocals.some((local) => text.includes(`截止 ${local}`))) matched = true;
    }
    expect(matched, `标题「${sample.title}」的任务行应显示与 due_at 一致的本地截止时间`).toBe(true);
  });
});
