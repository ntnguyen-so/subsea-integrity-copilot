/**
 * Shared map semantics under explicit fixtures: paired-station geometry, unassessed
 * warm-up symbols, measured anomalies and quoted agent findings stay distinct.
 * Report-only inspection bands cannot be invented from numerical station brackets.
 */
import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import { join } from "node:path";
import type { EvaluationReport } from "../../web/ts/evaluation";
import type { InvestigationCase, Projection, TaskDetail } from "../../web/ts/types";

test("live and evaluation legends distinguish suspected branches from inspection ranges", async ({ page }) => {
  const bundle = buildSync({
    stdin: { contents: 'export { mapLegend } from "./web/ts/evaluation_maps";', resolveDir: process.cwd(), loader: "ts" },
    bundle: true, write: false, format: "iife", globalName: "LegendFixture",
  }).outputFiles[0].text;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.setContent('<main id="legends"></main>');
  await page.addStyleTag({ path: join(process.cwd(), "web", "styles.css") });
  await page.addScriptTag({ content: `${bundle}
    document.getElementById("legends").append(
      LegendFixture.mapLegend(false, {
        label: "Agent investigation map legend", visibleKinds: ["pattern", "inspection"],
      }),
      LegendFixture.mapLegend(false),
      LegendFixture.mapLegend(true));` });
  for (const label of ["Agent investigation map legend", "Agent findings map legend"]) {
    const legend = page.getByLabel(label, { exact: true });
    const branch = legend.locator('[data-legend="pattern"]');
    const inspection = legend.locator('[data-legend="inspection"]');
    await expect(branch.locator("strong")).toHaveText("Suspected leak");
    await expect(branch.locator("small")).toHaveText("Branch flagged in agent report");
    await expect(inspection.locator("strong")).toHaveText("Inspection area");
    await expect(inspection.locator("small")).toHaveText("Section recommended for inspection");
    const red = await branch.locator("line").evaluate(line => getComputedStyle(line).stroke);
    const green = await inspection.locator("line").evaluate(line => getComputedStyle(line).stroke);
    expect(red).not.toBe(green);
  }
  const truth = page.getByLabel("Ground truth map legend", { exact: true });
  await expect(truth.locator('[data-legend="source"]')).toContainText("Known injected point");
  await expect(truth.locator('[data-legend="pattern"], [data-legend="inspection"]')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("accepted P5 report labels its leak without numerical station recommendations or an invented interval", async ({ page }) => {
  const taskId = process.env.SUBSEA_REPORT_UI_TASK_ID;
  test.skip(!taskId || !process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit accepted-report opt-in.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const response = await page.request.get(`/api/tasks/${taskId}/casefile`);
  expect(response.status()).toBe(200);
  const file: InvestigationCase = await response.json();
  expect(file.inspection).toBeNull();
  const projection: Projection = await (await page.request.get(`/api/replays/${file.generation_id}/projection`)).json();
  expect(projection.latest_window?.end_seconds).toBe(110);
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await page.goto("/");
  await page.route(`**/api/replays/${file.generation_id}/recordings`, route => route.fulfill({
    json: { recordings: [{
      task_id: taskId, state: "SUCCEEDED", source_seconds: 110,
      snapshot_id: file.snapshot_id, input_hash: file.input_hash, created_at: "2026-01-01",
      origin: "saved",
    }] },
  }));
  await page.goto("/?replay=" + encodeURIComponent(file.generation_id));
  await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED", { timeout: 30000 });
  await page.locator("#investigation-time").evaluate(element => {
    const slider = element as HTMLInputElement;
    slider.value = "110"; slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.locator("#tab-live").click();
  const map = page.locator("#agent-investigation-map");
  const drawing = map.locator('svg[aria-label="Dedicated agent investigation pipeline map"]');
  await expect(drawing.locator('[data-leak-label="P5"]')).toHaveText("Suspected leak · P5", { timeout: 45000 });
  await expect(drawing.locator(".eval-leak-pattern")).toHaveCount(1);
  await expect(drawing.locator('.eval-leak-pattern[data-segment-id="P5"]')).toHaveCount(1);
  await expect(drawing.locator("[data-focus-station], .eval-pressure-focus, .eval-focus-callout")).toHaveCount(0);
  await expect(drawing.locator(".eval-inspection")).toHaveCount(0);
  await expect(drawing.locator('[data-sensor="P2-ST2-A"] .eval-agent-issue')).toHaveCount(1);
  const detail: TaskDetail = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  const reportedP5Issues = detail.output_mapping?.mapping?.sensor_issues.filter(item => item.sensor_id.startsWith("P5-")) || [];
  await expect(drawing.locator('[data-sensor^="P5-"] .eval-agent-issue')).toHaveCount(reportedP5Issues.length);
  await expect(drawing.locator('[data-sensor="P7-ST2-A"] .eval-agent-issue')).toHaveCount(0);
  await expect(drawing.locator('[data-sensor="P1-ST7-B"] .eval-agent-issue')).toHaveCount(0);
  for (const issue of detail.output_mapping?.mapping?.sensor_issues.filter(item => item.kind === "missing") || []) {
    await expect(drawing.locator(`[data-sensor="${issue.sensor_id}"]`)).toHaveAttribute("data-issue-kinds", /missing/);
  }
  await expect(map.locator('[data-legend="inspection"]')).toHaveCount(0);
  await expect(map.locator('[data-legend="pressure-focus"]')).toHaveCount(0);
  const stroke = await map.locator('svg .eval-leak-pattern[data-segment-id="P5"]').evaluate(element => getComputedStyle(element).stroke);
  const alert = await map.locator("svg .anomalous .sensor-dot").first().evaluate(element => getComputedStyle(element).stroke);
  expect(stroke).not.toBe(alert);
  expect(writes).toEqual([]);
});

test("waiting agent map shows unassessed warm-up sensors without hiding real completed-window faults", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  const login = await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  expect(login.status()).toBe(200);
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; last_endpoint: number }) =>
    row.scenario === "S7" && row.last_endpoint >= 60);
  expect(replay).toBeDefined();
  const projection: Projection = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
  const snapshot = projection.latest_window!;
  expect(snapshot).not.toBeNull();
  let warming = true;
  const findings = projection.pack.sensors.map((sensor, index) => ({
    sensor_id: sensor.id, channel: "pressure" as const, expected: 60,
    received: warming ? 25 : index === 0 ? 59 : 60,
    usable: warming ? 25 : index === 0 ? 58 : 60,
    missing: warming ? 35 : index === 0 ? 1 : 0,
    hard_excluded: warming ? 1 : index === 0 ? 1 : 0,
    spike_count: 0, drift_suspected: false, peer_disagreement: false,
    anomaly_count: warming || index === 0 ? 1 : 0,
    max_score: 0, persistence_seconds: 0, evidence_ids: [],
  }));
  const frame = () => ({
    ...snapshot, end_seconds: warming ? 25 : 60,
    quality: {
      ...snapshot.quality, status: warming ? "WARMING_UP" : snapshot.quality.status,
      findings: warming ? findings : findings.map((item, index) => ({
        ...item, received: index === 0 ? 59 : 60, usable: index === 0 ? 58 : 60,
        missing: index === 0 ? 1 : 0, hard_excluded: index === 0 ? 1 : 0,
        anomaly_count: index === 0 ? 1 : 0,
      })),
    },
  });
  await page.route(`**/api/replays/${replay.id}/recordings`, route => route.fulfill({ json: { recordings: [] } }));
  await page.route(`**/api/replays/${replay.id}/windows`, route => route.fulfill({ json: { windows: [frame()] } }));
  await page.route(`**/api/replays/${replay.id}/projection`, route => route.fulfill({ json: {
    ...projection, latest_window: frame(), tasks: [], episodes: [],
    replay: { ...projection.replay, state: "PAUSED", investigation_window_id: null },
  } }));
  const posts: string[] = [];
  page.on("request", request => { if (request.method() === "POST") posts.push(request.url()); });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  const agentMap = page.locator("#agent-investigation-map");
  await expect(agentMap.locator("svg [data-sensor].unknown")).toHaveCount(projection.pack.sensors.length);
  await expect(agentMap.locator("svg [data-sensor].missing, svg [data-sensor].anomalous")).toHaveCount(0);
  await expect(agentMap).toContainText("Collecting a complete 60-second monitoring window");
  await expect(agentMap.locator('[data-legend="unknown"]')).toContainText("Not assessed");
  await expect(agentMap.locator('[data-legend="missing"], [data-legend="normal"]')).toHaveCount(0);
  const sensor = projection.pack.sensors[0].id;
  await agentMap.locator(`[data-sensor="${sensor}"]`).click();
  await expect(agentMap).toContainText(`${sensor} · not assessed`);
  await expect(page.locator("#topology [data-sensor].unknown")).toHaveCount(projection.pack.sensors.length);

  warming = false;
  await page.reload();
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  await expect(agentMap.locator("svg [data-sensor].unknown")).toHaveCount(0);
  await expect(agentMap.locator("svg [data-sensor].missing")).toHaveCount(1);
  await expect(agentMap.locator("svg [data-sensor].anomalous")).toHaveCount(1);
  await expect(agentMap.locator(`[data-sensor="${sensor}"]`)).toHaveClass(/missing/);
  await expect(page.locator("#topology [data-sensor].missing")).toHaveCount(1);
  expect(posts).toEqual([]);
});

test("live and evaluation agent maps share marker styles and paired station geometry", async ({ page }) => {
  const taskId = process.env.SUBSEA_REPORT_UI_TASK_ID;
  test.skip(!taskId || !process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit recorded-map opt-in.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const caseResponse = await page.request.get(`/api/tasks/${taskId}/casefile`);
  expect(caseResponse.status()).toBe(200);
  const file: InvestigationCase = await caseResponse.json();
  const detail: TaskDetail = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  expect(detail.output_mapping?.status).toBe("completed");
  const mapping = detail.output_mapping!.mapping!;
  const projectionResponse = await page.request.get(`/api/replays/${file.generation_id}/projection`);
  expect(projectionResponse.status()).toBe(200);
  const projection: Projection = await projectionResponse.json();
  const windowResponse = await page.request.get(`/api/windows/${file.snapshot_id}`);
  expect(windowResponse.status()).toBe(200);
  const snapshot: Projection["latest_window"] = await windowResponse.json();
  expect(snapshot).not.toBeNull();
  const intervals = mapping.leaks.filter(item => item.interval);
  file.inspection = { segment_id: "P6", start_m: 200, end_m: 600 };
  detail.casefile = file;
  snapshot!.location = {
    status: "located", best: { segment_id: "P6", chainage_m: 400,
      position: { x: 0, y: 0 }, residual: 0, strength: 1 },
    compatible: [], reason: "Numerical provenance regression fixture", method: "fixture-only",
    grid_m: 50, inspection_start_m: 200, inspection_end_m: 600, station_bracket_m: [200, 600],
  };
  await page.route(`**/api/tasks/${taskId}`, route => route.fulfill({ json: detail }));
  await page.route(`**/api/tasks/${taskId}/casefile`, route => route.fulfill({ json: file }));
  await page.route(`**/api/windows/${file.snapshot_id}`, route => route.fulfill({ json: snapshot }));
  await page.route(`**/api/replays/${file.generation_id}/recordings`, route => route.fulfill({ json: { recordings: [] } }));
  const flags = snapshot!.quality.findings;
  const anomalies = flags.filter(row => row.anomaly_count > 0).map(row => row.sensor_id);
  const missing = flags.filter(row => row.missing || row.hard_excluded).map(row => row.sensor_id);
  const report: EvaluationReport = {
    version: "spatial-evaluation-v1", status: "completed", run_id: "map-style-fixture",
    metrics: null, cases: [{
      case_id: "map-style", name: "Recorded-map style comparison", network_id: "N1",
      status: "completed", dataset_sha256: "fixture", root_count: 1, accepted_report: true,
      source_seconds: snapshot!.end_seconds, snapshot_id: snapshot!.id, input_hash: snapshot!.input_hash,
      truth: { leak_source: null, sensor_issues: [], pressure_anomaly_sensors: anomalies,
        missing_value_sensors: missing, pressure_trigger: true },
      authorized_inspection: file.inspection,
      extraction: { status: "completed", mapping },
    }],
    networks: [{
      id: "N1", name: "Recorded-map style comparison", status: "completed",
      pack: projection.pack, dataset_sha256: "fixture", frames: [{
        source_seconds: snapshot!.end_seconds, window_start_seconds: snapshot!.end_seconds - 60,
        snapshot_id: snapshot!.id, input_hash: snapshot!.input_hash, review_case_id: "map-style",
        truth: { leak_source: null, sensor_issues: [] }, pressure_summaries: {},
        detector: { pressure_anomaly_sensors: anomalies, missing_value_sensors: missing, coverage: snapshot!.quality.coverage },
      }],
    }],
  };
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  const inference: string[] = [];
  page.on("request", request => {
    if (request.method() === "POST" && request.url().endsWith("/questions")) inference.push(request.url());
  });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(file.generation_id) + "&view=live");
  await page.locator("#window-history").selectOption(file.snapshot_id);
  await expect(page.locator("#topology")).toHaveAttribute("data-snapshot", file.snapshot_id);
  await expect(page.locator("#topology .eval-inspection")).toHaveCount(intervals.length);
  await expect(page.locator("#topology .support-ring, #topology .candidate")).toHaveCount(0);
  await expect(page.locator('#map-legend [data-legend="selection"] small')).toHaveText("Shows this sensor's pressure trend");
  const liveSensors = await page.locator("#topology [data-sensor]").evaluateAll(items => items.map(item => {
    const dot = item.querySelector(".sensor-dot")!;
    return { id: item.getAttribute("data-sensor"), x: dot.getAttribute("cx"), y: dot.getAttribute("cy"), r: dot.getAttribute("r") };
  }));
  const style = (item: Element) => {
    const css = getComputedStyle(item);
    return { fill: css.fill, stroke: css.stroke, width: css.strokeWidth, dash: css.strokeDasharray };
  };
  const legendKinds = ["anomaly", "missing", "normal", "selection",
    ...(mapping.leaks.length ? ["pattern"] : []), ...(intervals.length ? ["inspection"] : [])];
  const liveStyles: Record<string, unknown> = {};
  const liveLabels: Record<string, string> = {};
  for (const kind of legendKinds) {
    const entry = page.locator(`#map-legend [data-legend="${kind}"]`);
    liveLabels[kind] = (await entry.locator("strong").textContent())!;
    liveStyles[kind] = await entry.locator("svg .sensor-dot, svg > line").evaluate(style);
  }
  const selectedId = projection.pack.sensors[0].id;
  await page.locator(`#topology [data-sensor="${selectedId}"]`).click();
  const selectedStyle = await page.locator(`#topology [data-sensor="${selectedId}"] .eval-selection`).evaluate(style);
  const livePatternStyle = mapping.leaks.length ? await page.locator("#topology .eval-leak-pattern").first().evaluate(style) : null;
  const liveIntervalStyle = intervals.length ? await page.locator("#topology .eval-inspection").first().evaluate(style) : null;
  const dedicated = page.locator("#agent-investigation-map");
  await expect(dedicated).toContainText("Agent-text extraction", { timeout: 45000 });
  await expect(dedicated.locator(".eval-inspection")).toHaveCount(intervals.length);
  await expect(dedicated.locator(".eval-pressure-focus, .eval-focus-callout")).toHaveCount(0);
  const issueLabels = (items: Element[]) => items
    .filter(item => item.getAttribute("data-issue-kinds"))
    .map(item => ({ sensor_id: item.getAttribute("data-sensor"), kinds: item.getAttribute("data-issue-kinds") }))
    .sort((a, b) => a.sensor_id!.localeCompare(b.sensor_id!));
  const dashboardIssues = await dedicated.locator("[data-sensor]").evaluateAll(issueLabels);
  expect(dashboardIssues.length).toBeGreaterThan(0);
  expect(dashboardIssues).toEqual([...new Set(mapping.sensor_issues.map(item => item.sensor_id))].map(sensor_id => ({
    sensor_id, kinds: mapping.sensor_issues.filter(item => item.sensor_id === sensor_id).map(item => item.kind).join(","),
  })).sort((a, b) => a.sensor_id.localeCompare(b.sensor_id)));
  await page.locator("#tab-live").click();
  const issue = mapping.sensor_issues.find(item => item.kind !== "missing")!;
  await dedicated.locator(`[data-sensor="${issue.sensor_id}"]`).click();
  await expect(dedicated).toContainText(issue.quote.text);
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const agent = page.locator("#evaluation-agent-map");
  await expect(agent.locator(".eval-inspection")).toHaveCount(intervals.length);
  expect(await agent.locator("[data-sensor]").evaluateAll(issueLabels)).toEqual(dashboardIssues);
  const legend = page.getByLabel("Agent findings map legend");
  for (const kind of legendKinds) {
    const entry = legend.locator(`[data-legend="${kind}"]`);
    await expect(entry.locator("strong")).toHaveText(liveLabels[kind]);
    expect(await entry.locator("svg .sensor-dot, svg > line").evaluate(style)).toEqual(liveStyles[kind]);
  }
  expect(await agent.locator("[data-sensor]").evaluateAll(items => items.map(item => {
    const dot = item.querySelector(".sensor-dot")!;
    return { id: item.getAttribute("data-sensor"), x: dot.getAttribute("cx"), y: dot.getAttribute("cy"), r: dot.getAttribute("r") };
  }))).toEqual(liveSensors);
  await agent.locator(`[data-sensor="${selectedId}"]`).click();
  expect(await agent.locator(`[data-sensor="${selectedId}"] .eval-selection`).evaluate(style)).toEqual(selectedStyle);
  if (mapping.leaks.length) {
    expect(await agent.locator(".eval-leak-pattern").first().evaluate(style)).toEqual(livePatternStyle);
  }
  if (intervals.length) expect(await agent.locator(".eval-inspection").first().evaluate(style)).toEqual(liveIntervalStyle);
  expect(inference).toEqual([]);

  await page.route(`**/api/replays/${file.generation_id}/projection`, route => route.fulfill({
    json: { ...projection, latest_window: snapshot, tasks: [], episodes: [],
      replay: { ...projection.replay, workflow: "sensor_alerts" } },
  }));
  await page.reload();
  await page.goto("/?replay=" + encodeURIComponent(file.generation_id) + "&view=live");
  await expect(page.locator("#topology [data-sensor]")).toHaveCount(projection.pack.sensors.length);
  await expect(page.locator("#topology .eval-leak-pattern, #topology .eval-inspection, #topology .eval-agent-issue")).toHaveCount(0);
  await expect(page.locator('#map-legend [data-legend="pattern"], #map-legend [data-legend="inspection"], #map-legend [data-legend="agent"]')).toHaveCount(0);
});
