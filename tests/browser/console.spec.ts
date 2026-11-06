import { test, expect } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";

test("real replay, sensor evidence, pinned questions and keyboard navigation", async ({ page }) => {
  const failures: string[] = [];
  page.on("pageerror", error => failures.push(error.message));
  const password = process.env.SUBSEA_OPERATOR_PASSWORD;
  if (!password) throw new Error("Load the owned environment before browser qualification");
  const login = await page.context().request.post("/api/login", {
    data: { username: "operator", password },
  });
  if (login.status() !== 200) throw new Error(`Local test login failed: HTTP ${login.status()}`);
  await page.goto("/");
  await expect(page.locator("#create-replay")).toBeEnabled();
  await expect(page.locator(".header-badges")).toContainText("SIMULATED STREAM");
  await expect(page.locator("#questions button")).toHaveText([
    "Leak or faulty sensors?", "Where should we inspect, and why?",
    "What evidence supports this, and what remains unknown?",
  ]);
  await page.locator("#scenario").selectOption("S1");
  await page.route("**/api/replays", async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    const body = route.request().postDataJSON();
    expect(body.mode).toBe("live");
    expect(body.workflow).toBe("agent_assisted");
    const reply = await route.fetch({ postData: JSON.stringify({ ...body, mode: "scripted" }) });
    await route.fulfill({ response: reply });
  });
  await page.locator("#create-replay").click();
  await expect(page.locator("#step")).toBeEnabled();
  await page.unrouteAll({ behavior: "wait" });
  await page.locator("#step").click();
  await expect(page.locator("#source-clock")).toContainText("5");
  await page.locator("#step").click();
  await expect(page.locator("#window-state")).toContainText(/WARMING[ _]UP/i);
  await page.locator("#speed").selectOption("5");
  await page.locator("#play").click();
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "possible_leak", {
    timeout: 120_000,
  });
  await page.locator("#play").click();
  await expect(page.locator("#play")).toHaveText("Play");
  await expect(page.locator("#source-clock")).toContainText("PAUSED");
  await expect(page.locator("#event-summary")).toContainText(/suspected[ _]leak/i, {
    timeout: 120_000,
  });
  await expect(page.locator("#location-summary")).toContainText("Priority inspection", {
    timeout: 30_000,
  });
  await expect(page.locator("#ask-submit")).toBeEnabled();
  await expect(page.locator("#deployment-summary")).toContainText("opposite pipe walls");
  await expect(page.locator("#topology [data-sensor]")).toHaveCount(24);
  await expect(page.locator("#topology .station-label")).toHaveCount(12);
  await expect(page.locator("#investigation-summary")).toContainText("Competing causes");
  await page.locator("#compare-sensors").click();
  await expect(page.locator("#comparison-charts svg")).toHaveCount(4);
  await expect(page.locator("#comparison-charts")).toContainText("P1-ST2");
  await expect(page.locator("#comparison-charts")).toContainText("P1-ST3");
  const yAxes = await page.locator("#comparison-charts svg").evaluateAll(charts => charts.map(chart =>
    [...chart.querySelectorAll('text[x="3"]')].map(tick => tick.textContent)));
  expect(yAxes.every(axis => JSON.stringify(axis) === JSON.stringify(yAxes[0]))).toBe(true);
  const sensor = page.locator("#topology [role=button].support").first();
  await expect(sensor).toBeVisible();
  await sensor.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#sensor-title")).not.toHaveText("Select a sensor");
  await expect(page.locator("#channel-charts svg")).toHaveCount(1);
  await expect(page.locator("#channel-charts")).toContainText("Pipeline pressure");
  await expect(page.locator("#channel-charts [data-anomaly=true]")).not.toHaveCount(0);
  await page.locator("#inspect-raw").click();
  await expect(page.locator("#tab-evidence")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#raw-table table")).toBeVisible();
  await page.locator("#tab-live").click();
  await page.locator("#question-tools > summary").click();
  await page.locator("#questions button").first().click();
  await page.locator("#ask-submit").click();
  await expect(page.locator("#answer-preview")).toContainText(/suspected[ _]leak/i, {
    timeout: 120_000,
  });
  await expect(page.locator("#answer-preview")).toContainText("overlapping drops");
  await expect(page.locator("#investigation-case")).toBeVisible();
  await expect(page.locator(".case-disposition")).toHaveText("Review supported inspection interval");
  await expect(page.locator(".case-interval")).toContainText("P1: 200-600 m");
  const handoffBasis = await page.locator("#investigation-case").getAttribute("data-snapshot");
  const downloadEvent = page.waitForEvent("download");
  await page.locator("#download-casefile").click();
  const download = await downloadEvent;
  const downloadPath = await download.path();
  expect(downloadPath).not.toBeNull();
  const handoff = JSON.parse(await readFile(downloadPath!, "utf8"));
  expect(handoff.snapshot_id).toBe(handoffBasis);
  expect(handoff.inspection).toEqual({ segment_id: "P1", start_m: 200, end_m: 600 });
  expect(handoff.provider_cost_usd).toBeNull();
  expect(handoff.interpretation_review.rounds.at(-1).assessment.decision).toBe("accept");
  await expect(page.locator(".case-grounding-review")).toContainText("Not a correctness guarantee");
  await page.locator(".case-grounding-review > summary").click();
  await expect(page.locator(".case-grounding-review blockquote").first()).toBeVisible();
  await expect(page.locator(".case-grounding-review")).toContainText("same underlying model");
  let followupRequests = 0;
  page.on("request", request => {
    if (request.method() === "POST" && request.url().endsWith("/questions")) followupRequests++;
  });
  const followup = handoff.interpretation.follow_up_questions[0];
  await page.locator(".case-followups button").first().click();
  await expect(page.locator("#question")).toHaveValue(followup);
  await expect(page.locator("#window-history")).toHaveValue(handoffBasis!);
  expect(followupRequests).toBe(0);
  const steppedResponse = page.waitForResponse(response =>
    response.request().method() === "POST" && response.url().endsWith("/control"));
  await page.locator("#step").click();
  const stepped = await (await steppedResponse).json();
  expect(stepped.latest_window_id).not.toBe(handoffBasis);
  await expect(page.locator(`#window-history option[value="${stepped.latest_window_id}"]`)).toHaveCount(1);
  await page.locator("#follow-live").click();
  await expect(page.locator("#answer-preview")).not.toHaveAttribute("data-snapshot", handoffBasis!);
  await page.locator("#execution-details > summary").click();
  await page.locator(`#task-tree button[data-task="${handoff.task_id}"]`).click();
  await expect(page.locator("#answer-preview")).toHaveAttribute("data-snapshot", handoffBasis!);
  await expect(page.locator("#answer-preview")).toContainText("Historical task explicitly selected");
  await page.locator("#tab-agents").click();
  await expect(page.locator("#task-tree")).toContainText(/sensor[ _]quality/i);
  await expect(page.locator("#task-tree")).toContainText(/event[ _]diagnosis/i);
  await page.locator("#tab-audit").focus();
  await page.keyboard.press("Home");
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  expect(failures).toEqual([]);
  await page.screenshot({ path: "runtime/console.png", fullPage: true });
});

