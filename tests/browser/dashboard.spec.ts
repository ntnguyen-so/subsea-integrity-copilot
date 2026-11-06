import { test, expect, type Page } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import type { Projection } from "../../web/ts/types";

async function prepare(page: Page, scenario: string, steps: number, mode = "scripted"): Promise<{ id: string; headers: Record<string, string> }> {
  const password = process.env.SUBSEA_OPERATOR_PASSWORD;
  if (!password) throw new Error("Load the owned environment before browser qualification");
  const login = await page.request.post("/api/login", { data: { username: "operator", password } });
  expect(login.status()).toBe(200);
  const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
  const created = await page.request.post("/api/replays", {
    headers, data: { scenario, mode, seed: 2026, idempotency_key: `dashboard-${Date.now()}-${scenario}` },
  });
  expect(created.status()).toBe(200);
  const { id } = await created.json();
  for (let index = 0; index < steps; index++) {
    const stepped = await page.request.post(`/api/replays/${id}/control`, {
      headers, data: { action: "step", idempotency_key: `dashboard-step-${index}` },
    });
    expect(stepped.status()).toBe(200);
  }
  await page.goto("/");
  await expect(page.locator("#create-replay")).toBeEnabled();
  await page.locator("#replay-history").selectOption(id);
  await expect(page.locator("#channel-charts svg")).toHaveCount(1);
  return { id, headers };
}

