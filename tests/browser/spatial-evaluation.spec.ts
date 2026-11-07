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
        leak_source: end > 90 ? { segment_id: "P5", chainage_m: 800 } : null,
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
      authorized_inspection: { segment_id: "P5", start_m: 600, end_m: 1000 },
      extraction: { status: "completed", mapping: {
        leaks: end > 90 ? [{ segment_id: "P5", assertion: "suspected", interval: { start_m: 600, end_m: 1000 },
          quote: { path: "answer.text", text: "unit-test-only" } }] : [],
        sensor_issues: [], instrumentation_concern: false,
      } },
    })),
  };
}

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
  await expect(page.locator(".spatial-agent strong")).toHaveText(["Not started", "Not started", "Not started"]);
  await page.getByRole("button", { name: "2:30 review · recorded" }).click();
  await page.getByRole("button", { name: "Play recording", exact: true }).click();
  await page.clock.runFor(5000);
  await expect(truth).toHaveAttribute("data-source-seconds", "150");
  await expect(agent).toHaveAttribute("data-source-seconds", "150");
  await expect(agent.locator(".eval-inspection")).toHaveCount(0);
  await expect(page.locator(".spatial-progress")).toContainText("Source paused for investigation");
  await page.clock.runFor(8500);
  await expect(agent).toHaveAttribute("data-source-seconds", "150");
  await expect(agent.locator(".eval-inspection")).toHaveCount(1);
  await page.getByRole("button", { name: "Pause recording", exact: true }).click();
  expect(posts).toEqual([]);
});

test("an accepted report for another snapshot cannot paint an inspection interval", async ({ page }) => {
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
  await expect(page.locator("#evaluation-agent-map .eval-inspection")).toHaveCount(0);
  await expect(page.locator(".spatial-map-caption").last()).toHaveAttribute("data-accepted", "false");
});
