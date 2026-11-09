import { test, expect } from "@playwright/test";
import type { EvaluationReport } from "../../web/ts/evaluation";
import type { SpatialFrame } from "../../web/ts/evaluation_maps";
import type { SitePack } from "../../web/ts/types";

function recording(): EvaluationReport {
  const lines = [
    ["P1", 0, -1600, 0, 0], ["P2", 0, 0, -1280, 960], ["P3", 0, 0, 1280, 960],
    ["P4", -1280, 960, -2560, 1920], ["P5", -1280, 960, -320, 2240],
    ["P6", 1280, 960, 320, 2240], ["P7", 1280, 960, 2560, 1920],
  ] as const;
  const segments = lines.map(([id, x1, y1, x2, y2]) => ({
    id, name: id, points: [{ x: x1, y: y1 }, { x: x2, y: y2 }], length_m: 1600, diameter_m: .5,
  }));
  const pack: SitePack = {
    id: "unit-test-only", name: "Unit-test-only geometry", version: "unit-test-only",
    segments, sensors: segments.flatMap(segment => Array.from({ length: 8 }, (_, station) =>
      ["A", "B"].map(tap => ({
        id: `${segment.id}-ST${station + 1}-${tap}`, station_id: `ST${station + 1}`,
        segment_id: segment.id, chainage_m: 100 + station * 200,
        position: { x: segment.points[0].x, y: segment.points[0].y },
        failure_domain_id: `gateway-${segment.id}-${station % 2}`, channels: ["pressure"] as ["pressure"],
      })),
    ).flat()),
    sample_seconds: 1, window_seconds: 60, hop_seconds: 5, lateness_seconds: 5,
    min_observers: 3, min_failure_domains: 2, min_coverage: .6, min_stations: 2,
    persistence_seconds: 15, neighborhood_m: 400,
  };
  const frames: SpatialFrame[] = Array.from({ length: 21 }, (_, index) => {
    const end = 60 + index * 15;
    return {
      source_seconds: end, window_start_seconds: end - 60,
      snapshot_id: `snapshot-${end}`, input_hash: `input-${end}`,
      review_case_id: [60, 150, 360].includes(end) ? `N1@${end}` : null,
      truth: {
        leak_source: end > 90 ? { segment_id: "P5", chainage_m: 800, start_seconds: 90 } : null,
        sensor_issues: end > 180 ? [{ sensor_id: "P3-ST7-A", kind: "drift" }] : [],
      },
      detector: {
        pressure_anomaly_sensors: end > 90 ? ["P5-ST4-A", "P5-ST4-B"] : [],
        missing_value_sensors: [], coverage: 1,
      }, pressure_summaries: {},
    };
  });
  return {
    version: "spatial-evaluation-v1", status: "completed", run_id: "unit-test-only",
    split: "development", planned_cases: 3, metrics: null,
    networks: [{ id: "N1", name: "Unit-test-only source", status: "completed", pack, frames, dataset_sha256: "test-only" }],
    cases: [60, 150, 360].map(end => ({
      case_id: `N1@${end}`, network_id: "N1", source_seconds: end,
      name: "Unit-test-only review", dataset_sha256: "test-only", status: "completed",
      snapshot_id: `snapshot-${end}`, input_hash: `input-${end}`,
      truth: { leak_source: end > 90 ? { segment_id: "P5", chainage_m: 800 } : null,
        sensor_issues: [], pressure_anomaly_sensors: [], missing_value_sensors: [], pressure_trigger: end > 90 },
      root_count: end > 90 ? 1 : 0, accepted_report: end > 90, root_id: `root-${end}`,
      agent_started_at: "2026-01-01T00:00:00Z", agent_elapsed_seconds: 400,
      interpretation: end > 90 ? { answer: { text: `Report at ${end}: the paired P5 pressure deficit supports a suspected leak at 600–1000 m.` } } : undefined,
      answer: end > 90 ? `Full report at ${end}: P5 suspected leak at 600–1000 m.\nChecked evidence: paired readings support this finding.` : undefined,
      agent_tasks: end > 90 ? [{
        id: `diagnosis-${end}`, root_id: `root-${end}`, role: "event_diagnosis", state: "SUCCEEDED",
        snapshot_id: `snapshot-${end}`, created_at: "2026-01-01T00:00:10Z", updated_at: "2026-01-01T00:00:20Z",
        summary: "Checked leak pattern", checked_finding: {
          hypothesis: "suspected_leak", segment_ids: ["P5"], snapshot_id: `snapshot-${end}`,
          input_hash: `input-${end}`, available_at: "2026-01-01T00:00:20Z", final_report: false,
        },
      }] : [],
      authorized_inspection: { segment_id: "P5", start_m: 600, end_m: 1000 },
      extraction: { status: "completed", mapping: {
        leaks: end > 90 ? [{ segment_id: "P5", assertion: "suspected", interval: { start_m: 600, end_m: 1000 },
          quote: { path: "answer.text", text: "unit-test-only" } }] : [],
        sensor_issues: end === 360 ? [{ sensor_id: "P5-ST4-A", kind: "drift" }] : [],
        instrumentation_concern: end === 360,
      } },
    })),
  };
}

function instrumentRecording(): EvaluationReport {
  const report = recording();
  const network = report.networks?.[0];
  if (!network) throw new Error("Missing test network");
  const offsets = [1, 3, 5, 7].flatMap(station => ["A", "B"].map(tap => ({
    sensor_id: `P7-ST${station}-${tap}`, kind: "offset",
  })));
  const late = [
    { sensor_id: "P1-ST6-A", kind: "drift" }, { sensor_id: "P3-ST7-A", kind: "drift" },
    { sensor_id: "P4-ST7-B", kind: "spike" }, { sensor_id: "P6-ST3-A", kind: "spike" },
    { sensor_id: "P4-ST8-A", kind: "invalid" }, { sensor_id: "P6-ST8-B", kind: "flatline" },
    { sensor_id: "P1-ST7-B", kind: "missing" }, { sensor_id: "P3-ST5-B", kind: "missing" },
  ];
  for (const frame of network.frames) {
    frame.truth.sensor_issues = frame.source_seconds > 90 ? [
      ...offsets, ...(frame.source_seconds > 180 ? late : []),
    ] : [];
    if (frame.source_seconds > 180) {
      frame.detector.missing_value_sensors = ["P4-ST8-A", "P1-ST7-B", "P3-ST5-B"];
      frame.detector.pressure_anomaly_sensors.push("P1-ST6-A", "P4-ST7-B");
    }
  }
  for (const row of report.cases) {
    const frame = network.frames.find(item => item.source_seconds === row.source_seconds);
    if (!frame || !row.extraction?.mapping) throw new Error("Missing reviewed test frame");
    row.truth.sensor_issues = structuredClone(frame.truth.sensor_issues);
    row.extraction.mapping.sensor_issues = structuredClone(frame.truth.sensor_issues);
  }
  const east = structuredClone(network);
  east.id = "N2";
  for (const frame of east.frames) {
    if (frame.review_case_id) frame.review_case_id = frame.review_case_id.replace("N1@", "N2@");
    if (frame.truth.leak_source) { frame.truth.leak_source.segment_id = "P6"; frame.truth.leak_source.chainage_m = 1000; }
    for (const issue of frame.truth.sensor_issues) {
      if (issue.sensor_id === "P6-ST3-A") issue.sensor_id = "P2-ST3-A";
      if (issue.sensor_id === "P6-ST8-B") issue.sensor_id = "P5-ST8-B";
    }
  }
  const eastRows = structuredClone(report.cases);
  for (const row of eastRows) {
    row.network_id = "N2"; row.case_id = row.case_id.replace("N1@", "N2@");
    const frame = east.frames.find(item => item.source_seconds === row.source_seconds);
    if (!frame || !row.extraction?.mapping) throw new Error("Missing east test frame");
    row.truth.sensor_issues = structuredClone(frame.truth.sensor_issues);
    row.extraction.mapping.sensor_issues = structuredClone(frame.truth.sensor_issues);
    if (row.truth.leak_source) { row.truth.leak_source.segment_id = "P6"; row.truth.leak_source.chainage_m = 1000; }
    for (const leak of row.extraction.mapping.leaks) {
      leak.segment_id = "P6"; leak.interval = { start_m: 800, end_m: 1200 };
    }
    row.authorized_inspection = { segment_id: "P6", start_m: 800, end_m: 1200 };
    for (const task of row.agent_tasks || []) if (task.checked_finding) task.checked_finding.segment_ids = ["P6"];
  }
  report.networks?.push(east); report.cases.push(...eastRows); report.planned_cases = 6;
  const perfect = (tp: number) => ({
    tp, fp: 0, fn: 0, precision: { value: 1 }, recall: { value: 1 }, f1: { value: 1 },
  });
  report.metrics = {
    completed_cases: 6, target_met: true, calibration_passed: true,
    groups: {
      leak_recognition: perfect(4), agent_pipeline_identification: perfect(4),
      agent_sensor_concerns: perfect(44), agent_issue_types: perfect(48),
    },
    rates: { localization_containment: { value: 1, numerator: 4, denominator: 4 } },
    localization_mean_midpoint_error_m: 0, localization_mean_width_m: 400, confirmed_cause_claims: 0,
  };
  return report;
}

