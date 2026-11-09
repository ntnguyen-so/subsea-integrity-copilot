/**
 * Owned-console navigation/replay integration: keyboard access, received evidence,
 * supported speed persistence and paused history returning to confirmed source time.
 * Requires local credentials/backend; saved monitoring inspection submits no questions.
 */
import { test, expect } from "@playwright/test";
import type { Projection, ReplaySession } from "../../web/ts/types";

test("recovery clears only obsolete connection errors after coherent state reload", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires the owned local operator environment.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const { replays }: { replays: ReplaySession[] } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find(row => row.latest_window_id && row.source_version === "pressure-v3");
  expect(replay).toBeDefined();
  let disconnected = true;
  await page.route(`**/api/replays/${replay!.id}/events?*`, route =>
    disconnected ? route.abort("failed") : route.continue());
  await page.goto("/?replay=" + encodeURIComponent(replay!.id) + "&view=live");
  await expect(page.locator("#notice")).toContainText("Event stream disconnected");
  disconnected = false;
  await expect(page.locator("#connection-state")).toHaveText("Connected · SSE", { timeout: 30000 });
  await expect(page.locator("#notice")).toBeEmpty();
  const windowsRoute = `**/api/replays/${replay!.id}/windows`;
  await page.route(windowsRoute, route => route.fulfill({
    status: 503, json: { detail: "Injected window history failure" },
  }));
  await page.locator("#reconnect").click();
  await expect(page.locator("#notice")).toContainText("Injected window history failure");
  await page.unroute(windowsRoute);
  await page.locator("#reconnect").click();
  await expect(page.locator("#connection-state")).toHaveText("Connected · SSE", { timeout: 30000 });
  await expect(page.locator("#notice")).toContainText("Injected window history failure");
});

test("projection refreshes do not starve a slow selected investigation read", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires the owned local operator environment.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.ok()).toBeTruthy();
  const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
  const created = await page.request.post("/api/replays", { headers, data: {
    scenario: "S1", seed: 2026, mode: "scripted", workflow: "agent_assisted",
    pause_on_anomaly: false, idempotency_key: crypto.randomUUID(),
  } });
  expect(created.ok()).toBeTruthy();
  const replay: ReplaySession = await created.json();
  const id = replay.id;
  for (let index = 0; index < 20; index++) {
    const stepped = await page.request.post(`/api/replays/${id}/control`, {
      headers, data: { action: "step", idempotency_key: `slow-receipt-${index}` },
    });
    expect(stepped.ok()).toBeTruthy();
  }
  await expect.poll(async () => {
    const current: Projection = await (await page.request.get(`/api/replays/${id}/projection`)).json();
    return current.tasks.some(task => task.role === "sensor_quality" && task.state === "SUCCEEDED");
  }, { timeout: 60000 }).toBe(true);
  const current: Projection = await (await page.request.get(`/api/replays/${id}/projection`)).json();
  const child = current.tasks.find(task => task.role === "sensor_quality" && task.state === "SUCCEEDED");
  expect(child).toBeDefined();
  await page.route(`**/api/replays/${id}/recordings`, route => route.fulfill({ json: { recordings: [] } }));
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await page.goto("/?replay=" + encodeURIComponent(id) + "&view=live");
  await page.locator("#investigation-technical > summary").click();
  let release = (): void => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  let reads = 0;
  await page.route(`**/api/tasks/${child!.id}`, async route => {
    reads++;
    await gate;
    await route.continue();
  });
  try {
    await page.locator(`#task-tree button[data-task="${child!.id}"]`).click();
    await expect.poll(() => reads).toBe(1);
    for (let index = 0; index < 3; index++) {
      const refreshed = page.waitForResponse(response =>
        new URL(response.url()).pathname === `/api/replays/${id}/windows` && response.ok());
      await page.locator("#reconnect").click();
      await refreshed;
      await page.waitForTimeout(200);
    }
    expect(reads).toBe(1);
  } finally {
    release();
  }
  await expect(page.locator("#task-detail")).toContainText(child!.id, { timeout: 30000 });
  expect(writes).toEqual([]);
});

