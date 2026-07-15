import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { VitestReporter } from "tdd-guard-vitest";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    css: true,
    exclude: ["**/e2e/**", "**/node_modules/**"],
    // tdd-guard reads results from <repo>/.claude/tdd-guard/data — the
    // reporter keeps the UI lane visible to the TDD hook, harmless in CI.
    reporters: [
      "default",
      new VitestReporter({ projectRoot: path.resolve(__dirname, "..") }),
    ],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
