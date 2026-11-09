/**
 * Real 1x scripted local replay: a clear monitoring warning must arrive independently
 * of pinned investigation evidence. Requires owned credentials/backend; the measured
 * warning path is an integration guarantee, not a population timeliness benchmark.
 */
import { test, expect } from "@playwright/test";
import { writeFile } from "node:fs/promises";

test("1x replay delivers a clear warning independently of the pinned investigation", async ({ page }) => {
  test.setTimeout(120_000);
  const password = process.env.SUBSEA_OPERATOR_PASSWORD;
  if (!password) throw new Error("Load the owned environment before browser qualification");
  const login = await page.context().request.post("/api/login", {
    data: { username: "operator", password },
  });
  expect(login.status()).toBe(200);
  const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
  const created = await page.context().request.post("/api/replays", {
    headers, data: { scenario: "S1", mode: "scripted", seed: 2026, idempotency_key: `timing-${Date.now()}` },
  });
  expect(created.status()).toBe(200);
  const replay = await created.json();
  for (let index = 0; index < 16; index++) {
    const stepped = await page.context().request.post(`/api/replays/${replay.id}/control`, {
      headers, data: { action: "step", idempotency_key: `timing-${index}` },
    });
    expect(stepped.status()).toBe(200);
  }
  await page.goto("/");
  await expect(page.locator("#create-replay")).toBeEnabled();
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  await expect(page.locator("#source-clock")).toContainText("80.0");
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "no_qualifying_event");
  const playing = page.waitForResponse(response => response.request().method() === "POST"
    && response.url().endsWith("/control") && response.request().postDataJSON().action === "play");
  const started = performance.now();
  await page.locator("#play").click();
  const reply = await playing;
  expect(reply.status()).toBe(200);
  const running = await reply.json();
  const acknowledged = performance.now();
  expect(running.speed).toBe(1);
  expect(running.clock_seconds).toBe(80);
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "possible_leak", { timeout: 75_000 });
  const observed = performance.now();
  await expect(page.locator("#monitoring-warning")).toContainText("Do not wait for the AI report");
  const basis = await page.locator("#monitoring-warning").getAttribute("data-snapshot");
  const snapshotResponse = await page.context().request.get(`/api/windows/${basis}`);
  expect(snapshotResponse.status()).toBe(200);
  const snapshot = await snapshotResponse.json();
  const sourceDelay = snapshot.clock_seconds - 90;
  const onsetDelayBounds = [(observed - acknowledged) / 1000 - 10, (observed - started) / 1000 - 10];
  expect(sourceDelay).toBeGreaterThanOrEqual(0);
  expect(sourceDelay).toBeLessThanOrEqual(120);
  expect(onsetDelayBounds[0]).toBeGreaterThanOrEqual(0);
  expect(onsetDelayBounds[1]).toBeLessThanOrEqual(120);
  await page.locator("#play").click();
  await expect(page.locator("#play")).toHaveText("Play");
  const history = await page.context().request.get(`/api/replays/${replay.id}/windows`);
  const previous = (await history.json()).windows.find((window: { end_seconds: number }) => window.end_seconds === 75);
  await page.locator("#window-history").selectOption(previous.id);
  await expect(page.locator("#event-summary")).toContainText("no event");
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "possible_leak");
  await expect(page.locator("#monitoring-warning")).not.toHaveAttribute("data-snapshot", previous.id);
  await page.context().setOffline(true);
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "unavailable", { timeout: 15_000 });
  await expect(page.locator("#monitoring-warning")).toContainText("Last recorded assessment: POSSIBLE LEAK");
  await writeFile("docs\\evidence\\warning-browser-timing.json", JSON.stringify({
    mode: "scripted", passed: true, replay_id: replay.id, replay_speed: 1,
    known_source_onset_seconds: 90, play_start_source_seconds: 80,
    warning_snapshot_id: basis, source_onset_to_warning_basis_seconds: sourceDelay,
    wall_play_request_to_observed_warning_seconds: (observed - started) / 1000,
    estimated_wall_onset_to_observed_warning_bounds_seconds: onsetDelayBounds,
    target_seconds: 120,
    limitations: [
      "One local 1x synthetic replay; warm-up preloaded through second 80.",
      "Onset wall time bounded by the play request interval; DOM assertion includes observation overhead.",
      "SCRIPTED agents, not hosted report latency; no physical sensor, external notification or human acknowledgement.",
      "Not a load test or field latency SLO.",
    ],
  }, null, 2) + "\n");
});
