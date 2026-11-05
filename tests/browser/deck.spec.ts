import { test, expect } from "@playwright/test";
import path from "node:path";
import { pathToFileURL } from "node:url";

const deck = pathToFileURL(path.join(process.cwd(), "docs", "INTERVIEW_DECK.html")).href;

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
  await page.clock.install();
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
