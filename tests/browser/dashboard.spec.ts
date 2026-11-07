import { test, expect, type Page } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import type { InvestigationCase, Projection } from "../../web/ts/types";

test("hosted golden recordings reopen with real public agent work and zero new inference", async ({ page }) => {
  test.skip(!process.env.SUBSEA_GOLDEN_UI_CASES_JSON, "Explicit recorded golden-data opt-in.");
  test.setTimeout(300_000);
  const url = "http://127.0.0.1:8087";
  const health = await (await page.request.get(`${url}/api/health`)).json();
  expect(health.monitor).toBe("disabled");
  expect(health.agent).toBe("disabled");
  const cases: { case_id: string; replay_id: string; root_task_id: string | null }[] =
    JSON.parse(process.env.SUBSEA_GOLDEN_UI_CASES_JSON!);
  expect(cases.filter(item => item.root_task_id).length).toBeGreaterThanOrEqual(3);
  const login = await page.request.post(`${url}/api/login`, {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  await page.goto(url);
  const receipts: unknown[] = [];
  const counters = (projection: Projection) => projection.tasks.map(task => ({
    id: task.id, state: task.state, model_calls: task.model_calls, tool_calls: task.tool_calls,
  })).sort((a, b) => a.id.localeCompare(b.id));
  for (const item of cases) {
    const before: Projection = await (await page.request.get(`${url}/api/replays/${item.replay_id}/projection`)).json();
    expect(before.replay.mode).toBe("live");
    await expect(page.locator(`#replay-history option[value="${item.replay_id}"]`)).toContainText("Recorded pressure sample");
    await expect(page.locator(`#replay-history option[value="${item.replay_id}"]`)).toHaveAttribute("title", new RegExp(before.replay.scenario));
    await page.locator("#replay-history").selectOption(item.replay_id);
    await expect(page.locator("#evidence-selection")).toHaveAttribute("data-snapshot-id", before.latest_window!.id, { timeout: 45_000 });
    await expect(page.locator("#channel-charts svg")).toHaveCount(1, { timeout: 45_000 });
    if (item.root_task_id) {
      const root = before.tasks.find(task => task.id === item.root_task_id)!;
      expect(["SUCCEEDED", "ABSTAINED"]).toContain(root.state);
      expect(root.model_calls).toBeGreaterThan(0);
      const file: InvestigationCase = await (await page.request.get(`${url}/api/tasks/${root.id}/casefile`)).json();
      expect(file.input_hash).toBe(before.latest_window!.input_hash);
      expect(file.snapshot_id).toBe(before.latest_window!.id);
      expect(file.reused_task_ids).toEqual([]);
      if (item.case_id === "G1" || item.case_id === "G3") {
        expect(file.interpretation?.regional_assessments?.some(region => region.hypothesis === "leak_pattern")).toBe(true);
        expect(file.inspection).toEqual({ segment_id: "P1", start_m: 200, end_m: 600 });
        await expect(page.locator("#topology .inspection-interval")).toHaveCount(1);
        await expect(page.locator("#topology .inspection-interval")).toHaveAttribute("data-segment-id", "P1");
        await expect(page.locator("#topology .inspection-interval")).toHaveAttribute("data-start-m", "200");
        await expect(page.locator("#topology .inspection-interval")).toHaveAttribute("data-end-m", "600");
      } else {
        expect(file.inspection).toBeNull();
        await expect(page.locator("#topology .inspection-interval")).toHaveCount(0);
      }
      await page.locator("#show-agent-work").click();
      for (const role of ["sensor_quality", "event_diagnosis", "operator_response", "grounding_reviewer"]) {
        await expect(page.locator(`.agent-role[data-role="${role}"]`)).toBeVisible();
      }
      await expect(page.locator('.agent-public-journal [data-kind="agent.draft"]')).not.toHaveCount(0, { timeout: 30_000 });
      await expect(page.locator('.agent-public-journal [data-kind="answer.checked"]')).not.toHaveCount(0);
      expect(await page.locator(".agent-public-journal li").count()).toBeGreaterThan(5);
    } else {
      expect(before.tasks).toHaveLength(0);
      await expect(page.locator("#investigation-hold")).toBeHidden();
    }
    const after: Projection = await (await page.request.get(`${url}/api/replays/${item.replay_id}/projection`)).json();
    expect(after.latest_window!.input_hash).toBe(before.latest_window!.input_hash);
    expect(after.replay.clock_seconds).toBe(before.replay.clock_seconds);
    expect(counters(after)).toEqual(counters(before));
    receipts.push({ case_id: item.case_id, replay_id: item.replay_id,
      root_task_id: item.root_task_id, input_hash: after.latest_window!.input_hash,
      displayed_inspection: await page.locator("#topology .inspection-interval").evaluateAll(elements =>
        elements.map(element => ({ segment_id: element.getAttribute("data-segment-id"),
          start_m: element.getAttribute("data-start-m"), end_m: element.getAttribute("data-end-m") }))),
      tasks: counters(after), new_inference_calls: 0 });
  }
  await writeFile("runtime/golden-ui-reopen.json", JSON.stringify({
    outcome: "passed", source: "actual hosted recordings", cases: receipts,
    limitations: ["Read-only saved-run UI verification, not another hosted accuracy trial."],
  }, null, 2) + "\n");
});

test("both workflows expose identical monitoring interfaces and sensor evidence", async ({ page }) => {
  test.setTimeout(480_000);
  const markerState = () => page.locator("#topology [data-sensor]").evaluateAll(elements =>
    elements.map(element => ({
      id: element.getAttribute("data-sensor"),
      flags: ["missing", "fault", "anomalous", "unknown"].filter(flag => element.classList.contains(flag)),
    })).sort((a, b) => (a.id || "").localeCompare(b.id || "")));
  const sharedInterface = async () => ({
    legend: await page.locator('#map-legend [data-legend="anomaly"], #map-legend [data-legend="missing"]').evaluateAll(
      elements => elements.map(element => element.outerHTML)),
    sensors: await page.locator("#sensor-list").innerText(),
    summary: await page.locator("#event-summary").innerText(),
    metrics: await page.locator("#domain-count,#sample-coverage,#window-state,#detector-stage").allTextContents(),
    tabs: await page.locator("[role=tab]").allTextContents(),
    comparison: await page.locator("#compare-sensors").innerText(),
    header: await page.locator("#inference-mode").innerText(),
  });
  const manualEvidence = async () => {
    await page.locator("#compare-sensors").click();
    await expect(page.locator("#comparison-charts svg")).toHaveCount(4, { timeout: 45_000 });
    const compared = await page.locator("#comparison-charts article > h3").allTextContents();
    await page.locator("#inspect-raw").click();
    await expect(page.locator("#raw-table table")).toBeVisible();
    const evidence = (await page.locator("#evidence-chips button").allTextContents())
      .map(label => label.split(" / ").slice(0, label.startsWith("CLAIM") ? 1 : 3).join(" / "));
    return { compared, evidence };
  };
  const baseline = await prepare(page, "S7", 23, "scripted", "sensor_alerts");
  await expect(page.locator('#map-legend [data-legend="quality"]')).toHaveCount(0);
  await expect(page.locator("#topology .sensor.missing").first()).toBeVisible();
  const alerts = await markerState();
  const baselineInterface = await sharedInterface();
  for (const selector of ["#agent-activity", ".agent-status-panel", "#tab-agents"]) await expect(page.locator(selector)).toBeVisible();
  for (const selector of [".engineer-details", "#question-tools"]) await expect(page.locator(selector)).not.toHaveAttribute("hidden");
  const before: Projection = await (await page.request.get(`/api/replays/${baseline.id}/projection`)).json();
  const beforeManual = await manualEvidence();
  const assisted = await prepare(page, "S7", 23);
  const after: Projection = await (await page.request.get(`/api/replays/${assisted.id}/projection`)).json();
  expect(after.latest_window!.input_hash).toBe(before.latest_window!.input_hash);
  expect(await markerState()).toEqual(alerts);
  const assistedInterface = await sharedInterface();
  expect(assistedInterface).toEqual(baselineInterface);
  expect({ ...after.warning, snapshot_id: null }).toEqual({ ...before.warning, snapshot_id: null });
  await expect(page.locator('#map-legend [data-legend="quality"]')).toHaveCount(0);
  const afterManual = await manualEvidence();
  expect(afterManual).toEqual(beforeManual);
  await writeFile("runtime/unified-mode-parity.json", JSON.stringify({
    outcome: "passed", fixture_mode: "scripted", sensor_count: after.pack.sensors.length,
    input_hash: after.latest_window!.input_hash, window_end: after.latest_window!.window_end,
    baseline: baselineInterface, assisted: assistedInterface, manual_evidence: afterManual,
    limitations: ["UI/workflow parity qualification, not hosted inference quality or field RCA accuracy.",
      "Agent progress and reviewed diagnosis/localization are deliberately excluded from identical sensor presentation."],
  }, null, 2) + "\n");
});

test("10x fresh hosted work freezes the source and displays real progress", async ({ page }) => {
  test.skip(process.env.SUBSEA_QUALIFY_PAUSED_LIVE !== "1", "Explicit hosted-inference opt-in.");
  test.setTimeout(600_000);
  const frames: unknown[] = [];
  let outcome = "failed";
  let result: Record<string, unknown> = {};
  try {
    const login = await page.request.post("/api/login", {
      data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
    });
    expect(login.status()).toBe(200);
    const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
    const created = await page.request.post("/api/replays", {
      headers, data: { scenario: "S7", mode: "live", seed: 2026, idempotency_key: `paused-live-${Date.now()}` },
    });
    expect(created.status()).toBe(200);
    const replay = await created.json();
    expect(replay.pause_on_anomaly).toBe(true);
    await page.goto("/");
    await page.locator("#replay-history").selectOption(replay.id);
    await page.locator("#speed").selectOption("10");
    await page.locator("#play").click();
    const observed: { pinned?: Projection; final?: Projection } = {};
    await expect.poll(async () => {
      const projection: Projection = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
      if (projection.replay.investigation_window_id) observed.pinned = projection;
      return Boolean(observed.pinned);
    }, { timeout: 180_000, intervals: [1000, 2000] }).toBe(true);
    const basis = observed.pinned;
    if (!basis) throw new Error("No held source window was observed");
    result = { replay_id: replay.id, source_seconds: basis.replay.clock_seconds, snapshot_id: basis.replay.investigation_window_id };
    await expect(page.locator("#investigation-hold")).toBeVisible();
    await expect(page.locator("#play")).toHaveText("Waiting for agents");
    await expect(page.locator("#play")).toBeDisabled();
    await expect(page.locator("#step")).toBeDisabled();
    await expect(page.locator("#agent-live-stages")).toContainText("Event Diagnosis Agent");
    const stepped = await page.request.post(`/api/replays/${replay.id}/control`, {
      headers, data: { action: "step", idempotency_key: "blocked-during-hosted-work" },
    });
    expect(stepped.status()).toBe(409);
    await expect(page.locator("#evidence-selection")).toHaveAttribute("data-snapshot-id", basis.replay.investigation_window_id!, { timeout: 30_000 });
    await expect(page.locator("#channel-charts svg")).toHaveCount(1, { timeout: 30_000 });
    await page.screenshot({ path: "runtime/paused-agent-running.png", fullPage: true });
    let activeObserved = false;
    await expect.poll(async () => {
      const projection: Projection = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
      expect(projection.replay.clock_seconds).toBe(basis.replay.clock_seconds);
      expect(projection.latest_window!.id).toBe(basis.replay.investigation_window_id);
      const root = projection.tasks.find(task => !task.parent_id && task.automatic);
      if (root && ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(root.state)) activeObserved = true;
      frames.push({ at: new Date().toISOString(), clock_seconds: projection.replay.clock_seconds,
        tasks: projection.tasks.map(task => ({ id: task.id, role: task.role, state: task.state,
          model_calls: task.model_calls, tool_calls: task.tool_calls, error_code: task.error_code })),
        activity: await page.locator("#agent-activity").textContent() });
      if (root?.state === "FAILED") throw new Error(`Fresh paused report withheld: ${root.error_code}`);
      observed.final = projection;
      return Boolean(root && ["SUCCEEDED", "ABSTAINED"].includes(root.state));
    }, { timeout: 310_000, intervals: [2000, 4000] }).toBe(true);
    expect(activeObserved).toBe(true);
    const completed = observed.final;
    if (!completed) throw new Error("No completed projection was recorded");
    const root = completed.tasks.find(task => !task.parent_id && task.automatic)!;
    const response = await page.request.get(`/api/tasks/${root.id}/casefile`);
    expect(response.status()).toBe(200);
    const file = await response.json();
    expect(file.reused_task_ids).toEqual([]);
    expect(file.fresh_model_calls).toBeGreaterThan(0);
    expect(file.interpretation_review.rounds.at(-1).assessment.decision).toBe("accept");
    result.casefile = file;
    await expect(page.locator("#play")).toHaveText("Continue monitoring");
    await expect(page.locator("#play")).toBeEnabled();
    await expect(page.locator("#agent-activity-state")).toContainText("Recorded agent report");
    await page.reload();
    await page.locator("#replay-history").selectOption(replay.id);
    await expect(page.locator("#agent-last-action")).toContainText("saved result, not a new inference");
    await expect(page.locator("#evidence-selection")).toHaveAttribute("data-snapshot-id", basis.replay.investigation_window_id!);
    await expect(page.locator("#channel-charts svg")).toHaveCount(1);
    const reopened: Projection = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
    expect(reopened.tasks.map(task => task.model_calls)).toEqual(completed.tasks.map(task => task.model_calls));
    await page.screenshot({ path: "runtime/paused-agent-reviewed.png", fullPage: true });
    outcome = "passed";
  } catch (error) {
    const message = error instanceof Error ? error.message.split("\nCall log:")[0] : "Paused qualification failed";
    result.error = message;
    throw new Error(message);
  } finally {
    await writeFile("runtime/paused-agent-live.json", JSON.stringify({ outcome, ...result, frames }, null, 2) + "\n");
  }
});

test("recorded paused hosted work restores coherent evidence without new inference", async ({ page }) => {
  test.skip(process.env.SUBSEA_QUALIFY_PAUSED_RECORDING !== "1", "Requires the retained paused-hosted qualification.");
  test.setTimeout(120_000);
  try {
    const receipt: { replay_id: string; snapshot_id: string } = JSON.parse(await readFile("runtime/paused-agent-live.json", "utf8"));
    const login = await page.request.post("/api/login", {
      data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
    });
    expect(login.status()).toBe(200);
    const before: Projection = await (await page.request.get(`/api/replays/${receipt.replay_id}/projection`)).json();
    expect(before.replay.investigation_window_id).toBe(receipt.snapshot_id);
    expect(before.replay.state).toBe("PAUSED");
    const root = before.tasks.find(task => task.automatic && !task.parent_id && task.snapshot_id === receipt.snapshot_id);
    expect(root?.mode).toBe("live");
    const report = await page.request.get(`/api/tasks/${root!.id}/casefile`);
    expect(report.status()).toBe(200);
    const handoff = await report.json();
    expect(handoff.state).toBe("ABSTAINED");
    expect(handoff.inspection).toBeNull();
    expect(handoff.interpretation.competing_causes.map((cause: { cause: string }) => cause.cause))
      .toEqual(expect.arrayContaining(["leak", "instrumentation_or_telemetry", "operating_change"]));
    await page.goto("/");
    await expect(page.locator("#create-replay")).toBeEnabled();
    await page.locator("#replay-history").selectOption(receipt.replay_id);
    await expect(page.locator("#evidence-selection")).toHaveAttribute("data-snapshot-id", receipt.snapshot_id, { timeout: 45_000 });
    await expect(page.locator("#channel-charts svg")).toHaveCount(1, { timeout: 45_000 });
    await expect(page.locator('#channel-charts [data-legend="missing"]')).toHaveText("Missing value");
    await expect(page.locator('#channel-charts [data-legend="anomaly"]')).toHaveText("Pressure anomaly");
    await expect(page.locator("#agent-last-action")).toContainText("saved result, not a new inference");
    await expect(page.locator("#play")).toHaveText("Continue monitoring");
    await expect(page.locator("#play")).toBeEnabled();
    await expect(page.locator("#step")).toBeDisabled();
    await expect(page.locator("#basis-warning")).toContainText("Simulation paused for investigation");
    await expect(page.locator("#agent-live-stages")).toContainText("Response Coordinator");
    await expect(page.locator("#agent-live-stages")).toContainText("Grounding Reviewer");
    await expect(page.locator("#agent-findings .agent-causes details")).toHaveCount(handoff.interpretation.competing_causes.length);
    await expect(page.locator("#topology .inspection-interval")).toHaveCount(0);
    await expect(page.locator('#map-legend [data-legend="inspection"]')).toBeHidden();
    const after: Projection = await (await page.request.get(`/api/replays/${receipt.replay_id}/projection`)).json();
    expect(after.tasks.map(task => [task.id, task.model_calls, task.tool_calls])).toEqual(
      before.tasks.map(task => [task.id, task.model_calls, task.tool_calls]));
    expect(after.replay.clock_seconds).toBe(before.replay.clock_seconds);
    await page.screenshot({ path: "runtime/paused-agent-reviewed.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await expect(page.locator("#play")).toBeVisible();
  } catch (error) {
    throw new Error(error instanceof Error ? error.message.split("\nCall log:")[0] : "Recorded qualification failed");
  }
});

test("extended network qualifies a fresh hosted investigation against matching sensor-only evidence", async ({ page }) => {
  test.skip(process.env.SUBSEA_QUALIFY_DASHBOARD_LIVE !== "1", "Opt in explicitly; this consumes hosted inference.");
  test.setTimeout(600_000);
  const started = performance.now();
  const frames: unknown[] = [];
  let outcome = "failed";
  let evidence: Record<string, unknown> = {};
  try {
    const baseline = await prepare(page, "S7", 23, "scripted", "sensor_alerts");
    const baselineProjection: Projection = await (await page.request.get(`/api/replays/${baseline.id}/projection`, { maxRetries: 2 })).json();
    expect(baselineProjection.tasks).toHaveLength(0);
    expect(baselineProjection.episodes).toHaveLength(0);
    evidence = { baseline: baselineProjection };
    const agent = await prepare(page, "S7", 23, "live");
    const initial: Projection = await (await page.request.get(`/api/replays/${agent.id}/projection`, { maxRetries: 2 })).json();
    evidence.agent_replay_id = agent.id;
    expect(initial.latest_window!.input_hash).toBe(baselineProjection.latest_window!.input_hash);
    expect(initial.latest_window!.end_seconds).toBe(110);
    await expect(page.locator("#agent-activity")).toBeVisible();
    await expect(page.locator("#topology [data-sensor]")).toHaveCount(112);
    await expect.poll(async () => {
      const current: Projection = await (await page.request.get(`/api/replays/${agent.id}/projection`, { maxRetries: 2 })).json();
      const root = current.tasks.find(task => task.automatic && !task.parent_id);
      frames.push({
        observed_after_seconds: (performance.now() - started) / 1000,
        source_seconds: current.replay.clock_seconds,
        tasks: current.tasks.map(task => ({
          id: task.id, role: task.role, state: task.state, snapshot_id: task.snapshot_id,
          model_calls: task.model_calls, tool_calls: task.tool_calls, error_code: task.error_code,
        })),
        pending_windows: current.episodes.map(episode => episode.pending_window_id),
        activity: await page.locator("#agent-activity").textContent(),
      });
      if (root?.state === "FAILED") throw new Error(`Hosted S7 report withheld: ${root.error_code}`);
      return root !== undefined && ["SUCCEEDED", "ABSTAINED"].includes(root.state)
        && !current.episodes.some(episode => episode.pending_window_id);
    }, { timeout: 300_000, intervals: [3000, 5000] }).toBe(true);
    await expect(page.locator("#automatic-state")).toContainText(/COPILOT HOSTED · (REPORT AVAILABLE|ABSTENTION)/);
    const taskId = await page.locator("#automatic-state").getAttribute("data-task");
    const response = await page.request.get(`/api/tasks/${taskId}/casefile`, { maxRetries: 2 });
    expect(response.status()).toBe(200);
    const handoff = await response.json();
    evidence.casefile = handoff;
    expect(handoff.input_hash).toBe(baselineProjection.latest_window!.input_hash);
    expect(handoff.inspection).toBeNull();
    expect(handoff.knowledge_packet.authority).toBe("synthetic_advisory_only");
    expect(handoff.knowledge_used_ids.length).toBeGreaterThan(0);
    expect(handoff.interpretation.regional_assessments.length).toBeGreaterThan(0);
    expect(handoff.steps.some((step: { tool: string; arguments: Record<string, unknown> }) =>
      step.tool === "history.compare" && Array.isArray(step.arguments.knowledge_ids)
      && step.arguments.knowledge_ids.length > 0 && typeof step.arguments.check_question === "string")).toBe(true);
    expect(handoff.interpretation_review.rounds.at(-1).assessment.decision).toBe("accept");
    expect(handoff.report_target_met).toBe(true);
    expect(handoff.sources.length).toBeGreaterThan(0);
    expect(handoff.comparisons.length).toBeGreaterThan(0);
    const cited = new Set(handoff.sources.filter((source: { use: string }) => source.use === "cited")
      .map((source: { document: { id: string } }) => source.document.id));
    expect(cited.has("OP-P2-EXTENDED-001")).toBe(true);
    expect(cited.has("MAINT-P7-GW-002")).toBe(true);
    expect(handoff.comparisons.some((comparison: { sensors: { sensor_id: string; change_bar: number | null }[] }) =>
      comparison.sensors.some(sensor => sensor.sensor_id.startsWith("P5-")
        && sensor.change_bar !== null && Math.abs(sensor.change_bar) >= .2))).toBe(true);
    await expect(page.locator("#agent-findings")).toContainText("P5");
    await page.locator("#map-focus").selectOption("P5");
    await expect(page.locator("#topology [data-sensor]")).toHaveCount(16);
    await expect(page.locator("#topology .inspection-interval")).toHaveCount(0);
    await expect(page.locator("#agent-findings")).toContainText("Why these checks");
    await expect(page.locator("#channel-charts svg")).toHaveCount(1);
    await page.screenshot({ path: "runtime/extended-network-agent.png", fullPage: true });
    outcome = "passed";
  } catch (error) {
    const message = error instanceof Error ? error.message.split("\nCall log:")[0] : "Qualification failed";
    evidence.error = message;
    throw new Error(message);
  } finally {
    await writeFile("runtime/extended-network-live.json", JSON.stringify({
      outcome, elapsed_seconds: (performance.now() - started) / 1000,
      observation_get_max_retries: 2, inference_retries: 0,
      limitations: [
        "Single synthetic workload, not field performance or measured engineering-time savings.",
        "Numerical tools determine the inspection interval; the LLM investigates context.",
        "Bounded, partial sensor-health review; one physical leak, not multi-leak localization.",
      ],
      ...evidence, frames,
    }, null, 2) + "\n");
  }
});

async function prepare(page: Page, scenario: string, steps: number, mode = "scripted", workflow = "agent_assisted", pauseOnAnomaly = false): Promise<{ id: string; headers: Record<string, string> }> {
  try {
    const password = process.env.SUBSEA_OPERATOR_PASSWORD;
    if (!password) throw new Error("Load the owned environment before browser qualification");
    const login = await page.request.post("/api/login", { data: { username: "operator", password } });
    expect(login.status()).toBe(200);
    const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
    const created = await page.request.post("/api/replays", {
      headers, data: { scenario, mode, workflow, pause_on_anomaly: pauseOnAnomaly, seed: 2026, idempotency_key: `dashboard-${Date.now()}-${scenario}` },
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
    const view: Projection = await (await page.request.get(`/api/replays/${id}/projection`)).json();
    if (!view.latest_window) throw new Error("Prepared replay has no completed evidence window");
    await expect(page.locator("#evidence-selection")).toHaveAttribute("data-snapshot-id", view.latest_window.id, { timeout: 45_000 });
    await expect(page.locator("#channel-charts svg")).toHaveCount(1, { timeout: 45_000 });
    return { id, headers };
  } catch (error) {
    throw new Error(error instanceof Error ? error.message.split("\nCall log:")[0] : "Replay preparation failed");
  }
}

test("missing-only coverage loss stays visible without pausing for agents", async ({ page }) => {
  const { id } = await prepare(page, "S3", 37, "scripted", "agent_assisted", true);
  const view: Projection = await (await page.request.get(`/api/replays/${id}/projection`)).json();
  expect(view.replay.clock_seconds).toBe(185);
  expect(view.replay.investigation_window_id).toBeNull();
  expect(view.tasks).toEqual([]);
  expect(view.episodes).toEqual([]);
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "coverage_lost");
  await expect(page.locator("#topology .sensor.missing")).toHaveCount(24);
  await expect(page.locator("#agent-stage")).toHaveText("Waiting for a pressure anomaly");
  await expect(page.locator("#automatic-conclusion")).toContainText("Missing values alone do not start agents");
  await expect(page.locator("#map-legend > span:visible")).toHaveText(["Pressure anomaly", "Missing value"]);
  await expect(page.locator("#play")).toBeEnabled();
  await expect(page.locator("#play")).toHaveText("Play");
});

test("brief geometry, correct wall sides and manual comparison agree with actual evidence", async ({ page }) => {
  const { id } = await prepare(page, "S1", 23);
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
  await expect(page.locator("#compare-sensors")).toHaveText("Compare sensor histories");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "runtime/dashboard-engineer-desktop.png", fullPage: true });
});

test("extended network supports readable branch focus without hiding manual cross-branch evidence", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message.split("\nCall log:")[0]));
  const { id } = await prepare(page, "S7", 29, "scripted", "sensor_alerts");
  const projection: Projection = await (await page.request.get(`/api/replays/${id}/projection`)).json();
  expect(projection.tasks).toHaveLength(0);
  expect(projection.episodes).toHaveLength(0);
  await expect(page.locator("#network-scale")).toContainText("11.2 km · 7 segments · 112 instruments");
  await expect(page.locator("#topology [data-sensor]")).toHaveCount(112);
  await expect(page.locator("#sensor-list tbody tr")).toHaveCount(112);
  await expect(page.locator("#topology .station-label")).toHaveCount(1);
  await expect(page.locator("#topology .inspection-interval")).toHaveCount(0);
  await page.locator("#map-focus").selectOption("P5");
  await expect(page.locator("#topology [data-sensor]")).toHaveCount(16);
  await expect(page.locator("#topology .station-label")).toHaveCount(8);
  const first = page.locator('#topology [data-sensor="P5-ST1-A"]');
  await first.focus();
  await first.press("End");
  await expect(page.locator('#topology [data-sensor="P5-ST8-B"]')).toBeFocused();
  await page.getByRole("button", { name: "Trend P7-ST3-A", exact: true }).click();
  await expect(page.locator("#map-focus")).toHaveValue("P7");
  await expect(page.locator("#sensor-title")).toContainText("P7-ST3-A");
  await expect(page.locator("#channel-charts svg")).toHaveCount(1);
  await page.locator("#map-focus").selectOption("");
  for (const sensor of ["P5-ST4-A", "P5-ST5-A", "P7-ST1-A", "P7-ST2-A"]) {
    await page.getByRole("checkbox", { name: `Compare ${sensor}`, exact: true }).check();
  }
  await page.locator("#compare-sensors").click();
  await expect(page.locator("#comparison-charts svg")).toHaveCount(4);
  await expect(page.locator("#comparison-charts article > h3")).toHaveText([
    "P5-ST4-A / gateway-P5-1", "P5-ST5-A / gateway-P5-0",
    "P7-ST1-A / gateway-P7-0", "P7-ST2-A / gateway-P7-1",
  ]);
  const snapshots = await page.evaluate(() => ["topology", "channel-charts"]
    .map(id => document.getElementById(id)!.getAttribute("data-snapshot")));
  expect(new Set(snapshots).size).toBe(1);
  expect(snapshots[0]).toBe(projection.latest_window!.id);
  await expect(page.locator("#window-history")).toHaveValue(projection.latest_window!.id);
  await page.screenshot({ path: "runtime/extended-network-manual.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#map-focus").selectOption("P7");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
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
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "sensor_alerts");
  injection = "unavailable";
  await page.locator("#reconnect").click();
  await expect(page.locator("#automatic-state")).toContainText("Not queued: agent unavailable");
  await expect(page.locator("#automatic-actions button")).toHaveCount(2);
  for (const control of await page.locator("#automatic-actions button").all()) await expect(control).toBeDisabled();
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "sensor_alerts");
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
  expect(positions[0].top).toBeLessThan(550);
  expect(positions[1].top - positions[0].bottom).toBeLessThan(24);
  await expect(page.locator("#agent-activity")).toBeVisible();
  await expect(page.locator("#agent-elapsed")).toContainText("SCRIPTED");
  await expect(page.locator("#automatic-progress .agent-role")).toHaveCount(4);
  await page.locator("#show-agent-work").click();
  await expect(page.locator("#agent-findings")).toBeInViewport();
  await page.locator("#question-tools > summary").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#question")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.locator("#question")).toBeHidden();
  await page.screenshot({ path: "runtime/dashboard-simplified-desktop.png", fullPage: true });
});

