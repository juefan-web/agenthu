import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    // tests/e2e 属 Playwright（构建包 CDP 冒烟），vitest 不得收集
    exclude: [...configDefaults.exclude, "tests/**"],
    // CI 上纯同步测试两次在默认 5s 超时（runner 被 vendor 重测试饿死，
    // M2 收口教训 3）——10s 只影响失败反馈延迟，不影响正常路径速度
    testTimeout: 10_000,
  },
});
