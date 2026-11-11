/**
 * Readings-first inspection with explicit synthetic API fixtures: absent versus
 * unusable samples, common peer scales, stable sensor/window selection and optional
 * source audit. Only identity/hash/version-matched accepted reports accompany data.
 */
import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import type { SensorInspection } from "../../web/ts/sensor_inspection";
import type { AgentTask, CanonicalObservation, InvestigationCase, Projection, Sensor, SitePack, TaskDetail, WindowSnapshot } from "../../web/ts/types";

const sensor: Sensor = { id: "P1-ST1-A", station_id: "P1-ST1", segment_id: "P1", chainage_m: 100,
  position: { x: 100, y: 0 }, failure_domain_id: "gateway-1", channels: ["pressure"] };
const peer: Sensor = { ...sensor, id: "P1-ST1-B" };
const pack: SitePack = { id: "fixture", name: "Fixture", version: "pack", sensors: [sensor, peer],
  segments: [{ id: "P1", name: "Pipeline 1", points: [{ x: 0, y: 0 }, { x: 200, y: 0 }], length_m: 200, diameter_m: 1 }],
  sample_seconds: 1, window_seconds: 4, hop_seconds: 1, lateness_seconds: 1,
  min_observers: 1, min_failure_domains: 1, min_coverage: 0.8, min_stations: 1, persistence_seconds: 1, neighborhood_m: 200 };
const window: WindowSnapshot = { id: "snapshot", site_id: "site", generation_id: "generation",
  window_start: "2026-01-01T00:00:00Z", window_end: "2026-01-01T00:00:04Z", end_seconds: 4,
  revision: 0, predecessor_id: null, input_hash: "input", pack_version: "pack", baseline_version: "baseline",
  parameter_version: "parameters", clock_seconds: 4, watermark_seconds: 4, created_at: "2026-01-01T00:00:04Z",
  canonical_count: 2,
  quality: { status: "READY", expected_samples: 4, received_samples: 2, usable_samples: 1, coverage: 0.25,
    failure_domains_available: 1, conflicts: [], issues: [], findings: [{
      sensor_id: sensor.id, channel: "pressure", expected: 4, received: 2, usable: 1, missing: 3,
      hard_excluded: 1, spike_count: 0, drift_suspected: false, peer_disagreement: false,
      anomaly_count: 0, max_score: 0, persistence_seconds: 0, evidence_ids: [],
    }] },
  event: { hypothesis: "insufficient_evidence", eligible_hypotheses: [], supporting_sensor_ids: [],
    failure_domain_count: 0, persistence_seconds: 0, segment_ids: [], evidence_ids: [], counterevidence: [],
    eligible_location: false, criteria_id: "fixture" }, location: null, claims: {}, evidence: {} };
function reading(id: string, second: number, value: number | null): CanonicalObservation {
  const stamp = `2026-01-01T00:00:0${second}Z`;
  return { id: `row-${id}-${second}`, identity: `${id}-${second}`, sensor_id: id, channel: "pressure",
    observed_at: stamp, received_at: stamp, value, unit: "bar", validity: value === null ? "invalid" : "usable",
    source_id: "fixture", source_record_id: String(second), transformations: ["Synthetic unit conversion"],
    original: { sensor_id: id, channel: "pressure", observed_at: stamp, received_at: stamp,
      value: value === null ? "N/A" : "1015.26", unit: "psi", source_id: "fixture", source_record_id: String(second) } };
}
const answer = "P1 has a suspected leak pattern; inspect 50–150 m. P1-ST1-A has a suspected measurement offset.";
const interpretation = { focus: "Fixture", answer: { text: answer, references: [] }, competing_causes: [], follow_up_questions: [] };
const task: AgentTask = { id: "root", root_id: "root", site_id: "site", generation_id: "generation",
  snapshot_id: window.id, episode_id: null, parent_id: null, role: "operator_response",
  purpose: "Fixture", question: "Fixture", mode: "live", state: "SUCCEEDED",
  created_at: window.window_end, updated_at: window.window_end, model_calls: 1, tool_calls: 0, plan: [], answer,
  result: { outcome: "complete", claim_refs: [], evidence_ids: [], limitations: [], hypothesis: null,
    recommendation_ids: [], summary: "", investigation: null, interpretation },
  error_code: null, error_message: null, automatic: true };
