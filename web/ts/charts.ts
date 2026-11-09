import { node, svg, time } from "./dom";
import type { CanonicalObservation, Channel, Sensor, WindowSnapshot } from "./types";

const labels: Record<Channel, string> = { pressure: "Pipeline pressure", acoustic: "Acoustic relative power (archived)", methane: "Dissolved methane (archived)", temperature: "Temperature (archived)" };

export function sharedPressureRange(readings: { sensor: Sensor; observations: CanonicalObservation[] }[],
  window: WindowSnapshot): [number, number] | undefined {
  const start = Date.parse(window.window_start), end = Date.parse(window.window_end);
  const ids = new Set(readings.map(item => item.sensor.id));
  const values = readings.flatMap(item => item.observations.flatMap(row =>
    row.channel === "pressure" && row.unit === "bar" && row.validity === "usable" && row.value !== null
      && Date.parse(row.observed_at) >= start && Date.parse(row.observed_at) < end ? [row.value] : []));
  for (const item of Object.values(window.evidence)) {
    if (item.kind !== "channel_summary" || !item.sensor_id || !ids.has(item.sensor_id)
      || item.channel !== "pressure" || item.value === null || typeof item.value !== "object" || Array.isArray(item.value)) continue;
    const model = item.value;
    if (typeof model.baseline_median === "number" && typeof model.baseline_scale === "number"
      && typeof model.anomaly_threshold === "number") {
      values.push(model.baseline_median - model.baseline_scale * model.anomaly_threshold,
        model.baseline_median + model.baseline_scale * model.anomaly_threshold);
    }
  }
  return values.length ? [Math.min(...values), Math.max(...values)] : undefined;
}