test("brief geometry, correct wall sides and manual comparison agree with actual evidence", async ({ page }) => {
  const { id } = await prepare(page, "S1", 37);
  const response = await page.request.get(`/api/replays/${id}/projection`);
  const projection: Projection = await response.json();
  const figure = await readFile("docs\\assets\\pressure-leak-vs-sensor-faults.svg", "utf8");
  const geometry = await page.evaluate(source => {
    const brief = new DOMParser().parseFromString(source, "image/svg+xml").querySelector('[data-scenario="S1"]')!;
    const segments = [...brief.querySelectorAll("g[data-segment-id]")].map(group => {
      const id = group.getAttribute("data-segment-id")!;
      const expected = group.querySelector("path")!.getAttribute("d")!.match(/-?\d+(?:\.\d+)?/g)!.map(Number);
      const actual = document.querySelector<SVGPolylineElement>(`#topology .pipe[data-segment-id="${id}"]`)!;
      const a = actual.points.getItem(0), b = actual.points.getItem(1);
      const [x1, y1, x2, y2] = expected;
      const signedOffset = (x: number, y: number, sx: number, sy: number, ex: number, ey: number): number =>
        ((ex - sx) * (y - sy) - (ey - sy) * (x - sx)) / Math.hypot(ex - sx, ey - sy);
      const fraction = (x: number, y: number, sx: number, sy: number, ex: number, ey: number): number =>
        ((x - sx) * (ex - sx) + (y - sy) * (ey - sy)) / ((ex - sx) ** 2 + (ey - sy) ** 2);
      const sensors = [...group.querySelectorAll("circle[data-sensor-id]")].map(sensor => {
        const sensorId = sensor.getAttribute("data-sensor-id")!;
        const circle = document.querySelector<SVGCircleElement>(`#topology [data-sensor="${sensorId}"] circle`)!;
        const x = circle.cx.baseVal.value, y = circle.cy.baseVal.value;
        const bx = Number(sensor.getAttribute("cx")), by = Number(sensor.getAttribute("cy"));
        return {
          id: sensorId, actualOffset: signedOffset(x, y, a.x, a.y, b.x, b.y),
          briefOffset: signedOffset(bx, by, x1, y1, x2, y2),
          actualFraction: fraction(x, y, a.x, a.y, b.x, b.y),
          briefFraction: fraction(bx, by, x1, y1, x2, y2),
        };
      });
      return { id, expected, actual: [a.x, a.y, b.x, b.y], sensors };
    });
    return segments;
  }, figure);
  expect(geometry).toHaveLength(3);
  const trunk = geometry.find(segment => segment.id === "P1")!;
  const scale = (trunk.actual[3] - trunk.actual[1]) / (trunk.expected[3] - trunk.expected[1]);
  expect(scale).toBeGreaterThan(0);
  const dx = trunk.actual[0] - trunk.expected[0] * scale, dy = trunk.actual[1] - trunk.expected[1] * scale;
  for (const segment of geometry) {
    for (let index = 0; index < 4; index++) expect(segment.actual[index]).toBeCloseTo(segment.expected[index] * scale + (index % 2 ? dy : dx), 3);
    for (const sensor of segment.sensors) {
      expect(sensor.actualOffset, sensor.id).toBeCloseTo(sensor.briefOffset, 1);
      expect(sensor.actualFraction, sensor.id).toBeCloseTo(sensor.briefFraction, 4);
    }
  }
  await expect(page.locator("#topology [data-sensor]")).toHaveCount(24);
  const interval = page.locator("#topology .inspection-interval");
  await expect(interval).toHaveAttribute("data-segment-id", "P1");
  await expect(interval).toHaveAttribute("data-start-m", "200");
  await expect(interval).toHaveAttribute("data-end-m", "600");
  const intervalFractions = await interval.evaluate(element => {
    const line = element as SVGPolylineElement;
    const pipe = document.querySelector<SVGPolylineElement>('#topology .pipe[data-segment-id="P1"]')!;
    const start = pipe.points.getItem(0).y, end = pipe.points.getItem(1).y;
    return [0, 1].map(index => (line.points.getItem(index).y - start) / (end - start));
  });
  expect(intervalFractions[0]).toBeCloseTo(.25, 4);
  expect(intervalFractions[1]).toBeCloseTo(.75, 4);
  expect((await page.locator("#topology").boundingBox())!.y).toBeLessThan(700);
  expect((await page.locator("#channel-charts svg").boundingBox())!.y).toBeLessThan(800);
  await expect(page.locator("#comparison-panel")).toBeHidden();
  await page.getByRole("checkbox", { name: "Compare P2-ST4-A", exact: true }).check();
  await page.getByRole("checkbox", { name: "Compare P3-ST1-B", exact: true }).check();
  await page.locator("#compare-sensors").click();
  await expect(page.locator("#comparison-panel")).toBeVisible();
  await expect(page.locator("#comparison-charts svg")).toHaveCount(2);
  await expect(page.locator("#comparison-charts article > h3")).toHaveText([
    "P2-ST4-A / gateway-P2-1", "P3-ST1-B / gateway-P3-0",
  ]);
  await expect(page.locator("#window-history")).toHaveValue(projection.latest_window!.id);
  await expect(page.locator("#selected-basis")).toBeVisible();
  await expect(page.locator("#sensor-list-basis")).toContainText("pinned review");
  await page.getByRole("button", { name: "Trend P1-ST2-A", exact: true }).click();
  await expect(page.locator("#channel-charts [data-anomaly=true]")).not.toHaveCount(0);
  await expect(page.locator("#trend-basis")).toContainText("PINNED TREND");
  await page.locator("#clear-comparison").click();
  await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(0);
  await expect(page.locator("#compare-sensors")).toHaveText("Compare event / fault sensors");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "runtime/dashboard-engineer-desktop.png", fullPage: true });
});