for (const [scenario, expected, counterevidence] of [
  ["S2", "sensor_or_telemetry_issue", "OPERATING_CONTEXT_REQUIRED"],
  ["S4", "insufficient_evidence", "COMMON_MODE_PRESSURE_CHANGE"],
  ["S5", "insufficient_evidence", "COVERAGE_LOST"],
]) {
  test(`pressure ${scenario} preserves uncertainty instead of inventing a leak location`, async ({ page }) => {
    const password = process.env.SUBSEA_OPERATOR_PASSWORD;
    if (!password) throw new Error("Load the owned environment before browser qualification");
    const login = await page.context().request.post("/api/login", {
      data: { username: "operator", password },
    });
    expect(login.status()).toBe(200);
    const { csrf_token } = await login.json();
    const headers = { "X-CSRF-Token": csrf_token };
    const created = await page.context().request.post("/api/replays", {
      headers, data: { scenario, mode: "scripted", seed: 2026, idempotency_key: `${scenario}-${Date.now()}` },
    });
    expect(created.status()).toBe(200);
    const replay = await created.json();
    expect(replay.source_version).toBe("pressure-v3");
    for (let index = 0; index < 37; index++) {
      const step = await page.context().request.post(`/api/replays/${replay.id}/control`, {
        headers, data: { action: "step", idempotency_key: `pressure-step-${index}` },
      });
      expect(step.status()).toBe(200);
    }
    const response = await page.context().request.get(`/api/replays/${replay.id}/projection`);
    expect(response.status()).toBe(200);
    const projection = await response.json();
    expect(projection.latest_window.event.hypothesis).toBe(expected);
    expect(projection.latest_window.event.counterevidence).toContain(counterevidence);
    expect(projection.latest_window.location).toBeNull();
    await page.goto("/");
    await expect(page.locator("#create-replay")).toBeEnabled();
    await page.locator("#replay-history").selectOption(replay.id);
    await expect(page.locator("#event-summary")).toContainText(expected.replaceAll("_", " "));
    await expect(page.locator("#location-summary")).toContainText("No confirmed leak location");
    await page.locator("#question-tools > summary").click();
    if (scenario === "S2") {
      await page.locator("#compare-sensors").click();
      await expect(page.locator("#comparison-charts")).toContainText("P1-ST2-A");
      await expect(page.locator("#comparison-charts")).toContainText("P2-ST2-A");
      await expect(page.locator("#comparison-charts")).toContainText("P3-ST3-A");
      await page.locator("#questions button").first().click();
      await page.locator("#ask-submit").click();
      await expect(page.locator("#answer-preview")).toContainText("Maintenance history supports instrumentation review", {
        timeout: 120_000,
      });
      await expect(page.locator("#answer-preview")).not.toContainText("Priority inspection");
      await expect(page.locator(".case-disposition")).toContainText("sensor/telemetry");
      await expect(page.locator(".case-interval")).toContainText("withheld");
      await expect(page.locator(".case-sources")).toContainText("MAINT");
    }
    if (scenario === "S4") {
      await page.locator("#question").fill(
        "Could a valve change explain this pressure pattern? What should the engineer verify before accepting that root cause?",
      );
      await page.locator("#ask-submit").click();
      await expect(page.locator("#answer-preview")).toContainText("Operating-change explanation is plausible", { timeout: 120_000 });
      await expect(page.locator("#answer-preview")).toContainText("concurrent leak is not ruled out");
      await expect(page.locator("#answer-preview")).toContainText("OP-VALVE-001");
      await expect(page.locator("#answer-preview")).toContainText("ENGINEERING INTERPRETATION");
      await expect(page.locator("#answer-preview")).toContainText("Could a valve change explain");
      await expect(page.locator("#answer-preview")).toContainText("QUESTIONS TO RESOLVE");
      await expect(page.locator("#history-investigation")).toContainText("history.search");
      await expect(page.locator("#history-investigation")).toContainText("history.read");
      await expect(page.locator("#history-investigation")).toContainText("history.compare");
      await expect(page.locator("#answer-preview")).not.toContainText("Priority inspection");
      await expect(page.locator(".case-disposition")).toContainText("Resolve evidence gaps");
      await expect(page.locator(".case-interval")).toContainText("withheld");
      const source = page.locator('.case-source[data-case-reference="OP-VALVE-001"]');
      await source.locator("summary").click();
      await expect(source.locator(".case-source-body")).toBeVisible();
      await expect(source).toContainText("current authority: true");
      await page.locator(".case-comparison summary").first().click();
      await expect(page.locator(".case-comparison table")).toBeVisible();
      await expect(page.locator(".case-comparison table")).toContainText("Usable / expected");
    }
    if (scenario === "S5") {
      await page.locator("#questions button").first().click();
      await page.locator("#ask-submit").click();
      await expect(page.locator(".case-disposition")).toContainText("Resolve evidence gaps", { timeout: 120_000 });
      await expect(page.locator(".case-interval")).toContainText("withheld");
      await expect(page.locator(".case-next-action")).toContainText("coverage");
      const handoff = await page.context().request.get(await page.locator("#download-casefile").getAttribute("href") || "");
      expect(handoff.status()).toBe(200);
      expect((await handoff.json()).inspection).toBeNull();
    }
  });
}

