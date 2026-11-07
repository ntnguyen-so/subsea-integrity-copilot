import { test, expect } from "@playwright/test";
import type { EvaluationReport } from "../../web/ts/evaluation";

test("evaluation opens authenticated recordings without submitting inference or exposing labels to monitoring", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit local evaluation UI opt-in.");
  const anonymous = await page.request.get("/api/evaluation");
  expect(anonymous.status()).toBe(401);
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const report: EvaluationReport = await (await page.request.get("/api/evaluation")).json();
  expect(report.cases).toHaveLength(8);
  const postRequests: string[] = [];
  page.on("request", request => { if (request.method() === "POST") postRequests.push(request.url()); });
  await page.goto("/");
  await page.getByRole("tab", { name: "Live" }).focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Evaluation" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#panel-evaluation")).toBeVisible();
  await expect(page.locator("#panel-live")).toBeHidden();
  await expect(page.locator(".evaluation-case")).toHaveCount(8);
  await expect(page.locator("#evaluation-results")).toContainText("deterministic comparison");
  if (report.metrics) {
    await expect(page.locator("#evaluation-results")).toContainText(
      report.metrics.target_met ? "Observed reference metrics exceed 95%." : "The >95% target is not yet met.",
    );
    const issues = report.metrics.groups.agent_issue_types;
    await expect(page.getByRole("row").filter({ hasText: "Agent issue-type mapping · sensor/window/type" }))
      .toContainText(`${issues.tp} / ${issues.fp} / ${issues.fn}`);
  }
  await page.locator('.evaluation-case[data-case="G1"] > summary').click();
  await expect(page.locator('.evaluation-case[data-case="G1"]')).toContainText("Leak source on P1 at 400 m");
  await expect(page.locator('.evaluation-case[data-case="G1"] .evaluation-hash')).toContainText(report.cases[0].dataset_sha256);
  if (report.cases[0].answer) {
    await page.getByText("Complete accepted report · sensor groups and checked evidence", { exact: true }).first().click();
    await expect(page.locator('.evaluation-case[data-case="G1"] details .evaluation-answer')).toHaveText(report.cases[0].answer);
  }
  for (const item of report.cases) {
    const source = item.truth.leak_source;
    if (source) await expect(page.locator(`.evaluation-case[data-case="${item.case_id}"]`))
      .toContainText(`Leak source on ${source.segment_id} at ${source.chainage_m} m`);
  }
  expect(postRequests).toEqual([]);
});