test("server-confirmed clock and selected trends stay live; only explicit review pins them", async ({ page }) => {
  const { id, headers } = await prepare(page, "S6", 14);
  await page.getByRole("button", { name: "Trend P2-ST3-A", exact: true }).click();
  await expect(page.locator("#trend-basis")).toContainText("LIVE TREND");
  await expect(page.locator("#channel-charts circle")).not.toHaveCount(0);
  await page.route("**/api/windows/*/sensors/P2-ST3-A", async route => {
    await new Promise(resolve => setTimeout(resolve, 1200));
    await route.continue();
  });
  const firstBasis = await page.locator("#selected-basis").textContent();
  await page.locator("#speed").selectOption("10");
  await page.locator("#play").click();
  const initial = Number(await page.locator("#source-clock").getAttribute("data-seconds"));
  await expect.poll(async () => Number(await page.locator("#source-clock").getAttribute("data-seconds"))).toBeGreaterThan(initial + 5);
  await expect(page.locator("#selected-basis")).not.toHaveText(firstBasis!);
  for (let frame = 0; frame < 4; frame++) {
    await page.waitForTimeout(500);
    expect(await page.locator("#channel-charts circle").count()).toBeGreaterThan(0);
    const snapshots = await page.evaluate(() => [
      document.getElementById("channel-charts")!.getAttribute("data-snapshot"),
      document.getElementById("topology")!.getAttribute("data-snapshot"),
    ]);
    expect(snapshots[0]).toBe(snapshots[1]);
  }
  await expect(page.locator("#sensor-title")).toContainText("P2-ST3-A");
  await expect(page.locator("#trend-basis")).toContainText("LIVE TREND");
  const values = await page.locator("#source-clock").evaluate(element => [
    element.getAttribute("data-seconds"), element.getAttribute("data-confirmed-seconds"),
  ]);
  expect(values[0]).toBe(values[1]);
  await expect(page.locator("#clock-basis")).toContainText("Server-confirmed");
  await page.locator("#inspect-raw").click();
  const pinned = await page.locator("#selected-basis").textContent();
  const latest = await page.locator("#live-bounds").textContent();
  await expect(page.locator("#raw-table tbody tr")).not.toHaveCount(0);
  await expect(page.locator("#live-bounds")).not.toHaveText(latest!);
  await expect(page.locator("#selected-basis")).toHaveText(pinned!);
  await page.unrouteAll({ behavior: "wait" });
  await page.context().setOffline(true);
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "unavailable");
  await expect(page.locator("#clock-basis")).toContainText("NOT CURRENT");
  const frozen = await page.locator("#source-clock").getAttribute("data-seconds");
  await page.waitForTimeout(1000);
  await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", frozen!);
  await page.context().setOffline(false);
  await expect(page.locator("#connection-state")).toContainText("Connected", { timeout: 30_000 });
  const stopped = await page.request.post(`/api/replays/${id}/control`, {
    headers,
    data: { action: "pause", idempotency_key: "dashboard-stop" },
  });
  expect(stopped.status()).toBe(200);
});

