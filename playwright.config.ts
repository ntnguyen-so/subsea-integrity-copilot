/**
 * Browser qualification against an already-running local console, not a server
 * launcher. One worker protects shared replay state; individual specs opt in to
 * hosted work/owned credentials. Trace/video capture is off to avoid content capture.
 * package.json defines build/typecheck entry points; tsconfig.json owns compiler
 * policy. Both remain machine-readable JSON without explanatory comments.
 */
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  // Real wall-time allowance for backend workflows; unrelated to replay speed.
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
