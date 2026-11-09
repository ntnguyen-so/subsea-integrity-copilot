/**
 * Offline deck/figure contract: source-pack geometry and identities, interview clock/
 * navigation, readable responsive layout and one-slide-per-print-page containment.
 * Opens local presentation assets, not the console or a hosted inference session.
 */
import { test, expect } from "@playwright/test";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";

const deck = pathToFileURL(path.join(process.cwd(), "docs", "INTERVIEW_DECK.html")).href;

test("topology depicts the source pack's connectivity, station distribution and sensor identities", async ({ page }) => {
  const pack: {
    segments: { id: string; length_m: number; diameter_m: number; points: { x: number; y: number }[] }[];
    sensors: {
      id: string; station_id: string; segment_id: string; chainage_m: number;
      failure_domain_id: string; position: { x: number; y: number };
    }[];
  } = JSON.parse(readFileSync(path.join(process.cwd(), "packs", "northsea.json"), "utf8"));
  await page.goto(pathToFileURL(path.join(process.cwd(), "docs", "assets", "pipeline-topology.svg")).href);
  const segments = await page.locator("g[data-length-m]").evaluateAll(nodes => nodes.map(node => ({
    id: node.getAttribute("data-segment-id"),
    length: Number(node.getAttribute("data-length-m")),
    sourceStart: [Number(node.getAttribute("data-start-x")), Number(node.getAttribute("data-start-y"))],
    sourceEnd: [Number(node.getAttribute("data-end-x")), Number(node.getAttribute("data-end-y"))],
    line: node.querySelector("path")!.getAttribute("d")!.match(/-?\d+(?:\.\d+)?/g)!.map(Number),
  })));
  const sensors = await page.locator("circle[data-sensor-id]").evaluateAll(nodes => nodes.map(node => ({
    id: node.getAttribute("data-sensor-id"),
    station: node.getAttribute("data-station-id"),
    segment: node.getAttribute("data-segment-id"),
    chainage: Number(node.getAttribute("data-chainage-m")),
    failureDomain: node.getAttribute("data-failure-domain"),
    sourceX: Number(node.getAttribute("data-source-x")),
    sourceY: Number(node.getAttribute("data-source-y")),
    x: Number(node.getAttribute("cx")), y: Number(node.getAttribute("cy")),
    radius: Number(node.getAttribute("r")), stroke: Number(node.getAttribute("stroke-width")),
  })));
  expect(sensors).toHaveLength(pack.sensors.length);
  for (let i = 0; i < sensors.length; i++) {
    for (let j = i + 1; j < sensors.length; j++) {
      const first = sensors[i], second = sensors[j];
      expect(Math.hypot(first.x - second.x, first.y - second.y),
        `${first.id} and ${second.id} remain individually visible`)
        .toBeGreaterThanOrEqual(first.radius + second.radius + (first.stroke + second.stroke) / 2);
    }
  }
  for (const source of pack.segments) {
    const drawn = segments.find(segment => segment.id === source.id)!;
    expect(drawn.length).toBe(source.length_m);
    expect(drawn.sourceStart).toEqual([source.points[0].x, source.points[0].y]);
    expect(drawn.sourceEnd).toEqual([source.points[1].x, source.points[1].y]);
  }
  const trunk = segments.find(segment => segment.id === "P1")!;
  for (const id of ["P2", "P3"]) {
    expect(segments.find(segment => segment.id === id)!.line.slice(0, 2)).toEqual(trunk.line.slice(2));
  }
  for (const source of pack.sensors) {
    const drawn = sensors.find(sensor => sensor.id === source.id)!;
    expect(drawn).toMatchObject({
      station: source.station_id, segment: source.segment_id,
      chainage: source.chainage_m, failureDomain: source.failure_domain_id,
      sourceX: source.position.x, sourceY: source.position.y,
    });
    const segment = segments.find(segment => segment.id === source.segment_id)!;
    const [x0, y0, x1, y1] = segment.line;
    const dx = x1 - x0, dy = y1 - y0;
    const fraction = ((drawn.x - x0) * dx + (drawn.y - y0) * dy) / (dx * dx + dy * dy);
    expect(fraction).toBeCloseTo(source.chainage_m / segment.length, 4);
    const physical = pack.segments.find(item => item.id === source.segment_id)!;
    const sx = physical.points[1].x - physical.points[0].x;
    const sy = physical.points[1].y - physical.points[0].y;
    const offset = Math.abs(sx * (source.position.y - physical.points[0].y) -
      sy * (source.position.x - physical.points[0].x)) / Math.hypot(sx, sy);
    expect(offset).toBeCloseTo(physical.diameter_m / 2);
  }
  const clippedLabels = await page.locator("svg text").evaluateAll(nodes => nodes.some(node => {
    if (!(node instanceof SVGGraphicsElement)) throw new Error("Expected an SVG text label");
    const svg = document.querySelector("svg");
    if (!(svg instanceof SVGSVGElement)) throw new Error("Expected an SVG diagram");
    const box = node.getBBox();
    return box.x < 0 || box.y < 0 || box.x + box.width > svg.viewBox.baseVal.width ||
      box.y + box.height > svg.viewBox.baseVal.height;
  }));
  expect(clippedLabels).toBe(false);
  const briefSource = readFileSync(path.join(process.cwd(), "docs", "ONE_PAGE_BRIEF.md"), "utf8");
  expect(briefSource).toContain("(assets/pressure-leak-vs-sensor-faults.svg)");
  await page.goto(pathToFileURL(path.join(process.cwd(), "docs", "assets", "pressure-leak-vs-sensor-faults.svg")).href);
  const evidence = JSON.parse(readFileSync(path.join(process.cwd(), "fixtures", "synthetic", "brief-evidence.json"), "utf8"));
  for (const scenario of ["S1", "S2"]) {
    const panel = page.locator(`[data-scenario="${scenario}"]`);
    await expect(panel.locator("circle[data-sensor-id]")).toHaveCount(pack.sensors.length);
    for (const sensor of pack.sensors) {
      await expect(panel.locator(`[data-sensor-id="${sensor.id}"]`)).toHaveAttribute("data-source-x", String(sensor.position.x));
    }
    for (const sensor of evidence.examples[scenario].snapshot.event.supporting_sensor_ids) {
      await expect(panel.locator(`[data-sensor-id="${sensor}"]`)).toHaveAttribute("fill", "#efb735");
    }
  }
  await page.goto(deck + "#demo-contract");
  await expect(page.locator(".topology img")).toBeVisible();
  expect(await page.locator(".topology img").evaluate(image =>
    image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0)).toBe(true);
});

