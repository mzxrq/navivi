import { defineConfig } from "@playwright/test";

// Browser tests of the UI with Tauri mocked (tests/e2e). Reuses a running `npm run dev` / `npm run tauri dev` on :1420.
export default defineConfig({
  testDir: "tests/e2e",
  use: { baseURL: "http://127.0.0.1:1420", channel: "msedge" }, // the Edge already on Windows: no browser download
  webServer: { command: "npm run dev", url: "http://127.0.0.1:1420", reuseExistingServer: true, timeout: 120_000 },
});