test("pinning a pending live read never presents the previous window as the new evidence", async ({ page }) => {
  const { id, headers } = await prepare(page, "S6", 14);
  let release = (): void => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/windows/*/sensors/P1-ST1-A", async route => { await gate; await route.continue(); });
  try {
    const nextRead = page.waitForRequest(request => /\/api\/windows\/[^/]+\/sensors\/P1-ST1-A$/.test(new URL(request.url()).pathname));
    await page.locator("#speed").selectOption("10");
    await page.locator("#play").click();
    const target = new URL((await nextRead).url()).pathname.split("/")[3];
    await expect(page.locator(`#window-history option[value="${target}"]`)).toHaveCount(1);
    await page.locator("#window-history").selectOption(target);
    await expect(page.locator("#selected-basis")).toContainText("PINNED");
    await expect(page.locator("#channel-charts svg")).toHaveCount(0);
    release();
    await expect(page.locator("#channel-charts")).toHaveAttribute("data-snapshot", target);
    await expect(page.locator("#channel-charts circle")).not.toHaveCount(0);
    await expect(page.locator("#topology")).toHaveAttribute("data-snapshot", target);
    await expect(page.locator("#trend-basis")).toContainText("PINNED TREND");
  } finally {
    release();
    const stopped = await page.request.post(`/api/replays/${id}/control`, {
      headers, data: { action: "pause", idempotency_key: "dashboard-pin-stop" },
    });
    expect(stopped.status()).toBe(200);
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("automatic report timestamps are explicit and failed analysis cannot clear a numerical warning", async ({ page }) => {
  const { id } = await prepare(page, "S1", 24);
  await expect(page.locator("#automatic-state")).toContainText(/REPORT AVAILABLE|ABSTENTION/, { timeout: 30_000 });
  const response = await page.request.get(`/api/replays/${id}/projection`);
  const projection: Projection = await response.json();
  const taskId = await page.locator("#automatic-state").getAttribute("data-task");
  const root = projection.tasks.find(task => task.id === taskId)!;
  expect(root.automatic).toBe(true);
  await expect(page.locator("#automatic-timeline")).toContainText("ALERT EVIDENCE / SOURCE UTC");
  await expect(page.locator("#automatic-timeline")).toContainText("REPORT RECORDED / PROCESSING UTC");
  await expect(page.locator("#automatic-timeline")).toContainText(new Date(root.created_at).toISOString().slice(0, 19).replace("T", " "));
  await page.getByRole("button", { name: "Review evidence", exact: true }).click();
  await expect(page.locator("#investigation-case")).toHaveAttribute("data-task", root.id);
  await expect(page.locator(".answer-timestamps")).toContainText("actual processing timestamps");
  await page.locator("#tab-live").click();
  let injection: "failed" | "unavailable" = "failed";
  await page.route(`**/api/replays/${id}/projection`, async route => {
    const reply = await route.fetch();
    const actual: Projection = await reply.json();
    const failed = { ...root, id: "injected-failed-root", root_id: "injected-failed-root",
      state: "FAILED", result: null, answer: null, error_code: "injected_provider_timeout",
      error_message: "Deliberate UI failure injection; no report is available.",
      created_at: new Date(Date.parse(root.created_at) + 600_000).toISOString(),
    };
    await route.fulfill({ response: reply, json: injection === "failed"
      ? { ...actual, tasks: [...actual.tasks, failed] }
      : { ...actual, tasks: [], episodes: actual.episodes.map(episode => ({
        ...episode, pending_window_id: actual.latest_window!.id, dispatch_status: "agent_unavailable",
      })) } });
  });
  await page.locator("#reconnect").click();
  await expect(page.locator("#automatic-state")).toContainText("REPORT WITHHELD");
  await expect(page.locator("#automatic-conclusion")).toContainText("No accepted report");
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "possible_leak");
  injection = "unavailable";
  await page.locator("#reconnect").click();
  await expect(page.locator("#automatic-state")).toContainText("Not queued: agent unavailable");
  await expect(page.locator("#automatic-actions button")).toHaveCount(0);
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "possible_leak");
  await page.unrouteAll({ behavior: "wait" });
});

test("unresolved-only triage exposes its source-time boundary without pretending an agent report exists", async ({ page }) => {
  await prepare(page, "S4", 20);
  await expect(page.locator("#automatic-state")).toHaveText("TRIAGE · NOT AN LLM REPORT");
  await expect(page.locator("#automatic-state")).not.toHaveAttribute("data-task", /.+/);
  await expect(page.locator("#automatic-timeline")).toContainText("UNRESOLVED-ONLY REVIEW BOUNDARY / SOURCE UTC");
  await expect(page.locator("#automatic-timeline")).not.toContainText("REPORT RECORDED");
  await expect(page.locator("#automatic-conclusion")).toContainText("Numerical warnings and manual review remain immediate");
  await expect(page.locator("#channel-charts svg")).toBeVisible();
});

test("monitoring controls and manual instruments fit a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await prepare(page, "S6", 14);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "Trend P1-ST1-B", exact: true }).click();
  await expect(page.locator("#sensor-title")).toContainText("P1-ST1-B");
  await expect(page.locator("#channel-charts svg")).toBeVisible();
  await page.screenshot({ path: "runtime/dashboard-engineer-mobile.png", fullPage: true });
});

test("default view prioritizes map, trend and assessment while optional tools stay collapsed", async ({ page }) => {
  await prepare(page, "S1", 24);
  await expect(page.locator("#automatic-state")).toContainText(/REPORT AVAILABLE|ABSTENTION/, { timeout: 30_000 });
  await expect(page.locator("#selected-basis")).toBeHidden();
  await expect(page.locator("#comparison-panel")).toBeHidden();
  await expect(page.locator("#answer-preview")).toBeHidden();
  for (const selector of [".run-settings", "#question-tools", "#system-details", ".agent-diagnostics"]) {
    await expect(page.locator(selector)).not.toHaveAttribute("open");
  }
  const positions = await page.locator(".live-grid, .agent-status-panel").evaluateAll(elements =>
    elements.map(element => ({ top: element.getBoundingClientRect().top, bottom: element.getBoundingClientRect().bottom })));
  expect(positions[0].top).toBeLessThan(450);
  expect(positions[1].bottom).toBeLessThanOrEqual(1100);
  await page.locator("#question-tools > summary").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#question")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.locator("#question")).toBeHidden();
  await page.screenshot({ path: "runtime/dashboard-simplified-desktop.png", fullPage: true });
});

test("LIVE automatic investigation completes while independent monitoring and manual review continue", async ({ page }) => {
  test.skip(process.env.SUBSEA_QUALIFY_DASHBOARD_LIVE !== "1", "Opt in explicitly; this consumes hosted inference.");
  test.setTimeout(420_000);
  const started = performance.now(), { id } = await prepare(page, "S1", 16, "live");
  const artifactPath = `runtime\\dashboard-live-${id}.json`;
  const receipts: { observed_after_seconds: number; projection: Projection }[] = [];
  let outcome = "incomplete";
  try {
    await page.locator("#speed").selectOption("10");
    await page.locator("#play").click();
    await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", /.+/, { timeout: 30_000 });
    const inFlight = await page.request.get(`/api/replays/${id}/projection`, { maxRetries: 2 });
    const current: Projection = await inFlight.json();
    receipts.push({ observed_after_seconds: (performance.now() - started) / 1000, projection: current });
    expect(current.tasks.some(task => task.automatic && ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(task.state))).toBe(true);
    await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "possible_leak", { timeout: 30_000 });
    await page.getByRole("button", { name: "Trend P1-ST2-A", exact: true }).click();
    await expect(page.locator("#channel-charts [data-anomaly=true]")).not.toHaveCount(0);
    await expect.poll(async () => Number(await page.locator("#source-clock").getAttribute("data-confirmed-seconds"))).toBeGreaterThan(185);
    await page.locator("#play").click();
    await expect(page.locator("#play")).toHaveText("Play");
    const monitored = await page.request.get(`/api/replays/${id}/projection`, { maxRetries: 2 });
    const progressed: Projection = await monitored.json();
    receipts.push({ observed_after_seconds: (performance.now() - started) / 1000, projection: progressed });
    expect(progressed.latest_window!.end_seconds).toBeGreaterThan(current.latest_window!.end_seconds);
    expect(progressed.tasks.some(task => task.automatic && ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(task.state))).toBe(true);
    await expect.poll(async () => {
      const response = await page.request.get(`/api/replays/${id}/projection`, { maxRetries: 2 });
      const projection: Projection = await response.json();
      const roots = projection.tasks.filter(task => task.automatic && !task.parent_id);
      const newest = [...roots].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
      receipts.push({ observed_after_seconds: (performance.now() - started) / 1000, projection });
      return !projection.episodes.some(episode => episode.pending_window_id) && newest?.state === "SUCCEEDED";
    }, { timeout: 300_000, intervals: [3000, 5000] }).toBe(true);
    await expect(page.locator("#automatic-state")).toContainText("COPILOT HOSTED · REPORT AVAILABLE");
    const taskId = await page.locator("#automatic-state").getAttribute("data-task");
    const file = await page.request.get(`/api/tasks/${taskId}/casefile`, { maxRetries: 2 });
    expect(file.status()).toBe(200);
    const handoff = await file.json();
    expect(handoff.inspection).toEqual({ segment_id: "P1", start_m: 200, end_m: 600 });
    expect(handoff.interpretation_review.rounds.at(-1).assessment.decision).toBe("accept");
    expect(handoff.report_target_met).toBe(true);
    await page.getByRole("button", { name: "Review evidence", exact: true }).click();
    await expect(page.locator("#investigation-case")).toHaveAttribute("data-task", taskId!);
    await expect(page.locator(".case-interval")).toContainText("P1: 200-600 m");
    await page.screenshot({ path: `runtime/dashboard-live-${id}.png`, fullPage: true });
    outcome = "passed";
  } finally {
    const session = await (await page.request.get("/api/session", { maxRetries: 2 })).json();
    await page.request.post(`/api/replays/${id}/control`, {
      headers: { "X-CSRF-Token": session.csrf_token },
      data: { action: "pause", idempotency_key: "dashboard-live-final-pause" },
    });
    await writeFile(artifactPath, JSON.stringify({
      outcome, replay_id: id, mode: "live", elapsed_seconds: (performance.now() - started) / 1000,
      observation_get_max_retries: 2,
      observation_retry_scope: "Playwright retries ECONNRESET on these idempotent observation GETs only; inference is not retried.",
      limitations: ["One synthetic S1 journey; includes every observed automatic root, not a reliability estimate.", "Same-model source review is not an expert correctness guarantee."],
      receipts,
    }, null, 2) + "\n");
  }
});
