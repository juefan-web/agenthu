import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    // tests/e2e 属 Playwright（构建包 CDP 冒烟），vitest 不得收集
    exclude: [...configDefaults.exclude, "tests/**"],
  },
});
