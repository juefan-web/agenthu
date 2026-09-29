import { defineConfig } from "@playwright/test";

/**
 * 构建包冒烟（B-5.2）：Playwright 经 CDP 连到**已运行**的 Tauri WebView2，
 * 不自行启动浏览器（round-4 验收已证明该驱动方式可行）。启动方式见同目录
 * README；测试串行（workers: 1）——主链是有状态的单一会话。
 */
export default defineConfig({
  testDir: ".",
  timeout: 180_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
});
