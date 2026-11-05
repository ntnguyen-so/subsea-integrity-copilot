const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("@playwright/test");
const { renderTopology } = require("./render-topology.cjs");

async function renderBrief(name) {
  const docs = path.join(__dirname, "..", "docs");
  const source = await fs.readFile(
    path.join(docs, `${name}.md`), "utf8",
  );
  const escape = value => value.replace(/[&<>"]/g, character =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);
  const paragraphs = source.trim().split(/\r?\n\s*\r?\n/);
  const title = paragraphs.shift().replace(/^#\s+/, "");
  const parts = [];
  for (const paragraph of paragraphs) {
    if (paragraph === "---") {
      parts.push('<div class="page-break"></div>');
      continue;
    }
    const image = paragraph.match(/^!\[([^\]]+)\]\(([^)]+)\)$/);
    if (image) {
      const imagePath = path.resolve(docs, ...image[2].split("/"));
      const mime = { ".svg": "image/svg+xml", ".png": "image/png" }[path.extname(imagePath).toLowerCase()];
      if (!imagePath.startsWith(docs + path.sep) || !mime) {
        throw new Error("Brief illustrations must be local SVG or PNG files inside docs.");
      }
      const bytes = await fs.readFile(imagePath);
      parts.push(`<figure><img alt="${escape(image[1])}" src="data:${mime};base64,${bytes.toString("base64")}"></figure>`);
    } else {
      parts.push(`<p>${escape(paragraph.replace(/\r?\n/g, " "))
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>')}</p>`);
    }
  }
  const body = parts.join("");
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<!doctype html><html lang="en"><meta charset="utf-8">
      <title>${escape(title)}</title><style>
      body{font:10pt/1.25 Arial,sans-serif;color:#17212b}
      h1{font-size:18pt;margin:0 0 8pt}p{margin:0 0 6pt;break-inside:avoid}
      figure{margin:0 0 6pt;break-inside:avoid}figure img{display:block;width:100%;height:auto}
      .page-break{break-before:page}a{color:#174c79;overflow-wrap:anywhere}
      </style><h1>${escape(title)}</h1>${body}</html>`);
    await page.locator("img").evaluateAll(images => Promise.all(images.map(image => image.decode())));
    const output = path.join(docs, `${name}.pdf`);
    const pdf = await page.pdf({
      path: output, format: "A4", margin: { top: "15mm", bottom: "15mm",
        left: "15mm", right: "15mm" }, printBackground: true,
    });
    const pages = pdf.toString("latin1").match(/\/Type\s*\/Page\b/g) || [];
    if (pages.length === 0) throw new Error("Brief PDF contains no pages");
    if (name === "SUBMISSION_BRIEF" && pages.length !== 1) {
      throw new Error(`Submission brief must be one page, found ${pages.length}`);
    }
    console.log(`${name} rendered: ${pages.length} pages.`);
  } finally {
    await browser.close();
  }
}

async function main() {
  await renderTopology();
  for (const name of ["ONE_PAGE_BRIEF", "SUBMISSION_BRIEF"]) await renderBrief(name);
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
