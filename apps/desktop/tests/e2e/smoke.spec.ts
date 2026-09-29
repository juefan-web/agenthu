import { test as base, chromium, expect, type BrowserContext, type Page } from "@playwright/test";

/**
 * 经 CDP 附着到构建包的 WebView2。连接地址可用 AGENTHU_CDP_URL 覆盖
 * （默认 http://127.0.0.1:9222，见 README 的启动命令）。
 */
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

const testUsername = process.env.AGENTHU_TEST_USERNAME;
const testPassword = process.env.AGENTHU_TEST_PASSWORD;

test.describe("构建包主链冒烟", () => {
  test("应用启动并渲染外壳与校园登录表单", async ({ app }) => {
    const { page } = app;
    await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "今天" })).toBeVisible();
    await expect(page.getByText("校园未连接").or(page.getByText("已连接"))).toBeVisible();
    await expect(page.getByLabel("学号")).toBeVisible();
    await expect(page.getByLabel("密码")).toBeVisible();
  });

  test("登录进入 2FA 并按凭据完成主链", async ({ app }) => {
    test.skip(!testUsername || !testPassword, "需要 AGENTHU_TEST_USERNAME / AGENTHU_TEST_PASSWORD");
    const { page } = app;

    await page.getByLabel("学号").fill(testUsername!);
    await page.getByLabel("密码").fill(testPassword!);
    await page.getByRole("button", { name: "登录" }).click();

    // 未受信设备会出现方式选择；受信设备直接就绪——两分支都接受
    await expect(
      page.getByText("校园会话已连接").or(page.getByRole("combobox", { name: /验证方式/ })),
    ).toBeVisible({ timeout: 60_000 });

    const methodSelect = page.getByRole("combobox", { name: /验证方式/ });
    if (await methodSelect.isVisible({ timeout: 1_000 }).catch(() => false)) {
      // 2FA：TOTP 码无法自动生成（密钥不出客户端），此步人工输入后由
      // 等待循环接续；README 记录了半自动口径。
      await methodSelect.selectOption("totp");
      await page.getByRole("button", { name: "使用验证器" }).click();
      await page.getByLabel("验证码").waitFor({ timeout: 300_000 });
      test.info().annotations.push({ type: "note", description: "等待人工输入验证码（≤5 分钟）" });
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
});
