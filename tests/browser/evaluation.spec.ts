/**
 * Workspace links use mocked sessions; recorded evaluation integration requires
 * explicit local-credential opt-in. Opening findings submits no inference and
 * monitoring stays truth-blind. This checks UI isolation, not label correctness.
 */
import { test, expect } from "@playwright/test";
import type { EvaluationReport } from "../../web/ts/evaluation";

test("evaluation deep link opens the workspace and retains it through sign-in", async ({ page }) => {
  let evaluationReads = 0;
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/session") return route.fulfill({
      json: { authenticated: false, csrf_token: null, username: null },
    });
    if (path === "/api/login") return route.fulfill({
      json: { authenticated: true, csrf_token: "test-csrf", username: "operator" },
    });
    if (path === "/api/evaluation") {
      evaluationReads++;
      return route.fulfill({
        json: { version: "reference-evaluation-v1", status: "not_run", cases: [], metrics: null },
      });
    }
    if (path === "/api/replays") return route.fulfill({ json: { replays: [] } });
    return route.fulfill({ status: 503, json: { detail: "Live catalog unavailable in this test." } });
  });
  await page.goto("/?tab=evaluation");
  await expect(page.getByRole("tab", { name: "Evaluation", exact: true }))
    .toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#panel-evaluation")).toBeVisible();
  await expect(page.locator("#evaluation-results")).toContainText("Sign in");
  await page.locator("#password").fill("test-only");
  await page.locator("#login-form").getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#login-panel")).toBeHidden();
  await expect.poll(() => evaluationReads).toBeGreaterThan(0);
  await expect(page.getByRole("tab", { name: "Evaluation", exact: true }))
    .toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#panel-evaluation")).toBeVisible();
});

for (const tab of ["live", "unknown"]) {
  test(`dashboard link defaults safely to Live for tab=${tab}`, async ({ page }) => {
    await page.route("**/api/session", route => route.fulfill({
      json: { authenticated: false, csrf_token: null, username: null },
    }));
    await page.goto(`/?tab=${tab}`);
    await expect(page.getByRole("tab", { name: "Live", exact: true }))
      .toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#panel-live")).toBeVisible();
    await expect(page.locator("#panel-evaluation")).toBeHidden();
  });
}

test("evaluation opens authenticated recordings without submitting inference or exposing labels to monitoring", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local evaluation UI opt-in.");
  const anonymous = await page.request.get("/api/evaluation");
  expect(anonymous.status()).toBe(401);
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const report: EvaluationReport = await (await page.request.get("/api/evaluation")).json();
  expect(report.cases.length).toBeGreaterThan(0);
  expect(new Set(report.cases.map(item => item.case_id)).size).toBe(report.cases.length);
  const postRequests: string[] = [];
  page.on("request", request => { if (request.method() === "POST") postRequests.push(request.url()); });
  await page.goto("/");
  await page.getByRole("tab", { name: "Live" }).focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Evaluation" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#panel-evaluation")).toBeVisible();
  await expect(page.locator("#panel-live")).toBeHidden();
  await expect(page.locator("#question-tools")).toHaveCount(0);
  await expect(page.locator("#system-details")).toBeHidden();
  const provenance = page.getByRole("region", { name: "Evaluation provenance and limits" });
  await expect(provenance).toBeVisible();
  await expect(provenance).toContainText("Orange pressure alerts and preliminary screening warnings remain deterministic");
  if (report.remapped_at) {
    await expect(provenance).toContainText("not fresh agent runs");
    await expect(provenance).toContainText("not a full-cohort evaluation of the revised prompts");
  }
  if (report.version === "spatial-evaluation-v1") {
    await expect(page.locator("#evaluation-truth-map [data-sensor]")).toHaveCount(112);
    await expect(page.locator("#evaluation-agent-map [data-sensor]")).toHaveCount(112);
    await page.locator(".spatial-evidence > summary").click();
  }
  await expect(page.locator(".evaluation-case")).toHaveCount(report.cases.length);
  await expect(page.locator("#evaluation-results")).toContainText("deterministic comparison");
  if (report.metrics) {
    await expect(page.locator("#evaluation-results")).toContainText(
      report.metrics.target_met ? report.version === "spatial-evaluation-v1" ?
        "Observed review-checkpoint metrics exceed 95%; this is not continuous coverage." :
        "Observed reference metrics exceed 95%." : "The >95% target is not yet met.",
    );
    const issues = report.metrics.groups.agent_issue_types;
    await expect(page.getByRole("row").filter({ hasText: report.version === "spatial-evaluation-v1" ?
      "Agent issue-type mapping · network/review/sensor/type" : "Agent issue-type mapping · sensor/window/type" }))
      .toContainText(`${issues.tp} / ${issues.fp} / ${issues.fn}`);
  }
  const first = report.cases.find(item => item.answer) || report.cases[0];
  const caseSelector = `.evaluation-case[data-case="${first.case_id}"]`;
  await page.locator(`${caseSelector} > summary`).click();
  if (first.truth.leak_source) await expect(page.locator(caseSelector)).toContainText(
    `Leak source on ${first.truth.leak_source.segment_id} at ${first.truth.leak_source.chainage_m} m`,
  );
  await expect(page.locator(`${caseSelector} .evaluation-hash`)).toContainText(first.dataset_sha256);
  if (first.answer) {
    await page.getByText("Complete accepted report · sensor groups and checked evidence", { exact: true }).first().click();
    await expect(page.locator(`${caseSelector} details .evaluation-answer`)).toHaveText(first.answer);
  }
  for (const item of report.cases) {
    const source = item.truth.leak_source;
    if (source) await expect(page.locator(`.evaluation-case[data-case="${item.case_id}"]`))
      .toContainText(`Leak source on ${source.segment_id} at ${source.chainage_m} m`);
  }
  const accepted = report.cases.filter(item => item.accepted_report);
  const reportOnly = accepted.filter(item => item.extraction?.status === "completed"
    && item.extraction.source_text_scope === "incident-answer-only-v1").length;
  await expect(provenance).toContainText(`${reportOnly}/${accepted.length} accepted reports`);
  await page.getByRole("tab", { name: "Agent reliability", exact: true }).click();
  await expect(page.locator("#evaluation-scope-label")).toHaveText("FROZEN REFERENCES / RECORDED ANSWERS");
  await page.getByRole("tab", { name: "Detection", exact: true }).click();
  for (const name of ["Live", "Inspect"]) {
    await page.getByRole("tab", { name, exact: true }).click();
    await expect(page.locator("#question-tools")).toHaveCount(0);
    await expect(page.locator("#system-details")).toBeVisible();
  }
  expect(postRequests).toEqual([]);
});