test("light theme has readable contrast and the map, chart and legend agree on pressure anomalies", async ({ page }) => {
  const { id } = await prepare(page, "S1", 37);
  const projection: Projection = await (await page.request.get(`/api/replays/${id}/projection`)).json();
  await page.getByRole("button", { name: "Trend P1-ST2-A", exact: true }).click();
  await expect(page.locator("#channel-charts [data-anomaly=true]")).not.toHaveCount(0);
  await expect(page.locator("#topology .sensor.selected")).toHaveCount(1);
  const selected = page.locator('#topology [data-sensor="P1-ST2-A"]');
  await expect(selected).toHaveClass(/anomalous/);
  await expect(selected.locator(".selection-ring")).toBeVisible();
  const styles = await page.evaluate(() => {
    const color = (selector: string, property: string): string => getComputedStyle(document.querySelector(selector)!).getPropertyValue(property);
    return {
      dot: color('#topology [data-sensor="P1-ST2-A"] .sensor-dot', "fill"),
      legend: color('#map-legend [data-legend="anomaly"] .sensor-dot', "fill"),
      sample: color('#channel-charts circle[data-anomaly="true"]', "fill"),
      plotLegend: color('#channel-charts [data-legend="anomaly"] .legend-mark', "background-color"),
      selected: color('#topology [data-sensor="P1-ST2-A"] .selection-ring', "stroke"),
    };
  });
  expect(new Set([styles.dot, styles.legend, styles.sample, styles.plotLegend]).size).toBe(1);
  expect(styles.selected).not.toBe(styles.dot);
  for (const finding of projection.latest_window!.quality.findings) {
    const marker = page.locator(`#topology [data-sensor="${finding.sensor_id}"]`);
    if (finding.anomaly_count > 0) await expect(marker).toHaveClass(/anomalous/);
    if (finding.missing || finding.hard_excluded) await expect(marker).toHaveClass(/missing/);
  }
  const contrast = await page.evaluate(() => {
    const rgb = (value: string): number[] => value.match(/[\d.]+/g)!.map(Number);
    const luminance = (channels: number[]): number => channels.slice(0, 3).map(v => {
      const s = v / 255; return s <= .04045 ? s / 12.92 : ((s + .055) / 1.055) ** 2.4;
    }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
    const selectors = ["#automatic-conclusion", "#trend-basis", ".sensor-list button", ".sensor-list td",
      "#source-clock", "#automatic-state", "#map-legend span", ".chart-legend span", "#topology .station-label", ".chart svg text"];
    return selectors.map(selector => {
      const element = document.querySelector(selector)!;
      const style = getComputedStyle(element);
      let background = [255, 255, 255];
      for (let ancestor: Element | null = element; ancestor; ancestor = ancestor.parentElement) {
        const candidate = rgb(getComputedStyle(ancestor).backgroundColor);
        if (candidate.length === 3 || candidate[3] === 1) { background = candidate; break; }
      }
      const foreground = rgb(element instanceof SVGElement ? style.fill : style.color);
      const a = luminance(foreground), b = luminance(background);
      return { selector, ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) };
    });
  });
  for (const item of contrast) expect(item.ratio, item.selector).toBeGreaterThanOrEqual(4.5);
  await page.screenshot({ path: "runtime/dashboard-light-desktop.png", fullPage: true });
});

