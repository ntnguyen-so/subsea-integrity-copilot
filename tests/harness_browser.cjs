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
    await page.goto(new URL(`/?replay=${encodeURIComponent(replayId)}&view=live`, url).href);
    await page.locator("#investigation-technical > summary").click();
    await Promise.all([
      page.waitForResponse(response =>
        response.url() === new URL(`/api/tasks/${taskId}`, url).href
          && response.status() === 200),
      page.locator(`#task-tree button[data-task="${taskId}"]`).click(),
    ]);
    await expect(page.locator("#history-investigation")).toBeVisible({ timeout: 15000 });
    await expect(page.locator("#history-investigation")).toContainText("Executed evidence checks");
    const response = await context.request.get(`${url}/api/tasks/${taskId}`);
    const detail = await response.json();
    expect(detail.task.state).toBe("SUCCEEDED");
    expect(detail.harness_events.some(event => event.type === "harness.started")).toBeTruthy();
    expect(detail.harness_events.some(event => event.type === "validation.repair_requested")).toBeTruthy();
    const denied = await context.request.post(`${url}/api/replays/${replayId}/questions`, {
      headers: { "X-CSRF-Token": session.csrf_token },
      data: {
        question: "What caused the event? denial control", snapshot_id: detail.task.snapshot_id,
        mode: "scripted", idempotency_key: "denial",
      },
    });
    expect(denied.status()).toBe(200);
    const deniedTask = await denied.json();
    await expect.poll(async () => {
      const current = await context.request.get(`${url}/api/tasks/${deniedTask.id}`);
      expect(current.ok()).toBeTruthy();
      const record = await current.json();
      const types = record.harness_events.map(event => event.type);
      return types.includes("validation.rejected") && types.includes("validation.repair_requested");
    }, { timeout: 30000 }).toBe(true);
    await page.locator(`#task-tree button[data-task="${deniedTask.id}"]`).click();
    await expect(page.locator("#task-detail")).toContainText(deniedTask.id);
    await expect(page.locator("#tab-audit, #tab-agents, #event-feed")).toHaveCount(0);
    expect(failures).toEqual([]);
    await context.close();
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