test("recorded monitoring, sensor evidence and keyboard navigation work without question submission", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires the owned local operator environment.");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const { replays }: { replays: ReplaySession[] } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find(row => row.latest_window_id && row.source_version === "pressure-v3");
  expect(replay).toBeDefined();
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(replay!.id) + "&view=live");
  await expect(page.locator("#topology [data-sensor]")).not.toHaveCount(0);
  await expect(page.locator("#question-tools, #questions, #ask-form, #ask-submit, #tab-agents, #panel-agents")).toHaveCount(0);
  await page.locator("#topology [data-sensor]").first().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#sensor-title")).not.toHaveText("Select a sensor");
  await expect(page.locator("#channel-charts svg")).not.toHaveCount(0);
  await page.locator("#inspect-raw").click();
  await expect(page.locator("#tab-evidence")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".inspection-samples table")).toBeVisible();
  await page.locator("#source-audit > summary").click();
  await expect(page.locator("#raw-table table")).toBeVisible();
  await page.locator("#tab-evidence").focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#tab-evaluation")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#investigation-technical")).not.toHaveAttribute("open");
  await page.locator("#investigation-technical > summary").click();
  await expect(page.locator("#task-tree")).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("dashboard persists 20x and 30x speeds for live simulation and rejects unsupported speeds", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires the owned local operator environment.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.ok()).toBeTruthy();
  const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
  const created = await page.request.post("/api/replays", { headers, data: {
    scenario: "S1", seed: 2026, mode: "scripted", workflow: "sensor_alerts",
    idempotency_key: `high-speed-test-${Date.now()}`,
  } });
  expect(created.ok()).toBeTruthy();
  const replay: ReplaySession = await created.json();
  await page.route(`**/api/replays/${replay.id}/recordings`, route =>
    route.fulfill({ json: { recordings: [] } }));
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  await expect(page.locator("#speed")).toBeEnabled();
  for (const speed of [20, 30]) {
    const changed = page.waitForResponse(response =>
      response.url().endsWith(`/api/replays/${replay.id}/control`) && response.request().method() === "POST");
    await page.locator("#speed").selectOption(String(speed));
    expect((await changed).ok()).toBeTruthy();
    await expect(page.locator("#speed")).toHaveValue(String(speed));
    const response = await page.request.get(`/api/replays/${replay.id}/projection`);
    expect(response.ok()).toBeTruthy();
    const projection = await response.json();
    expect(projection.replay.speed).toBe(speed);
    expect(projection.replay.state).toBe("PAUSED");
    expect(projection.tasks).toEqual([]);
  }
  const invalid = await page.request.post(`/api/replays/${replay.id}/control`, { headers, data: {
    action: "speed", speed: 40, idempotency_key: "unsupported-speed",
  } });
  expect(invalid.status()).toBe(422);
});

test("paused live monitoring reviews a previous window then returns to the source before advancing", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires the owned local operator environment.");
  const login = await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
  const replay = await (await page.request.post("/api/replays", { headers, data: {
    scenario: "S1", seed: 2026, mode: "scripted", workflow: "sensor_alerts",
    idempotency_key: `live-time-buttons-${Date.now()}`,
  } })).json();
  for (let step = 0; step < 3; step++) {
    expect((await page.request.post(`/api/replays/${replay.id}/control`, { headers, data: {
      action: "step", idempotency_key: `initial-step-${step}`,
    } })).ok()).toBeTruthy();
  }
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  await expect(page.locator("#speed")).toBeEnabled();
  await page.locator("#speed").selectOption("5");
  const back = page.getByRole("button", { name: "Back 5s", exact: true });
  const forward = page.getByRole("button", { name: "Forward 5s", exact: true });
  await expect(back).toBeEnabled();
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await back.click();
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "5");
  const historical = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
  expect(historical.replay.clock_seconds).toBe(15);
  await forward.click();
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "10");
  expect(writes).toEqual([]);
  await forward.click();
  await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", "20");
  expect(writes).toHaveLength(1);
  const current = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
  expect(current.replay.state).toBe("PAUSED");
  expect(current.tasks).toEqual([]);
  let clock = current.replay.clock_seconds;
  for (const speed of [1, 2, 10, 20, 30]) {
    await page.locator("#speed").selectOption(String(speed));
    await expect(page.locator("#step-back")).toHaveText(`Back ${speed}s`);
    await expect(page.locator("#step")).toHaveText(`Forward ${speed}s`);
    await page.locator("#step").click();
    clock += speed;
    await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", String(clock));
  }
});
