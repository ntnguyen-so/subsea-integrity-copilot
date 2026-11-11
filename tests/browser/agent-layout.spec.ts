/**
 * Agent-workspace contract: readable role selection, retained focus, honest reviewer/
 * mapper states and accessible trace links. Mixes isolated fixtures with opted-in
 * owned recordings; rendering a saved workspace must not start new inference.
 */
import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import { join } from "node:path";
import { availableRecording, type SavedInvestigation } from "../../web/ts/investigation_playback";
import { reportText } from "../../web/ts/presentation";
import type { AgentTask, ConsoleEvent, Projection, ReplaySession, TaskDetail, WindowSnapshot } from "../../web/ts/types";

test("dashboard removes Audit and the rail note while preserving live updates and trace access", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays }: { replays: ReplaySession[] } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find(row => row.latest_window_id && row.workflow === "agent_assisted");
  expect(replay).toBeDefined();
  const projection: Projection = await (await page.request.get(`/api/replays/${replay!.id}/projection`)).json();
  const event: ConsoleEvent = {
    id: projection.cursor + 1, site_id: replay!.site_id, generation_id: replay!.id,
    type: "window.completed", created_at: projection.server_time,
    simulated_seconds: replay!.clock_seconds, snapshot_id: replay!.latest_window_id,
    task_id: null, payload: {},
  };
  await page.route(`**/api/replays/${replay!.id}/events?*`, route => route.fulfill({
    contentType: "text/event-stream",
    body: `event: window.completed\ndata: ${JSON.stringify(event)}\n\n`,
  }));
  let projections = 0;
  page.on("request", request => {
    if (request.url().endsWith(`/api/replays/${replay!.id}/projection`)) projections++;
  });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(replay!.id) + "&view=live");
  await expect.poll(() => projections).toBeGreaterThan(1);
  await expect(page.locator("#connection-state")).toContainText("reconnecting");
  await expect(page.locator("#notice")).not.toContainText(/Malformed backend event|Event scope mismatch|Required console element missing/);
  await expect(page.locator(".rail [role=tab]")).toContainText(["Live", "Maintenance", "Evaluation"]);
  await expect(page.locator("#tab-audit, #panel-audit, #tab-agents, #panel-agents, #event-feed, .rail-note")).toHaveCount(0);
  await page.locator("#tab-evaluation").focus();
  await page.keyboard.press("Home");
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#system-details")).toHaveCount(0);
  await expect(page.locator("#connection-state")).toBeVisible();
  await page.locator("#investigation-technical > summary").click();
  await expect(page.locator("#view-langfuse")).toBeVisible();
  expect(errors).toEqual([]);
});

test("question entry and Agents navigation are removed from every workspace", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".agent-status-panel .analysis-cue")).toContainText("Accepted report → Report-to-map Mapper → Map updates");
  for (const tab of ["live", "evidence", "evaluation"]) {
    await page.locator(`#tab-${tab}`).click();
    await expect(page.locator("#tab-agents, #panel-agents, #question-tools, #question, #questions, #ask-form, #ask-submit")).toHaveCount(0);
  }
  await page.locator("#tab-live").click();
  await expect(page.locator("#investigation-technical")).not.toHaveAttribute("open");
  await expect(page.locator("#investigation-technical #execution-details")).toHaveCount(1);
  await expect(page.locator("#investigation-technical > summary")).toHaveText("Execution details");
  await expect(page.locator("details#execution-details")).toHaveCount(0);
  expect(errors).toEqual([]);
});

function agent(role: string, text: string): AgentTask {
  return {
    id: role, root_id: "operator_response", site_id: "fixture", generation_id: "fixture",
    snapshot_id: "fixture", episode_id: null, parent_id: role === "operator_response" ? null : "operator_response",
    role, purpose: "Fixture", question: "Fixture", mode: "live", state: "SUCCEEDED",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:01:00Z",
    model_calls: 1, tool_calls: 1, plan: ["quality", "diagnosis", "answer"], answer: text,
    error_code: null, error_message: null, automatic: true,
    result: { outcome: "complete", claim_refs: [], evidence_ids: [], limitations: [],
      hypothesis: null, recommendation_ids: [], summary: "", investigation: null, interpretation: null },
  };
}