for (const workflow of ["sensor_alerts", "agent_assisted"] as const) {
test(`${workflow} shows only pressure and missing-value sensor flags while retaining screening evidence`, async ({ page }) => {
  const { id } = await prepare(page, "S2", 37, "scripted", workflow);
  const projection: Projection = await (await page.request.get(`/api/replays/${id}/projection`)).json();
  const quality = projection.latest_window!.quality.findings.filter(f => f.spike_count || f.drift_suspected || f.peer_disagreement);
  expect(quality.length).toBeGreaterThan(0);
  await expect(page.locator("#topology .sensor.fault, #topology .quality-mark")).toHaveCount(0);
  await expect(page.locator('#map-legend [data-legend="quality"]')).toHaveCount(0);
  await expect(page.locator('#map-legend [data-legend="missing"]')).toHaveText("Missing value");
  await expect(page.locator('#map-legend [data-legend="normal"], #map-legend [data-legend="selected"], #map-legend [data-legend="unknown"]')).toHaveCount(0);
  for (const [key, selector] of [["support", ".support-ring"], ["inspection", ".inspection-interval"]]) {
    expect(await page.locator(`#map-legend [data-legend="${key}"]`).isVisible())
      .toBe(await page.locator(`#topology ${selector}`).count() > 0);
  }
  await expect(page.locator("#sensor-list")).not.toContainText(/Spikes|Drift suspected|Paired disagreement/);
  for (const finding of projection.latest_window!.quality.findings) {
    const marker = page.locator(`#topology [data-sensor="${finding.sensor_id}"]`);
    expect(await marker.getAttribute("class")).toMatch(finding.anomaly_count > 0 ? /anomalous/ : /^(?!.*anomalous)/);
    expect(await marker.getAttribute("class")).toMatch(finding.missing || finding.hard_excluded ? /missing/ : /^(?!.*missing)/);
  }
  const sensor = quality[0].sensor_id;
  await page.getByRole("button", { name: `Trend ${sensor}`, exact: true }).click();
  await page.locator("#inspect-raw").click();
  await expect(page.locator("#raw-table table")).toBeVisible();
});
}