function historyRecording(): EvaluationReport {
  const report = instrumentRecording();
  report.evaluation_history = {
    entries: [{
      archive_id: "archived-original", run_id: "old-run", suite: "current",
      created_at: "2026-01-01T00:00:00Z", status: "completed", split: "development",
      label: "original-cohort", available: true,
    }], warnings: [],
  };
  report.previous_runs = [{
    run_id: "summary-only", status: "completed", split: "development", seed: 1, metrics: null,
  }];
  return report;
}

test("evaluation approaches start collapsed below the selectors and retain expansion across tab and suite changes", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  await page.route("**/api/evaluation", route => route.fulfill({ json: recording() }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation", exact: true }).click();
  const detection = page.getByLabel("Detection evaluation approach", { exact: true });
  const suite = page.getByRole("combobox", { name: "Evaluation suite", exact: true });
  const run = page.getByRole("combobox", { name: "Evaluation run", exact: true });
  await expect(detection).toHaveJSProperty("open", false);
  await expect(detection.locator("p").first()).toBeHidden();
  const suiteBounds = await suite.boundingBox(), runBounds = await run.boundingBox();
  const approachBounds = await detection.boundingBox();
  if (!suiteBounds || !runBounds || !approachBounds) throw new Error("Missing evaluation controls");
  expect(suiteBounds.y).toBeLessThan(runBounds.y);
  expect(runBounds.y).toBeLessThan(approachBounds.y);
  await detection.locator(":scope > summary").click();
  await expect(detection.locator("p").first()).toBeVisible();
  await expect(detection.getByRole("heading", { name: "What this evaluates", exact: true })).toBeVisible();
  await expect(detection.getByRole("heading", { name: "Goal", exact: true })).toBeVisible();
  await expect(detection).toContainText("A later correct report must not conceal an earlier missed detection");
  await suite.selectOption("recovery");
  await expect(detection).toHaveJSProperty("open", true);
  await detection.locator(":scope > summary").click();
  await page.getByRole("tab", { name: "Agent reliability", exact: true }).click();
  await expect(page.locator("#evaluation-scope-label")).toHaveText("FROZEN REFERENCES / RECORDED ANSWERS");
  const agent = page.getByLabel("Agent reliability evaluation approach", { exact: true });
  await expect(page.locator("#evaluation-approach-panel > details").first()).toHaveAttribute("id", "agent-reference-method");
  await expect(agent.locator(":scope > summary")).toHaveText("Agent reliability: approach and ground truth");
  await expect(agent).toHaveJSProperty("open", false);
  await expect(agent.locator("p").first()).toBeHidden();
  const summary = agent.locator(":scope > summary");
  await summary.focus();
  await summary.press("Enter");
  await expect(agent.locator("p").first()).toBeVisible();
  await expect(agent.getByRole("heading", { name: "What this evaluates", exact: true })).toBeVisible();
  await expect(agent.getByRole("heading", { name: "Goal", exact: true })).toBeVisible();
  await expect(agent).toContainText("controlled answer-quality component benchmark");
  await expect(agent).toContainText("advisory model judgments, not engineer-authored gold answers");
  await expect(agent).not.toContainText("withdrawn");
  await expect(agent).not.toContainText("reused unchanged");
  await page.getByRole("tab", { name: "Detection", exact: true }).click();
  await expect(page.locator("#evaluation-scope-label")).toHaveText("GROUND TRUTH / AGENT FINDINGS");
  await expect(detection).toHaveJSProperty("open", false);
  await page.getByRole("tab", { name: "Agent reliability", exact: true }).click();
  await expect(agent).toHaveJSProperty("open", true);
  await summary.focus();
  await summary.press("Enter");
  await expect(agent).toHaveJSProperty("open", false);
});

test("history dropdown loads original reports and recorded scores without inference and restores latest", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const latest = historyRecording(), archived = instrumentRecording();
  const history = latest.evaluation_history;
  if (!history) throw new Error("Missing test history");
  for (const status of ["running", "incomplete", "failed", "not_run"]) {
    history.entries.push({
      archive_id: `archive-${status}`, run_id: `run-${status}`, suite: "current",
      status, label: `${status}-cohort`, available: true,
    });
    latest.previous_runs?.push({
      run_id: `summary-${status}`, status, split: "development", seed: 1, metrics: null,
    });
  }
  archived.run_id = "old-run"; archived.historical_archive_id = "archived-original";
  archived.historical_archive_label = "original-cohort";
  if (!archived.metrics) throw new Error("Missing test metrics");
  archived.metrics.groups.leak_recognition.precision.value = .25;
  archived.cases[1].answer = "Original archived incident answer, not the latest report.";
  const posts: string[] = [];
  page.on("request", request => { if (request.method() === "POST") posts.push(request.url()); });
  await page.route("**/api/evaluation**", route => route.fulfill({
    json: new URL(route.request().url()).searchParams.has("archive_id") ? archived : latest,
  }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation", exact: true }).click();
  const picker = page.getByRole("combobox", { name: "Evaluation run", exact: true });
  await expect(picker.locator("option")).toHaveCount(3);
  await expect(picker.locator("option", { hasText: /running|incomplete|failed|not_run/ })).toHaveCount(0);
  await expect(picker.locator("option", { hasText: "summary only" })).toBeDisabled();
  await picker.selectOption("archived-original");
  await expect(page.getByText(/Historical result · old-run/)).toBeVisible();
  await page.getByText("Whole-run review-checkpoint metrics, known labels, original reports and Langfuse traces", { exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "Agent leak-pattern recognition · network/review" }).getByText("25.0%", { exact: true })).toBeVisible();
  const originalCase = page.locator('.evaluation-case[data-case="N1@150"]');
  await originalCase.locator(":scope > summary").click();
  await originalCase.getByText("Complete accepted report · sensor groups and checked evidence", { exact: true }).click();
  await expect(originalCase.getByText("Original archived incident answer, not the latest report.", { exact: true })).toBeVisible();
  await picker.selectOption("");
  await expect(page.getByText(/Historical result · old-run/)).toHaveCount(0);
  await expect(page.getByText("Original archived incident answer, not the latest report.", { exact: true })).toHaveCount(0);
  expect(posts).toEqual([]);
});

test("returning to latest during a delayed history load cannot replace it with a stale archive", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const latest = historyRecording(), archived = instrumentRecording();
  archived.run_id = "old-run"; archived.historical_archive_id = "archived-original";
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/evaluation**", async route => {
    if (new URL(route.request().url()).searchParams.has("archive_id")) {
      await held;
      if (!route.request().failure()) await route.fulfill({ json: archived });
    } else await route.fulfill({ json: latest });
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation", exact: true }).click();
  const picker = page.getByRole("combobox", { name: "Evaluation run", exact: true });
  await picker.selectOption("archived-original");
  await expect(page.getByText(/Loading the original archived result/)).toBeVisible();
  await picker.selectOption("");
  release();
  await expect(picker).toHaveValue("");
  await expect(page.getByText(/Historical result · old-run/)).toHaveCount(0);
  await expect(page.getByText(/Loading the original archived result/)).toHaveCount(0);
  await page.getByRole("combobox", { name: "Evaluation suite", exact: true }).selectOption("recovery");
  await expect(picker.locator("option")).toHaveCount(1);
});