test("specialist outputs explain accepted findings, distinguish absent from unusable, and retain exact source scope", async ({ page }) => {
  const quality = agent("sensor_quality", "Accepted quality claim references.");
  quality.result!.summary = "Sensor A has ten absent readings and two unusable readings. This does not diagnose hardware failure.";
  quality.result!.claim_refs = ["coverage", "sensor-a"];
  quality.result!.limitations = ["missing_data", "partial_health_review", "read_only"];
  const diagnosis = agent("event_diagnosis", "Accepted diagnosis claim references.");
  diagnosis.result!.summary = "Pressure changes may have more than one explanation. No leak is physically confirmed.";
  diagnosis.result!.investigation = {
    assessment: "unresolved", document_ids: ["operation"], rejected_document_ids: ["draft"],
    comparison_call_ids: ["comparison"], next_action: "inspect_supported_interval",
  };
  const tasks = [quality, diagnosis, agent("operator_response", "Coordinator report.")];
  const basis: WindowSnapshot = {
    id: "fixture", site_id: "fixture", generation_id: "fixture",
    window_start: "2026-01-01T00:01:00Z", window_end: "2026-01-01T00:02:00Z",
    end_seconds: 120, revision: 1, predecessor_id: null, input_hash: "fixture",
    pack_version: "fixture", baseline_version: "fixture", parameter_version: "fixture",
    clock_seconds: 120, watermark_seconds: 120, created_at: "2026-01-01T00:02:00Z", canonical_count: 110,
    quality: { status: "DEGRADED", expected_samples: 120, received_samples: 110,
      usable_samples: 108, coverage: 0.9, failure_domains_available: 1, findings: [], conflicts: [], issues: [] },
    event: { hypothesis: "suspected_leak", eligible_hypotheses: [], supporting_sensor_ids: [],
      failure_domain_count: 1, persistence_seconds: 0, segment_ids: [], evidence_ids: [],
      counterevidence: [], eligible_location: false, criteria_id: "fixture" },
    location: null, evidence: {},
    claims: {
      coverage: { id: "coverage", kind: "coverage", evidence_ids: [], value: {
        expected_samples: 120, received_samples: 110, usable_samples: 108,
      } },
      "sensor-a": { id: "sensor-a", kind: "sensor_health", evidence_ids: [], value: {
        sensor_id: "A", channel: "pressure", expected: 60, received: 50, usable: 48, missing: 12, anomaly_count: 2,
      } },
      "uncited-sensor": { id: "uncited-sensor", kind: "sensor_health", evidence_ids: [], value: {
        sensor_id: "UNCITED", expected: 60, received: 60, usable: 60, anomaly_count: 50,
      } },
    },
  };
  const bundle = buildSync({
    stdin: { contents: 'export { renderAgentWork } from "./web/ts/agentwork";', resolveDir: process.cwd(), loader: "ts" },
    bundle: true, write: false, format: "iife", globalName: "SpecialistFixture",
  }).outputFiles[0].text;
  await page.setContent('<main><div id="progress" class="agent-roles"></div><div id="findings"></div></main>');
  await page.addStyleTag({ path: join(process.cwd(), "web", "styles.css") });
  await page.addScriptTag({ content: `${bundle}
    window.specialistTasks = ${JSON.stringify(tasks)};
    window.specialistBasis = ${JSON.stringify(basis)};
    window.renderSpecialists = () => SpecialistFixture.renderAgentWork(
      document.getElementById("progress"), document.getElementById("findings"),
      window.specialistTasks[2], window.specialistTasks, null, window.specialistBasis, null, () => {}, []);
    window.renderSpecialists();` });
  const reader = page.locator(".agent-output-panel:visible");
  await page.getByRole("tab", { name: "Sensor Quality Agent output" }).click();
  await expect(reader).toContainText("108 of 120 expected readings could be used (90.0%)");
  await expect(reader).toContainText("10 did not arrive; 2 arrived but could not be used");
  await expect(reader.locator(".agent-specialist-findings")).toContainText(quality.result!.summary);
  await expect(reader).toContainText("1 sensor-level finding cited");
  await expect(reader).toContainText("other sensors are not cleared");
  const sensors = reader.locator('[data-section="specialist-sensors:sensor_quality"]');
  await sensors.locator("summary").click();
  const row = sensors.locator("tbody tr");
  await expect(row).toHaveCount(1);
  await expect(row.locator("th, td")).toHaveText(["A / pressure", "48 / 60", "10", "2", "2"]);
  await expect(sensors).not.toContainText("UNCITED");
  const original = reader.locator('[data-section="specialist-original:sensor_quality"]');
  await original.locator("summary").click();
  await expect(original.locator("pre")).toContainText('"claim_refs":');
  await expect(original.locator("pre")).toContainText(quality.answer!);
  await page.evaluate(() => {
    const fixture = window as typeof window & { specialistTasks: AgentTask[]; renderSpecialists: () => void };
    fixture.specialistTasks[0].updated_at = "2026-01-01T00:03:00Z"; fixture.renderSpecialists();
  });
  await expect(sensors).toHaveAttribute("open");
  await expect(original).toHaveAttribute("open");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole("tab", { name: "Event Diagnosis Agent output" }).click();
  await expect(reader.locator(".agent-specialist-findings")).toContainText(diagnosis.result!.summary);
  await expect(reader).toContainText("operating-history check did not settle the cause");
  await expect(reader).toContainText("1 source document(s) cited; 1 read document(s) excluded");
  await expect(reader).toContainText("1 executed sensor comparison(s) cited");
  await expect(reader).toContainText("Plan an engineering inspection");
  await expect(reader).toContainText("not an authorized action");
  await page.evaluate(() => {
    const fixture = window as typeof window & {
      specialistBasis: WindowSnapshot; specialistTasks: AgentTask[]; renderSpecialists: () => void;
    };
    fixture.specialistBasis = { ...fixture.specialistBasis, id: "different-window" };
    fixture.specialistTasks[0].state = "ABSTAINED"; fixture.renderSpecialists();
  });
  await page.getByRole("tab", { name: "Sensor Quality Agent output" }).click();
  await expect(reader).toContainText("could not reach a supported conclusion");
  await expect(reader).toContainText("exact source window is not loaded");
  await expect(reader.getByText("108 of 120 expected readings", { exact: false })).toHaveCount(0);
  await expect(reader.locator("table")).toHaveCount(0);
  await page.evaluate(() => {
    const fixture = window as typeof window & { specialistTasks: AgentTask[]; renderSpecialists: () => void };
    fixture.specialistTasks[0].state = "FAILED"; fixture.renderSpecialists();
  });
  await expect(reader.locator(".agent-handoff-output")).toHaveCount(0);
  await expect(reader).toContainText("No accepted output is available");
});

