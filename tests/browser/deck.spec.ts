/**
 * Offline deck/figure contract: source-pack geometry, reader navigation,
 * portable images, no-script reading and one-chapter-per-print-page containment.
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
  expect(briefSource).toContain("(assets/brief-sensor-alerts.png)");
  expect(briefSource).toContain("(assets/brief-agent-assisted.png)");
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
  await page.goto(deck + "#manual-reading");
  await expect(page.locator("#manual-reading img")).toBeVisible();
  expect(await page.locator("#manual-reading img").evaluate(image =>
    image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0)).toBe(true);
});

test("reader navigation supports contents, deep links, history and an all-pages mode", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(deck);
  const ids = await page.locator(".slide").evaluateAll(slides => slides.map(slide => slide.id));
  const destinations = await page.locator(".toc a").evaluateAll(anchors =>
    anchors.map(anchor => anchor.getAttribute("href")!.slice(1)));
  expect(destinations).toEqual(ids.slice(1));
  expect(new Set(ids).size).toBe(ids.length);
  await expect(page.locator(".slide:visible")).toHaveCount(1);
  await expect(page.locator("#contents")).toBeVisible();
  await expect(page.locator("#position")).toHaveText(`1 / ${ids.length}`);
  await expect(page.locator("#previous")).toBeDisabled();
  await page.locator("#contents h1").click();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#problem")).toBeVisible();
  await expect(page.locator("#problem h1")).toBeFocused();
  await page.getByRole("button", { name: "Contents", exact: true }).click();
  await page.locator('.toc a[href="#roles"]').click();
  await expect(page.locator("#roles")).toBeVisible();
  await page.goBack();
  await expect(page.locator("#contents")).toBeVisible();
  await page.goForward();
  await expect(page.locator("#roles")).toBeVisible();
  await page.getByRole("combobox", { name: "Go to page" }).selectOption(String(ids.indexOf("review")));
  await expect(page.locator("#review")).toBeVisible();
  await page.getByRole("button", { name: "Read all", exact: true }).click();
  await expect(page.locator(".slide:visible")).toHaveCount(ids.length);
  await expect(page.locator("#reading-mode")).toHaveAttribute("aria-pressed", "true");
  await page.locator('.toc a[href="#mapping"]').click();
  await expect(page.locator("#position")).toHaveText(`${ids.indexOf("mapping") + 1} / ${ids.length}`);
  await page.getByRole("button", { name: "One page", exact: true }).click();
  await expect(page.locator(".slide:visible")).toHaveCount(1);
  await expect(page.locator("#mapping")).toBeVisible();
  await page.goto(deck + "#boundaries");
  await expect(page.locator("#boundaries")).toBeVisible();
  await expect(page.locator("#next")).toBeDisabled();
  await page.goto(deck + "#not-a-slide");
  await expect(page.locator("#contents")).toBeVisible();
  expect(errors).toEqual([]);
});

test("deck is portable offline and embeds the unmodified source screenshots", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", request => {
    if (/^https?:/i.test(request.url())) externalRequests.push(request.url());
  });
  await page.context().setOffline(true);
  await page.goto(deck);
  const receipt = JSON.parse(readFileSync(path.join(process.cwd(), "docs", "evidence",
    "brief-dashboard-comparison.json"), "utf8"));
  for (const capture of receipt.captures as { file: string }[]) {
    const asset = path.basename(capture.file);
    const image = page.locator(`img[data-asset="${asset}"]`);
    const src = await image.getAttribute("src");
    expect(src).toMatch(/^data:image\/png;base64,/);
    expect(Buffer.from(src!.split(",")[1], "base64"))
      .toEqual(readFileSync(path.join(process.cwd(), "docs", "assets", asset)));
    expect(await image.evaluate(image =>
      image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0)).toBe(true);
  }
  await page.getByRole("button", { name: "Read all", exact: true }).click();
  await expect(page.locator("#assisted-reading")).toContainText("700-900 m");
  await expect(page.locator("#evaluation-results")).toContainText("not 72 independent physical faults");
  expect(externalRequests).toEqual([]);
});

test("reading is complete without JavaScript and page scrolling keeps its normal keyboard behavior", async ({ browser, page }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const noScript = await context.newPage();
    await noScript.goto(deck);
    const count = await noScript.locator(".slide").count();
    await expect(noScript.locator(".slide:visible")).toHaveCount(count);
    await expect(noScript.locator(".controls")).toBeHidden();
    await expect(noScript.locator("#review")).toContainText("source content");
    await expect(noScript.locator("#boundaries")).toBeVisible();
  } finally {
    await context.close();
  }
  await page.setViewportSize({ width: 390, height: 600 });
  await page.goto(deck + "#contents");
  await page.locator("#contents h1").click();
  await page.keyboard.press("Space");
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
  await expect(page).toHaveURL(/#contents$/);
  await page.keyboard.press("PageDown");
  await expect(page).toHaveURL(/#contents$/);
  await page.locator("#next").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/#contents$/);
  await page.keyboard.press("Enter");
  await expect(page.locator("#problem")).toBeVisible();
});

test("chapters remain readable on desktop and mobile and fit separate print pages", async ({ page }) => {
  await page.goto(deck);
  const ids = await page.locator(".slide").evaluateAll(slides => slides.map(slide => slide.id));
  for (const viewport of [
    { width: 1600, height: 900 }, { width: 1280, height: 720 }, { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    for (const [index, id] of ids.entries()) {
      await page.getByRole("combobox", { name: "Go to page" }).selectOption(String(index));
      await expect(page.locator("#" + id)).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `${id} at ${viewport.width}px has no document-level horizontal overflow`).toBe(true);
      await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
      const last = await page.locator("#" + id + " > :last-child").boundingBox();
      const controls = await page.locator(".controls").boundingBox();
      expect(last, id).not.toBeNull();
      expect(controls, id).not.toBeNull();
      expect(last!.y + last!.height, `${id} can be scrolled clear of navigation`)
        .toBeLessThanOrEqual(controls!.y + 1);
    }
  }
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.emulateMedia({ media: "print" });
  await expect(page.locator(".slide:visible")).toHaveCount(ids.length);
  await expect(page.locator(".controls")).toBeHidden();
  for (const id of ids) {
    const overflow = await page.locator("#" + id).evaluate(slide =>
      slide.scrollHeight > slide.clientHeight + 1 || slide.scrollWidth > slide.clientWidth + 1);
    expect(overflow, `${id} print overflow`).toBe(false);
  }
  await page.setViewportSize({ width: 800, height: 900 });
  expect(await page.locator("#review .flow > div:nth-child(2)").evaluate(step =>
    getComputedStyle(step, "::after").content)).toBe('"\u2192"');
});
