/**
 * Readings-first inspection workspace: one scoped window, optional peer on a shared
 * pressure scale, then the accepted report for that same evidence. Missing/unusable
 * samples and a model's instrument concern are deliberately different concepts.
 */
import { renderCharts, sharedPressureRange } from "./charts";
import { bounds, button, friendly, node, time } from "./dom";
import { reportText } from "./presentation";
import type { CanonicalObservation, Sensor, SitePack, TaskDetail, WindowSnapshot } from "./types";

export interface InspectionReadings { sensor: Sensor; observations: CanonicalObservation[] }
export interface SensorInspection {
  pack: SitePack | null;
  window: WindowSnapshot | null;
  sensor: Sensor | null;
  readings: CanonicalObservation[];
  loading: boolean;
  error: string | null;
  peer: InspectionReadings | null;
  peerSensor: Sensor | null;
  peerLoading: boolean;
  peerError: string | null;
  reportError: string | null;
  reports: (TaskDetail | null)[];
  pending: boolean;
  openReport(taskId: string): void;
  inspectWindow(snapshotId: string): void;
}

/** Require identity, input hash and all numerical versions before attaching prose to readings. */
export function inspectionReportMatches(detail: TaskDetail, window: WindowSnapshot): boolean {
  const { task, casefile: file } = detail;
  return Boolean(file && task.parent_id === null && task.role === "operator_response"
    && ["SUCCEEDED", "ABSTAINED"].includes(task.state) && task.result && task.answer
    && task.state === file.state && file.task_id === task.id
    && task.snapshot_id === window.id && file.snapshot_id === window.id
    && task.site_id === window.site_id && task.generation_id === window.generation_id && file.generation_id === window.generation_id
    && file.input_hash === window.input_hash && file.pack_version === window.pack_version
    && file.baseline_version === window.baseline_version && file.parameter_version === window.parameter_version);
}

function pressureReadings(rows: CanonicalObservation[], window: WindowSnapshot): CanonicalObservation[] {
  const start = Date.parse(window.window_start), end = Date.parse(window.window_end);
  return rows.filter(row => row.channel === "pressure"
    && Date.parse(row.observed_at) >= start && Date.parse(row.observed_at) < end)
    .sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at));
}

// Only saved, matched report mappings provide issue labels/inspection intervals.
// A failed lookup or incomplete mapping cannot be replaced with detector diagnoses.
function agentCompanion(container: HTMLElement, state: SensorInspection): void {
  const panel = node("section", "", "inspection-agent");
  panel.append(node("h3", "3 · What does the accepted agent report say?"),
    node("p", "Use the report as an explanation to check against the measurements, not as confirmation of a leak or hardware fault.", "muted"));
  const window = state.window!, sensor = state.sensor!;
  if (state.reportError) panel.append(node("p", `Report lookup unavailable: ${state.reportError}. No agent findings are substituted.`, "summary"));
  const matching = state.pending ? [] : state.reports.filter((detail): detail is TaskDetail =>
    detail !== null && inspectionReportMatches(detail, window));
  const matched = matching.find(detail => detail.output_mapping?.status === "completed") || matching[0];
  const report = matched?.casefile;
  if (matched && report?.interpretation) {
    panel.dataset.status = "matched"; panel.dataset.snapshot = window.id; panel.dataset.task = matched.task.id;
    panel.append(node("p", `Report and readings use the same window: ${bounds(window.window_start, window.window_end)} · revision ${window.revision}.`,
      "inspection-report-basis"));
    if (!report.interpretation_review) panel.append(node("p", "Archived report: no current-protocol grounding review.", "muted"));
    const mapping = matched.output_mapping?.status === "completed" ? matched.output_mapping.mapping : null;
    const issues = mapping?.sensor_issues.filter(item => item.sensor_id === sensor.id) || [];
    const leaks = mapping?.leaks.filter(item => item.segment_id === sensor.segment_id) || [];
    for (const issue of issues) panel.append(node("h4",
      `${sensor.id}: ${friendly(issue.kind)} · ${issue.assertion}${issue.kind === "missing" ? " readings, not a hardware-fault diagnosis" : " measurement concern"}`),
      node("blockquote", issue.quote.text, "inspection-agent-quote"));
    for (const leak of leaks) panel.append(node("h4",
      `${sensor.segment_id}: ${leak.assertion} leak finding${leak.interval ? ` · inspection ${leak.interval.start_m}–${leak.interval.end_m} m, not an exact leak point` : " · no inspection interval stated"}`),
      node("blockquote", leak.quote.text, "inspection-agent-quote"));
    if (!mapping) panel.append(node("p", "Sensor-specific extraction is unavailable. Read the accepted report below; no instrument diagnosis is inferred from the orange alerts."));
    else if (!issues.length && !leaks.length) panel.append(node("p",
      `No specific instrument issue or leak branch finding is extracted for ${sensor.id}. This is not evidence that the sensor or pipeline is healthy.`));
    const full = node("details");
    full.append(node("summary", "Read the accepted incident report"),
      node("p", reportText(report.interpretation.answer.text, report.interpretation.answer.references), "inspection-report-text"));
    panel.append(full, button("Review this report's sources and execution", () => state.openReport(matched.task.id)));
  } else {
    panel.dataset.status = state.pending ? "pending" : "unavailable";
    panel.append(node("p", state.pending
      ? "An investigation is still running for this window. Its draft is provisional; inspect the readings without waiting for an accepted answer."
      : "No accepted report matches this measurement window. No agent diagnosis is attached to these readings."));
    const other = state.reports.find(detail => detail?.casefile?.interpretation
      && detail.task.parent_id === null && ["SUCCEEDED", "ABSTAINED"].includes(detail.task.state)
      && detail.task.generation_id === window.generation_id && detail.task.snapshot_id !== window.id);
    if (other?.casefile) {
      panel.dataset.status = "different-window";
      panel.append(node("p", `A report is available for a different window (${bounds(other.casefile.window_start, other.casefile.window_end)}). It is not applied to the readings above.`),
        button("Inspect the report's measurement window", () => state.inspectWindow(other.task.snapshot_id)));
    } else if (!state.pending && state.reports.some(detail => detail?.casefile?.interpretation
      && ["SUCCEEDED", "ABSTAINED"].includes(detail.task.state)
      && detail.task.generation_id === window.generation_id && detail.task.snapshot_id === window.id)) {
      panel.append(node("p", "A recorded report refers to this window ID, but its source identity or versions do not match these readings. Its findings are withheld; inspect its preserved sources before using it."));
    }
  }
  container.append(panel);
}