test("an older API or an unavailable archive never displays latest scores as historical", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  await page.route("**/api/evaluation**", route => route.fulfill({ json: historyRecording() }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation", exact: true }).click();
  await page.getByRole("combobox", { name: "Evaluation run", exact: true }).selectOption("archived-original");
  await expect(page.getByText(/running API needs a reload/)).toBeVisible();
  await expect(page.getByText("Whole-run review-checkpoint metrics, known labels, original reports and Langfuse traces", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Historical result · old-run/)).toHaveCount(0);
});

test("paired pipeline maps replay only source-matched findings and freeze source time during the recorded investigation", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const report = recording();
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  const posts: string[] = [];
  page.on("request", request => { if (request.method() === "POST") posts.push(request.url()); });
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const truth = page.locator("#evaluation-truth-map"), agent = page.locator("#evaluation-agent-map");
  await expect(truth.locator("[data-sensor]")).toHaveCount(112);
  await expect(agent.locator("[data-sensor]")).toHaveCount(112);
  await expect(truth.locator(".eval-source")).toHaveCount(1);
  await expect(agent.locator(".eval-inspection")).toHaveCount(1);
  await expect(page.locator(".spatial-timing")).toContainText("Leak onset: 1:30");
  await expect(page.locator(".spatial-timing")).toContainText("first measured alert on P5: 1:45");
  await expect(page.locator(".spatial-timing")).toContainText("first agent admission: 2:30");
  await expect(page.locator(".spatial-timing")).toContainText("+60 s source delay");
  await expect(page.locator(".spatial-timing")).toContainText("400.0 s");
  const legend = page.getByLabel("Agent findings map legend");
  await expect(legend.locator(".eval-leak-pattern")).toHaveCount(1);
  await expect(legend.locator(".eval-inspection")).toHaveCount(1);
  await expect(legend.locator(".eval-agent-issue")).toHaveCount(1);
  await expect(legend.locator(".anomalous .sensor-dot")).toHaveCount(1);
  const ring = agent.locator('[data-sensor="P5-ST4-A"] .eval-agent-issue');
  await expect(ring).toHaveCount(1);
  const style = (item: Element) => {
    const css = getComputedStyle(item);
    return { fill: css.fill, stroke: css.stroke, dash: css.strokeDasharray };
  };
  expect(await ring.evaluate(style)).toEqual(await legend.locator(".eval-agent-issue").evaluate(style));
  expect(await agent.locator(".eval-leak-pattern").evaluate(style)).toEqual(await legend.locator(".eval-leak-pattern").evaluate(style));
  const positions = async (side: typeof truth) => side.locator("[data-sensor]").evaluateAll(items => items.map(item => {
    const dot = item.querySelector(".sensor-dot");
    return [item.getAttribute("data-sensor"), dot?.getAttribute("cx"), dot?.getAttribute("cy")];
  }));
  expect(await positions(truth)).toEqual(await positions(agent));
  await truth.locator('[data-sensor="P3-ST7-A"]').click();
  await expect(page.locator(".spatial-sensor-detail")).toContainText("known issue: drift");
  await expect(agent.locator(".eval-selection")).toHaveCount(1);
  await page.getByRole("slider", { name: "Synchronized recording time" }).fill("90");
  await expect(truth.locator(".eval-source")).toHaveCount(0);
  await expect(agent.locator(".eval-inspection")).toHaveCount(0);
  await expect(agent.locator(".eval-warning-pattern")).toHaveCount(0);
  await expect(page.locator(".spatial-agent strong")).toHaveText(["Not started", "Not started", "Not started"]);
  await page.getByRole("button", { name: "2:30 review · recorded" }).click();
  await page.getByRole("button", { name: "Play recording", exact: true }).click();
  await page.clock.runFor(500);
  await expect(agent.locator(".eval-warning-pattern")).toHaveCount(0);
  await page.clock.runFor(4500);
  await expect(truth).toHaveAttribute("data-source-seconds", "150");
  await expect(agent).toHaveAttribute("data-source-seconds", "150");
  await expect(agent.locator(".eval-inspection")).toHaveCount(0);
  await expect(agent.locator(".eval-warning-pattern, .eval-leak-pattern")).toHaveCount(0);
  await expect(page.locator(".spatial-map-caption").last()).toContainText("final findings not yet available");
  await expect(page.locator(".spatial-progress")).toContainText("Source paused for investigation");
  await page.clock.runFor(8500);
  await expect(agent).toHaveAttribute("data-source-seconds", "150");
  await expect(agent.locator(".eval-inspection")).toHaveCount(1);
  await expect(agent.locator(".eval-warning-pattern")).toHaveCount(0);
  await page.clock.runFor(3000);
  expect(Number(await agent.getAttribute("data-source-seconds"))).toBeGreaterThan(150);
  await expect(agent.locator('[data-segment-id="P5"].eval-leak-pattern')).toHaveCount(1);
  await expect(agent).toHaveAttribute("data-findings-source-seconds", "150");
  await expect(page.getByRole("region", { name: "Agent findings report" })).toContainText("Report at 150");
  await page.getByRole("button", { name: "Pause recording", exact: true }).click();
  expect(posts).toEqual([]);
});

test("inspection bands use report intervals, never numerical localization fallbacks", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  for (const row of report.cases) {
    row.authorized_inspection = { segment_id: "P6", start_m: 100, end_m: 500 };
  }
  const earlier = report.cases[1];
  if (!earlier.extraction?.mapping) throw new Error("Missing test mapping");
  earlier.extraction.mapping.leaks[0].interval = null;
  earlier.interpretation = { answer: { text: "P5 suspected leak; inspection interval withheld." } };
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const map = page.locator("#evaluation-agent-map");
  const interval = map.locator(".eval-inspection");
  await expect(interval).toHaveCount(1);
  await expect(interval).toHaveAttribute("data-segment-id", "P5");
  await expect(interval).toHaveAttribute("data-start-m", "600");
  await expect(interval).toHaveAttribute("data-end-m", "1000");
  await expect(map.locator(".eval-pressure-focus, .eval-focus-callout")).toHaveCount(0);
  await page.getByRole("button", { name: "2:30 review · recorded" }).click();
  await expect(map.locator(".eval-leak-pattern")).toHaveCount(1);
  await expect(interval).toHaveCount(0);
  await expect(page.locator(".spatial-map-caption").last()).toContainText("interval withheld");
});

test("five-second recordings expose the early review and do not skip it at 30x", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.run_id = "early-review-test";
  report.frame_hop_seconds = 5;
  report.admission_policy = "first-pressure-context-v1";
  const network = report.networks![0];
  const template = network.frames[3];
  network.frames = Array.from({ length: 61 }, (_, index) => {
    const end = 60 + index * 5;
    return { ...template, source_seconds: end, window_start_seconds: end - 60,
      snapshot_id: `snapshot-${end}`, input_hash: `input-${end}`,
      review_case_id: end === 110 ? "N1@110" : null,
      truth: { leak_source: end > 90 ? { segment_id: "P5", chainage_m: 800, start_seconds: 90 } : null, sensor_issues: [] },
      detector: { ...template.detector, pressure_anomaly_sensors: end > 90 ? ["P5-ST4-A"] : [] },
    };
  });
  report.cases = [{ ...report.cases[1], case_id: "N1@110", source_seconds: 110,
    snapshot_id: "snapshot-110", input_hash: "input-110", agent_elapsed_seconds: 400,
    root_id: "root-110", agent_tasks: [{
      ...report.cases[1].agent_tasks![0], root_id: "root-110", snapshot_id: "snapshot-110",
      checked_finding: {
        hypothesis: "suspected_leak", segment_ids: ["P5"], snapshot_id: "snapshot-110",
        input_hash: "input-110", available_at: "2026-01-01T00:00:20Z", final_report: false,
      },
    }],
  }];
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await expect(page.locator(".spatial-timing")).toContainText("first agent admission: 1:50");
  await expect(page.locator(".spatial-timing")).toContainText("+20 s source delay");
  await page.getByRole("slider", { name: "Synchronized recording time" }).fill("90");
  await page.getByRole("button", { name: "Play recording", exact: true }).click();
  await page.clock.runFor(2000);
  await expect(page.locator("#evaluation-agent-map")).toHaveAttribute("data-source-seconds", "110");
  await expect(page.locator("#evaluation-agent-map .eval-inspection")).toHaveCount(0);
  await expect(page.locator("#evaluation-agent-map .eval-warning-pattern, #evaluation-agent-map .eval-leak-pattern")).toHaveCount(0);
  await expect(page.locator(".spatial-map-caption").last()).toContainText("final findings not yet available");
  await expect(page.locator(".spatial-timing")).toContainText("20.0 s original model wall time (not final)");
  await expect(page.locator(".spatial-progress")).toContainText("30× playback, not faster inference");
});

test("a mismatched new report cannot replace the last valid source-matched finding", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.cases[2].snapshot_id = "wrong-snapshot";
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await expect(page.locator("#evaluation-truth-map .eval-source")).toHaveCount(1);
  await expect(page.locator("#evaluation-agent-map .eval-inspection")).toHaveCount(1);
  await expect(page.locator("#evaluation-agent-map")).toHaveAttribute("data-findings-source-seconds", "150");
  await expect(page.locator("#evaluation-agent-map")).toHaveAttribute("data-findings-snapshot", "snapshot-150");
  await expect(page.locator("#evaluation-agent-map .eval-warning-pattern")).toHaveCount(0);
  await expect(page.locator(".spatial-map-caption").last()).toHaveAttribute("data-accepted", "false");
  await expect(page.locator(".spatial-map-caption").last()).toContainText("current review snapshot mismatch");
  await expect(page.getByRole("region", { name: "Agent findings report" })).toContainText("Report at 150");
});

