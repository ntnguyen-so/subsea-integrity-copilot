import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import { reportText } from "../../web/ts/presentation";
import type { InvestigationCase, Projection } from "../../web/ts/types";

test("report prose hides internal citations without removing measurements or ordinary brackets", () => {
  const original = "P5 focus 600-1000 m [ev-227; KN-LOCALIZATION-R1]. Pressure (bar) is lower at [ST4, ST5] (claim-114). [the executed comparisons]";
  expect(reportText(original)).toBe("P5 focus 600-1000 m. Pressure (bar) is lower at [ST4, ST5].");
  expect(original).toContain("[ev-227; KN-LOCALIZATION-R1]");
  expect(reportText("Offset [custom-source].", ["custom-source"])).toBe("Offset.");
});

test("long decimal measurements are readable without rounding tiny changes to zero or editing source text", () => {
  const source = "P6 loses 1.4278944857561129 bar versus 0.000000123456789 bar. Step -2.608612345678 bar.";
  expect(reportText(source)).toBe("P6 loses 1.428 bar versus 1.23e-7 bar. Step -2.609 bar.");
  expect(source).toContain("1.4278944857561129");
  expect(reportText("Reference [measurement-1.234567891].", ["measurement-1.234567891"])).toBe("Reference.");
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
  await page.addScriptTag({ content: `${bundle}\nReportFixture.renderCasefile(document.getElementById("fixture"), ${JSON.stringify(file)}, { claim: () => {} });` });
  await expect(page.locator(".case-assessment")).toContainText("because paired ST4/ST5");
  await expect(page.locator(".case-assessment")).not.toContainText("ev-227");
  await expect(page.locator(".case-causes")).not.toContainText("MAINT-TEST");
  await expect(page.locator(".case-followups")).toHaveCount(0);
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
  await page.goto("/?replay=" + encodeURIComponent(file.generation_id) + "&view=live");
  await page.locator("#investigation-technical > summary").click();
  await page.locator(`#task-tree button[data-task="${taskId}"]`).click();
  await expect(page.locator("#investigation-case")).toHaveAttribute("data-task", taskId!);
  await expect(page.locator(".case-assessment")).toHaveText(
    reportText(file.interpretation!.answer.text, file.interpretation!.answer.references),
  );
  await expect(page.locator(".case-assessment")).not.toContainText(/\b(?:ev-\d+|claim-\d+|KN-[\w-]+)\b/);
  await expect(page.locator(".case-followups")).toHaveCount(0);
  await page.locator(".case-audit > summary").click();
  await expect(page.locator(".case-audit > .chips").first()).toContainText(file.interpretation!.answer.references[0]);
  const after = await page.request.get(`/api/tasks/${taskId}/casefile`);
  expect(await after.json()).toEqual(file);
  expect(inferenceRequests).toEqual([]);
});

