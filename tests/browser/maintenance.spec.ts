import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import { join } from "node:path";
import type { MaintenanceCatalog, MaintenanceRecord } from "../../web/ts/maintenance";
import type { ReplaySession } from "../../web/ts/types";

const approved: MaintenanceRecord = {
  id: "MAINT-002", title: "Gateway calibration <not markup>", type: "maintenance",
  asset_ids: ["P7", "gateway-P7-0"], authored_at: "2026-01-01T00:01:15Z",
  available_at: "2026-01-01T00:01:20Z", effective_from: "2026-01-01T00:01:20Z",
  effective_to: null, revision: 2, supersedes: "MAINT-001", status: "approved",
  body: "Fictional maintenance source. <img src=x onerror=alert(1)> No hardware failure is confirmed.",
  admissible: true, exclusion_reason: null,
};
const catalog: MaintenanceCatalog = {
  generation_id: "fixture", site_id: "northsea", pack_version: "fixture", source_seconds: 120,
  as_of: "2026-01-01T00:02:00Z", corpus_version: "fixture-corpus",
  records: [approved, { ...approved, id: "MAINT-001", revision: 1, supersedes: null,
    status: "superseded", admissible: false, exclusion_reason: "Superseded revision." }],
  knowledge: {
    version: "knowledge-fixture", selected_at: "2026-11-10T00:00:00Z", authority: "advisory_only",
    excluded: { "KN-DRAFT": "not_curated" },
    cards: [{
      id: "KN-PROCEDURE", title: "Test competing pressure explanations", kind: "procedure", status: "curated",
      applies_when: "Several pressure observers change.", guidance: "Compare actual measurements; do not infer a leak from one flag.",
      verification_steps: ["Check usable coverage.", "Compare synchronized independent observers."],
      counterexamples: ["An operating change may coexist with a leak."],
      limitations: ["Not a field-approved procedure."], review_basis: "Research-derived guidance.",
      sources: [{ reference: "Fixture source", locator: "Section 1", boundary: "Not a site validation." }],
    }],
  },
};
const bundle = () => buildSync({
  stdin: { contents: 'export { MaintenancePanel } from "./web/ts/maintenance";', resolveDir: process.cwd(), loader: "ts" },
  bundle: true, write: false, format: "iife", globalName: "MaintenanceFixture",
}).outputFiles[0].text;