test("every recording holds its data window through mapping and result admission", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.run_id = "all-recordings-admission";
  report.status = "running";
  const original = structuredClone(report);
  report.networks = [];
  report.cases = [];
  for (const id of ["N1", "N2", "N3"]) {
    const network = structuredClone(original.networks![0]);
    network.id = id;
    for (const frame of network.frames) {
      frame.snapshot_id = `${id}-${frame.snapshot_id}`;
      frame.input_hash = `${id}-${frame.input_hash}`;
      frame.review_case_id = frame.review_case_id?.replace("N1", id) || null;
      if (frame.truth.leak_source && id !== "N1") {
        frame.truth.leak_source = id === "N3" ? null : { ...frame.truth.leak_source, segment_id: "P6" };
      }
    }
    report.networks.push(network);
    for (const row of structuredClone(original.cases)) {
      row.network_id = id;
      row.case_id = row.case_id.replace("N1", id);
      row.snapshot_id = `${id}-${row.snapshot_id}`;
      row.input_hash = `${id}-${row.input_hash}`;
      row.agent_tasks = [];
      if (id === "N3") {
        row.truth.leak_source = null;
        row.authorized_inspection = null;
        row.extraction!.mapping!.leaks = [];
      } else if (id === "N2") {
        row.truth.leak_source = row.truth.leak_source ? { ...row.truth.leak_source, segment_id: "P6" } : null;
        if (row.authorized_inspection) row.authorized_inspection.segment_id = "P6";
        for (const leak of row.extraction!.mapping!.leaks) leak.segment_id = "P6";
      }
      row.agent_elapsed_seconds = 2;
      if (row.source_seconds === 150) {
        row.status = "mapping_output";
        row.extraction!.status = "running";
      }
      report.cases.push(row);
    }
  }
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const truth = page.locator("#evaluation-truth-map"), agent = page.locator("#evaluation-agent-map");
  for (const id of ["N1", "N2", "N3"]) {
    await page.getByRole("combobox", { name: "Evaluation recording" }).selectOption(id);
    await page.getByRole("slider", { name: "Synchronized recording time" }).fill("150");
    await page.getByRole("button", { name: "Play recording", exact: true }).click();
    await page.clock.runFor(2000);
    await expect(truth).toHaveAttribute("data-source-seconds", "150");
    await expect(agent).toHaveAttribute("data-source-seconds", "150");
    await expect(agent.locator(".eval-inspection")).toHaveCount(0);
    await expect(page.locator(".spatial-alignment")).toContainText("admitting investigation results");
    const row = report.cases.find(item => item.case_id === `${id}@150`)!;
    row.extraction!.status = "completed";
    row.status = "judging_explanation";
    let refreshed = page.waitForResponse("**/api/evaluation");
    await page.getByRole("tab", { name: "Evaluation" }).click();
    await refreshed;
    await page.clock.runFor(500);
    await expect(page.locator(".spatial-alignment")).toHaveAttribute("data-state", "waiting");
    await expect(agent.locator(".eval-inspection")).toHaveCount(0);
    row.status = "completed";
    row.investigation_elapsed_seconds = 12;
    row.result_admitted_at = "2026-01-01T00:00:12Z";
    refreshed = page.waitForResponse("**/api/evaluation");
    await page.getByRole("tab", { name: "Evaluation" }).click();
    await refreshed;
    await page.clock.runFor(250);
    await expect(truth).toHaveAttribute("data-source-seconds", "150");
    await expect(agent).toHaveAttribute("data-source-seconds", "150");
    await expect(page.locator(".spatial-alignment")).toHaveAttribute("data-state", "admitted");
    await expect(agent.locator(".eval-inspection")).toHaveCount(id === "N3" ? 0 : 1);
    await page.clock.runFor(3000);
    expect(await truth.getAttribute("data-source-seconds")).toEqual(await agent.getAttribute("data-source-seconds"));
    expect(Number(await agent.getAttribute("data-source-seconds"))).toBeGreaterThan(150);
  }
});

test("pausing an investigation preserves progress and holds through recorded admission time", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.run_id = "pause-resume-admission";
  report.cases[1].agent_elapsed_seconds = 120;
  report.cases[1].investigation_elapsed_seconds = 300;
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await page.getByRole("button", { name: "2:30 review · recorded" }).click();
  await page.getByRole("button", { name: "Play recording", exact: true }).click();
  await page.clock.runFor(5000);
  await expect(page.locator("#evaluation-agent-map .eval-inspection")).toHaveCount(0);
  await page.getByRole("button", { name: "Pause recording", exact: true }).click();
  await page.clock.runFor(10000);
  await expect(page.locator("#evaluation-truth-map")).toHaveAttribute("data-source-seconds", "150");
  await page.getByRole("button", { name: "Play recording", exact: true }).click();
  await page.clock.runFor(5000);
  await expect(page.locator("#evaluation-agent-map")).toHaveAttribute("data-source-seconds", "150");
  await expect(page.locator("#evaluation-agent-map .eval-inspection")).toHaveCount(1);
  await expect(page.locator(".spatial-alignment")).toContainText("results admitted on both maps");
});

test("both legends use aligned pipeline and instrument groups on narrow screens", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  await page.route("**/api/evaluation", route => route.fulfill({ json: recording() }));
  await page.setViewportSize({ width: 390, height: 1000 });
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  for (const label of ["Ground truth map legend", "Agent findings map legend"]) {
    const legend = page.getByLabel(label);
    await expect(legend.locator("h4")).toHaveText(["Pipeline", "Instruments"]);
    const layout = await legend.evaluate(element => ({
      display: getComputedStyle(element).display,
      overflow: element.scrollWidth > element.clientWidth,
      itemsFit: [...element.querySelectorAll(".spatial-legend-item")].every(item => item.scrollWidth <= item.clientWidth),
    }));
    expect(layout).toEqual({ display: "grid", overflow: false, itemsFit: true });
  }
});

test("a recorded failure is admitted explicitly before synchronized playback continues", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.run_id = "failed-admission";
  const row = report.cases[1];
  row.status = "failed";
  row.accepted_report = false;
  row.error_code = "agent_timeout";
  row.agent_tasks = [];
  row.agent_elapsed_seconds = 5;
  row.investigation_elapsed_seconds = 10;
  delete row.extraction;
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await page.getByRole("button", { name: "2:30 review · failed" }).click();
  await page.getByRole("button", { name: "Play recording", exact: true }).click();
  await page.clock.runFor(250);
  await expect(page.locator(".spatial-alignment")).toHaveAttribute("data-state", "waiting");
  await page.clock.runFor(250);
  await expect(page.locator("#evaluation-truth-map")).toHaveAttribute("data-source-seconds", "150");
  await expect(page.locator("#evaluation-agent-map .eval-inspection")).toHaveCount(0);
  await expect(page.locator(".spatial-alignment")).toContainText("failure admitted: agent_timeout");
  await expect(page.locator(".spatial-map-caption").last()).toContainText("Investigation failed: agent_timeout");
  await page.clock.runFor(3000);
  expect(await page.locator("#evaluation-truth-map").getAttribute("data-source-seconds"))
    .toEqual(await page.locator("#evaluation-agent-map").getAttribute("data-source-seconds"));
  expect(Number(await page.locator("#evaluation-agent-map").getAttribute("data-source-seconds"))).toBeGreaterThan(150);
});

test("N1 retains its admitted leak and original report between reviews without showing future findings", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.run_id = "N1-findings-continuity";
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const slider = page.getByRole("slider", { name: "Synchronized recording time" });
  const agent = page.locator("#evaluation-agent-map");
  const output = page.getByRole("region", { name: "Agent findings report" });
  await slider.fill("135");
  await expect(agent.locator(".eval-leak-pattern")).toHaveCount(0);
  await expect(output).toContainText("No agent output has been released yet");
  await expect(output).not.toContainText("Report at 150");
  for (const seconds of [150, 165, 180, 345]) {
    await slider.fill(String(seconds));
    await expect(page.locator("#evaluation-truth-map")).toHaveAttribute("data-source-seconds", String(seconds));
    await expect(agent).toHaveAttribute("data-source-seconds", String(seconds));
    await expect(agent.locator('[data-segment-id="P5"].eval-leak-pattern')).toHaveCount(1);
    await expect(agent.locator(".eval-inspection")).toHaveCount(1);
    await expect(agent).toHaveAttribute("data-findings-source-seconds", "150");
    await expect(output).toContainText(report.cases[1].interpretation!.answer.text);
    await expect(output).not.toContainText("Report at 360");
    if (seconds > 150) {
      await expect(page.locator(".spatial-map-caption").last()).toContainText("retained from 2:30");
      await expect(page.locator(".spatial-findings-basis").last()).toContainText(`current data ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`);
    }
  }
  await output.getByText("Full recorded answer and checked evidence", { exact: true }).click();
  await expect(output).toContainText(report.cases[1].answer!);
  await slider.fill("360");
  await expect(agent).toHaveAttribute("data-findings-source-seconds", "360");
  await expect(output).toContainText(report.cases[2].interpretation!.answer.text);
  await slider.fill("90");
  await expect(agent.locator(".eval-leak-pattern")).toHaveCount(0);
  await expect(output).not.toContainText("Report at 150");
  await expect(output).not.toContainText("Report at 360");
});

test("a newer no-leak reassessment replaces the old leak only after admission", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.run_id = "admitted-reassessment";
  const reassessment = report.cases[2];
  reassessment.agent_tasks = [];
  reassessment.extraction!.mapping!.leaks = [];
  reassessment.authorized_inspection = null;
  reassessment.interpretation = { answer: { text: "Latest agent reassessment: no supported leak pattern." } };
  reassessment.answer = "Recorded no-leak reassessment and its checked evidence.";
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await page.getByRole("slider", { name: "Synchronized recording time" }).fill("345");
  await page.getByRole("button", { name: "Play recording", exact: true }).click();
  await page.clock.runFor(2000);
  const agent = page.locator("#evaluation-agent-map");
  const output = page.getByRole("region", { name: "Agent findings report" });
  await expect(agent).toHaveAttribute("data-source-seconds", "360");
  await expect(agent).toHaveAttribute("data-findings-source-seconds", "150");
  await expect(agent.locator(".eval-leak-pattern")).toHaveCount(1);
  await expect(output).toContainText("Report at 150");
  await expect(output).not.toContainText(reassessment.interpretation.answer.text);
  await page.clock.runFor(12500);
  await expect(agent).toHaveAttribute("data-findings-source-seconds", "360");
  await expect(agent.locator(".eval-leak-pattern")).toHaveCount(0);
  await expect(agent.locator(".eval-inspection")).toHaveCount(0);
  await expect(output).toContainText(reassessment.interpretation.answer.text);
  await expect(page.locator("#evaluation-truth-map .eval-source")).toHaveCount(1);
});