test("live monitoring exposes its exact investigation trace without opening receipts", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires the owned local operator environment.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const { replays } = await (await page.request.get("/api/replays")).json();
  let recorded: Projection | undefined;
  for (const replay of replays.slice(0, 10)) {
    const candidate: Projection = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
    if (candidate.tasks.some(task => task.role === "operator_response" && task.model_calls > 0)) {
      recorded = candidate;
      break;
    }
  }
  expect(recorded, "A saved investigation must be available").toBeDefined();
  await page.route(`**/api/replays/${recorded!.replay.id}/recordings`, route =>
    route.fulfill({ json: { recordings: [] } }));
  const posts: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.method() === "POST") posts.push(request.url()); });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(recorded!.replay.id) + "&view=live");
  const headerLink = page.locator(".agent-status-panel .panel-heading").getByRole("link", { name: "Open whole investigation in Langfuse" });
  await expect(headerLink).toBeVisible();
  const headerTaskId = await headerLink.getAttribute("data-task");
  expect(recorded!.tasks.some(task => task.id === headerTaskId && !task.parent_id)).toBe(true);
  const trace = await (await page.request.get(`/api/tasks/${headerTaskId}/trace`)).json();
  const sessionUrl = trace.trace_layout === "investigation-v1" ? trace.langfuse_url
    : `http://127.0.0.1:3001/project/subsea-copilot/sessions/${trace.session_id}`;
  await expect(headerLink).toHaveAttribute("href", sessionUrl);
  const related = recorded!.tasks.filter(task => task.root_id === headerTaskId && task.id !== headerTaskId);
  expect(related.length).toBeGreaterThan(0);
  for (const task of related) {
    const agentTrace = await (await page.request.get(`/api/tasks/${task.id}/trace`)).json();
    if (trace.trace_layout === "investigation-v1") expect(agentTrace.trace_id).toBe(trace.trace_id);
    else expect(agentTrace.trace_id).not.toBe(trace.trace_id);
    expect(agentTrace.session_id).toBe(trace.session_id);
  }
  await expect(headerLink).toHaveAttribute("target", "_blank");
  await expect(page.locator(".agent-conclusion-label")).toHaveCount(0);
  await expect(page.locator(".engineer-details")).toHaveCount(0);
  await page.locator("#investigation-technical > summary").click();
  await page.getByRole("button", { name: "View Langfuse run", exact: true }).click();
  const link = page.locator("#trace-view").getByRole("link", { name: "Open whole investigation in Langfuse" });
  await expect(link).toBeVisible();
  await expect(page.locator("#execution-details")).not.toHaveAttribute("open");
  const traceText = await page.locator("#trace-view").innerText();
  expect(traceText).toMatch(/Stored trace/);
  await page.locator("#trace-view summary").click();
  const traceId = (await page.locator("#trace-view .public-record").innerText()).match(/trace_id: ([a-f0-9]{32})/)?.[1];
  expect(traceId).toBeTruthy();
  await expect(link).toHaveAttribute("href", sessionUrl);
  await expect(page.locator("#trace-view").getByRole("link", { name: "Open this agent attempt in Langfuse" }))
    .toHaveAttribute("href", `http://127.0.0.1:3001/project/subsea-copilot/traces/${traceId}`);
  expect(posts).toEqual([]);
  const other = replays.find((replay: { id: string }) => replay.id !== recorded!.replay.id);
  expect(other).toBeDefined();
  await page.goto("/?replay=" + encodeURIComponent(other.id) + "&view=live");
  await expect(link).toHaveCount(0);
  await expect(page.locator("#automatic-langfuse")).not.toHaveAttribute("data-task", headerTaskId!);
  expect(errors).toEqual([]);
});

test("a new scripted investigation records handed-off agents in one trace", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires the owned local operator environment.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
  const created = await page.request.post("/api/replays", {
    headers, data: { scenario: "S1", seed: 2026, mode: "scripted", idempotency_key: `unified-trace-${Date.now()}` },
  });
  expect(created.status()).toBe(200);
  const replay = await created.json();
  let snapshotId: string | undefined;
  for (let step = 0; step < 2; step++) {
    const controlled = await page.request.post(`/api/replays/${replay.id}/control`, {
      headers, data: { action: "step", idempotency_key: `step-${step}` },
    });
    expect(controlled.status()).toBe(200);
    snapshotId = (await controlled.json()).latest_window_id;
  }
  const submitted = await page.request.post(`/api/replays/${replay.id}/questions`, {
    headers, data: {
      snapshot_id: snapshotId, mode: "scripted",
      question: "Is this a possible leak or an instrumentation issue?", idempotency_key: "check",
    },
  });
  expect(submitted.status()).toBe(200);
  const root = await submitted.json();
  await expect.poll(async () => {
    const detail = await (await page.request.get(`/api/tasks/${root.id}`)).json();
    return detail.task.state;
  }, { timeout: 45_000 }).toMatch(/^(SUCCEEDED|ABSTAINED)$/);
  const rootTrace = await (await page.request.get(`/api/tasks/${root.id}/trace`)).json();
  expect(rootTrace.trace_layout).toBe("investigation-v1");
  const detail = await (await page.request.get(`/api/tasks/${root.id}`)).json();
  expect(detail.children.map((child: { role: string }) => child.role)).toEqual(
    expect.arrayContaining(["sensor_quality", "event_diagnosis"]),
  );
  for (const child of detail.children) {
    const childTrace = await (await page.request.get(`/api/tasks/${child.id}/trace`)).json();
    expect(childTrace.trace_id).toBe(rootTrace.trace_id);
    expect(childTrace.span_id).not.toBe(rootTrace.span_id);
  }
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  await expect(page.locator("#automatic-langfuse")).toBeVisible();
  await expect(page.locator("#automatic-langfuse")).toHaveAttribute("href", rootTrace.langfuse_url);
});