test("maintenance cards preserve original bodies and distinguish approval from execution and supersession", async ({ page }) => {
  await page.setContent('<main><div id="records"></div></main>');
  await page.addStyleTag({ path: join(process.cwd(), "web", "styles.css") });
  await page.addScriptTag({ content: `${bundle()}
    window.panel = new MaintenanceFixture.MaintenancePanel(
      document.getElementById("records"), () => Promise.resolve(${JSON.stringify(catalog)}));
    window.panel.load("fixture", 120);` });
  const record = page.locator('[data-document="MAINT-002"]');
  await expect(record).toHaveAttribute("data-admissible", "true");
  await expect(record.locator("pre")).toHaveText(approved.body);
  await expect(record.locator("h3")).toHaveText(approved.title);
  await expect(record.locator("img")).toHaveCount(0);
  await expect(record).toContainText("does not prove that work was executed");
  await expect(record).toContainText("Replaces revision: MAINT-001");
  await expect(record.locator("details")).toHaveAttribute("open");
  await expect(page.locator('[data-document="MAINT-001"]')).toHaveAttribute("data-admissible", "false");
  await expect(page.locator('[data-document="MAINT-001"] details')).not.toHaveAttribute("open");
  await expect(page.locator("#records")).toContainText("not an inventory of documents read by an agent");
  const knowledge = page.locator('[aria-labelledby="pressure-knowledge-title"]');
  await expect(knowledge).toContainText("not incident evidence");
  await expect(knowledge).toContainText("wall clock");
  await expect(knowledge.locator('[data-knowledge="KN-PROCEDURE"] details')).toHaveAttribute("open");
  await expect(knowledge).toContainText("Compare synchronized independent observers.");
  await expect(knowledge).toContainText("An operating change may coexist with a leak.");
  await expect(knowledge).toContainText("Evidence boundary: Not a site validation.");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("maintenance navigation withholds stale responses and exposes failures without substituting old documents", async ({ page }) => {
  await page.setContent('<div id="records"></div>');
  await page.addScriptTag({ content: `${bundle()}
    window.oldCatalog = ${JSON.stringify(catalog)};
    window.panel = new MaintenanceFixture.MaintenancePanel(document.getElementById("records"), path =>
      path.includes("old") ? new Promise(resolve => window.finishOld = resolve)
      : path.includes("failed") ? Promise.reject(new Error("Service unavailable"))
      : Promise.resolve({ ...window.oldCatalog, generation_id: "new", records: [] }));
    window.panel.load("old", 120);
    window.panel.load("new", 120);` });
  await expect(page.locator("#records")).toContainText("No maintenance records are visible");
  await page.evaluate(() => {
    const fixture = window as typeof window & {
      finishOld: (value: MaintenanceCatalog) => void; oldCatalog: MaintenanceCatalog;
    };
    fixture.finishOld({ ...fixture.oldCatalog, generation_id: "old" });
  });
  await expect(page.locator("[data-document]")).toHaveCount(0);
  await page.addScriptTag({ content: 'window.panel.load("failed", 120);' });
  await expect(page.locator("#records")).toContainText("Maintenance unavailable: Service unavailable");
  await expect(page.locator("[data-document]")).toHaveCount(0);
  await page.addScriptTag({ content: 'window.panel.load("wrong-scope", 120);' });
  await expect(page.locator("#records")).toContainText("scope mismatch");
});

test("top-level Maintenance tab follows S7 source time and starts no inference", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned reference records.");
  const login = await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  expect(login.ok()).toBeTruthy();
  const { replays }: { replays: ReplaySession[] } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find(row => row.scenario === "S7" && row.seed === 2026 && row.workflow === "agent_assisted");
  expect(replay).toBeDefined();
  const writes: string[] = [], errors: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/?replay=" + encodeURIComponent(replay!.id) + "&tab=maintenance");
  await expect(page.locator("#tab-maintenance")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#panel-maintenance")).toBeVisible();
  await expect(page.locator("#evidence-selection")).toBeHidden();
  await page.locator("#tab-maintenance").focus();
  await page.keyboard.press("Home");
  await expect(page.locator("#tab-live")).toBeFocused();
  const mode = page.getByRole("switch", { name: /switch to/ });
  await expect(mode).toBeEnabled();
  if (await mode.getAttribute("aria-checked") === "true") await mode.click();
  const slider = page.getByRole("slider", { name: "Selected source time" });
  for (const seconds of [79, 80]) {
    await page.locator("#tab-live").click();
    await slider.evaluate((element, value) => {
      if (!(element instanceof HTMLInputElement)) throw new Error("Expected source-time input");
      element.value = String(value); element.dispatchEvent(new Event("input", { bubbles: true }));
    }, seconds);
    await page.locator("#tab-maintenance").click();
    await expect(page.locator("#maintenance-records [data-source-seconds]")).toHaveAttribute("data-source-seconds", String(seconds));
    await expect(page.locator('#maintenance-records [data-document="MAINT-P7-GW-002"]')).toHaveCount(seconds < 80 ? 0 : 1);
    await expect(page.locator('#maintenance-records [data-document="MAINT-P7-GW-001"]')).toHaveAttribute("data-admissible", "false");
  }
  const response = await page.request.get(`/api/replays/${replay!.id}/maintenance?source_seconds=80`);
  expect(response.ok()).toBeTruthy();
  const source: MaintenanceCatalog = await response.json();
  const original = source.records.find(record => record.id === "MAINT-P7-GW-002")!;
  await expect(page.locator('[data-document="MAINT-P7-GW-002"] pre')).toHaveText(original.body);
  await expect(page.locator('[data-document="MAINT-P7-GW-002"]')).toHaveAttribute("data-admissible", "true");
  await expect(page.getByRole("heading", { name: "Pressure Investigation Knowledge", exact: true })).toBeVisible();
  await expect(page.locator("[data-knowledge]")).toHaveCount(5);
  const program = page.locator('[data-knowledge="KN-INVESTIGATION-PROGRAM-R1"]');
  await expect(program.locator("details")).toHaveAttribute("open");
  await expect(program).toContainText("Quality: establish what was measured reliably");
  await expect(program).toContainText("Critic: check case facts and knowledge citations");
  await page.locator("#tab-maintenance").focus();
  await page.keyboard.press("End");
  await expect(page.locator("#tab-evaluation")).toBeFocused();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
