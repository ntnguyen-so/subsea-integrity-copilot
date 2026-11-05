const fs = require("node:fs/promises");
const path = require("node:path");

const layouts = {
  P1: { start: [45, 91], end: [405, 91], label: [185, 50] },
  P2: { start: [405, 91], end: [745, 6], label: [760, 21] },
  P3: { start: [405, 91], end: [745, 176], label: [760, 173] },
};
const escape = value => String(value).replace(/[&<>"]/g, character =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);

async function renderTopology() {
  const pack = JSON.parse(await fs.readFile(
    path.join(__dirname, "..", "packs", "northsea.json"), "utf8"));
  const segments = new Map(pack.segments.map(segment => [segment.id, segment]));
  if (segments.size !== 3 || pack.sensors.length !== 24) {
    throw new Error("Topology illustration expects the three-segment, 24-node demo pack.");
  }
  const p1 = segments.get("P1");
  const p2 = segments.get("P2");
  const p3 = segments.get("P3");
  if (!p1 || !p2 || !p3 || [p1, p2, p3].some(segment =>
    segment.points.length !== 2 || segment.length_m !== 800) ||
    [p2, p3].some(segment => segment.points[0].x !== p1.points[1].x ||
      segment.points[0].y !== p1.points[1].y)) {
    throw new Error("Site topology changed; review the schematic before rendering.");
  }
  const lines = [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 200" role="img" aria-labelledby="topology-title topology-desc">',
    '<title id="topology-title">Synthetic Y-shaped pipeline network with 24 sensor nodes</title>',
    '<desc id="topology-desc">P1 connects to P2 and P3. Each segment is 800 metres with four stations at 100, 300, 500 and 700 metres. Each station has A and B sensors eight metres on either side. This is a topology schematic, not a geographic scale drawing; offsets are exaggerated.</desc>',
    '<rect x="1" y="1" width="898" height="198" rx="7" fill="#f4f8fa" stroke="#c4d5dd"/>',
    '<g font-family="Arial,sans-serif" fill="#173c4b">',
  ];
  for (const [id, layout] of Object.entries(layouts)) {
    const segment = segments.get(id);
    lines.push(`<g data-segment-id="${id}" data-length-m="${segment.length_m}" data-start-x="${segment.points[0].x}" data-start-y="${segment.points[0].y}" data-end-x="${segment.points[1].x}" data-end-y="${segment.points[1].y}">`);
    lines.push(`<path d="M${layout.start.join(" ")} L${layout.end.join(" ")}" fill="none" stroke="#5e7a89" stroke-width="4"/>`);
    lines.push(`<text x="${layout.label[0]}" y="${layout.label[1]}" font-size="20" font-weight="700">${id} / ${segment.length_m}m</text>`);
    const dx = layout.end[0] - layout.start[0], dy = layout.end[1] - layout.start[1];
    const length = Math.hypot(dx, dy);
    const sensors = pack.sensors.filter(sensor => sensor.segment_id === id);
    if (sensors.length !== 8 || sensors.some(sensor =>
      ![100, 300, 500, 700].includes(sensor.chainage_m) || !/-[AB]$/.test(sensor.id))) {
      throw new Error(`Unexpected station distribution on ${id}.`);
    }
    for (const sensor of sensors) {
      const side = sensor.id.endsWith("-A") ? 1 : -1;
      const fraction = sensor.chainage_m / segment.length_m;
      const x = layout.start[0] + dx * fraction - side * dy / length * 6;
      const y = layout.start[1] + dy * fraction + side * dx / length * 6;
      const fill = side === 1 ? "#136d7d" : "#759fd5";
      lines.push(`<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="4.2" fill="${fill}" stroke="#fff" stroke-width=".6" data-sensor-id="${escape(sensor.id)}" data-station-id="${escape(sensor.station_id)}" data-segment-id="${id}" data-chainage-m="${sensor.chainage_m}" data-failure-domain="${escape(sensor.failure_domain_id)}" data-source-x="${sensor.position.x}" data-source-y="${sensor.position.y}"><title>${escape(sensor.id)}; ${sensor.chainage_m}m; ${escape(sensor.failure_domain_id)}</title></circle>`);
    }
    if (id === "P1") {
      for (const chainage of [100, 300, 500, 700]) {
        const x = layout.start[0] + dx * chainage / segment.length_m;
        lines.push(`<text x="${x}" y="120" text-anchor="middle" font-size="17">${chainage}m</text>`);
      }
    }
    lines.push("</g>");
  }
  lines.push(
    '<circle cx="405" cy="91" r="5" fill="#173c4b"/>',
    '<text x="346" y="69" font-size="16">Junction</text>',
    '<text x="779" y="95" font-size="16">24 nodes</text>',
    '<circle cx="785" cy="111" r="4.2" fill="#136d7d"/><text x="797" y="117" font-size="16">A</text>',
    '<circle cx="833" cy="111" r="4.2" fill="#759fd5"/><text x="845" y="117" font-size="16">B</text>',
    '<text x="18" y="195" font-size="15.5">Each segment: ST1-ST4 at 100/300/500/700m; A/B nodes 8m either side. Schematic; offsets exaggerated.</text>',
    "</g></svg>",
  );
  const output = path.join(__dirname, "..", "docs", "assets", "pipeline-topology.svg");
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, lines.join("\n") + "\n", "utf8");
  return output;
}

module.exports = { renderTopology };
if (require.main === module) {
  renderTopology().then(() => console.log("Rendered topology from the authoritative site pack."))
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}
