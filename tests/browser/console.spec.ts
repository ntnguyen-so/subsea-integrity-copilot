import { test, expect } from "@playwright/test";

test("real replay, sensor evidence, pinned questions and keyboard navigation", async ({ page }) => {
  const failures: string[] = [];
  page.on("pageerror", error => failures.push(error.message));
  const password = process.env.SUBSEA_OPERATOR_PASSWORD;
  if (!password) throw new Error("Load the owned environment before browser qualification");
  const login = await page.context().request.post("/api/login", {
    data: { username: "operator", password },
  });
  if (login.status() !== 200) throw new Error(`Local test login failed: HTTP ${login.status()}`);
  await page.goto("/");
  await expect(page.locator("#create-replay")).toBeEnabled();
  await expect(page.locator(".header-badges")).toContainText("SIMULATED STREAM");
  await page.locator("#scenario").selectOption("S1");
  await page.locator("#create-replay").click();
  await expect(page.locator("#step")).toBeEnabled();
  await page.locator("#step").click();
  await expect(page.locator("#source-clock")).toContainText("5");
  await page.locator("#step").click();
  await expect(page.locator("#window-state")).toContainText(/WARMING[ _]UP/i);
  await page.locator("#speed").selectOption("10");
  await page.locator("#play").click();
  await expect(page.locator("#event-summary")).toContainText(/suspected[ _]leak/i, {
    timeout: 120_000,
  });
  await page.locator("#play").click();
  await expect(page.locator("#play")).toHaveText("Play");
  await expect(page.locator("#ask-submit")).toBeEnabled();
  const sensor = page.locator("#topology [role=button]").first();
  await expect(sensor).toBeVisible();
  await sensor.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#sensor-title")).not.toHaveText("Select a sensor");
  await expect(page.locator("#channel-charts svg")).toHaveCount(3);
  await page.locator("#inspect-raw").click();
  await expect(page.locator("#tab-evidence")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#raw-table table")).toBeVisible();
  await page.locator("#tab-live").click();
  await page.locator("#questions button").first().click();
  await page.locator("#ask-submit").click();
  await expect(page.locator("#answer-preview")).toContainText(/suspected[ _]leak/i, {
    timeout: 120_000,
  });
  await page.locator("#tab-agents").click();
  await expect(page.locator("#task-tree")).toContainText(/sensor[ _]quality/i);
  await expect(page.locator("#task-tree")).toContainText(/event[ _]diagnosis/i);
  await page.locator("#tab-audit").focus();
  await page.keyboard.press("Home");
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  expect(failures).toEqual([]);
  await page.screenshot({ path: "runtime/console.png", fullPage: true });
});
