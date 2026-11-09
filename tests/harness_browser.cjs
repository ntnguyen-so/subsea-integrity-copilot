// Browser leg for a pre-existing harness task: argv supplies local URL, replay and
// task IDs; SUBSEA_OPERATOR_PASSWORD supplies access. Checks public executed receipts,
// durable validation/repair events and a denial-control submission, never private
// reasoning. Requires running services/Chrome; posts a scripted question on each run
// (stable idempotency key), so it is an integration probe rather than read-only export.
const { chromium, expect } = require("@playwright/test");

(async () => {
  const [url, replayId, taskId] = process.argv.slice(2);
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const context = await browser.newContext();
    const login = await context.request.post(`${url}/api/login`, {
      data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
    });
    expect(login.status()).toBe(200);
    const session = await login.json();
    const page = await context.newPage();
    const failures = [];
    page.on("pageerror", error => failures.push(error.message));
    await page.goto(url);
    await page.locator("#replay-history").selectOption(replayId);
    await page.locator("#tab-agents").click();
    await page.locator("#execution-details > summary").click();
    await Promise.all([
      page.waitForResponse(response =>
        response.url() === new URL(`/api/tasks/${taskId}`, url).href
          && response.status() === 200),
      page.locator(`[data-task="${taskId}"]`).click(),
    ]);
    await expect(page.locator("#history-investigation")).toBeVisible({ timeout: 15000 });
    await expect(page.locator("#history-investigation")).toContainText("Executed evidence checks");
    const response = await context.request.get(`${url}/api/tasks/${taskId}`);
    const detail = await response.json();
    expect(detail.task.state).toBe("SUCCEEDED");
    expect(detail.harness_events.some(event => event.type === "harness.started")).toBeTruthy();
    expect(detail.harness_events.some(event => event.type === "validation.repair_requested")).toBeTruthy();
    await page.locator("#tab-audit").click();
    await page.locator("#event-filter").selectOption("answer");
    const denied = await context.request.post(`${url}/api/replays/${replayId}/questions`, {
      headers: { "X-CSRF-Token": session.csrf_token },
      data: {
        question: "What caused the event? denial control", snapshot_id: detail.task.snapshot_id,
        mode: "scripted", idempotency_key: "denial",
      },
    });
    expect(denied.status()).toBe(200);
    await expect(page.locator("#event-feed")).toContainText("validation.rejected", {
      timeout: 15000,
    });
    await expect(page.locator("#event-feed")).toContainText("validation.repair_requested", {
      timeout: 15000,
    });
    expect(failures).toEqual([]);
    await context.close();
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
