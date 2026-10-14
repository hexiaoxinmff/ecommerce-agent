import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Vitest 配置（仅测试用；构建仍走 vite.config.ts + tsc -b）
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: false,
    css: true,
  },
});
