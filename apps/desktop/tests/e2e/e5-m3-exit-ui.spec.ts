import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test as base, chromium, expect, type BrowserContext, type Page } from "@playwright/test";

/**
 * E5 — M3 出口场景 UI 半边（#44 讲解页 + #46 上传链合入后）。场景定义见
 * TASKS/m3-e5-exit-scenario.md Phase 2；后端半边（API 全链）见
 * e5-m3-exit.spec.ts。
 *
 * 覆盖：构建包内 Backend 登录 → 讲解视图 → 同意门（读文案→开启）→ 提问
 * （带 Learning Memory）→ 引用标记/引用卡渲染与跳转 → 删 Memory 后同问
 * 不再体现 → 历史删除。课件仍由 API 造数（/v1/files 上传）——B 上传 UI
 * 的真机链（campus 会话）是验收轮人工项，不在本 spec。
 *
 * 前置：构建包以 CDP 运行（README 启动命令）；`AGENTHU_E5_UI=1`；
 * `AGENTHU_TEST_BACKEND_URL` 与构建期 `VITE_BACKEND_URL` 同源（A 栈）。
 */

const backendUrl = process.env.AGENTHU_TEST_BACKEND_URL;
const backendEmail = process.env.AGENTHU_TEST_BACKEND_EMAIL;
const backendPassword = process.env.AGENTHU_TEST_BACKEND_PASSWORD;

const COURSE = "信号与系统E5UI";
const QUESTION = "What does the sampling theorem require?";
const RUN = `e5ui-${Date.now()}`;

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
test.skip(process.env.AGENTHU_E5_UI !== "1",
  "E5 UI 半边需 AGENTHU_E5_UI=1（构建包 + CDP，见 tests/e2e/README.md）");

interface Api {
  get: (path: string) => Promise<unknown>;
  post: (path: string, body?: unknown, method?: string) => Promise<unknown>;
  upload: (path: string, filename: string, contentType: string, bytes: Buffer, fields: Record<string, string>) => Promise<unknown>;
}

async function registerAndLogin(): Promise<{ api: Api; email: string }> {
  const email = `${RUN}@e5.test`;
  const password = "e5ui-pass-123456";
  const register = await fetch(`${backendUrl}/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: `E5 UI ${RUN}` }),
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
  const api: Api = {
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
      if (!res.ok) throw new Error(`${method} ${path} → ${res.status}：${(await res.text()).slice(0, 200)}`);
      return res.status === 204 ? null : res.json();
    },
    upload: async (path, filename, contentType, bytes, fields) => {
      const form = new FormData();
      form.append("file", new Blob([new Uint8Array(bytes)], { type: contentType }), filename);
      for (const [key, value] of Object.entries(fields)) form.append(key, value);
      const res = await fetch(`${backendUrl}${path}`, { method: "POST", headers: auth(), body: form });
      if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
      return res.json();
    },
  };
  return { api, email };
}

async function waitFor<T>(label: string, probe: () => Promise<T>, done: (value: T) => boolean, timeoutMs = 90_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await probe();
    if (done(value)) return value;
    if (Date.now() > deadline) throw new Error(`等待超时：${label}`);
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
}

test("e5-ui: 讲解页全链（登录→同意→提问→引用可核→删记忆不再体现→历史删除）", async ({ app }) => {
  const { page } = app;
  page.on("dialog", (dialog) => void dialog.accept());

  // API 造数：上传 fixture 课件 + 建 Learning Memory
  const { api } = await registerAndLogin();
  const fixture = readFileSync(fileURLToPath(new URL("./fixtures/e5-lecture.pdf", import.meta.url)));
  const file = (await api.upload("/v1/files", "e5-lecture.pdf", "application/pdf", fixture, { course_name: COURSE })) as { id: string };
  await waitFor("chunks clean", async () =>
    (await api.get(`/v1/files/${file.id}/chunks?limit=50&offset=0`)) as { items: { scan_status: string }[] },
    (body) => body.items.length >= 2 && body.items.every((chunk) => chunk.scan_status === "clean"));
  const memory = (await api.post("/v1/memory", {
    content: "E5 UI 记忆：用户偏好中文讲解对照英文原文", level: 1, confidence: 0.9, domain: "study",
  })) as { id: string };

  // 构建包内 Backend 登录（构建期源 = AGENTHU_TEST_BACKEND_URL 同源）。
  // 残留登录态先退出（token 在 Stronghold 跨重启存活）；成功信号 =
  // 登录表单消失（仅未登录渲染）；后续「课程讲解」标题是 backend 就绪
  // 的正向证据（侧栏「已连接」是校园会话状态，不能用作此断言）。
  const backendLogout = page.getByRole("button", { name: "退出 Backend" });
  if (await backendLogout.isVisible()) {
    await backendLogout.click();
    await expect(backendLogout).toBeHidden({ timeout: 10_000 });
  }
  await page.getByLabel("Backend 邮箱").fill(`${RUN}@e5.test`);
  await page.getByLabel("Backend 密码").fill("e5ui-pass-123456");
  await page.getByRole("button", { name: "登录 Backend" }).click();
  await expect(page.getByRole("button", { name: "登录 Backend" })).toBeHidden({ timeout: 30_000 });

  // 讲解视图 + 选课 → 同意门（先见文案，开启后回显已开启）
  await page.getByRole("button", { name: "讲解" }).click();
  await expect(page.getByRole("heading", { name: "课程讲解" })).toBeVisible();
  await page.getByLabel("课程").fill(COURSE);
  await expect(page.getByText(/开启前请阅读授权说明/)).toBeVisible();
  expect((await page.getByText(/30/).allTextContents()).length).toBeGreaterThan(0); // 文案含 ≤30 天披露
  await page.getByRole("button", { name: "同意并开启" }).click();
  await expect(page.getByText(/资料问答已开启/)).toBeVisible({ timeout: 30_000 });

  // 提问 1（记忆在上下文）：引用标记 + 引用卡（文件名+页码）+ 记忆参考句。
  // 注：ask 成功会 invalidate 历史，「最新回答卡」与「历史列表里的同一条」
  // 同时渲染 → 同文案出现两处，断言一律 .first()。
  await page.getByLabel("问题").fill(QUESTION);
  await page.getByRole("button", { name: "提问" }).click();
  await expect(page.getByTitle("跳到引用").first()).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/e5-lecture\.pdf · 第/).first()).toBeVisible();
  await expect(page.getByText(/已落地 · 1 条引用 · 模型/).first()).toBeVisible();
  await expect(page.getByText(/参考学习记忆：/).first()).toBeVisible();
  // 双向跳转：引用卡→标记方向置高亮并滚动（onHighlight 在卡按钮上）；
  // 标记→卡方向只滚动。两个方向各走一遍。
  await page.getByText(/e5-lecture\.pdf · 第/).first().click();
  await expect(page.locator(".citation-marker.highlighted").first()).toBeVisible();
  await page.getByTitle("跳到引用").first().click();

  // 删 Learning Memory → 同问再问 → 回答不再体现（UI 侧断言）
  await api.post(`/v1/memory/${memory.id}`, undefined, "DELETE");
  await page.getByLabel("问题").fill(QUESTION);
  await page.getByRole("button", { name: "提问" }).click();
  await expect(page.getByText(/没有参考任何学习记忆/).first()).toBeVisible({ timeout: 90_000 });

  // 历史与删除入口（confirm 已自动接受）
  await page.getByText(/展开历史（2 条）/).click();
  await page.getByRole("button", { name: "删除" }).first().click();
  await expect(page.getByText(/展开历史（1 条）/)).toBeVisible({ timeout: 30_000 });
});