const file: InvestigationCase = { schema_version: "investigation-v1", task_id: task.id,
  generation_id: "generation", snapshot_id: window.id, question: "Fixture", mode: "live", state: "SUCCEEDED",
  window_start: window.window_start, window_end: window.window_end, input_hash: window.input_hash,
  pack_version: "pack", baseline_version: "baseline", parameter_version: "parameters", history_version: null,
  disposition: "Fixture", hypothesis: null, inspection: null, next_action: "Verify independently",
  interpretation, checked_claims: [], limitations: [], sources: [], comparisons: [], steps: [], reused_task_ids: [],
  fresh_model_calls: 1, fresh_tool_calls: 0, recorded_elapsed_seconds: 1, provider_cost_usd: null, authority: "Read only",
  report_target_seconds: 300, report_target_met: true, interpretation_review: null, knowledge_packet: null, knowledge_used_ids: [] };
const report: TaskDetail = { task, casefile: file, children: [], receipts: [], investigation_receipts: [],
  output_mapping: { status: "completed", mapping: {
    leaks: [{ segment_id: "P1", assertion: "suspected", interval: { start_m: 50, end_m: 150 },
      quote: { path: "answer.text", text: answer } }],
    sensor_issues: [{ sensor_id: sensor.id, kind: "offset", assertion: "suspected", quote: { path: "answer.text", text: answer } }],
    instrumentation_concern: true } } };

function inspectionBundle(): string {
  return buildSync({ stdin: {
    contents: 'export { renderSensorInspection } from "./web/ts/sensor_inspection";', resolveDir: process.cwd(), loader: "ts" },
    bundle: true, write: false, format: "iife", globalName: "InspectionFixture" }).outputFiles[0].text;
}

test("sensor-only inspection excludes both live and recorded agent explanations", async ({ page }) => {
  const state: Omit<SensorInspection, "openReport" | "inspectWindow"> = {
    pack, window, sensor, readings: [reading(sensor.id, 0, 70)],
    loading: false, error: null, peer: null, peerSensor: null, peerLoading: false,
    peerError: null, reportError: null, reports: [report], pending: false,
    recordedReport: { snapshot: window, detail: report }, agentAssisted: false,
  };
  await page.setContent('<main id="inspection"></main>');
  await page.addScriptTag({ content: `${inspectionBundle()}
    InspectionFixture.renderSensorInspection(document.getElementById("inspection"),
      { ...${JSON.stringify(state)}, openReport: () => {}, inspectWindow: () => {} });` });
  await expect(page.locator(".inspection-samples tbody tr")).toHaveCount(1);
  await expect(page.locator(".inspection-metrics")).toBeVisible();
  await expect(page.locator(".inspection-agent")).toHaveCount(0);
  await expect(page.locator("#inspection")).not.toContainText(answer);
});