test("deck follows the interview schedule and supports chapter, keyboard and notes navigation", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(deck);
  const budgets = await page.locator(".slide:not([data-chapter=appendix])").evaluateAll(slides =>
    slides.reduce<Record<string, number>>((totals, slide) => {
      const chapter = slide.getAttribute("data-chapter")!;
      totals[chapter] = (totals[chapter] || 0) + Number(slide.getAttribute("data-minutes"));
      return totals;
    }, {}));
  expect(budgets).toEqual({ problem: 5, demo: 10, technical: 30, business: 10, questions: 5 });
  await expect(page.locator(".slide")).toHaveCount(22);
  await expect(page.locator(".slide:visible")).toHaveCount(1);
  await expect(page.locator("#position")).toHaveText("1 / 18");
  await expect(page.locator("#previous")).toBeDisabled();
  await page.locator("h1:visible").click();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#risk")).toBeVisible();
  await page.keyboard.press("n");
  await expect(page.locator("#speaker-panel")).toBeVisible();
  await expect(page.locator("#notes-body")).toContainText("Do not invent vessel rates");
  await page.locator("[data-jump=architecture]").click();
  await expect(page.locator("#architecture")).toBeVisible();
  await expect(page.locator("[data-jump=architecture]")).toHaveAttribute("aria-current", "step");
  await expect(page.locator("#notes-body")).toContainText("two loops");
  await page.locator("#slide-select").selectOption("localization");
  await expect(page.locator("#localization")).toBeVisible();
  await page.locator("#notes-toggle").click();
  await expect(page.locator("#speaker-panel")).toBeHidden();
  await page.getByRole("button", { name: "Appendix", exact: true }).click();
  await expect(page.locator("#quality-appendix")).toBeVisible();
  await expect(page.locator("#position")).toHaveText("A1 / 4");
  await page.locator("h1:visible").click();
  await page.keyboard.press("End");
  await expect(page.locator("#questions")).toBeVisible();
  await page.goto(deck + "#not-a-slide");
  await expect(page.locator("#promise")).toBeVisible();
  await expect(page).toHaveURL(/#promise$/);
  expect(errors).toEqual([]);
});

test("interview clock survives navigation, pauses and resets without real waiting", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-01-01T00:00:00Z") });
  await page.clock.pauseAt(new Date("2026-01-01T00:00:01Z"));
  await page.goto(deck);
  await page.locator("#timer-toggle").click();
  await page.clock.runFor(2100);
  await expect(page.locator("#clock")).toHaveText("00:02 / 60:00");
  await page.locator("#slide-select").selectOption("pilot");
  await expect(page.locator("#clock")).toHaveText("00:02 / 60:00");
  await page.locator("#timer-toggle").click();
  await page.clock.runFor(2100);
  await expect(page.locator("#clock")).toHaveText("00:02 / 60:00");
  await page.locator("#timer-toggle").click();
  await page.clock.fastForward(3_600_000);
  await expect(page.locator("#clock")).toHaveClass(/over/);
  await page.locator("#timer-reset").click();
  await expect(page.locator("#clock")).toHaveText("00:00 / 60:00");
  await expect(page.locator("#clock")).not.toHaveClass(/over/);
  await expect(page.locator("#timer-toggle")).toHaveText("Start clock");
});

test("all slides fit desktop presentation and print pages, with readable mobile scrolling", async ({ page }) => {
  await page.goto(deck);
  const ids = await page.locator(".slide").evaluateAll(slides => slides.map(slide => slide.id));
  for (const viewport of [{ width: 1600, height: 900 }, { width: 1280, height: 720 }]) {
    await page.setViewportSize(viewport);
    for (const id of ids) {
      await page.locator("#slide-select").selectOption(id);
      await expect(page.locator("#" + id)).toBeVisible();
      const bounds = await page.locator("#" + id).boundingBox();
      const controls = await page.locator(".controls").boundingBox();
      expect(bounds, id).not.toBeNull();
      expect(controls, id).not.toBeNull();
      expect(bounds!.y + bounds!.height, `${id} fits above presentation controls`).toBeLessThanOrEqual(controls!.y + 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), id).toBe(true);
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const id of ids) {
    await page.locator("#slide-select").selectOption(id);
    await expect(page.locator("#" + id)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${id} mobile overflow`).toBe(true);
  }
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.emulateMedia({ media: "print" });
  await expect(page.locator(".slide:visible")).toHaveCount(22);
  await expect(page.locator(".controls")).toBeHidden();
  for (const id of ids) {
    const overflow = await page.locator("#" + id).evaluate(slide =>
      slide.scrollHeight > slide.clientHeight + 1 || slide.scrollWidth > slide.clientWidth + 1);
    expect(overflow, `${id} print overflow`).toBe(false);
  }
});
