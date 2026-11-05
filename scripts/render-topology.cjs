const fs = require("node:fs/promises");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const escape = value => String(value).replace(/[&<>"]/g, character =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);

function network(pack, { x, y, scale }, snapshot = null) {
  const project = point => ({ x: x + point.x * scale, y: y - point.y * scale });
  const result = [];
  for (const segment of pack.segments) {
    const [start, end] = segment.points.map(project);
    result.push(`<g data-segment-id="${segment.id}" data-length-m="${segment.length_m}" data-start-x="${segment.points[0].x}" data-start-y="${segment.points[0].y}" data-end-x="${segment.points[1].x}" data-end-y="${segment.points[1].y}">`);
    result.push(`<path d="M${start.x} ${start.y} L${end.x} ${end.y}" fill="none" stroke="#237c87" stroke-width="14" stroke-linecap="round"/>`);
    for (const sensor of pack.sensors.filter(item => item.segment_id === segment.id)) {
      const fraction = sensor.chainage_m / segment.length_m;
      const dx = end.x - start.x, dy = end.y - start.y, length = Math.hypot(dx, dy);
      const side = sensor.id.endsWith("-A") ? -1 : 1;
      const sx = start.x + dx * fraction - side * dy / length * 11;
      const sy = start.y + dy * fraction + side * dx / length * 11;
      const finding = snapshot?.quality.findings.find(item => item.sensor_id === sensor.id);
      const support = snapshot?.event.supporting_sensor_ids.includes(sensor.id);
      const fault = finding && (finding.spike_count || finding.peer_disagreement ||
        finding.hard_excluded || finding.missing > finding.expected * .1);
      const fill = support ? "#efb735" : fault ? "#e76c4c" : "#e4f3f5";
      result.push(`<circle cx="${sx.toFixed(2)}" cy="${sy.toFixed(2)}" r="5" fill="${fill}" stroke="#16445c" stroke-width="1" data-sensor-id="${escape(sensor.id)}" data-station-id="${escape(sensor.station_id)}" data-segment-id="${segment.id}" data-chainage-m="${sensor.chainage_m}" data-failure-domain="${escape(sensor.failure_domain_id)}" data-source-x="${sensor.position.x}" data-source-y="${sensor.position.y}"><title>${escape(sensor.id)}; ${sensor.chainage_m}m; ${escape(sensor.failure_domain_id)}</title></circle>`);
    }
    const lx = end.x;
    const ly = segment.id === "P1" ? start.y + 26 : end.y - 20;
    result.push(`<text x="${lx}" y="${ly}" text-anchor="middle" font-size="17" font-weight="700">${escape(segment.name)} / ${segment.id}</text></g>`);
  }
  return result.join("\n");
}

function trace(values, x, y, label, start, end) {
  const usable = values.filter(item => item.value !== null);
  const min = Math.min(...usable.map(item => item.value));
  const max = Math.max(...usable.map(item => item.value));
  let previous = null;
  const points = values.map(item => {
    if (item.value === null) { previous = null; return ""; }
    const command = previous !== null && item.seconds - previous <= 1.5 ? "L" : "M";
    previous = item.seconds;
    return `${command}${x + (item.seconds - start) / (end - start) * 190},${y + 50 - (item.value - min) / Math.max(max - min, .01) * 35}`;
  }).join(" ");
  return `<text x="${x}" y="${y - 4}" font-size="14">${escape(label)}</text><rect x="${x}" y="${y + 2}" width="190" height="55" fill="#fff" stroke="#bfd3dd"/><path d="${points}" fill="none" stroke="#186ba0" stroke-width="2"/>`;
}

async function renderTopology() {
  const root = path.join(__dirname, "..");
  execFileSync("uv", ["run", "python", path.join(__dirname, "export-brief-evidence.py")],
    { cwd: root, windowsHide: true });
  const pack = JSON.parse(await fs.readFile(path.join(root, "packs", "northsea.json"), "utf8"));
  const evidence = JSON.parse(await fs.readFile(path.join(root, "fixtures", "synthetic", "brief-evidence.json"), "utf8"));
  if (evidence.pack_version !== pack.version ||
      Object.values(evidence.examples).some(item => item.snapshot.pack_version !== pack.version)) {
    throw new Error("Brief evidence and site pack disagree; run export-brief-evidence.py.");
  }
  const assets = path.join(root, "docs", "assets");
  const header = (width, height, title) =>
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img"><title>${title}</title><g font-family="Arial,sans-serif" fill="#173c4b">`;
  const topology = header(900, 520, "The brief's Y-shaped pressure network: Trunk, Branch A and Branch B") +
    '<rect x="1" y="1" width="898" height="518" rx="8" fill="#f4f8fa" stroke="#c4d5dd"/>' +
    network(pack, { x: 450, y: 205, scale: .31 }) +
    '<text x="450" y="510" text-anchor="middle" font-size="15">24 pipe-mounted instruments; four A/B stations per 800m segment. Wall offsets enlarged for display.</text></g></svg>';
  await fs.writeFile(path.join(assets, "pipeline-topology.svg"), topology + "\n", "utf8");
  const parts = [header(1500, 900, "The brief's pressure investigation, generated from the same topology and observations as the demo")];
  parts.push('<rect width="1500" height="900" fill="#fff"/>');
  for (const [index, scenario] of ["S1", "S2"].entries()) {
    const left = index * 750;
    const sample = evidence.examples[scenario];
    if ((!index && sample.snapshot.location?.status !== "located") ||
        (index && sample.snapshot.event.hypothesis !== "sensor_or_telemetry_issue")) {
      throw new Error("Brief examples no longer support their stated investigation outcomes.");
    }
    parts.push(`<g data-scenario="${scenario}" data-pack-version="${escape(pack.version)}">`);
    parts.push(`<rect x="${left + 8}" y="8" width="734" height="700" rx="10" fill="#f3f8fb" stroke="#356581"/><rect x="${left + 8}" y="8" width="734" height="62" rx="10" fill="#1e486c"/><text x="${left + 375}" y="48" text-anchor="middle" fill="#fff" font-size="29" font-weight="700">${index ? "Possible sensor faults" : "Possible pipeline leak"}</text>`);
    parts.push(network(pack, { x: left + 275, y: 285, scale: .255 }, sample.snapshot));
    const labels = index ? ["Spike / Branch A", "Missing / Branch B", "Drift / Trunk"] : null;
    for (const [row, [sensor, values]] of Object.entries(sample.traces).entries()) {
      parts.push(trace(values, left + 510, 365 + row * 95, `${labels?.[row] || "Pressure drop"}: ${sensor}`, sample.window_start_seconds, sample.window_end_seconds));
    }
    parts.push(`<text x="${left + 375}" y="634" text-anchor="middle" font-size="19" font-weight="700">${index ? "Scattered spikes, gaps and drift" : "Nearby pressure drops overlap in time"}</text>`);
    const interval = sample.snapshot.location;
    parts.push(`<text x="${left + 375}" y="665" text-anchor="middle" font-size="17">${index ? "Review instrumentation; do not infer a leak location." : `Inspect Trunk / P1, ${interval.inspection_start_m}-${interval.inspection_end_m}m; not an exact leak point.`}</text>`);
    parts.push("</g>");
  }
  parts.push('<text x="750" y="753" text-anchor="middle" font-size="23" font-weight="700">Existing detector alerts → Agent-assisted investigation → Human review</text>');
  parts.push('<text x="750" y="796" text-anchor="middle" font-size="20">Patterns are evidence, not proof: check operating changes and shared failures.</text>');
  parts.push('<text x="750" y="834" text-anchor="middle" font-size="17">Demo assumptions: 24 pipe-mounted pressure instruments, 12 paired stations, three connected 800m segments.</text>');
  const example = evidence.examples.S1;
  parts.push(`<text x="750" y="867" text-anchor="middle" font-size="15">Same ${escape(pack.version)} geometry as console; seed 2026, [${example.window_start_seconds},${example.window_end_seconds})s, pressure in bar; independent trace y-scales; synthetic.</text></g></svg>`);
  await fs.writeFile(path.join(assets, "pressure-leak-vs-sensor-faults.svg"), parts.join("\n") + "\n", "utf8");
}

module.exports = { renderTopology };
if (require.main === module) {
  renderTopology().then(() => console.log("Rendered both brief and presentation figures from shared evidence."))
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}