test("asking a question opens Agents before its task detail read completes", async ({ page }) => {
  const password = process.env.SUBSEA_OPERATOR_PASSWORD;
  if (!password) throw new Error("Load the owned environment before browser qualification");
  const login = await page.context().request.post("/api/login", {
    data: { username: "operator", password },
  });
  expect(login.status()).toBe(200);
  const { csrf_token } = await login.json();
  const headers = { "X-CSRF-Token": csrf_token };
  const created = await page.context().request.post("/api/replays", {
    headers, data: { scenario: "S6", mode: "scripted", idempotency_key: `navigation-${Date.now()}` },
  });
  expect(created.status()).toBe(200);
  const replay = await created.json();
  for (let index = 0; index < 13; index++) {
    const step = await page.context().request.post(`/api/replays/${replay.id}/control`, {
      headers, data: { action: "step", idempotency_key: `navigation-step-${index}` },
    });
    expect(step.status()).toBe(200);
  }
  await page.goto("/");
  await expect(page.locator("#create-replay")).toBeEnabled();
  await page.locator("#replay-history").selectOption(replay.id);
  await expect(page.locator("#ask-submit")).toBeEnabled();
  await page.locator("#question-tools > summary").click();
  await page.locator("#questions button").first().click();

  let releaseRead = () => {};
  const heldRead = new Promise<void>(resolve => { releaseRead = () => resolve(); });
  await page.route("**/api/tasks/*", async route => {
    if (!/^\/api\/tasks\/[^/]+$/.test(new URL(route.request().url()).pathname)) {
      await route.continue();
      return;
    }
    await heldRead;
    await route.continue();
  });
  const firstRead = page.waitForRequest(request =>
    /^\/api\/tasks\/[^/]+$/.test(new URL(request.url()).pathname), { timeout: 15_000 });
  const submission = page.waitForResponse(response =>
    response.request().method() === "POST" && response.url().endsWith("/questions"));
  try {
    await page.locator("#ask-submit").click();
    expect((await submission).status()).toBe(200);
    await firstRead;
    await expect(page.locator("#tab-agents")).toHaveAttribute("aria-selected", "true", {
      timeout: 3000,
    });
  } finally {
    releaseRead();
  }
  await expect(page.locator("#task-detail")).toContainText("Public investigation");
});

