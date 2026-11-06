import { test, expect } from "@playwright/test";

test("actual projection counters and every pipeline chip are explicit", async ({ page }) => {
  const password = process.env.SUBSEA_OPERATOR_PASSWORD;
  if (!password) throw new Error("Load the owned environment before browser qualification");
  const login = await page.context().request.post("/api/login", {
    data: { username: "operator", password },
  });
  expect(login.status()).toBe(200);
  const response = await page.context().request.get("/api/replays");
  expect(response.status()).toBe(200);
  const history: { replays: { id: string; latest_window_id: string | null; state: string; source_version: string; scenario: string }[] } = await response.json();
  const replay = history.replays.find(item => item.source_version === "pressure-v3" && item.scenario === "S1" && item.latest_window_id && item.state === "PAUSED")
    || history.replays.find(item => item.source_version === "pressure-v3" && item.scenario === "S1" && item.latest_window_id);
  if (!replay) throw new Error("Counter regression needs an existing replay");
  await page.goto("/");
  await expect(page.locator("#create-replay")).toBeEnabled();
  const projectionResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/replays/${replay.id}/projection`);
  await page.locator("#replay-history").selectOption(replay.id);
  const projection: { pack: { segments: { id: string }[] }; tasks: { state: string; model_calls: number }[] } = await (await projectionResponse).json();
  const calls = projection.tasks.reduce((sum, task) => sum + task.model_calls, 0);
  await expect(page.locator("#budget-usage")).toContainText(`${calls} model calls in listed tasks`);
  await expect(page.locator("#budget-usage")).toContainText("generation model-call limit: unknown");
  await page.locator(".engineer-details > summary").click();
  const chips = page.locator("#ontology .chip.entity");
  await expect(chips).toHaveCount(projection.pack.segments.length);
  for (const segment of projection.pack.segments) {
    await expect(page.locator("#ontology").getByRole("button", { name: `PIPELINE ${segment.id}`, exact: true })).toBeVisible();
  }
});

test("real sensor charts survive projection refreshes on a pinned window", async ({ page }) => {
  const password = process.env.SUBSEA_OPERATOR_PASSWORD;
  if (!password) throw new Error("Load the owned environment before browser qualification");
  const errors: string[] = [];
  const sensorReads: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (/\/api\/windows\/[^/]+\/sensors\/[^/]+$/.test(new URL(request.url()).pathname)) {
      sensorReads.push(request.url());
    }
  });
  const login = await page.context().request.post("/api/login", {
    data: { username: "operator", password },
  });
  expect(login.status()).toBe(200);
  const history = await page.context().request.get("/api/replays");
  expect(history.status()).toBe(200);
  const data: { replays: { id: string; latest_window_id: string | null; state: string; source_version: string; scenario: string }[] } = await history.json();
  const replay = data.replays.find(item => item.source_version === "pressure-v3" && item.scenario === "S1" && item.latest_window_id && item.state === "PAUSED")
    || data.replays.find(item => item.source_version === "pressure-v3" && item.scenario === "S1" && item.latest_window_id);
  if (!replay) throw new Error("Sensor regression needs an existing real replay with a computed window");
  await page.goto("/");
  await expect(page.locator("#create-replay")).toBeEnabled();
  await page.locator("#replay-history").selectOption(replay.id);
  await expect(page.locator("#selected-basis")).toContainText("CURRENT VIEW");
  const sensor = page.locator("#topology [data-sensor]").first();
  await sensor.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#selected-basis")).toContainText("CURRENT VIEW");
  await page.locator("#window-history").selectOption(replay.latest_window_id!);
  await expect(page.locator("#selected-basis")).toContainText("PINNED");
  const basis = await page.locator("#selected-basis").textContent();
  for (let index = 0; index < 3; index++) await page.locator("#reconnect").click();
  await expect(page.locator("#channel-charts svg")).toHaveCount(1, { timeout: 30_000 });
  await expect(page.locator("#selected-basis")).toHaveText(basis || "");
  await page.locator("#reconnect").click();
  await expect(page.locator("#connection-state")).toContainText("Connected", { timeout: 30_000 });
  await expect(page.locator("#channel-charts svg")).toHaveCount(1);
  await page.locator("#inspect-raw").click();
  await expect(page.locator("#raw-table table")).toBeVisible();
  await expect(page.locator("#raw-table")).toContainText("Original value / unit");
  await expect(page.locator("#raw-table tbody tr")).not.toHaveCount(0);
  expect(sensorReads).toHaveLength(1);
  expect(errors).toEqual([]);
});