test("unassessed sensors remain explicitly unassessed during warm-up", async ({ page }) => {
  await prepare(page, "S6", 2);
  await expect(page.locator("#topology .sensor.unknown")).toHaveCount(24);
  await expect(page.locator("#topology .sensor.anomalous, #topology .sensor.fault, #topology .sensor.support")).toHaveCount(0);
  await expect(page.locator("#sensor-list")).toContainText("not assessed");
  await expect(page.locator("#map-legend > span:visible")).toHaveText(["Pressure anomaly", "Missing value"]);
});

test("knowledge-assisted handoff shows regional reasoning and actual guidance-to-check links", async ({ page }) => {
  await prepare(page, "S7", 23);
  await expect(page.locator("#agent-activity-state")).toContainText("Recorded agent report");
  const taskId = await page.locator("#automatic-state").getAttribute("data-task");
  const response = await page.request.get(`/api/tasks/${taskId}/casefile`);
  expect(response.status()).toBe(200);
  const handoff = await response.json();
  expect(handoff.inspection).toBeNull();
  expect(handoff.knowledge_packet.authority).toBe("synthetic_advisory_only");
  expect(handoff.interpretation.regional_assessments.length).toBeGreaterThan(0);
  await expect(page.locator("#agent-findings .agent-region")).toHaveCount(handoff.interpretation.regional_assessments.length);
  const checks = page.locator("#agent-findings .agent-checks");
  await checks.locator("summary").click();
  await expect(checks.locator("li")).toHaveCount(handoff.steps.filter((step: { tool: string }) => step.tool.startsWith("history.")).length);
  await expect(checks).toContainText("KN-");
  for (const step of handoff.steps.filter((step: { tool: string }) => step.tool === "history.compare")) {
    await expect(checks.locator(`[data-call-id="${step.call_id}"]`)).toContainText(step.arguments.check_question);
  }
  await page.locator("#agent-findings .agent-knowledge > summary").click();
  await expect(page.locator("#agent-findings .knowledge-card")).toHaveCount(handoff.knowledge_used_ids.length);
  await expect(page.locator("#agent-findings")).not.toContainText(/\bdemo\b/i);
  await page.locator("#map-focus").selectOption("P5");
  await expect(page.locator("#topology [data-sensor]")).toHaveCount(16);
  await expect(page.locator("#channel-charts svg")).toHaveCount(1);
  await page.screenshot({ path: "runtime/joint-pattern-knowledge-dashboard.png", fullPage: true });
});