test("a failed later review does not erase the previous admitted report or render its text as HTML", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.run_id = "failed-later-review";
  report.cases[1].interpretation = { answer: { text: 'P5 leak remains suspected. <img src="invalid" onerror="window.reportInjected=true">' } };
  report.cases[2].status = "failed";
  report.cases[2].accepted_report = false;
  report.cases[2].error_code = "agent_timeout";
  report.cases[2].agent_tasks = [];
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await page.getByRole("slider", { name: "Synchronized recording time" }).fill("360");
  const output = page.getByRole("region", { name: "Agent findings report" });
  await expect(page.locator("#evaluation-agent-map")).toHaveAttribute("data-findings-source-seconds", "150");
  await expect(page.locator("#evaluation-agent-map .eval-leak-pattern")).toHaveCount(1);
  await expect(page.locator(".spatial-map-caption").last()).toContainText("current investigation failed: agent_timeout");
  await expect(output).toContainText(report.cases[1].interpretation.answer.text);
  await expect(output.locator("img")).toHaveCount(0);
  expect(await page.evaluate(() => Object.prototype.hasOwnProperty.call(window, "reportInjected"))).toBe(false);
});

test("a specialist screening warning never supplies agent-map findings when the final report fails", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  const report = recording();
  report.run_id = "retained-specialist-output";
  for (const row of report.cases.filter(item => item.source_seconds! > 90)) {
    row.status = "failed";
    row.accepted_report = false;
    row.error_code = "grounding_failed";
  }
  report.cases[2].agent_tasks = [];
  const publicOutput = "Specialist warning: a joint P5 pressure deficit supports a possible leak.";
  report.cases[1].activity = [{
    id: 1, site_id: "unit-test-only", generation_id: "retained-specialist-output",
    type: "answer.checked", created_at: "2026-01-01T00:00:20Z",
    simulated_seconds: 150, snapshot_id: "snapshot-150", task_id: "diagnosis-150",
    payload: { role: "event_diagnosis", public_output: publicOutput },
  }];
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await page.getByRole("slider", { name: "Synchronized recording time" }).fill("165");
  await expect(page.locator("#evaluation-agent-map .eval-warning-pattern, #evaluation-agent-map .eval-leak-pattern")).toHaveCount(0);
  await expect(page.locator("#evaluation-agent-map .eval-inspection")).toHaveCount(0);
  await expect(page.locator(".spatial-map-caption").last()).toContainText("no review of this window");
  const output = page.getByRole("region", { name: "Agent findings report" });
  await expect(output).toContainText("No agent output has been released yet.");
  await expect(output).not.toContainText(publicOutput);
  await expect(output).not.toContainText(report.cases[1].interpretation!.answer.text);
});

for (const networkId of ["N1", "N2"]) {
  test(`${networkId} shows ground-truth pressure alerts and layered P4 faults using the legend symbols`, async ({ page }) => {
    test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
    await page.request.post("/api/login", {
      data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
    });
    const report = recording();
    report.run_id = `${networkId}-sensor-symbols`;
    const network = report.networks?.[0];
    if (!network) throw new Error("Missing test network");
    network.id = networkId;
    for (const frame of network.frames) {
      if (frame.review_case_id) frame.review_case_id = frame.review_case_id.replace("N1@", `${networkId}@`);
      if (frame.source_seconds <= 180) continue;
      frame.truth.sensor_issues.push(
        { sensor_id: "P4-ST7-B", kind: "spike" },
        { sensor_id: "P4-ST8-A", kind: "invalid" },
      );
      frame.detector.pressure_anomaly_sensors.push("P4-ST7-B");
      frame.detector.missing_value_sensors.push("P4-ST7-B", "P4-ST8-A");
    }
    for (const row of report.cases) {
      row.network_id = networkId;
      row.case_id = row.case_id.replace("N1@", `${networkId}@`);
      if (row.source_seconds === 360 && row.extraction?.mapping) {
        row.extraction.mapping.sensor_issues = [
          { sensor_id: "P4-ST7-B", kind: "spike" },
          { sensor_id: "P4-ST8-A", kind: "invalid" },
        ];
      }
      if (networkId === "N2" && row.root_count) {
        row.status = "failed"; row.accepted_report = false; row.error_code = "grounding_failed";
      }
    }
    await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
    await page.goto("/");
    await page.getByRole("tab", { name: "Evaluation" }).click();
    const truth = page.locator("#evaluation-truth-map");
    const agent = page.locator("#evaluation-agent-map");
    const legend = page.getByLabel("Ground truth map legend");
    const agentLegend = page.getByLabel("Agent findings map legend");
    const style = (item: Element) => {
      const css = getComputedStyle(item);
      return { fill: css.fill, stroke: css.stroke, width: css.strokeWidth, dash: css.strokeDasharray, radius: item.getAttribute("r") };
    };
    await expect(truth.locator(".anomalous")).toHaveCount(3);
    await expect(agent.locator(".anomalous")).toHaveCount(3);
    const healthyAlert = truth.locator('[data-sensor="P5-ST4-A"]');
    await expect(healthyAlert).toHaveAttribute("aria-label", /Pressure anomaly.*No injected instrument problem/);
    await expect(healthyAlert.locator(".eval-known-issue")).toHaveCount(0);
    expect(await healthyAlert.locator(".sensor-dot").evaluate(style)).toEqual(
      await legend.locator(".anomalous .sensor-dot").evaluate(style),
    );
    const invalid = truth.locator('[data-sensor="P4-ST8-A"]');
    await expect(invalid).toHaveAttribute("aria-label", /Missing \/ invalid readings.*Known instrument issue: invalid/);
    expect(await invalid.locator(".sensor-dot").evaluate(style)).toEqual(
      await legend.locator(".missing .sensor-dot").evaluate(style),
    );
    expect(await invalid.locator(".eval-known-issue").evaluate(style)).toEqual(
      await legend.locator(".eval-known-issue").evaluate(style),
    );
    const spike = truth.locator('[data-sensor="P4-ST7-B"]');
    await expect(spike).toHaveAttribute("class", /anomalous missing/);
    await expect(spike).toHaveAttribute("aria-label", /Pressure anomaly.*Missing \/ invalid readings.*spike/);
    expect((await spike.locator(".sensor-dot").evaluate(style)).fill).toBe(
      (await legend.locator(".anomalous .sensor-dot").evaluate(style)).fill,
    );
    expect((await spike.locator(".sensor-dot").evaluate(style)).dash).toBe(
      (await legend.locator(".missing .sensor-dot").evaluate(style)).dash,
    );
    expect(await spike.locator(".eval-known-issue").evaluate(style)).toEqual(
      await legend.locator(".eval-known-issue").evaluate(style),
    );
    if (networkId === "N1") {
      expect(await agent.locator('[data-sensor="P4-ST8-A"] .eval-agent-issue').evaluate(style)).toEqual(
        await agentLegend.locator(".eval-agent-issue").evaluate(style),
      );
    } else await expect(agent.locator(".eval-agent-issue")).toHaveCount(0);
    await invalid.click();
    await expect(page.locator(".spatial-sensor-detail")).toContainText("known issue: invalid");
    await expect(page.locator(".spatial-sensor-detail")).toContainText("missing / invalid readings: yes");
    for (const [map, key] of [[truth, legend], [agent, agentLegend]]) {
      expect(await map.locator(".eval-selection").evaluate(style)).toEqual(
        await key.locator(".eval-selection").evaluate(style),
      );
    }
    await expect(legend).toContainText("Selected sensor");
    await expect(page.locator(".spatial-legend-footnote").first()).toContainText("Symbols combine");
    await page.getByRole("slider", { name: "Synchronized recording time" }).fill("150");
    await expect(truth.locator('[data-sensor="P4-ST8-A"] .eval-known-issue')).toHaveCount(0);
    await expect(truth.locator('[data-sensor="P4-ST8-A"]')).not.toHaveAttribute("class", /missing/);
    await expect(truth.locator(".anomalous")).toHaveCount(2);
  });
}

test("overall cards include uncovered periods across N1 and N2 and stay fixed while maps are replayed", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = instrumentRecording();
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const card = page.locator('.spatial-scorecards [data-metric="agent_sensor_concerns"]');
  const slider = page.getByRole("slider", { name: "Synchronized recording time" });
  for (const network of ["N1", "N2"]) {
    await page.getByRole("combobox", { name: "Evaluation recording", exact: true }).selectOption(network);
    await slider.fill("255");
    await expect(card.locator("strong")).toHaveText("58.3%");
    await expect(card).toContainText("252/432 covered · 180 uncovered · 0 false alarms");
    await expect(card).toContainText("All issue-type recall: 53.3% · 256/480 covered");
    await expect(page.locator(".spatial-score-basis")).toContainText("Overall results · 2 cases · 42 recorded source windows");
    await expect(page.getByRole("group", { name: "Overall evaluation scores" })).toBeVisible();
    await expect(page.locator(".spatial-qualification")).not.toContainText("metrics exceed 95%");
    await page.locator(".spatial-instrument-audit").evaluate((element: HTMLDetailsElement) => { element.open = true; });
    for (const sensor of ["P1-ST6-A", "P4-ST7-B", "P4-ST8-A", network === "N1" ? "P6-ST8-B" : "P5-ST8-B"]) {
      await expect(page.locator(".spatial-instrument-audit")).toContainText(sensor);
    }
    await expect(page.locator("#evaluation-agent-map .eval-agent-issue")).toHaveCount(8);
    await slider.fill("360");
    await expect(card.locator("strong")).toHaveText("58.3%");
    await expect(card).toContainText("252/432 covered · 180 uncovered · 0 false alarms");
    await expect(page.locator("#evaluation-agent-map .eval-agent-issue")).toHaveCount(14);
    await slider.fill("105");
    await expect(card.locator("strong")).toHaveText("58.3%");
    await expect(page.locator("#evaluation-agent-map .eval-agent-issue")).toHaveCount(0);
    await expect(page.locator('.spatial-scorecards [data-metric="leak_recognition"] strong')).toHaveText("83.3%");
    await expect(page.locator('.spatial-scorecards [data-metric="localization_containment"] strong')).toHaveText("30/36");
    await slider.fill("60");
    await expect(card.locator("strong")).toHaveText("58.3%");
  }
  await page.locator(".spatial-evidence > summary").click();
  await expect(page.locator(".spatial-evidence")).toContainText("unreviewed windows and detection delays are not measured by this aggregate");
});