export function renderCharts(container: HTMLElement, sensor: Sensor, observations: CanonicalObservation[], window: WindowSnapshot, sampleSeconds: number, sharedRange?: [number, number]): void {
  container.replaceChildren();
  const start = Date.parse(window.window_start);
  const end = Date.parse(window.window_end);
  for (const channel of sensor.channels) {
    const section = node("section", "", "chart");
    const heading = node("div", "", "chart-heading");
    heading.append(node("h3", labels[channel]));
    const records = observations.filter(o => o.channel === channel && Date.parse(o.observed_at) >= start && Date.parse(o.observed_at) < end)
      .sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at));
    const usable = records.filter(o => o.validity === "usable" && o.value !== null);
    const values = usable.flatMap(o => o.value === null ? [] : [o.value]);
    const unit = [...new Set(records.map(o => o.unit))].join(" / ") || "unit not reported";
    const chart = svg("svg", { viewBox: "0 0 360 170", role: "img", "aria-label": `${labels[channel]}, ${unit}. ${usable.length} usable of ${records.length} received. Missing or invalid readings shown as gaps. ${time(window.window_start)} to ${time(window.window_end)}.` });
    chart.append(svg("title", {}, `${labels[channel]} — ${unit}; visible immutable window`));
    const summary = Object.values(window.evidence).find(item => item.kind === "channel_summary" && item.sensor_id === sensor.id && item.channel === channel)?.value;
    const model = summary !== null && typeof summary === "object" && !Array.isArray(summary) ? summary : null;
    const center = typeof model?.baseline_median === "number" ? model.baseline_median : null;
    const scale = typeof model?.baseline_scale === "number" ? model.baseline_scale : null;
    const threshold = typeof model?.anomaly_threshold === "number" ? model.anomaly_threshold : null;
    const band = center !== null && scale !== null && threshold !== null ? [center - scale * threshold, center + scale * threshold] : [];
    const low = sharedRange ? Math.min(sharedRange[0], ...band) : values.length ? Math.min(...values, ...band) : 0;
    const high = sharedRange ? Math.max(sharedRange[1], ...band) : values.length ? Math.max(...values, ...band) : 1;
    const padding = high === low ? Math.max(Math.abs(low) * .05, .01) : (high - low) * .08;
    const min = low - padding, max = high + padding;
    const x = (timestamp: number): number => 48 + (timestamp - start) / (end - start) * 296;
    const y = (value: number): number => 128 - (value - min) / (max - min) * 108;
    for (const value of band) chart.append(svg("line", { x1: 48, x2: 344, y1: y(value), y2: y(value), class: "threshold", stroke: "var(--sample-alert)", "stroke-dasharray": "4 3" }));
    for (let index = 0; index < 3; index++) {
      const yy = 20 + index * 54;
      chart.append(svg("line", { x1: 48, x2: 344, y1: yy, y2: yy, class: "grid" }));
      if (values.length) chart.append(svg("text", { x: 3, y: yy + 4 }, Number((max - index * (max - min) / 2).toPrecision(6)).toString()));
    }
    // Expected-time slots expose absence even when no missing record exists.
    const step = Math.max(sampleSeconds * 1000, 1);
    const maxSlots = Math.min(5000, Math.ceil((end - start) / step));
    let gapStart: number | null = null, gaps = 0;
    for (let index = 0; index <= maxSlots; index++) {
      const ts = start + index * step;
      const available = index < maxSlots && usable.some(o => Math.abs(Date.parse(o.observed_at) - ts) < step * .45);
      if (!available && index < maxSlots && gapStart === null) { gapStart = ts; gaps++; }
      if ((available || index === maxSlots) && gapStart !== null) {
        const right = Math.min(ts, end);
        chart.append(svg("rect", { x: x(gapStart), y: 20, width: Math.max(1, x(right) - x(gapStart)), height: 108, class: "gap" }));
        gapStart = null;
      }
    }
    let path = "", previous: number | null = null, previousUsable = false;
    for (const record of records) {
      const ts = Date.parse(record.observed_at);
      if (record.validity !== "usable" || record.value === null) { previousUsable = false; continue; }
      const connected = previousUsable && previous !== null && ts > previous && ts - previous <= step * 1.5;
      path += `${connected ? "L" : "M"}${x(ts).toFixed(2)},${y(record.value).toFixed(2)} `;
      const anomalous = band.length === 2 && (record.value < band[0] || record.value > band[1]);
      chart.append(svg("circle", { cx: x(ts), cy: y(record.value), r: anomalous ? 2.5 : 1.7, fill: anomalous ? "var(--sample-alert)" : "var(--cyan)", "data-anomaly": String(anomalous) }));
      previous = ts;
      previousUsable = true;
    }
    if (path) chart.append(svg("path", { d: path }));
    chart.append(svg("text", { x: 48, y: 149 }, new Date(start).toISOString().slice(11, 19)));
    chart.append(svg("text", { x: 344, y: 149, "text-anchor": "end" }, `${new Date(end).toISOString().slice(11, 19)} UTC`));
    if (!values.length) chart.append(svg("text", { x: 196, y: 78, "text-anchor": "middle" }, "No usable measurements"));
    const legend = node("div", "", "chart-legend");
    legend.setAttribute("aria-label", "Pressure chart legend");
    const entry = (key: string, label: string): void => {
      const item = node("span");
      item.dataset.legend = key;
      const icon = node("i", "", `legend-mark ${key}`);
      icon.setAttribute("aria-hidden", "true");
      item.append(icon, document.createTextNode(label)); legend.append(item);
    };
    entry("pressure", "Pressure");
    if (band.length) {
      entry("anomaly", "Pressure anomaly");
      entry("baseline", "Baseline limits");
    }
    entry("missing", "Missing value");
    heading.append(legend);
    section.append(heading, chart, node("p", `${unit} · ${usable.length} usable / ${records.length} received · ${gaps} gap interval${gaps === 1 ? "" : "s"}. Original samples in Inspect's optional audit.`));
    if (band.length) section.append(node("p", "Amber points are individual pressure anomalies, not leak diagnoses or sensor-fault classifications."));
    container.append(section);
  }
}
