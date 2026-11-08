import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import { reportText } from "../../web/ts/presentation";
import type { InvestigationCase } from "../../web/ts/types";

test("report prose hides internal citations without removing measurements or ordinary brackets", () => {
  const original = "P5 focus 600-1000 m [ev-227; KN-LOCALIZATION-R1]. Pressure (bar) is lower at [ST4, ST5] (claim-114). [the executed comparisons]";
  expect(reportText(original)).toBe("P5 focus 600-1000 m. Pressure (bar) is lower at [ST4, ST5].");
  expect(original).toContain("[ev-227; KN-LOCALIZATION-R1]");
  expect(reportText("Offset [custom-source].", ["custom-source"])).toBe("Offset.");
});

test("assessment is readable without run evidence while its original audit remains available", async ({ page }) => {
  const file: InvestigationCase = {
    schema_version: "investigation-v1", task_id: "fixture", generation_id: "fixture",
    snapshot_id: "fixture", question: "Fixture-only incident", mode: "scripted",
    state: "SUCCEEDED", window_start: "2026-01-01T00:01:00Z",
    window_end: "2026-01-01T00:02:00Z", input_hash: "fixture",
    pack_version: "fixture", baseline_version: "fixture", parameter_version: "fixture",
    history_version: null, disposition: "Recorded fixture result", hypothesis: "suspected_leak",
    inspection: { segment_id: "P5", start_m: 600, end_m: 1000 },
    next_action: "Recorded workflow recommendation",
    interpretation: {
      focus: "inspection_rationale",
      answer: {
        text: "P5 has a leak pattern. Focus 600-1000 m because paired ST4/ST5 readings fall more than adjacent ST3/ST6 [ev-227].",
        references: ["ev-227"],
      },
      competing_causes: [{
        cause: "instrumentation_or_telemetry", stance: "possible",
        text: "Sensor A drifts while co-located B stays stable, which fits a measurement-path problem rather than a joint pressure loss [MAINT-TEST].",
        references: ["MAINT-TEST"],
      }],
      regional_assessments: [{
        sensor_ids: ["P5-ST4-A", "P5-ST5-A"], hypothesis: "leak_pattern",
        text: "The boundaries are halfway between the stronger central stations and weaker neighbors [ev-227].",
        references: ["ev-227"],
      }],
      follow_up_questions: ["Does an independent reference confirm the physical pressure?"],
    },
    checked_claims: [], limitations: [], comparisons: [], steps: [], reused_task_ids: [],
    fresh_model_calls: 0, fresh_tool_calls: 0, recorded_elapsed_seconds: 0,
    provider_cost_usd: null, authority: "Read-only fixture",
    report_target_seconds: 900, report_target_met: true, interpretation_review: null,
    knowledge_packet: null, knowledge_used_ids: [],
    sources: [{
      document: { id: "MAINT-TEST", title: "Fixture source", body: "Original source [ev-227]: 1.3 bar." },
      use: "cited",
    }],
  };
  const bundle = buildSync({
    stdin: { contents: 'export { renderCasefile } from "./web/ts/casefile";', resolveDir: process.cwd(), loader: "ts" },
    bundle: true, write: false, format: "iife", globalName: "ReportFixture",
  }).outputFiles[0].text;
  await page.setContent('<main id="fixture"></main>');
  await page.addScriptTag({ content: `${bundle}\nReportFixture.renderCasefile(document.getElementById("fixture"), ${JSON.stringify(file)}, { draft: () => {}, claim: () => {} });` });
  await expect(page.locator(".case-assessment")).toContainText("because paired ST4/ST5");
  await expect(page.locator(".case-assessment")).not.toContainText("ev-227");
  await expect(page.locator(".case-causes")).not.toContainText("MAINT-TEST");
  await expect(page.locator(".case-followups")).not.toBeVisible();
  await expect(page.locator(".case-work-summary")).not.toBeVisible();
  await page.locator(".case-region > summary").click();
  await expect(page.locator(".case-region p")).toContainText("boundaries are halfway");
  await expect(page.locator(".case-region p")).not.toContainText("ev-227");
  await page.locator(".case-audit > summary").click();
  await expect(page.locator(".case-audit .chips").first()).toContainText("ev-227");
  await page.locator(".case-source > summary").click();
  await expect(page.locator(".case-source-body")).toHaveText("Original source [ev-227]: 1.3 bar.");
});

test("a real recorded assessment reopens without citations or new inference", async ({ page }) => {
  const taskId = process.env.SUBSEA_REPORT_UI_TASK_ID;
  test.skip(!taskId || !process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit recorded-report opt-in.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const response = await page.request.get(`/api/tasks/${taskId}/casefile`);
  expect(response.status()).toBe(200);
  const file: InvestigationCase = await response.json();
  const inferenceRequests: string[] = [];
  page.on("request", request => {
    if (request.method() === "POST" && request.url().endsWith("/questions")) inferenceRequests.push(request.url());
  });
  await page.goto("/");
  await page.locator("#replay-history").selectOption(file.generation_id);
  await page.locator("#tab-agents").click();
  const details = page.locator("#execution-details");
  if (await details.getAttribute("open") === null) await details.locator(":scope > summary").click();
  await page.locator(`#task-tree button[data-task="${taskId}"]`).click();
  await expect(page.locator("#investigation-case")).toHaveAttribute("data-task", taskId!);
  await expect(page.locator(".case-assessment")).toContainText("Why this location");
  await expect(page.locator(".case-assessment")).not.toContainText(/\b(?:ev-\d+|claim-\d+|KN-[\w-]+)\b/);
  await expect(page.locator(".case-followups")).not.toBeVisible();
  await page.locator(".case-audit > summary").click();
  await expect(page.locator(".case-audit > .chips").first()).toContainText(file.interpretation!.answer.references[0]);
  const after = await page.request.get(`/api/tasks/${taskId}/casefile`);
  expect(await after.json()).toEqual(file);
  expect(inferenceRequests).toEqual([]);
});