test("readings distinguish unreceived and unusable data, compare one scale, and attach only matching accepted findings", async ({ page }) => {
  const bundle = inspectionBundle();
  const state: Omit<SensorInspection, "openReport" | "inspectWindow"> = { pack, window, sensor,
    readings: [reading(sensor.id, 0, 70), reading(sensor.id, 1, null)],
    loading: false, error: null, peer: { sensor: peer, observations: [reading(peer.id, 0, 80), reading(peer.id, 1, 80.1)] },
    peerSensor: peer, peerLoading: false, peerError: null, reportError: null, reports: [report], pending: false };
  await page.setContent('<main><div id="inspection"></div></main>');
  await page.addStyleTag({ path: join(process.cwd(), "web", "styles.css") });
  await page.addScriptTag({ content: `${bundle}
    window.inspectionState = ${JSON.stringify(state)};
    window.renderInspection = () => InspectionFixture.renderSensorInspection(document.getElementById("inspection"),
      { ...window.inspectionState, openReport: () => {}, inspectWindow: () => {} });
    window.renderInspection();` });
  await expect(page.locator(".inspection-metrics dd")).toHaveText(["1", "1", "2"]);
  await expect(page.locator(".inspection-samples thead th")).toHaveText(["Measured at (UTC)", "Pressure (bar)", "Reading status"]);
  await expect(page.locator(".inspection-samples tbody tr").nth(0)).toContainText("70");
  await expect(page.locator(".inspection-samples tbody tr").nth(1)).toContainText("Unavailable");
  const axes = await page.locator(".inspection-trends svg").evaluateAll(charts =>
    charts.map(chart => [...chart.querySelectorAll('text[x="3"]')].map(item => item.textContent)));
  expect(axes).toHaveLength(2); expect(axes[0]).toEqual(axes[1]);
  await expect(page.locator("#inspection")).toContainText("paired agreement is not independent verification");
  await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "matched");
  await expect(page.locator(".inspection-agent-quote")).toHaveCount(2);
  await expect(page.locator(".inspection-agent")).toContainText("50–150 m, not an exact leak point");
  await page.evaluate(() => {
    const fixture = window as typeof window & { inspectionState: SensorInspection; renderInspection: () => void };
    fixture.inspectionState.reports[0]!.casefile!.input_hash = "different-input"; fixture.renderInspection();
  });
  await expect(page.locator(".inspection-agent-quote")).toHaveCount(0);
  await expect(page.locator(".inspection-agent")).toContainText("No accepted report matches");
  await page.evaluate(() => {
    const fixture = window as typeof window & { inspectionState: SensorInspection; renderInspection: () => void };
    fixture.inspectionState.reports[0]!.casefile!.snapshot_id = "older-snapshot";
    fixture.inspectionState.reports[0]!.task.snapshot_id = "older-snapshot"; fixture.renderInspection();
  });
  await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "different-window");
  await expect(page.getByRole("button", { name: "Inspect the report's measurement window" })).toBeVisible();
  await page.evaluate(() => {
    const fixture = window as typeof window & { inspectionState: SensorInspection; renderInspection: () => void };
    fixture.inspectionState.reports = []; fixture.inspectionState.pending = true; fixture.renderInspection();
  });
  await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "pending");
  await expect(page.locator(".inspection-agent")).toContainText("draft is provisional");
  await page.evaluate(() => {
    const fixture = window as typeof window & { inspectionState: SensorInspection; renderInspection: () => void };
    fixture.inspectionState.error = "API disconnected"; fixture.renderInspection();
  });
  await expect(page.locator("#inspection")).toContainText("Readings unavailable: API disconnected");
  await expect(page.locator(".inspection-samples tbody tr")).toHaveCount(0);
  await page.evaluate(() => {
    const fixture = window as typeof window & { inspectionState: SensorInspection; renderInspection: () => void };
    fixture.inspectionState.pack = null; fixture.inspectionState.window = null;
    fixture.inspectionState.sensor = null; fixture.renderInspection();
  });
  await expect(page.locator("#inspection")).toContainText("Choose a run and a sensor");
  await expect(page.locator("#inspection")).not.toHaveAttribute("data-sensor");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("compatible recorded findings accompany reconstructed readings only with the exact original evidence", async ({ page }) => {
  const displayed: WindowSnapshot = { ...window, id: "display-snapshot", generation_id: "display-generation" };
  const state: Omit<SensorInspection, "openReport" | "inspectWindow"> = {
    pack, window: displayed, sensor, readings: [reading(sensor.id, 0, 70)],
    loading: false, error: null, peer: null, peerSensor: null, peerLoading: false,
    peerError: null, reportError: null, reports: [], pending: false,
    recordedReport: { snapshot: window, detail: report },
  };
  await page.setContent('<main><div id="inspection"></div></main>');
  await page.addScriptTag({ content: `${inspectionBundle()}
    window.inspectionState = ${JSON.stringify(state)};
    window.renderInspection = () => InspectionFixture.renderSensorInspection(document.getElementById("inspection"),
      { ...window.inspectionState, openReport: () => {}, inspectWindow: () => {} });
    window.renderInspection();` });
  await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "matched");
  await expect(page.locator(".inspection-agent")).toContainText("Compatible saved investigation");
  await expect(page.locator(".inspection-agent-quote")).toHaveCount(2);
  const mismatches: Partial<WindowSnapshot>[] = [
    { input_hash: "different" }, { site_id: "different" }, { window_start: "2025-01-01T00:00:00Z" },
    { window_end: "2027-01-01T00:00:00Z" }, { end_seconds: 5 }, { clock_seconds: 5 },
    { pack_version: "different" }, { baseline_version: "different" }, { parameter_version: "different" },
  ];
  for (const mismatch of mismatches) {
    await page.evaluate(selected => {
      const fixture = window as typeof window & { inspectionState: SensorInspection; renderInspection: () => void };
      fixture.inspectionState.window = selected; fixture.renderInspection();
    }, { ...displayed, ...mismatch });
    await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "unavailable");
    await expect(page.locator(".inspection-agent-quote")).toHaveCount(0);
  }
  await page.evaluate(selected => {
    const fixture = window as typeof window & { inspectionState: SensorInspection; renderInspection: () => void };
    fixture.inspectionState.window = selected;
    fixture.inspectionState.recordedReport!.detail.casefile!.input_hash = "invalid-original";
    fixture.renderInspection();
  }, displayed);
  await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "unavailable");
  await expect(page.locator(".inspection-agent-quote")).toHaveCount(0);
});