test("LIVE engineer question, source review, follow-up and downloaded handoff", async ({ page }) => {
  const replayId = process.env.SUBSEA_LIVE_HANDOFF_REPLAY;
  test.skip(!replayId, "Explicitly seed and opt in; this test consumes hosted inference.");
  test.setTimeout(720_000);
  const password = process.env.SUBSEA_OPERATOR_PASSWORD;
  if (!password || !replayId) throw new Error("Load the owned environment and live fixture ID");
  const login = await page.context().request.post("/api/login", {
    data: { username: "operator", password },
  });
  expect(login.status()).toBe(200);
  await page.goto("/");
  await expect(page.locator("#create-replay")).toBeEnabled();
  await page.locator("#replay-history").selectOption(replayId);
  await expect(page.locator("#inference-mode")).toHaveText("COPILOT HOSTED");
  const evidence = await page.context().request.get(`/api/replays/${replayId}/projection`);
  expect(evidence.status()).toBe(200);
  const projection = await evidence.json();
  const snapshotId = projection.latest_window.id;
  expect(projection.replay.clock_seconds).toBe(185);
  expect(projection.latest_window.end_seconds).toBe(180);
  expect(projection.tasks).toHaveLength(0);
  const artifacts = [];
  await page.locator("#question-tools > summary").click();
  await page.locator("#question").fill(
    "Could a valve change explain this pressure pattern? What should the engineer verify before accepting that root cause?",
  );
  for (let turn = 0; turn < 2; turn++) {
    const question = await page.locator("#question").inputValue();
    const submitted = page.waitForResponse(response =>
      response.request().method() === "POST" && response.url().endsWith("/questions"));
    await page.locator("#ask-submit").click();
    const reply = await submitted;
    expect(reply.status()).toBe(200);
    const task = await reply.json();
    expect(task.snapshot_id).toBe(snapshotId);
    let completed;
    await expect.poll(async () => {
      const state = await page.context().request.get(`/api/tasks/${task.id}`);
      expect(state.status()).toBe(200);
      completed = (await state.json()).task;
      return completed.state;
    }, { timeout: 330_000, intervals: [1000, 2000, 3000] }).toMatch(/^(SUCCEEDED|ABSTAINED|FAILED|CANCELLED)$/);
    expect(completed.state, JSON.stringify(completed)).toBe("ABSTAINED");
    await expect(page.locator("#investigation-case")).toHaveAttribute("data-snapshot", snapshotId, { timeout: 15_000 });
    await expect(page.locator("#investigation-case")).toHaveAttribute("data-task", task.id);
    await expect(page.locator(".case-disposition")).toHaveText("Resolve evidence gaps; location withheld");
    const exported = await page.context().request.get(`/api/tasks/${task.id}/casefile`);
    expect(exported.status()).toBe(200);
    const file = await exported.json();
    expect(file.question).toBe(question);
    expect(file.mode).toBe("live");
    expect(file.state).toBe("ABSTAINED");
    expect(file.inspection).toBeNull();
    expect(file.fresh_model_calls).toBeGreaterThan(0);
    expect(file.report_target_met).toBe(true);
    expect(file.interpretation_review.rounds.at(-1).assessment.decision).toBe("accept");
    await expect(page.locator(".case-grounding-review")).toContainText("Independent grounding review accepted");
    if (turn === 0) {
      expect(file.steps.map((step: { tool: string }) => step.tool)).toEqual(
        expect.arrayContaining(["history.search", "history.read", "history.compare"]),
      );
      expect(file.sources.some((source: { document: { id: string }; use: string }) =>
        source.document.id === "OP-VALVE-001" && source.use === "cited")).toBe(true);
      await page.locator('.case-source[data-case-reference="OP-VALVE-001"] > summary').click();
      await expect(page.locator('.case-source[data-case-reference="OP-VALVE-001"] .case-source-body')).toBeVisible();
    }
    artifacts.push(file);
    if (turn === 0) {
      await page.locator(".case-followups button").first().click();
      await expect(page.locator("#window-history")).toHaveValue(snapshotId);
      await expect(page.locator("#question")).toHaveValue(file.interpretation.follow_up_questions[0]);
    }
  }
  expect(artifacts[0].task_id).not.toBe(artifacts[1].task_id);
  const downloadEvent = page.waitForEvent("download");
  await page.locator("#download-casefile").click();
  const download = await downloadEvent;
  const path = await download.path();
  expect(path).not.toBeNull();
  expect(JSON.parse(await readFile(path!, "utf8"))).toEqual(artifacts[1]);
  await writeFile("docs\\evidence\\handoff-browser-engineer-v2-live.json", JSON.stringify({
    passed: true, mode: "live", replay_id: replayId,
    fixture: "Mature synthetic S4 seeded to isolate question/follow-up costs; no automatic roots.",
    limitations: ["Same-model critic and exact-source checks cannot guarantee prose entailment; engineer review remains required."],
    handoffs: artifacts,
  }, null, 2) + "\n");
});