for (const scenario of ["S7", "S3"]) {
  test(`${scenario} saved specialist findings are readable on Live without new inference`, async ({ page }) => {
    test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned recordings.");
    const login = await page.request.post("/api/login", { data: {
      username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
    } });
    expect(login.ok()).toBeTruthy();
    const { replays }: { replays: ReplaySession[] } = await (await page.request.get("/api/replays")).json();
    const replay = replays.find(row => row.scenario === scenario && row.seed === 2026 && row.workflow === "agent_assisted");
    expect(replay).toBeDefined();
    const endpoint = `/api/replays/${replay!.id}/recordings`;
    const { recordings }: { recordings: SavedInvestigation[] } = await (await page.request.get(endpoint)).json();
    const selected = availableRecording(recordings, 120)!;
    expect(selected.source_seconds).toBe(120);
    const frame: { detail: TaskDetail } = await (await page.request.get(`${endpoint}/${selected.task_id}`)).json();
    const writes: string[] = [], errors: string[] = [];
    page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/?replay=" + encodeURIComponent(replay!.id) + "&view=live");
    const mode = page.getByRole("switch", { name: /switch to/ });
    await expect(mode).toBeEnabled();
    if (await mode.getAttribute("aria-checked") === "true") await mode.click();
    await expect(mode).toHaveAttribute("aria-checked", "false");
    const slider = page.getByRole("slider", { name: "Selected source time" });
    await expect(slider).toBeEnabled();
    await slider.evaluate(element => {
      if (!(element instanceof HTMLInputElement)) throw new Error("Expected source-time input");
      element.value = "120"; element.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", selected.task_id);
    for (const role of ["sensor_quality", "event_diagnosis"]) {
      const task = frame.detail.children.find(child => child.role === role)!;
      expect(task.state).toMatch(/^(SUCCEEDED|ABSTAINED)$/);
      expect(task.result!.summary.trim()).not.toBe("");
      await page.locator(`#agent-output-tab-${role}`).click();
      const panel = page.locator("#automatic-progress .agent-output-panel:visible");
      await expect(panel.locator(".agent-specialist-findings")).toContainText(reportText(
        task.result!.summary, [...task.result!.claim_refs, ...task.result!.evidence_ids],
      ), { useInnerText: true });
      await expect(panel.getByRole("heading", { name: "Limits and handoff" })).toBeVisible();
      await expect(panel.getByText("Original technical handoff and source references", { exact: true })).toBeVisible();
      if (role === "sensor_quality") {
        await expect(panel).toContainText("did not arrive");
        await expect(panel).toContainText("arrived but could not be used");
        await expect(panel).not.toContainText("exact source window is not loaded");
      } else await expect(panel).toContainText("Response Coordinator");
    }
    await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("withheld report identifies reviewer stage and shows actionable corrections from saved events", async ({ page }) => {
  const root = agent("operator_response", "");
  root.state = "FAILED"; root.answer = null; root.result = null; root.error_code = "grounding_rejected";
  const children = [agent("sensor_quality", "Quality checked."), agent("event_diagnosis", "Diagnosis checked.")];
  const events: ConsoleEvent[] = [1, 2].map(round => ({
    id: round, site_id: root.site_id, generation_id: root.generation_id, task_id: root.id,
    snapshot_id: root.snapshot_id, simulated_seconds: 110, created_at: root.updated_at,
    type: "answer.critique", payload: {
      round, decision: "revise", issues: 1, checks: [{
        paragraph_id: "answer", verdict: "unsupported", reason: `Correction from round ${round}.`,
        support: [], corrections: [{
          excerpt: "Observation gaps", instruction: "Use the pinned-window counts; do not add overlapping periods.",
          source_references: ["read-evidence-fixture"],
        }],
      }],
    },
  }));
  const bundle = buildSync({
    stdin: { contents: 'export { renderAgentWork } from "./web/ts/agentwork";', resolveDir: process.cwd(), loader: "ts" },
    bundle: true, write: false, format: "iife", globalName: "FailedFixture",
  }).outputFiles[0].text;
  await page.setContent('<main><div id="progress"></div><div id="findings"></div></main>');
  await page.addStyleTag({ path: join(process.cwd(), "web", "styles.css") });
  await page.addScriptTag({ content: `${bundle}
    FailedFixture.renderAgentWork(document.getElementById("progress"), document.getElementById("findings"),
      ${JSON.stringify(root)}, ${JSON.stringify([root, ...children])}, null, null, null,
      id => window.openedFailedTask = id, ${JSON.stringify(events)});` });
  await expect(page.locator(".agent-failure-summary")).toHaveAttribute("data-stage", "grounding_reviewer");
  await expect(page.locator(".agent-failure-summary")).toContainText("Sensor Quality Agent: SUCCEEDED");
  await expect(page.locator(".agent-failure-summary")).toContainText("Round 1");
  await expect(page.locator(".agent-failure-summary")).toContainText("Round 2");
  await expect(page.locator(".agent-grounding-review")).toHaveAttribute("open");
  await expect(page.locator(".agent-grounding-review")).toContainText("Use the pinned-window counts");
  await expect(page.locator(".agent-grounding-review")).toContainText("read-evidence-fixture");
  await expect(page.locator(".agent-grounding-review")).not.toContainText("No detailed grounding review");
  await expect(page.locator(".agent-role-updates, .agent-public-journal")).toHaveCount(0);
  await page.getByRole("button", { name: "Open failed coordinator receipts and trace" }).click();
  expect(await page.evaluate(() => (window as typeof window & { openedFailedTask: string }).openedFailedTask)).toBe(root.id);
});

test("agent outputs use one wide reader with keyboard selection and preserved selection on updates", async ({ page }) => {
  const tasks = [
    agent("sensor_quality", "Quality finding\n\nSensor A has missing readings; no pressure value is inferred."),
    agent("event_diagnosis", "Diagnosis finding\n\nPaired sensors show a sustained pressure loss. ".repeat(15)),
    agent("operator_response", "Leak assessment\nLeak pattern detected on P5.\n\nWhy this location\nCentral paired deficits exceed neighboring stations [ev-227]."),
  ];
  const events: ConsoleEvent[] = [{
    id: 1, site_id: "fixture", generation_id: "fixture", type: "agent.check_completed",
    created_at: "2026-01-01T00:00:30Z", simulated_seconds: 120, snapshot_id: "fixture",
    task_id: "event_diagnosis", payload: { role: "event_diagnosis", title: "Compare paired pressures",
      status: "completed", observation: "Both central pairs fell together.", purpose: "Distinguish a shared pressure loss from one bad reading." },
  }];
  const bundle = buildSync({
    stdin: { contents: 'export { renderAgentWork } from "./web/ts/agentwork";', resolveDir: process.cwd(), loader: "ts" },
    bundle: true, write: false, format: "iife", globalName: "AgentFixture",
  }).outputFiles[0].text;
  await page.setContent('<main><div id="progress" class="agent-roles"></div><div id="findings" class="agent-findings"></div></main>');
  await page.addStyleTag({ path: join(process.cwd(), "web", "styles.css") });
  await page.addScriptTag({ content: `${bundle}
    window.fixtureTasks = ${JSON.stringify(tasks)};
    window.fixtureEvents = ${JSON.stringify(events)};
    window.renderFixture = () => AgentFixture.renderAgentWork(
      document.getElementById("progress"), document.getElementById("findings"),
      window.fixtureTasks[2], window.fixtureTasks, null, null, null,
      id => window.openedFixtureTask = id, window.fixtureEvents);
    window.renderFixture();` });
  const reader = page.locator(".agent-output-panel:visible");
  await expect(page.getByRole("tablist", { name: "Choose an agent output" }).getByRole("tab")).toHaveCount(4);
  await expect(page.getByRole("tab", { name: "Grounding Reviewer output" })).toHaveCount(0);
  await expect(page.locator(".agent-selector")).not.toContainText("Read output");
  await expect(page.locator(".agent-selector")).not.toContainText("LLM presentation step");
  const cards = await page.locator(".agent-selector .agent-role").evaluateAll(elements =>
    elements.map(element => {
      const bounds = element.getBoundingClientRect();
      return { top: bounds.top, height: bounds.height };
    }));
  expect(new Set(cards.map(card => card.top)).size).toBe(1);
  expect(Math.max(...cards.map(card => card.height))).toBeLessThan(120);
  await expect(reader).toHaveCount(1);
  await expect(reader.locator(":scope > h3")).toHaveText("Response Coordinator");
  await expect(reader.getByRole("heading", { name: "Why this location" })).toBeVisible();
  await expect(reader).not.toContainText("ev-227");
  await expect(page.locator(".agent-journal, .agent-evidence, .agent-technical")).toHaveCount(0);
  await expect(page.locator("#findings")).toBeEmpty();
  await expect(page.locator("#findings")).toBeHidden();

  await page.getByRole("tab", { name: "Event Diagnosis Agent output" }).click();
  await expect(reader.locator(":scope > h3")).toHaveText("Event Diagnosis Agent");
  const output = reader.locator(".agent-handoff-output");
  expect((await output.boundingBox())!.width).toBeGreaterThan(600);
  expect(await output.evaluate(item => getComputedStyle(item).maxHeight)).toBe("none");
  await expect(reader).toContainText("Paired sensors show a sustained pressure loss.");
  await expect(page.locator(".agent-role-updates, .agent-public-journal")).toHaveCount(0);
  await expect(reader).not.toContainText("Both central pairs fell together.");
  await reader.getByRole("button", { name: "Open executed receipts" }).click();
  expect(await page.evaluate(() => (window as typeof window & { openedFixtureTask: string }).openedFixtureTask)).toBe("event_diagnosis");
  await page.evaluate(() => {
    const fixture = window as typeof window & { fixtureTasks: AgentTask[]; renderFixture: () => void };
    fixture.fixtureTasks[0].updated_at = "2026-01-01T00:02:00Z";
    fixture.renderFixture();
  });
  await expect(page.getByRole("tab", { name: "Event Diagnosis Agent output" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".agent-role-updates, .agent-public-journal")).toHaveCount(0);
  await expect(page.locator(".agent-journal, .agent-evidence, .agent-technical")).toHaveCount(0);
  await page.getByRole("tab", { name: "Event Diagnosis Agent output" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Response Coordinator output" })).toBeFocused();
  await expect(reader.locator(":scope > h3")).toHaveText("Response Coordinator");
  await page.keyboard.press("End");
  await expect(reader.locator(":scope > h3")).toHaveText("Report-to-map Mapper");
  await expect(reader).toContainText("no new diagnosis");
  await page.keyboard.press("ArrowLeft");
  await expect(reader.locator(":scope > h3")).toHaveText("Response Coordinator");
  await expect(page.locator('.agent-role[data-role="operator_response"] .agent-review-status')).toHaveText("Review: Not started");
  await expect(reader.locator(".agent-grounding-review")).not.toHaveAttribute("open");
  await reader.locator(".agent-grounding-review > summary").click();
  await expect(reader).toContainText("No detailed grounding review");
  await page.evaluate(() => {
    const fixture = window as typeof window & { fixtureEvents: ConsoleEvent[]; renderFixture: () => void };
    fixture.fixtureEvents.push({
      id: 2, site_id: "fixture", generation_id: "fixture", type: "answer.critique",
      created_at: "2026-01-01T00:02:30Z", simulated_seconds: 120, snapshot_id: "fixture",
      task_id: "operator_response", payload: { decision: "revise", issues: 1 },
    });
    fixture.renderFixture();
  });
  await expect(page.locator('.agent-role[data-role="operator_response"] .agent-review-status')).toHaveText("Review: Changes requested");
  await expect(reader.locator(".agent-grounding-review")).toHaveAttribute("open");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "Sensor Quality Agent output" }).click();
  await expect(reader).toContainText("Sensor A has missing readings");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("report mapper shows acceptance dependency, saved quoted labels and failure without inventing activity", async ({ page }) => {
  const root = agent("operator_response", "Suspected leak on P5; inspect 200–600 m. Sensor A has an offset.");
  root.result!.interpretation = {
    focus: "Incident", answer: { text: root.answer!, references: [] },
    competing_causes: [], follow_up_questions: [],
  };
  const detail: TaskDetail = {
    task: root, children: [], receipts: [], investigation_receipts: [], casefile: null,
    output_mapping: null,
  };
  const bundle = buildSync({
    stdin: { contents: 'export { renderAgentWork, renderIdleAgentWork } from "./web/ts/agentwork";', resolveDir: process.cwd(), loader: "ts" },
    bundle: true, write: false, format: "iife", globalName: "AgentFixture",
  }).outputFiles[0].text;
  await page.setContent('<main><div id="progress" class="agent-roles"></div><div id="findings"></div></main>');
  await page.addStyleTag({ path: join(process.cwd(), "web", "styles.css") });
  await page.addScriptTag({ content: `${bundle}
    window.mapperRoot = ${JSON.stringify(root)};
    window.mapperDetail = ${JSON.stringify(detail)};
    window.renderMapper = () => AgentFixture.renderAgentWork(
      document.getElementById("progress"), document.getElementById("findings"),
      window.mapperRoot, [window.mapperRoot], window.mapperDetail, null, null, () => {}, []);
    AgentFixture.renderIdleAgentWork(document.getElementById("progress"), document.getElementById("findings"), true);` });
  const status = page.locator('.agent-role[data-role="report_mapper"] .agent-tab-status');
  const reader = page.locator(".agent-output-panel:visible");
  await page.locator("#progress").evaluate(element => { element.style.maxWidth = "640px"; });
  const positions = await page.locator(".agent-selector .agent-role").evaluateAll(elements =>
    elements.map(element => {
      const bounds = element.getBoundingClientRect();
      return { top: bounds.top, height: bounds.height };
    }));
  expect(new Set(positions.map(position => position.top)).size).toBe(1);
  expect(Math.max(...positions.map(position => position.height))).toBeLessThan(130);
  await page.locator(".agent-selector").screenshot({ path: test.info().outputPath("compact-agent-selector.png") });
  await expect(status).toHaveText("Waiting for accepted report");
  await expect(reader.locator(".agent-output-empty")).not.toContainText("interim messages appear below");
  await page.getByRole("tab", { name: "Report-to-map Mapper output" }).click();
  await expect(reader).toContainText("Provisional drafts do not populate the agent map");
  await page.evaluate(() => {
    const fixture = window as typeof window & { mapperRoot: AgentTask; renderMapper: () => void };
    fixture.mapperRoot.state = "RUNNING"; fixture.renderMapper();
  });
  await expect(status).toHaveText("Waiting for accepted report");
  await page.evaluate(() => {
    const fixture = window as typeof window & { mapperRoot: AgentTask; renderMapper: () => void };
    fixture.mapperRoot.state = "SUCCEEDED"; fixture.renderMapper();
  });
  await expect(status).toHaveText("Not available yet");
  await page.getByRole("tab", { name: "Report-to-map Mapper output" }).click();
  await expect(reader).toContainText("does not establish that a model call is running");
  await page.evaluate(() => {
    const fixture = window as typeof window & { mapperDetail: TaskDetail; renderMapper: () => void };
    fixture.mapperDetail.output_mapping = {
      status: "completed", mapping: {
        leaks: [{ segment_id: "P5", assertion: "suspected", interval: { start_m: 200, end_m: 600 },
          quote: { path: "answer.text", text: "Suspected leak on P5; inspect 200–600 m." } }],
        sensor_issues: [{ sensor_id: "A", kind: "offset", assertion: "suspected",
          quote: { path: "answer.text", text: "Sensor A has an offset." } }],
        instrumentation_concern: true,
      },
    };
    fixture.renderMapper();
  });
  await expect(status).toHaveText("Ready");
  await expect(reader).toContainText("1 leak branch finding(s) · 1 report-stated inspection interval(s) · 1 instrument issue label(s)");
  await reader.getByText("Saved map labels and exact report quotations", { exact: true }).click();
  await expect(reader.locator(".agent-mapping-findings")).toContainText("P5: suspected leak · inspect 200–600 m");
  await expect(reader.locator(".agent-mapping-findings")).toContainText("Sensor A has an offset.");
  await page.evaluate(() => {
    const fixture = window as typeof window & { mapperRoot: AgentTask; renderMapper: () => void };
    fixture.mapperRoot.updated_at = "2026-01-01T00:02:00Z"; fixture.renderMapper();
  });
  await expect(reader.locator('[data-section="mapper:quotes"]')).toHaveAttribute("open");
  await page.evaluate(() => {
    const fixture = window as typeof window & { mapperDetail: TaskDetail; renderMapper: () => void };
    fixture.mapperDetail.output_mapping = { status: "failed", mapping: null, error_code: "extraction_quote_mismatch" };
    fixture.renderMapper();
  });
  await expect(status).toHaveText("Failed");
  await expect(reader).toContainText("extraction_quote_mismatch");
  await expect(reader).toContainText("accepted report remains available");
  await expect(reader.locator(".agent-mapping-findings")).toHaveCount(0);
  await page.evaluate(() => {
    const fixture = window as typeof window & { mapperRoot: AgentTask; renderMapper: () => void };
    fixture.mapperRoot.state = "FAILED"; fixture.renderMapper();
  });
  await expect(status).toHaveText("Not run");
});

test("Live freshness only warns about outdated analysis or a pending warning", async ({ page }) => {
  const taskId = process.env.SUBSEA_REPORT_UI_TASK_ID;
  test.skip(!taskId || !process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit recorded-agent opt-in.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const detail: TaskDetail = await (await page.request.get(`/api/tasks/${taskId}`)).json();
  const projection: Projection = await (await page.request.get(`/api/replays/${detail.task.generation_id}/projection`)).json();
  const basis = await (await page.request.get(`/api/windows/${detail.task.snapshot_id}`)).json();
  const incident = projection.episodes.find(episode => episode.id === detail.task.episode_id);
  expect(incident).toBeDefined();
  let state: "current" | "historical" | "missing" | "pending" | "idle" = "current";
  await page.route(`**/api/replays/${detail.task.generation_id}/recordings`, route =>
    route.fulfill({ json: { recordings: [] } }));
  await page.route(`**/api/replays/${detail.task.generation_id}/events?*`, route =>
    route.fulfill({ contentType: "text/event-stream", body: ": fixture\n\n" }));
  await page.route(`**/api/replays/${detail.task.generation_id}/projection`, route =>
    route.fulfill({ json: {
      ...projection,
      replay: { ...projection.replay, latest_window_id: basis.id, investigation_window_id: null },
      latest_window: state === "missing" ? null : basis,
      tasks: state === "idle" ? [] : [
        { ...detail.task, automatic: true, snapshot_id: state === "historical" ? "historical-snapshot" : basis.id },
        ...detail.children,
      ],
      episodes: state === "pending"
        ? [{ ...incident, pending_window_id: basis.id, dispatch_status: "agent_unavailable" }]
        : [],
    } }));
  const writes: string[] = [], errors: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(detail.task.generation_id) + "&view=live");
  await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", taskId!);
  await expect(page.locator("#automatic-freshness")).toHaveCount(0);
  await expect(page.locator("#automatic-actions button")).toHaveCount(0);
  state = "historical";
  await page.locator("#reconnect").click();
  await expect(page.locator("#automatic-freshness")).toContainText("Historical analysis");
  state = "current";
  await page.locator("#reconnect").click();
  await expect(page.locator("#automatic-freshness")).toHaveCount(0);
  state = "missing";
  await page.locator("#reconnect").click();
  await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", taskId!);
  await expect(page.locator("#automatic-freshness")).toHaveCount(0);
  state = "pending";
  await page.locator("#reconnect").click();
  await expect(page.locator("#automatic-freshness")).toContainText("New material warning is pending: agent unavailable");
  await expect(page.locator("#automatic-freshness")).not.toContainText("Historical analysis");
  state = "idle";
  await page.locator("#reconnect").click();
  await expect(page.locator("#automatic-state")).not.toHaveAttribute("data-task");
  await expect(page.locator("#automatic-actions")).toBeEmpty();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("a real recorded agent workspace exposes each output without new inference", async ({ page }) => {
  const taskId = process.env.SUBSEA_REPORT_UI_TASK_ID;
  test.skip(!taskId || !process.env.SUBSEA_OPERATOR_PASSWORD, "Explicit recorded-agent opt-in.");
  const login = await page.request.post("/api/login", {
    data: { username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD },
  });
  expect(login.status()).toBe(200);
  const response = await page.request.get(`/api/tasks/${taskId}/casefile`);
  expect(response.status()).toBe(200);
  const file = await response.json();
  await page.route(`**/api/replays/${file.generation_id}/recordings`, route =>
    route.fulfill({ json: { recordings: [] } }));
  const inference: string[] = [];
  page.on("request", request => {
    if (request.method() === "POST" && request.url().endsWith("/questions")) inference.push(request.url());
  });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(file.generation_id) + "&view=live");
  await expect(page.locator("#automatic-progress .agent-selector")).toBeVisible();
  await expect(page.locator("#agent-findings .agent-evidence, #agent-findings .agent-journal, #agent-findings .agent-technical")).toHaveCount(0);
  await expect(page.locator("#automatic-progress .agent-role-updates, #automatic-progress .agent-public-journal")).toHaveCount(0);
  await expect(page.locator("#automatic-actions button")).toHaveCount(0);
  await expect(page.locator("#investigation-technical")).not.toHaveAttribute("open");
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Response Coordinator output", exact: true }).click();
  await page.locator("#automatic-progress .agent-output-panel:visible").getByRole("button", { name: "Open executed receipts" }).click();
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#investigation-technical")).toHaveAttribute("open");
  await expect(page.locator("#execution-details")).toBeVisible();
  await expect(page.locator("#investigation-case")).toHaveAttribute("data-task", taskId!);
  await expect(page.locator("#question-tools, .case-followups")).toHaveCount(0);
  const tabs = page.locator("#automatic-progress").getByRole("tab");
  await expect(tabs).toHaveCount(4);
  for (const label of ["Sensor Quality Agent", "Event Diagnosis Agent", "Response Coordinator", "Report-to-map Mapper"]) {
    await page.getByRole("tab", { name: `${label} output`, exact: true }).click();
    const panel = page.locator("#automatic-progress .agent-output-panel:visible");
    await expect(panel).toHaveCount(1);
    await expect(panel.locator(":scope > h3")).toHaveText(label);
    await expect(panel.locator(":scope > .agent-handoff-output")).toBeVisible();
  }
  await page.getByRole("tab", { name: "Response Coordinator output", exact: true }).click();
  await expect(page.locator("#automatic-progress .agent-output-panel:visible")).toContainText(file.interpretation.answer.text.split("\n")[0]);
  await expect(page.locator(".agent-conclusion-label")).toHaveCount(0);
  await expect(page.locator("#automatic-conclusion")).toBeHidden();
  await expect(page.locator("#automatic-conclusion")).toBeEmpty();
  await page.locator("#automatic-progress").screenshot({ path: "runtime\\agent-output-workspace.png" });
  expect(inference).toEqual([]);
});