test("two customer modes keep one interface and add only reviewed investigation on matching S1 data", async ({ page }) => {
  const baseline = await prepare(page, "S1", 23, "live", "sensor_alerts");
  await expect(page.locator("#workflow option")).toHaveText(["Sensor alerts only", "Agent-assisted investigation"]);
  await expect(page.locator("#mode")).toHaveCount(0);
  await expect(page.locator("#inference-mode")).toContainText("EVIDENCE");
  await expect(page.locator("#manual-workflow")).toHaveCount(0);
  await expect(page.locator("#monitoring-warning")).not.toContainText(/\bdemo\b/i);
  await expect(page.locator(".agent-status-panel")).toBeVisible();
  await expect(page.locator("#agent-activity")).toBeVisible();
  await expect(page.locator("#question-tools")).not.toHaveAttribute("hidden");
  await expect(page.locator("#tab-agents")).toBeVisible();
  await expect(page.locator("#automatic-progress .agent-role")).toHaveCount(4);
  await expect(page.locator("#topology .support-ring, #topology .inspection-interval")).toHaveCount(0);
  await expect(page.locator("#map-legend > span:visible")).toHaveText(["Pressure anomaly", "Missing value"]);
  await expect(page.locator("#sensor-list")).not.toContainText("Overlapping pressure drop");
  await expect(page.locator("#event-summary")).toContainText("do not establish cause or location");
  await expect(page.locator("#domain-count")).toContainText("instrument domains available");
  await expect(page.locator("#agent-stage")).toContainText("execution off");
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "sensor_alerts");
  const before: Projection = await (await page.request.get(`/api/replays/${baseline.id}/projection`)).json();
  expect(before.tasks).toEqual([]);
  expect(before.episodes).toEqual([]);
  await page.screenshot({ path: "runtime/dashboard-sensor-alerts.png", fullPage: true });
  await page.locator("#inspect-raw").click();
  await expect(page.locator("#evidence-chips")).toContainText("CLAIM");
  await expect(page.locator("#raw-table table")).toBeVisible();
  await page.locator("#tab-evidence").focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#tab-agents")).toHaveAttribute("aria-selected", "true");
  const assisted = await prepare(page, "S1", 23);
  const after: Projection = await (await page.request.get(`/api/replays/${assisted.id}/projection`)).json();
  expect(after.latest_window!.input_hash).toBe(before.latest_window!.input_hash);
  await expect(page.locator("#manual-workflow")).toHaveCount(0);
  await expect(page.locator(".agent-status-panel")).toBeVisible();
  await expect(page.locator("#topology .inspection-interval")).toHaveCount(1);
  await expect(page.locator('#map-legend [data-legend="inspection"]')).toBeVisible();
  await expect(page.locator("#automatic-state")).toContainText("SCRIPTED");
  await expect(page.locator("#location-summary")).toContainText("200–600m");
  await expect(page.locator("#event-summary")).toContainText("do not establish cause or location");
  await expect(page.locator("#agent-activity-state")).toContainText("Recorded agent report");
  await expect(page.locator("#agent-findings")).toContainText("operational records read");
  await expect(page.locator("#automatic-progress .agent-role > strong")).toHaveText([
    "Sensor Quality Agent", "Event Diagnosis Agent", "Response Coordinator", "Grounding Reviewer",
  ]);
  await expect(page.locator('#agent-findings [data-kind="agent.handoff_requested"]')).toHaveCount(2);
  await expect(page.locator('#agent-findings [data-kind="agent.check_completed"]')).not.toHaveCount(0);
  await expect(page.locator('#agent-findings [data-kind="agent.draft"]')).not.toHaveCount(0);
  await expect(page.locator('#agent-findings [data-kind="agent.review_requested"]')).not.toHaveCount(0);
  await expect(page.locator("#agent-findings")).toContainText("Agent's check question");
  const taskId = await page.locator("#automatic-state").getAttribute("data-task");
  const detail = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  const handoff = detail.casefile;
  expect(handoff.hypothesis).toBe("suspected_leak");
  expect(handoff.inspection).toEqual({ segment_id: "P1", start_m: 200, end_m: 600 });
  expect(handoff.interpretation.competing_causes.map((cause: { cause: string }) => cause.cause))
    .toEqual(expect.arrayContaining(["operating_change"]));
  await expect(page.locator("#agent-findings .agent-causes details")).toHaveCount(handoff.interpretation.competing_causes.length);
  await page.getByRole("button", { name: "Compare with existing workflow", exact: true }).click();
  await expect(page.locator("#workflow-comparison")).toBeVisible();
  await expect(page.locator("#investigation-case")).toHaveAttribute("data-task", taskId!);
  await expect(page.locator("#workflow-comparison")).toHaveAttribute("data-snapshot", handoff.snapshot_id);
  await expect(page.locator("#workflow-comparison")).toHaveAttribute("data-input-hash", handoff.input_hash);
  await expect(page.locator(".workflow-existing")).toContainText("No combined leak/malfunction classification");
  await expect(page.locator(".workflow-existing")).toContainText("Not yet measured");
  await expect(page.locator('.workflow-added [data-value="classification"]')).toContainText("Possible leak, not confirmed");
  await expect(page.locator(".workflow-added")).toContainText(`${handoff.sources.length} documents read`);
  await expect(page.locator(".workflow-added")).toContainText("Not a live-model latency measurement");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "Inspect this exact detector window", exact: true }).click();
  await expect(page.locator("#window-history")).toHaveValue(handoff.snapshot_id);
});

