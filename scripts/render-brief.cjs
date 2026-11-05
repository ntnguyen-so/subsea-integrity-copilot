const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("@playwright/test");
const { renderTopology } = require("./render-topology.cjs");

async function main() {
  await renderTopology();
  const docs = path.join(__dirname, "..", "docs");
  const source = await fs.readFile(
    path.join(__dirname, "..", "docs", "ONE_PAGE_BRIEF.md"), "utf8",
  );
  const escape = value => value.replace(/[&<>"]/g, character =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);
  const paragraphs = source.trim().split(/\r?\n\s*\r?\n/);
  const title = paragraphs.shift().replace(/^#\s+/, "");
  const parts = [];
  for (const paragraph of paragraphs) {
    const image = paragraph.match(/^!\[([^\]]+)\]\(([^)]+)\)$/);
    if (image) {
      const imagePath = path.resolve(docs, ...image[2].split("/"));
      if (!imagePath.startsWith(docs + path.sep) || !imagePath.endsWith(".svg")) {
        throw new Error("Brief illustrations must be local SVG files inside docs.");
      }
      const svg = await fs.readFile(imagePath);
      parts.push(`<figure><img alt="${escape(image[1])}" src="data:image/svg+xml;base64,${svg.toString("base64")}"></figure>`);
    } else {
      parts.push(`<p>${escape(paragraph.replace(/\r?\n/g, " "))
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")}</p>`);
    }
  }
  const body = parts.join("");
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<!doctype html><html lang="en"><meta charset="utf-8">
      <title>${escape(title)}</title><style>
      body{font:10pt/1.3 Arial,sans-serif;color:#17212b}
      h1{font-size:18pt;margin:0 0 12pt}p{margin:0 0 8pt}
      figure{margin:0 0 8pt}figure img{display:block;width:100%;height:auto}
      </style><h1>${escape(title)}</h1>${body}</html>`);
    await page.locator("img").evaluateAll(images => Promise.all(images.map(image => image.decode())));
    const output = path.join(__dirname, "..", "docs", "ONE_PAGE_BRIEF.pdf");
    const pdf = await page.pdf({
      path: output, format: "A4", margin: { top: "15mm", bottom: "15mm",
        left: "15mm", right: "15mm" }, printBackground: true,
    });
    const pages = pdf.toString("latin1").match(/\/Type\s*\/Page\b/g) || [];
    if (pages.length !== 1) throw new Error(`Brief has ${pages.length} pages; expected one`);
    console.log("Original one-page brief rendered and page count verified.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
