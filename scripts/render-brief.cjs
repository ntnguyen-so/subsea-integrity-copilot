// Offline document export: regenerate shared topology/evidence assets, then convert
// the canonical customer/submission brief into its one-page PDF (overwriting).
// Requires uv/project Python and installed Chrome/Playwright; no hosted model calls.
// This is a deliberately small Markdown subset, not a general Markdown/HTML engine.
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("@playwright/test");
const { renderTopology } = require("./render-topology.cjs");

// Escape text first; only HTTPS links and bounded local SVG/PNG illustrations are
// expanded. The final page-count assertion catches layout drift on repeated renders.
async function renderBrief(name) {
  const docs = path.join(__dirname, "..", "docs");
  const source = await fs.readFile(
    path.join(docs, `${name}.md`), "utf8",
  );
  const escape = value => value.replace(/[&<>"]/g, character =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);
  const inline = value => escape(value)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>');
  async function imageMarkup(value) {
    const image = value.match(/^!\[([^\]]+)\]\(([^)]+)\)$/);
    if (!image) return null;
    const imagePath = path.resolve(docs, ...image[2].split("/"));
    const mime = { ".svg": "image/svg+xml", ".png": "image/png" }[path.extname(imagePath).toLowerCase()];
    if (!imagePath.startsWith(docs + path.sep) || !mime) {
      throw new Error("Brief illustrations must be local SVG or PNG files inside docs.");
    }
    const bytes = await fs.readFile(imagePath);
    return `<img alt="${escape(image[1])}" src="data:${mime};base64,${bytes.toString("base64")}">`;
  }
  const paragraphs = source.trim().split(/\r?\n\s*\r?\n/);
  const title = paragraphs.shift().replace(/^#\s+/, "");
  const parts = [];
  for (const paragraph of paragraphs) {
    if (paragraph === "---") {
      parts.push('<div class="page-break"></div>');
      continue;
    }
    const lines = paragraph.split(/\r?\n/);
    if (lines.length >= 3 && lines.every(line => line.startsWith("|") && line.endsWith("|"))) {
      const rows = lines.map(line => line.slice(1, -1).split("|").map(cell => cell.trim()));
      if (rows[1].every(cell => /^:?-+:?$/.test(cell)) &&
          rows.every(row => row.length === rows[0].length)) {
        const bodyRows = await Promise.all(rows.slice(2).map(async row =>
          `<tr>${(await Promise.all(row.map(async cell =>
            `<td>${await imageMarkup(cell) || inline(cell)}</td>`))).join("")}</tr>`));
        parts.push(`<table><thead><tr>${rows[0].map(cell => `<th>${inline(cell)}</th>`).join("")}</tr></thead><tbody>${
          bodyRows.join("")
        }</tbody></table>`);
        continue;
      }
    }
    const image = await imageMarkup(paragraph);
    if (image) {
      parts.push(`<figure>${image}</figure>`);
    } else {
      parts.push(`<p>${inline(paragraph.replace(/\r?\n/g, " "))}</p>`);
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
      table{width:100%;border-collapse:collapse;margin:0 0 6pt;table-layout:fixed;break-inside:avoid}
      th,td{border:1px solid #c9d6e2;padding:6pt;text-align:left;vertical-align:top}
      td img{display:block;width:100%;height:auto}
      th{background:#edf3f8;color:#173c4b}tr{break-inside:avoid}
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
    if (pages.length !== 1) {
      throw new Error(`${name} must be one page, found ${pages.length}`);
    }
    console.log(`${name} rendered: ${pages.length} pages.`);
  } finally {
    await browser.close();
  }
}

async function main() {
  await renderTopology();
  await renderBrief("ONE_PAGE_BRIEF");
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
