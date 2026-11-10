// Rebuild figures, embed the deck's screenshots and print docs/INTERVIEW_DECK.pdf.
// Requires uv/project Python and Chrome/Playwright, not backend services or inference.
// Reruns overwrite assets/PDF; a slide/page mismatch deletes the invalid PDF.
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("@playwright/test");
const { renderTopology } = require("./render-topology.cjs");

async function main() {
  await renderTopology();
  const source = path.join(__dirname, "..", "docs", "INTERVIEW_DECK.html");
  let html = await fs.readFile(source, "utf8");
  for (const asset of ["brief-sensor-alerts.png", "brief-agent-assisted.png"]) {
    const pattern = new RegExp(`<img\\s+data-asset="${asset.replaceAll(".", "\\.")}"\\s+src="[^"]*"(\\s+[^>]*>)\\s*`);
    if (!pattern.test(html)) throw new Error(`Missing embedded-image marker: ${asset}`);
    const image = await fs.readFile(path.join(__dirname, "..", "docs", "assets", asset));
    html = html.replace(pattern, (_, attributes) =>
      `<img data-asset="${asset}"\n        src="data:image/png;base64,${image.toString("base64")}"\n        ${attributes.trimStart()}\n      `);
  }
  await fs.writeFile(source, html);
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(pathToFileURL(source).href);
    await page.locator("img").evaluateAll(images => Promise.all(images.map(image => image.decode())));
    if (errors.length) throw new Error(errors.join("\n"));
    const expected = await page.locator(".slide").count();
    await page.emulateMedia({ media: "print" });
    const overflow = await page.locator(".slide").evaluateAll(slides => slides
      .filter(slide => slide.scrollHeight > slide.clientHeight + 1 ||
        slide.scrollWidth > slide.clientWidth + 1).map(slide => slide.id));
    if (overflow.length) throw new Error(`Print overflow: ${overflow.join(", ")}`);
    // Printed relative references need a stable repository URL, not a local file URL.
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
    console.log(`Rendered ${expected} reader-first pages and embedded both screenshots in the standalone HTML.`);
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