test("detailed tables expose every case and snapshot without crediting later reports to earlier misses", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = instrumentRecording();
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const cases = page.getByRole("table", { name: "Metrics by case", exact: true });
  const snapshots = page.getByRole("table", { name: "Metrics by snapshot", exact: true });
  await expect(cases).toBeVisible();
  await expect(snapshots.locator("tbody tr")).toHaveCount(42);
  for (const table of [cases, snapshots]) {
    for (const header of await table.getByRole("columnheader").all()) {
      await expect(header).toHaveAttribute("title", /\S/);
      await expect(header).toHaveAccessibleDescription(await header.getAttribute("title") || "");
    }
    const branchHeader = table.getByRole("columnheader", { name: "Correct branch recall", exact: true });
    await expect(branchHeader).toHaveAttribute("title", /TP \/ \(TP \+ FN\).*not locating the exact leak point/);
    await expect(table.getByRole("columnheader", { name: "Leak false-positive rate", exact: true }))
      .toHaveAttribute("title", /No-leak snapshots.*\/ all no-leak snapshots/);
  }
  for (const network of ["N1", "N2"]) {
    const total = cases.locator(`tr[data-network="${network}"]`);
    await expect(total).toContainText("21 windows · 2 fresh reviews · 13 retained · 6 without an admitted report");
    await expect(total.locator('[data-metric="agent_sensor_concerns"]')).toContainText("58.3% (126/216)");
    await expect(total.locator('[data-metric="agent_sensor_concerns"]')).toContainText("TP 126 · FN 90 · FP 0");
    const early = snapshots.locator(`tr[data-network="${network}"][data-source-seconds="105"]`);
    await expect(early).toContainText("No admitted report");
    await expect(early.locator('[data-metric="agent_sensor_concerns"]')).toContainText("0.0% (0/8)");
    const late = snapshots.locator(`tr[data-network="${network}"][data-source-seconds="255"]`);
    await expect(late).toContainText("Retained from 2:30");
    await expect(late).toContainText("No review at this snapshot");
    await expect(late.locator('[data-metric="agent_sensor_concerns"]')).toContainText("57.1% (8/14)");
    await expect(late.locator('[data-metric="agent_sensor_concerns"]')).toContainText("TP 8 · FN 6 · FP 0");
    await expect(late.locator('[data-metric="issueTypes"]')).toContainText("50.0% (8/16)");
    await late.locator("details > summary").click();
    await expect(late).toContainText(network === "N1" ? "P6-ST8-B" : "P5-ST8-B");
    await expect(late).toContainText("P4-ST8-A (invalid)");
    const final = snapshots.locator(`tr[data-network="${network}"][data-source-seconds="360"]`);
    await expect(final).toContainText("Admitted at 6:00");
    await expect(final).toContainText("New admitted report");
    await expect(final.locator('[data-metric="agent_sensor_concerns"]')).toContainText("100.0% (14/14)");
  }
  const before = await snapshots.innerText();
  await page.getByRole("combobox", { name: "Evaluation recording", exact: true }).selectOption("N2");
  await page.getByRole("slider", { name: "Synchronized recording time" }).fill("105");
  await expect(snapshots).toHaveText(before, { useInnerText: true });
});

test("withdrawn agent audits stay hidden and reference evaluation starts explicitly unrun", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = recording();
  report.agent_process = {
    planned_agent_reviews: 3, attempted_reviews: 2, not_attempted_reviews: 1,
    terminal_reviews: 2, accepted_reports: 1, mapped_reports: 1, failed_reviews: 1,
    timeouts: 1, model_calls: 10, model_calls_not_recorded: 1,
    latency_samples: 2, p50_wall_seconds: 500, p95_wall_seconds: 900, max_wall_seconds: 900,
    basis: "All dispatched reviews, including failures and timeouts.",
    checks: { evidence: { label: "Evidence-reference validation", passed: 1, failed: 0,
      not_recorded: 1, denominator: 2 } },
    roles: [{ role: "sensor_quality", assigned: 2, succeeded: 1, abstained: 0, failed: 1, pending: 0 }],
  };
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  const posts: string[] = [];
  page.on("request", request => { if (request.method() === "POST") posts.push(request.url()); });
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const suites = page.getByRole("combobox", { name: "Evaluation suite", exact: true });
  await expect(suites.locator("option")).toHaveText([
    "Leak and sensor-issue detection", "Leak recovery and new leaks",
    "No-leak scenarios and false alarms",
  ]);
  for (const suite of ["recovery", "non_leak"]) {
    await suites.selectOption(suite);
    await expect(page.locator("#evaluation-results")).toContainText("Not run: no live agent results");
    await expect(page.locator(".spatial-scorecards")).toHaveCount(0);
  }
  await page.getByRole("tab", { name: "Agent reliability", exact: true }).click();
  await expect(page.locator("#evaluation-results")).toContainText("independently authored factual references");
  await expect(page.locator("#evaluation-results")).not.toContainText("withdrawn");
  await expect(page.locator("#evaluation-results")).toContainText("Not run: no dataset-based");
  await expect(page.getByRole("row").filter({ hasText: "Mapped final reports delivered" })).toHaveCount(0);
  await expect(page.locator("#evaluation-results")).not.toContainText("50.0% (1/2)");
  await page.getByRole("tab", { name: "Detection", exact: true }).click();
  await suites.selectOption("current");
  await expect(page.locator(".spatial-scorecards")).toBeVisible();
  await expect(page.getByLabel("Detection evaluation approach", { exact: true })).toBeVisible();
  expect(posts).toEqual([]);
});

