import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import type { AgentTask, ExecutionUsage, Projection, TaskDetail } from "../../web/ts/types";

test("API estimate uses standard billing without a range or cache pricing without a live provider", async ({ page }) => {
  await page.setContent(`<section id="execution-summary">
    <span id="execution-elapsed"></span><span id="execution-tokens"></span>
    <span id="execution-token-detail"></span><span id="execution-cost"></span>
    <span id="execution-cost-reason"></span><span id="execution-cost-detail"></span>
    <div id="execution-pricing"></div></section>`);
  const usage: ExecutionUsage = {
    input_tokens: 1000, output_tokens: 100, total_tokens: 1100,
    cache_read_tokens: 200, cache_write_tokens: 300, reserved_calls: 2,
    completed_calls: 1, reported_calls: 1, cache_reported_calls: 1, priced_calls: 1,
    models: ["gpt-6.1-sol"], cost_usd: 0.003, cost_min_usd: 0.003, cost_max_usd: 0.003,
    pricing_url: "https://developers.openai.com/api/docs/pricing", pricing_date: "2026-11-08",
    pricing_basis: "OpenAI API equivalent", pricing_assumptions: "All input uses standard input rates.",
    rates_per_million: { "gpt-6.1-sol": { short: [2, 10], long: [4, 15] } },
  };
  const render = async (value: ExecutionUsage | null): Promise<void> => {
    const bundle = buildSync({
      stdin: {
        contents: `import { ExecutionMetrics } from "./web/ts/execution_metrics";
          new ExecutionMetrics().set({
            state: "SUCCEEDED", created_at: "2026-11-08T00:00:00Z", updated_at: "2026-11-08T00:00:10Z"
          }, ${JSON.stringify(value)}, true, "2026-11-08T00:00:10Z");`,
        resolveDir: process.cwd(),
      },
      bundle: true, write: false, format: "iife",
    });
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
  };
  await render(usage);
  await expect(page.locator("#execution-cost")).toHaveText("$0.0030");
  await expect(page.locator("#execution-cost-reason")).toHaveText(
    "Standard input and output rates; all input billed at the input rate.",
  );
  await expect(page.locator("#execution-cost-detail")).toHaveText(
    "Based on 1 of 2 model calls; unpriced calls are excluded. Not a Copilot charge.",
  );
  await expect(page.locator("#execution-summary")).not.toContainText(/cache|retention|Lower:|Upper:/i);
  await expect(page.getByRole("row", { name: "Input $2 $4", exact: true })).toBeVisible();
  await expect(page.getByRole("row", { name: "Output (includes reasoning) $10 $15", exact: true })).toBeVisible();

  await render({ ...usage, cost_max_usd: usage.cost_min_usd, cache_write_tokens: 0, reserved_calls: 1 });
  await expect(page.locator("#execution-cost")).toHaveText("$0.0030");
  await expect(page.locator("#execution-cost-detail")).toHaveText("Based on 1 of 1 model calls. Not a Copilot charge.");

  await render({ ...usage, cost_usd: null, cost_min_usd: null, cost_max_usd: null, priced_calls: 0 });
  await expect(page.locator("#execution-cost")).toHaveText("Cost not yet available");
  await expect(page.locator("#execution-cost-detail")).toContainText("Based on 0 of 2 model calls; unpriced calls are excluded");
  await render({ ...usage, cost_usd: undefined, cost_min_usd: 0.00277, cost_max_usd: 0.00352 });
  await expect(page.locator("#execution-cost")).toHaveText("Cost not yet available");
  await render({ ...usage, cost_usd: undefined, cost_min_usd: 0.002, cost_max_usd: 0.002 });
  await expect(page.locator("#execution-cost")).toHaveText("Cost not yet available");
  await render(null);
  await expect(page.locator("#execution-pricing")).toBeEmpty();
});

