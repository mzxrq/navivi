import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Same React + Lingui macro setup as the app, so a component test can import files that use `t` / `<Trans>`.
export default defineConfig({
  plugins: [react({ babel: { plugins: ["@lingui/babel-plugin-lingui-macro"] } })],
  test: {
    // Plain Node is enough for the logic tests; a test that renders a component or hook opts in with
    // `// @vitest-environment jsdom` on its first line.
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