for (const reviewMode of ["legacy", "quality", "failed-review"]) {
test(`agent answer quality preserves original references and explicit failure accounting: ${reviewMode}`, async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = recording();
  const checks = { measurement_facts: true, instrument_evidence: true, leak_evidence: true, evidence_references: true };
  report.agent_reference_evaluation = {
    version: "agent-reference-evaluation-v1", status: "completed", run_id: "reference-run",
    split: "development", dataset_sha256: "frozen-reference-hash", policy_version: "v1",
    policy_sha256: "policy-hash", implementation_unchanged: true, requested_model: "test-model",
    scope: "Controlled component benchmark, not field reliability.", reference_origin: "Authored before inference",
    ground_truth_supplied_to_agent: false,
    metrics: { planned: 3, completed: 2, failed: 1, all_checks_passed: 1,
      checks: Object.fromEntries(Object.keys(checks).map(key => [
        key, { passed: key === "measurement_facts" ? 1 : 2, denominator: 3 },
      ])) },
    cases: [
      { id: "AR-D1", name: "Normalize units", family: "facts", split: "development", status: "completed",
        input: { pressure_kPa: 8000 }, expected: { pressure_bar: 80 }, actual: { pressure_bar: 80 },
        checks, elapsed_seconds: 10, model_receipt: { observed_model: "test-model", mode: "live" } },
      { id: "AR-D2", name: "Failed transport", family: "facts", split: "development", status: "failed",
        input: {}, expected: {}, actual: null, checks: Object.fromEntries(Object.keys(checks).map(key => [key, false])),
        elapsed_seconds: 180, error_code: "timeout" },
      { id: "AR-H1", name: "Wrong pressure", family: "facts", split: "held_out", status: "completed",
        input: { pressure_kPa: 8000 }, expected: { pressure_bar: 80 }, actual: { pressure_bar: 79 },
        checks: { ...checks, measurement_facts: false }, elapsed_seconds: 15,
        model_receipt: { observed_model: "test-model", mode: "live" } },
    ],
  };
  if (reviewMode !== "legacy") {
    const reference = report.agent_reference_evaluation;
    const failed = reviewMode === "failed-review";
    const qualityKeys = ["grounding", "numeric_accuracy", "causal_support", "scope", "uncertainty", "usefulness"];
    const dimensions = Object.fromEntries(qualityKeys.map(key => [key, {
      average: key === "usefulness" ? failed ? null : 5 : key === "numeric_accuracy" && !failed ? 3.5 : 5,
      scored: key === "usefulness" ? failed ? 0 : 1 : failed ? 1 : 2,
      concerns: key === "numeric_accuracy" && !failed ? 1 : 0,
      insufficient_evidence: key === "usefulness" && failed ? 1 : 0,
      not_applicable: key === "usefulness" && !failed ? 1 : 0,
    }]));
    report.agent_reference_evaluation = { ...reference,
      answer_quality: { policy_version: "agent-answer-quality-v1", requested_judge_model: "test-reviewer",
        rubric_sha256: "frozen-rubric", dimensions: Object.fromEntries(qualityKeys.map(key => [key, `Frozen ${key} rubric`])),
        advisory: true, limitations: ["No engineer-authored gold explanation."],
        metrics: { planned: 3, reviewed: failed ? 1 : 2, execution_failed: failed ? 1 : 0,
          not_reviewed: failed ? 2 : 1, no_concerns: failed ? 0 : 1, with_concerns: failed ? 0 : 1,
          insufficient_evidence: failed ? 1 : 0, dimensions } },
      cases: reference.cases.map(item => {
        if (item.status !== "completed") return item;
        const explanation = `The reading is ${item.actual.pressure_bar} bar.`;
        return { ...item, input: { ...item.input, measurements: [{ id: "M1", pressure_kPa: 8000 }] },
          answer: { facts: item.actual, explanation, next_steps: ["Compare an independent measurement."],
            limitations: ["Synthetic packet only; no field safety assurance."] },
          judge: failed && item.id === "AR-H1" ?
            { status: "execution_failed", verdict: null, error_code: "invalid_citation",
              reason: "No valid review was delivered; no score is inferred." } :
            { status: "completed", model_receipt: { observed_model: "test-reviewer" },
              verdict: { summary: "Advisory review of the frozen answer.",
                dimensions: qualityKeys.map(key => {
                  const unscored = key === "usefulness" && item.id === "AR-D1";
                  const concern = key === "numeric_accuracy" && item.id === "AR-H1";
                  return { dimension: key,
                    status: unscored ? failed ? "insufficient_evidence" : "not_applicable" : concern ? "concern" : "supported",
                    score: unscored ? null : concern ? 2 : 5,
                    rationale: concern ? "79 bar disagrees with the original 80 bar reference." : "The frozen packet supports this opinion.",
                    evidence_ids: ["M1"], answer_excerpt: explanation };
                }) } },
        };
      }),
    };
  }
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await page.getByRole("tab", { name: "Agent reliability", exact: true }).click();
  const overview = page.getByLabel("Agent reference evaluation overview", { exact: true });
  await expect(overview.getByRole("article", { name: "Answers reviewed", exact: true }))
    .toContainText(reviewMode === "legacy" ? "0/3" : reviewMode === "failed-review" ? "1/3" : "2/3");
  await expect(overview.getByRole("article", { name: "Reviews without concerns", exact: true }))
    .toContainText(reviewMode === "legacy" ? "Not assessed" : reviewMode === "failed-review" ? "0/1" : "1/2");
  await expect(overview.getByRole("article", { name: "Answer execution/output failures", exact: true }).getByText("1", { exact: true })).toBeVisible();
  await expect(page.locator("#evaluation-results")).toContainText("frozen-reference-hash");
  await expect(page.getByRole("row").filter({ hasText: "AR-D2" })).toContainText("failed: timeout");
  const aggregate = page.getByLabel("Aggregate answer quality", { exact: true });
  if (reviewMode === "legacy") {
    await expect(overview).toContainText("no six-dimensional answer-quality reviews");
    await expect(aggregate.getByRole("cell", { name: "Not scored", exact: true })).toHaveCount(6);
    await expect(aggregate).not.toContainText("/5");
  } else {
    await expect(aggregate.getByRole("row").filter({ hasText: "Numerical accuracy" }))
      .toContainText(reviewMode === "failed-review" ? "5.00/5 · 1 scored" : "3.50/5 · 2 scored");
    await expect(aggregate.getByRole("row").filter({ hasText: "Actionable usefulness" }))
      .toContainText(reviewMode === "failed-review" ? "Not scored" : "5.00/5 · 1 scored");
    if (reviewMode === "failed-review") {
      await expect(overview.getByRole("article", { name: "Review execution failures", exact: true })).toContainText("1");
      await expect(page.getByRole("row").filter({ hasText: "AR-H1" })).toContainText("invalid_citation");
    }
  }
  await aggregate.getByText("Supporting ground-truth checks · frozen dataset", { exact: true }).click();
  await expect(aggregate).toContainText("Measurement facts (1 delivered answer)");
  await expect(aggregate.getByRole("row").filter({ hasText: "held_out" })).toContainText("0");
  const method = page.getByLabel("Agent reliability evaluation approach", { exact: true });
  await expect(method).toHaveJSProperty("open", false);
  const overviewBounds = await overview.boundingBox(), resultBounds = await page.locator("#agent-reference-results").boundingBox();
  const methodBounds = await method.boundingBox();
  if (!overviewBounds || !resultBounds || !methodBounds) throw new Error("Missing reference evaluation sections");
  expect(overviewBounds.y).toBeLessThan(resultBounds.y);
  expect(methodBounds.y).toBeLessThan(overviewBounds.y);
  await page.getByRole("link", { name: "Inspect reference case AR-D1", exact: true }).click();
  const detail = page.locator('.evaluation-case[data-reference-case="AR-D1"]');
  await expect(detail).toHaveJSProperty("open", true);
  await expect(detail.getByText("Ground truth fixed before inference", { exact: true })).toBeVisible();
  await expect(detail.getByText("Actual agent output", { exact: true })).toBeVisible();
  if (reviewMode !== "legacy") {
    await expect(detail.getByText("Saved investigation answer", { exact: true })).toBeVisible();
    await expect(detail).toContainText("Compare an independent measurement.");
    await expect(detail).toContainText("Frozen evidence IDs: M1");
    await expect(detail.getByRole("row").filter({ hasText: "Actionable usefulness" })).toContainText("Not scored");
    await expect(detail.locator("blockquote").first()).toHaveText("The reading is 80 bar.");
  }
  await detail.getByText("Frozen agent input", { exact: true }).click();
  await expect(detail.locator("pre").filter({ hasText: '"pressure_kPa": 8000' })).toBeVisible();
  await page.getByRole("link", { name: "How the evaluation works", exact: true }).click();
  await expect(method).toHaveJSProperty("open", true);
  await expect(page.locator("#evaluation-results")).toContainText("does not run the production planner");
  await page.setViewportSize({ width: 480, height: 900 });
  const comparison = detail.locator(".agent-reference-comparison");
  const panes = comparison.locator(":scope > section");
  const expectedBounds = await panes.nth(0).boundingBox(), actualBounds = await panes.nth(1).boundingBox();
  if (!expectedBounds || !actualBounds) throw new Error("Missing reference comparison");
  expect(expectedBounds.x).toBe(actualBounds.x);
  expect(expectedBounds.y).toBeLessThan(actualBounds.y);
});
}

test("recorded recovery suites display episode metrics and their own case names without replacing the current run", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = recording(), recovery = recording();
  recovery.suite = "recovery"; recovery.suite_name = "Recovery and repeated events";
  recovery.run_id = "unit-test-recovery";
  recovery.implementation_unchanged = false;
  const network = recovery.networks?.[0];
  if (!network) throw new Error("Missing test network");
  network.id = "R1"; network.name = "Leak stops and pressure recovers";
  network.status = "failed";
  for (const frame of network.frames) {
    if (frame.review_case_id) frame.review_case_id = frame.review_case_id.replace("N1@", "R1@");
  }
  for (const row of recovery.cases) { row.network_id = "R1"; row.case_id = row.case_id.replace("N1@", "R1@"); }
  recovery.metrics = {
    completed_cases: 3, target_met: false, calibration_passed: true, groups: {}, rates: {},
    localization_mean_midpoint_error_m: null, localization_mean_width_m: null, confirmed_cause_claims: 0,
    temporal: {
      basis: "Recovery scoring starts after one full window without the leak.",
      episodes: [{ network_id: "R1", episode: 1, segment_id: "P5", onset_seconds: 90, stop_seconds: 180,
        first_fresh_correct_review_seconds: 150, detection_delay_source_seconds: 60,
        active_windows: 6, uncovered_active_windows: 3, clean_recovery_start_seconds: 240,
        first_clear_review_seconds: null, clearance_delay_source_seconds: null,
        clean_recovery_windows: 9, false_leak_recovery_windows: 9, unassessed_recovery_windows: 0 }],
      controls: [],
    },
  };
  report.additional_evaluations = [recovery];
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const suites = page.getByRole("combobox", { name: "Evaluation suite", exact: true });
  await suites.selectOption("recovery");
  await expect(page.getByRole("heading", { name: "Leak recovery and new leaks", exact: true })).toBeVisible();
  await expect(page.locator("#evaluation-results")).toContainText("No admitted clearance");
  await expect(page.locator("#evaluation-results")).toContainText("9/9 clean windows falsely reported");
  await expect(page.locator("#evaluation-results")).toContainText("Implementation changed during this run");
  await expect(page.getByRole("columnheader", { name: "Recorded / planned windows", exact: true })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "failed" }).first()).toContainText("R1");
  await expect(page.locator("#evaluation-results")).toContainText("zero recorded windows is not zero misses");
  await expect(page.getByRole("combobox", { name: "Evaluation recording", exact: true }))
    .toContainText("R1 · Leak stops and pressure recovers");
  await suites.selectOption("current");
  await expect(page.getByRole("combobox", { name: "Evaluation recording", exact: true })).toContainText("N1 · Broad leak");
});