test("live elapsed clock advances while usage is partial and freezes after completion", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; last_endpoint: number }) => row.scenario === "S7" && row.last_endpoint >= 60);
  const original: Projection = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
  const snapshot = original.latest_window!;
  expect(snapshot).not.toBeNull();
  const now = Date.now();
  let completed = false, reported = true;
  const root = (): AgentTask => ({
    id: "runtime-fixture", root_id: "runtime-fixture", site_id: original.replay.site_id,
    generation_id: replay.id, snapshot_id: snapshot.id, episode_id: null, parent_id: null,
    role: "operator_response", purpose: "answer_question", question: "Review pressure",
    mode: "live", state: completed ? "FAILED" : "RUNNING",
    created_at: new Date(now - 10000).toISOString(), updated_at: new Date(now).toISOString(),
    model_calls: 2, tool_calls: 0, plan: [], result: null, answer: null,
    error_code: completed ? "fixture_only" : null, error_message: null, automatic: true,
  });
  const usage = (): ExecutionUsage => ({
    input_tokens: 1000, output_tokens: 100, total_tokens: 1100,
    cache_read_tokens: 200, cache_write_tokens: 300, reserved_calls: 2,
    completed_calls: 1, reported_calls: reported ? 1 : 0, cache_reported_calls: 1, priced_calls: reported ? 1 : 0,
    models: ["gpt-6.1-sol"], cost_usd: reported ? 0.003 : null, cost_min_usd: reported ? 0.003 : null, cost_max_usd: reported ? 0.003 : null,
    pricing_url: "https://developers.openai.com/api/docs/pricing", pricing_date: "2026-11-08",
    pricing_basis: "OpenAI API equivalent", pricing_assumptions: "All input uses standard input rates.",
    rates_per_million: { "gpt-6.1-sol": { short: [2, 10], long: [4, 15] } },
  });
  await page.route(`**/api/replays/${replay.id}/recordings`, route => route.fulfill({ json: { recordings: [] } }));
  await page.route(`**/api/replays/${replay.id}/projection`, route => route.fulfill({ json: {
    ...original, tasks: [root()], episodes: [], server_time: new Date(now).toISOString(),
    replay: { ...original.replay, state: "PAUSED", investigation_window_id: snapshot.id },
  } }));
  await page.route("**/api/tasks/runtime-fixture/trace", route => route.fulfill({ json: {} }));
  await page.route("**/api/tasks/runtime-fixture", route => {
    const detail: TaskDetail = {
      task: root(), children: [], casefile: null, receipts: [], investigation_receipts: [],
      execution_usage: usage(),
    };
    return route.fulfill({ json: detail });
  });
  await page.clock.install({ time: now });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(replay.id) + "&view=live");
  await expect(page.locator("#execution-elapsed")).toContainText("Running");
  await expect(page.locator("#execution-tokens")).toHaveText("1,100 tokens");
  await expect(page.locator("#execution-token-detail")).toContainText("1/2 calls reported");
  await expect(page.locator("#execution-cost")).toHaveText("$0.0030");
  await expect(page.locator("#execution-cost-detail")).toContainText("Not a Copilot charge");
  const before = await page.locator("#execution-elapsed").textContent();
  await page.clock.fastForward(4000);
  await expect(page.locator("#execution-elapsed")).not.toHaveText(before!);
  await page.locator("#execution-summary > details > summary").click();
  await expect(page.locator("#execution-pricing")).toContainText("Estimate = input tokens");

  completed = true; reported = false;
  await page.reload();
  await expect(page.locator("#execution-elapsed")).toHaveText("FAILED · 00:10");
  await expect(page.locator("#execution-cost")).toHaveText("Cost not yet available");
  await expect(page.locator("#execution-summary")).not.toHaveClass(/execution-running/);
  await page.clock.fastForward(4000);
  await expect(page.locator("#execution-elapsed")).toHaveText("FAILED · 00:10");
});

test("preserved S7 reports show original usage and frozen duration without new calls", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; seed: number }) => row.scenario === "S7" && row.seed === 2026);
  const { recordings } = await (await page.request.get(`/api/replays/${replay.id}/recordings`)).json();
  const saved = recordings.filter((row: { state: string; source_seconds: number }) =>
    row.state === "SUCCEEDED" && row.source_seconds === 100).at(-1);
  expect(saved).toBeDefined();
  const frame = await (await page.request.get(`/api/replays/${replay.id}/recordings/${saved.task_id}`)).json();
  expect(frame.detail.execution_usage.reported_calls).toBeGreaterThan(0);
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await page.goto("/");
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  await expect(page.locator("#play")).toBeEnabled({ timeout: 30000 });
  await page.locator("#investigation-time").evaluate(element => {
    const slider = element as HTMLInputElement;
    slider.value = "100"; slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.locator("#tab-live").click();
  await expect(page.locator("#execution-elapsed")).toContainText("Recorded duration");
  await expect(page.locator("#execution-tokens")).toHaveText(`${frame.detail.execution_usage.total_tokens.toLocaleString()} tokens`);
  const duration = await page.locator("#execution-elapsed").textContent();
  await page.locator("#step").click();
  await expect(page.locator("#execution-elapsed")).toHaveText(duration!);
  expect(writes).toEqual([]);
});
