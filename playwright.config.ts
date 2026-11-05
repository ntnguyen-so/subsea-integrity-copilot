import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:8086",
    channel: "chrome",
    headless: true,
    viewport: { width: 1600, height: 1100 },
    trace: "off",
    video: "off",
  },
});