test("a novice can choose a sensor, compare readings and inspect the report window without navigating internal IDs", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD || !process.env.SUBSEA_REPORT_UI_TASK_ID, "Requires an owned recorded report.");
  const errors: string[] = [], writes: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const response = await page.request.get(`/api/tasks/${process.env.SUBSEA_REPORT_UI_TASK_ID}/casefile`);
  expect(response.ok(), `Recorded casefile returned HTTP ${response.status()}`).toBeTruthy();
  const file: InvestigationCase = await response.json();
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(file.generation_id) + "&view=live");
  await expect(page.locator("#channel-charts svg")).not.toHaveCount(0);
  await page.locator("#inspect-raw").click();
  await expect(page.locator("#inspection-sensor")).toBeEnabled();
  await expect(page.locator(".inspection-samples tbody tr")).not.toHaveCount(0);
  await expect(page.locator("#source-audit")).not.toHaveAttribute("open");
  await expect(page.locator("#evidence-chips")).toBeHidden();
  await page.locator("#inspection-pipeline").selectOption("P5");
  await page.locator("#inspection-sensor").selectOption("P5-ST4-A");
  await expect(page.locator("#sensor-inspection-workspace")).toHaveAttribute("data-sensor", "P5-ST4-A");
  await expect(page.locator(".inspection-trends svg")).toHaveCount(2);
  await expect(page.locator("#inspection-peer")).toHaveValue("P5-ST4-B");
  await page.locator("#window-history").selectOption(file.snapshot_id);
  await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "matched");
  await expect(page.locator(".inspection-agent")).toHaveAttribute("data-snapshot", file.snapshot_id);
  await expect(page.locator(".inspection-agent")).toContainText("same window");
  await page.locator("#source-audit > summary").click();
  await expect(page.locator("#raw-table table")).toBeVisible();
  await expect(page.locator("#evidence-chips button")).not.toHaveCount(0);
  await page.locator("#source-audit > summary").click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(errors).toEqual([]); expect(writes).toEqual([]);
});

