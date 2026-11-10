/**
 * Owned local integration: monitoring loads without the removed System details and
 * sensor charts survive refresh while pinned to immutable evidence. Requires loaded
 * operator credentials and an existing backend/run, not a fabricated browser dataset.
 */
import { test, expect } from "@playwright/test";

test("System details are removed without breaking monitoring", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
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
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  const projection: { pack: { sensors: { id: string }[] } } = await (await projectionResponse).json();
  await expect(page.locator("#system-details, #system-connection, #budget-usage")).toHaveCount(0);
  await expect(page.locator("#topology [data-sensor]")).toHaveCount(projection.pack.sensors.length);
  await expect(page.locator("#source-clock")).toContainText("UTC");
  await expect(page.locator("#connection-state")).toBeVisible();
  await expect(page.locator(".engineer-details")).toHaveCount(0);
  expect(errors).toEqual([]);
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
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  await expect(page.locator("#selected-basis")).toContainText("CURRENT VIEW");
  const sensor = page.locator("#topology [data-sensor]").first();
  await sensor.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#selected-basis")).toContainText("CURRENT VIEW");
  await page.locator("#window-history").selectOption(replay.latest_window_id!);
  await expect(page.locator("#selected-basis")).toContainText("PINNED");
  await expect(page.locator("#channel-charts svg")).toHaveCount(1, { timeout: 30_000 });
  const basis = await page.locator("#selected-basis").textContent();
  const pinnedReads = sensorReads.length;
  for (let index = 0; index < 3; index++) await page.locator("#reconnect").click();
  await expect(page.locator("#channel-charts svg")).toHaveCount(1, { timeout: 30_000 });
  await expect(page.locator("#selected-basis")).toHaveText(basis || "");
  await page.locator("#reconnect").click();
  await expect(page.locator("#connection-state")).toContainText("Connected", { timeout: 30_000 });
  await expect(page.locator("#channel-charts svg")).toHaveCount(1);
  expect(sensorReads).toHaveLength(pinnedReads);
  await page.locator("#inspect-raw").click();
  await page.locator("#source-audit > summary").click();
  await expect(page.locator("#raw-table table")).toBeVisible();
  await expect(page.locator("#raw-table")).toContainText("Original value / unit");
  await expect(page.locator("#raw-table tbody tr")).not.toHaveCount(0);
  expect(new Set(sensorReads).size).toBe(sensorReads.length);
  expect(errors).toEqual([]);
});
