const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("@playwright/test");
const { renderTopology } = require("./render-topology.cjs");

async function main() {
  await renderTopology();
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const source = path.join(__dirname, "..", "docs", "INTERVIEW_DECK.html");
    await page.goto(pathToFileURL(source).href);
    await page.locator("img").evaluateAll(images => Promise.all(images.map(image => image.decode())));
    if (errors.length) throw new Error(errors.join("\n"));
    const expected = await page.locator(".slide").count();
    await page.locator("a[href]").evaluateAll(anchors => {
      for (const anchor of anchors) {
        const href = anchor.getAttribute("href");
        if (href && !href.startsWith("#") && !/^[a-z][a-z0-9+.-]*:/i.test(href)) {
          anchor.setAttribute("href", new URL(href,
            "https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/").href);
        }
      }
    });
    const output = path.join(__dirname, "..", "docs", "INTERVIEW_DECK.pdf");
    const pdf = await page.pdf({
      path: output, preferCSSPageSize: true, printBackground: true,
      margin: { top: 0, bottom: 0, left: 0, right: 0 },
    });
    const pages = pdf.toString("latin1").match(/\/Type\s*\/Page\b/g) || [];
    if (pages.length !== expected) {
      await fs.unlink(output);
      throw new Error(`Deck has ${pages.length} PDF pages; expected ${expected}. Check print overflow.`);
    }
    console.log(`Rendered ${expected} widescreen slides: 18 timed slides + 4 on-demand appendices.`);
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