test("failed non-leak investigations do not imply a perfect false-alarm score", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = recording(), controls = recording();
  controls.suite = "non_leak"; controls.run_id = "failed-controls";
  controls.cases.forEach(row => { row.status = "failed"; row.accepted_report = false; row.extraction = undefined; });
  controls.metrics = {
    completed_cases: 0, target_met: false, calibration_passed: true, groups: {}, rates: {},
    localization_mean_midpoint_error_m: null, localization_mean_width_m: null, confirmed_cause_claims: 0,
    temporal: {
      basis: "Absent reports do not prove health.", episodes: [],
      controls: [{ network_id: "C1", name: "No-leak control", windows: 61,
        assessed_windows: 0, unassessed_windows: 61, false_leak_windows: 0, inspection_windows: 0 }],
    },
  };
  report.additional_evaluations = [controls];
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await page.getByRole("combobox", { name: "Evaluation suite", exact: true }).selectOption("non_leak");
  const row = page.getByRole("row").filter({ hasText: "C1 · No-leak control" });
  await expect(row).toContainText("61 without a report");
  await expect(row).toContainText("Not assessed: no admitted reports");
  await expect(row).not.toContainText("0.0%");
});

test("overall cards distinguish false sensors and wrong types without changing during historical report admission", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = instrumentRecording();
  const final = report.cases.find(row => row.case_id === "N1@360");
  if (!final?.extraction?.mapping) throw new Error("Missing final test mapping");
  const invalid = final.extraction.mapping.sensor_issues.find(item => item.sensor_id === "P4-ST8-A");
  if (!invalid) throw new Error("Missing invalid-reading test issue");
  invalid.kind = "drift";
  final.extraction.mapping.sensor_issues.push(
    { sensor_id: "P5-ST4-A", kind: "drift" },
    { sensor_id: "P7-ST1-A", kind: "offset" },
  );
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const card = page.locator('.spatial-scorecards [data-metric="agent_sensor_concerns"]');
  await expect(card).toContainText("252/432 covered · 180 uncovered · 1 false alarms · precision 99.6%");
  await expect(card).toContainText("All issue-type recall: 53.1% · 255/480 covered");
  await page.locator(".spatial-instrument-audit > summary").click();
  await expect(page.locator(".spatial-instrument-audit")).toContainText("P4-ST8-A (invalid)");
  await expect(page.locator(".spatial-instrument-audit")).toContainText("P4-ST8-A (drift)");
  await expect(page.locator(".spatial-instrument-audit")).toContainText("P5-ST4-A");
  const finalDetails = page.getByRole("table", { name: "Metrics by snapshot", exact: true })
    .locator('tr[data-network="N1"][data-source-seconds="360"]');
  await expect(finalDetails.locator('[data-metric="agent_sensor_concerns"]')).toContainText("TP 14 · FN 0 · FP 1");
  await expect(finalDetails.locator('[data-metric="issueTypes"]')).toContainText("TP 15 · FN 1 · FP 2");
  await page.getByRole("button", { name: "2:30 review · recorded" }).click();
  await page.getByRole("button", { name: "Play recording", exact: true }).click();
  await page.clock.runFor(3000);
  await expect(page.locator("#evaluation-agent-map .eval-warning-pattern, #evaluation-agent-map .eval-leak-pattern")).toHaveCount(0);
  await expect(card.locator("strong")).toHaveText("58.3%");
  await expect(card).toContainText("252/432 covered · 180 uncovered · 1 false alarms");
  await page.clock.runFor(11000);
  await expect(card.locator("strong")).toHaveText("58.3%");
  await expect(card).toContainText("252/432 covered · 180 uncovered · 1 false alarms");
});

test("overall cards reject mismatched reviews and label partial or wholly empty recordings", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = instrumentRecording();
  const final = report.cases.find(row => row.case_id === "N1@360");
  const empty = report.networks?.find(network => network.id === "N2");
  if (!final || !empty) throw new Error("Missing test records");
  final.input_hash = "wrong-input";
  empty.frames = []; empty.status = "running";
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const card = page.locator('.spatial-scorecards [data-metric="agent_sensor_concerns"]');
  await expect(card.locator("strong")).toHaveText("55.6%");
  await expect(card).toContainText("120/216 covered · 96 uncovered");
  await expect(page.locator(".spatial-score-basis")).toContainText("2 cases · 21 recorded source windows · partial recording");
  const snapshots = page.getByRole("table", { name: "Metrics by snapshot", exact: true });
  await expect(snapshots.locator("tbody tr")).toHaveCount(21);
  const mismatched = snapshots.locator('tr[data-network="N1"][data-source-seconds="360"]');
  await expect(mismatched).toContainText("Mismatched review; not used");
  await expect(mismatched).toContainText("Retained from 2:30");
  await expect(mismatched.locator('[data-metric="agent_sensor_concerns"]')).toContainText("57.1% (8/14)");
  await expect(page.getByRole("table", { name: "Metrics by case", exact: true })
    .locator('tr[data-network="N2"]')).toContainText("Pending");
  await page.getByRole("combobox", { name: "Evaluation recording", exact: true }).selectOption("N2");
  await expect(card.locator("strong")).toHaveText("55.6%");
  await expect(page.locator(".spatial-score-basis")).toContainText("partial recording");
  for (const network of report.networks || []) network.frames = [];
  report.status = "running";
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await expect(card.locator("strong")).toHaveText("Pending");
  await expect(card).toContainText("No recorded source windows");
  await expect(page.locator(".spatial-score-basis")).toContainText("0 recorded source windows · partial recording");
  await expect(page.locator(".spatial-instrument-audit")).not.toContainText("P4-ST8-A");
  await expect(snapshots).toContainText("No recorded source windows. Snapshot metrics are pending.");
});

test("overall coverage retains older admitted findings after failure but respects a newer negative reassessment", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = instrumentRecording();
  const negative = report.cases.find(row => row.case_id === "N1@360");
  const failed = report.cases.find(row => row.case_id === "N2@360");
  if (!negative?.extraction?.mapping || !failed) throw new Error("Missing final test reviews");
  negative.extraction.mapping = { leaks: [], sensor_issues: [], instrumentation_concern: false };
  failed.status = "failed"; failed.accepted_report = false; failed.error_code = "grounding_failed";
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const card = page.locator('.spatial-scorecards [data-metric="agent_sensor_concerns"]');
  await expect(card.locator("strong")).toHaveText("53.7%");
  await expect(card).toContainText("232/432 covered · 200 uncovered · 0 false alarms");
  await expect(card).toContainText("All issue-type recall: 48.3% · 232/480 covered");
  await expect(page.locator('.spatial-scorecards [data-metric="localization_containment"] strong')).toHaveText("29/36");
  const snapshots = page.getByRole("table", { name: "Metrics by snapshot", exact: true });
  const failedDetails = snapshots.locator('tr[data-network="N2"][data-source-seconds="360"]');
  await expect(failedDetails).toContainText("Failed review: grounding_failed");
  await expect(failedDetails).toContainText("Retained from 2:30");
  const negativeDetails = snapshots.locator('tr[data-network="N1"][data-source-seconds="360"]');
  await expect(negativeDetails).toContainText("New admitted report");
  await expect(negativeDetails.locator('[data-metric="agent_sensor_concerns"]')).toContainText("0.0% (0/14)");
});

test("leak false-positive rate counts no-leak windows and retains false reports until a newer reassessment", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = instrumentRecording();
  const negative = report.networks?.find(network => network.id === "N2");
  const final = report.cases.find(row => row.case_id === "N2@360");
  if (!negative || !final?.extraction?.mapping) throw new Error("Missing negative test recording");
  for (const frame of negative.frames) frame.truth.leak_source = null;
  final.extraction.mapping.leaks = [];
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const card = page.locator('.spatial-scorecards [data-metric="leak_false_positive_rate"]');
  await expect(card.locator("strong")).toHaveText("58.3%");
  await expect(card).toContainText("14/24 no-leak windows falsely reported as leakage");
  const caseDetails = page.getByRole("table", { name: "Metrics by case", exact: true }).locator('tr[data-network="N2"]');
  await expect(caseDetails).toContainText("66.7% (14/21)");
  const snapshots = page.getByRole("table", { name: "Metrics by snapshot", exact: true });
  await expect(snapshots.locator('tr[data-network="N2"][data-source-seconds="255"]')).toContainText("100.0% (1/1)");
  await expect(snapshots.locator('tr[data-network="N2"][data-source-seconds="360"]')).toContainText("0.0% (0/1)");
  await page.getByRole("combobox", { name: "Evaluation recording", exact: true }).selectOption("N2");
  await page.getByRole("slider", { name: "Synchronized recording time" }).fill("105");
  await expect(page.locator("#evaluation-agent-map .eval-leak-pattern")).toHaveCount(0);
  await expect(card.locator("strong")).toHaveText("58.3%");
  final.status = "failed"; final.accepted_report = false;
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await expect(card.locator("strong")).toHaveText("62.5%");
  await expect(card).toContainText("15/24 no-leak windows falsely reported as leakage");
  await expect(caseDetails).toContainText("71.4% (15/21)");
});

test("leak false-positive rate is not zero when there are no negative windows to measure", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local UI opt-in.");
  await page.request.post("/api/login", { data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD } });
  const report = instrumentRecording();
  for (const network of report.networks || []) network.frames = network.frames.filter(frame => frame.truth.leak_source);
  await page.route("**/api/evaluation", route => route.fulfill({ json: report }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Evaluation" }).click();
  const card = page.locator('.spatial-scorecards [data-metric="leak_false_positive_rate"]');
  await expect(card.locator("strong")).toHaveText("Not applicable");
  await expect(card).toContainText("false-positive rate cannot be measured");
});