export function renderSensorInspection(container: HTMLElement, state: SensorInspection): void {
  container.replaceChildren();
  delete container.dataset.sensor; delete container.dataset.snapshot;
  container.setAttribute("aria-busy", String(state.loading));
  const { pack, window, sensor } = state;
  if (!pack || !window || !sensor) {
    container.append(node("p", "Choose a run and a sensor above. No received measurement window is available yet.", "empty"));
    return;
  }
  container.dataset.sensor = sensor.id; container.dataset.snapshot = window.id;
  const basis = node("section", "", "inspection-basis");
  basis.append(node("h3", `${sensor.id} · ${sensor.segment_id} · ${sensor.chainage_m} m`),
    node("p", `Station ${sensor.station_id} · acquisition domain ${sensor.failure_domain_id}`),
    node("p", `Inspecting ${bounds(window.window_start, window.window_end)} · revision ${window.revision}. Choosing Inspect pins a received window, not the live monitoring clock.`));
  container.append(basis);
  if (state.error) {
    container.append(node("p", `Readings unavailable: ${state.error}. No earlier sensor readings are substituted.`, "summary"));
    agentCompanion(container, state); return;
  }
  if (state.loading) {
    container.append(node("p", "Loading this sensor's received readings…", "empty"));
    return;
  }
  const rows = pressureReadings(state.readings, window);
  const usable = rows.filter(row => row.validity === "usable" && row.value !== null);
  const finding = window.quality.findings.find(item => item.sensor_id === sensor.id && item.channel === "pressure");
  // Distinguish received-but-unusable rows from absent sample times. Absence uses
  // the backend expected count minus distinct received timestamps, not raw row count.
  const receivedTimes = new Set(rows.map(row => row.observed_at));
  const metrics = node("dl", "", "inspection-metrics");
  for (const [label, value] of [
    ["Usable readings", String(usable.length)],
    ["Received without usable value", String(rows.length - usable.length)],
    ["No reading received", finding ? String(Math.max(0, finding.expected - receivedTimes.size)) : "Not reported"],
  ]) metrics.append(node("dt", label), node("dd", value));
  container.append(metrics);
  if (window.quality.status === "WARMING_UP") container.append(node("p", "The full monitoring window is still forming; sensor health and pressure causes are not yet assessed.", "muted"));
  const trend = node("section", "", "inspection-trends");
  const readings: InspectionReadings[] = [{ sensor, observations: rows }];
  if (state.peer) readings.push(state.peer);
  const range = sharedPressureRange(readings, window);
  for (const item of readings) {
    const card = node("article"), charts = node("div");
    card.append(node("h3", item.sensor.id), charts);
    renderCharts(charts, { ...item.sensor, channels: ["pressure"] }, item.observations, window, pack.sample_seconds, range);
    trend.append(card);
  }
  container.append(trend);
  if (state.peerSensor) {
    container.append(node("p", state.peerLoading ? `Loading comparison ${state.peerSensor.id} for the same window…`
      : state.peerError ? `Comparison unavailable: ${state.peerError}. No other sensor is substituted.`
        : state.peer ? `${sensor.id} and ${state.peer.sensor.id} share the same time window and pressure scale. ${sensor.failure_domain_id === state.peer.sensor.failure_domain_id
          ? "They share an acquisition domain: paired agreement is not independent verification."
          : "Their declared acquisition domains differ; other shared dependencies remain unknown."}`
          : "No comparison readings loaded.", state.peerError ? "summary" : "muted"));
  }
  const samples = node("section", "", "inspection-samples");
  samples.append(node("h3", "Received readings"),
    node("p", "Pressure values below are normalized to bar and shown to six significant digits. Blank or unusable readings are not filled in. The optional audit retains original precision, units, timestamps and transformations.", "muted"));
  const table = node("table"), head = node("tr"), body = node("tbody");
  table.append(node("caption", `${sensor.id} · received pressure readings in the inspected window`));
  for (const title of ["Measured at (UTC)", "Pressure (bar)", "Reading status"]) {
    const th = node("th", title); th.scope = "col"; head.append(th);
  }
  const thead = node("thead"); thead.append(head);
  for (const row of rows) {
    const tr = node("tr"); tr.dataset.observation = row.id;
    tr.append(node("td", time(row.observed_at)),
      node("td", row.validity === "usable" && row.value !== null ? Number(row.value.toPrecision(6)).toString() : "Unavailable"),
      node("td", row.validity === "usable" && row.value !== null ? "Usable reading" : `Received but unusable · ${friendly(row.validity)}`));
    body.append(tr);
  }
  table.append(thead, body);
  const wrap = node("div", "", "table-wrap"); wrap.append(table); samples.append(wrap);
  if (!rows.length) samples.append(node("p", "No pressure records were received in this window. Absence is a data gap, not zero pressure.", "empty"));
  const grid = node("div", "", "inspection-review-grid");
  grid.append(samples); agentCompanion(grid, state); container.append(grid);
}