test("agent work stays separate from a running detector and rejects mismatched automatic handoffs", async ({ page }) => {
  const { id } = await prepare(page, "S1", 23);
  await expect(page.locator("#automatic-state")).toContainText("REPORT AVAILABLE");
  const projection: Projection = await (await page.request.get(`/api/replays/${id}/projection`)).json();
  const root = projection.tasks.find(task => task.automatic && !task.parent_id)!;
  let pending = true;
  await page.route(`**/api/replays/${id}/projection`, async route => {
    const reply = await route.fetch();
    const actual: Projection = await reply.json();
    await route.fulfill({ response: reply, json: pending ? { ...actual, tasks: actual.tasks.map(task =>
      task.id === root.id ? { ...task, state: "RUNNING", result: null, answer: null } : task) } : actual });
  });
  await page.locator("#reconnect").click();
  await expect(page.locator("#agent-activity-state")).toContainText("no reviewed report yet");
  await expect(page.locator("#topology .inspection-interval")).toHaveCount(0);
  await expect(page.locator('#map-legend [data-legend="inspection"]')).toBeHidden();
  await expect(page.locator("#automatic-conclusion")).toContainText("Investigating");
  await expect(page.locator("#agent-findings .agent-source-finding")).toHaveCount(0);
  const elapsed = await page.locator("#agent-elapsed").innerText();
  await expect.poll(() => page.locator("#agent-elapsed").innerText()).not.toBe(elapsed);
  await expect(page.locator("#source-clock")).toContainText("PAUSED");
  pending = false;
  await page.locator("#reconnect").click();
  await expect(page.locator("#agent-activity-state")).toContainText("Recorded agent report");
  await expect(page.locator("#topology .inspection-interval")).toHaveCount(1);
  await expect(page.locator('#map-legend [data-legend="inspection"]')).toBeVisible();
  await expect(page.locator("#agent-findings")).toContainText("final decision accepted");
  const source = page.locator("#agent-findings .agent-source").first();
  await source.locator("summary").click();
  await page.locator("#reconnect").click();
  await expect(source).toHaveAttribute("open");
  await page.route(`**/api/tasks/${root.id}`, async route => {
    const reply = await route.fetch();
    const detail = await reply.json();
    await route.fulfill({ response: reply, json: { ...detail, casefile: { ...detail.casefile, input_hash: "injected-mismatch" } } });
  });
  await page.locator("#reconnect").click();
  await expect(page.locator("#agent-findings")).toContainText("refusing an unmatched comparison");
  await expect(page.locator("#topology .inspection-interval")).toHaveCount(0);
  await expect(page.locator('#map-legend [data-legend="inspection"]')).toBeHidden();
  await expect(page.locator("#agent-findings .agent-source-finding")).toHaveCount(0);
  await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "sensor_alerts");
  await page.unrouteAll({ behavior: "wait" });
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
    await expect(page.locator("#monitoring-warning")).toHaveAttribute("data-kind", "sensor_alerts", { timeout: 30_000 });
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