for (const workflow of ["sensor_alerts", "agent_assisted"] as const) {
test(`${workflow} inspection and comparison work on unflagged readings without agent assistance`, async ({ page }) => {
  const errors: string[] = [], unexpected: string[] = [], writes: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.method() !== "GET") writes.push(request.url()); });
  const other: Sensor = { ...sensor, id: "P2-ST1-A", segment_id: "P2", station_id: "P2-ST1" };
  const fixturePack: SitePack = { ...pack, sensors: [sensor, peer, other],
    segments: [...pack.segments, { ...pack.segments[0]!, id: "P2", name: "Pipeline 2" }] };
  const fixtureWindow: WindowSnapshot = { ...window, quality: {
    ...window.quality, expected_samples: 12, received_samples: 12, usable_samples: 12, coverage: 1,
    findings: fixturePack.sensors.map(item => ({
      ...window.quality.findings[0]!, sensor_id: item.id, received: 4, usable: 4,
      missing: 0, hard_excluded: 0,
    })),
  }, evidence: {
    "pressure-source": { id: "pressure-source", sensor_id: sensor.id, channel: "pressure",
      kind: "channel_summary", value: { baseline_median: 75, baseline_scale: 1, anomaly_threshold: 3 } },
  } };
  const projection: Projection = { pack: fixturePack, latest_window: fixtureWindow,
    replay: { id: window.generation_id, site_id: window.site_id, scenario: "fixture", source_version: "pressure-v3",
      seed: 1, mode: "live", workflow, pause_on_anomaly: false,
      investigation_window_id: null, detected_alert_keys: [], state: "PAUSED", clock_seconds: 4,
      speed: 1, duration_seconds: 360, epoch: window.window_start, latest_window_id: window.id,
      version: 1, updated_at: window.window_end, error: null },
    warning: { kind: "fixture", severity: "info", snapshot_id: window.id, title: "Synthetic inspection fixture", message: "" },
    episodes: [], tasks: workflow === "agent_assisted" ? [task] : [], cursor: 0,
    health: { agent: "running", monitor: "running", observability: {} }, server_time: window.window_end };
  await page.route("http://127.0.0.1:8086/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: readFileSync(join(process.cwd(), "web", "index.html"), "utf8") });
    if (path === "/assets/styles.css") return route.fulfill({ contentType: "text/css", body: readFileSync(join(process.cwd(), "web", "styles.css"), "utf8") });
    if (path === "/assets/console.js") return route.fulfill({ contentType: "text/javascript", body: readFileSync(join(process.cwd(), "web", "dist", "console.js"), "utf8") });
    if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: ": fixture\n\n" });
    const responses: Record<string, unknown> = {
      "/api/session": { authenticated: true, csrf_token: "synthetic-fixture", username: "operator" },
      "/api/scenarios": { scenarios: [{ id: "fixture", name: "Synthetic fixture" }] },
      "/api/replays": { replays: [projection.replay] },
      "/api/replays/generation/projection": projection,
      "/api/replays/generation/windows": { windows: [fixtureWindow] },
      "/api/tasks/root": report,
      "/api/tasks/root/trace": {},
      "/api/windows/snapshot": fixtureWindow,
      "/api/evaluation": { version: "reference-evaluation-v1", status: "not_run", cases: [], metrics: null },
    };
    if (path.endsWith("/recordings")) return route.fulfill({ json: { base_playback_speed: 5, recordings: [] } });
    const chosen = fixturePack.sensors.find(item => path === `/api/windows/snapshot/sensors/${item.id}`);
    if (chosen) return route.fulfill({ json: { sensor: chosen,
      observations: [0, 1, 2, 3].map(second => reading(chosen.id, second, chosen.id === peer.id ? 80 : 70)) } });
    if (path in responses) return route.fulfill({ json: responses[path] });
    unexpected.push(path);
    return route.fulfill({ status: 404, json: { detail: `No synthetic fixture for ${path}` } });
  });
  await page.goto("/?replay=" + encodeURIComponent(window.generation_id) + "&view=live");
  await expect(page.locator(".rail [role=tab]")).toHaveCount(3);
  await expect(page.getByRole("button", { name: "Follow current", exact: true })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Inspect", exact: true })).toHaveCount(0);
  await page.locator("#tab-live").focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#tab-evaluation")).toBeFocused();
  await page.keyboard.press("Home");
  await expect(page.locator("#tab-live")).toBeFocused();
  await expect(page.locator("#channel-charts svg")).not.toHaveCount(0);
  await page.locator("#compare-sensors").click();
  await expect(page.locator("#comparison-charts article")).toHaveCount(3);
  await expect(page.locator("#comparison-charts svg")).toHaveCount(3);
  await expect(page.locator("#window-history")).toHaveValue(fixtureWindow.id);
  await page.locator("#inspect-raw").click();
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".manual-panel #panel-evidence")).toBeVisible();
  await expect(page.locator("#sensor-inspection-title")).toBeFocused();
  await expect(page.locator(".inspection-samples tbody tr")).toHaveCount(4);
  if (workflow === "agent_assisted") await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "matched");
  else await expect(page.locator(".inspection-agent")).toHaveCount(0);
  await expect(page.locator("#source-audit")).not.toHaveAttribute("open");
  await expect(page.locator(".inspection-trends svg")).toHaveCount(2);
  await page.locator("#inspection-pipeline").selectOption("P2");
  await expect(page.locator("#inspection-sensor")).toHaveValue(other.id);
  await expect(page.locator("#sensor-inspection-workspace")).toHaveAttribute("data-sensor", other.id);
  await page.locator("#inspection-pipeline").selectOption("P1");
  await page.locator("#inspection-sensor").selectOption(peer.id);
  await expect(page.locator("#inspection-sensor")).toHaveValue(peer.id);
  await expect(page.locator("#inspection-peer")).toHaveValue(sensor.id);
  await page.locator("#inspection-sensor").selectOption(sensor.id);
  await page.locator("#inspection-peer").selectOption("");
  await expect(page.locator(".inspection-trends svg")).toHaveCount(1);
  await page.locator("#inspection-peer").selectOption(peer.id);
  await expect(page.locator(".inspection-trends svg")).toHaveCount(2);
  await expect(page.locator("#sensor-inspection-workspace")).toContainText("paired agreement is not independent verification");
  await page.getByRole("checkbox", { name: `Compare ${sensor.id}`, exact: true }).check();
  await page.getByRole("checkbox", { name: `Compare ${peer.id}`, exact: true }).check();
  await page.locator("#compare-sensors").click();
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".manual-panel #comparison-panel")).toBeVisible();
  await expect(page.locator("#comparison-title")).toBeFocused();
  await expect(page.locator("#panel-evidence")).toBeHidden();
  await expect(page.locator("#comparison-charts article > h3")).toHaveText([
    `${sensor.id} / ${sensor.failure_domain_id}`, `${peer.id} / ${peer.failure_domain_id}`,
  ]);
  await expect(page.locator("#window-history")).toHaveValue(fixtureWindow.id);
  await page.locator("#inspect-raw").click();
  await expect(page.locator(".manual-panel #panel-evidence")).toBeVisible();
  await expect(page.locator("#comparison-panel")).toBeHidden();
  await expect(page.locator("#inspection-sensor")).toHaveValue(sensor.id);
  await expect(page.locator(".inspection-trends svg")).toHaveCount(2);
  await page.screenshot({ path: test.info().outputPath("sensor-inspection-desktop.png"), fullPage: true });
  await page.locator("#source-audit > summary").click();
  await expect(page.locator("#raw-table table")).toBeVisible();
  await expect(page.locator("#raw-table")).toContainText("psi");
  await page.locator("#evidence-chips button").first().click();
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".manual-panel #panel-evidence")).toBeVisible();
  await expect(page.locator("#source-audit")).toHaveAttribute("open");
  await expect(page.locator("#evidence-detail")).toContainText("pressure-source");
  await page.locator("#source-audit > summary").click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: test.info().outputPath("sensor-inspection-mobile.png"), fullPage: true });
  expect(errors).toEqual([]); expect(unexpected).toEqual([]); expect(writes).toEqual([]);
});
}
