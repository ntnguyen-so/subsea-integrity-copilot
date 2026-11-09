/**
 * Shared schematic symbols/geometry plus recorded truth-vs-report playback.
 * Truth is an evaluation-only layer, never a monitoring input. Agent findings come
 * from admitted quoted report mappings, not browser inference or detector fallbacks.
 * Overall scores cover recorded windows, not just successful review checkpoints.
 */
import { button, node, svg } from "./dom";
import { agentName } from "./agentwork";
import type { CheckedFinding, EvaluationCase, EvaluationReport } from "./evaluation";
import type { ConsoleEvent, InvestigationCase, OutputExtraction, Point, SitePack, WindowSnapshot } from "./types";

interface Issue { sensor_id: string; kind: string }
interface Source { segment_id: string; chainage_m: number; start_seconds?: number }
export interface SpatialFrame {
  source_seconds: number; window_start_seconds: number; snapshot_id: string; input_hash: string;
  review_case_id: string | null;
  truth: { leak_source: Source | null; sensor_issues: Issue[]; operating_change?: { segment_id: string } | null };
  detector: { pressure_anomaly_sensors: string[]; missing_value_sensors: string[]; coverage: number };
  pressure_summaries: Record<string, { baseline_median?: number; recent_pressure_drop_bar?: number; max_score?: number }>;
}
export interface SpatialNetwork {
  id: string; name: string; status: string; pack: SitePack; dataset_sha256: string;
  frames: SpatialFrame[];
}
interface Playback {
  run: string; network: string; seconds: number; playing: boolean; reviewed: boolean;
  investigationSeconds: number; sourceAccumulator: number; holdSeconds: number;
  sensor: string; speed: number; started: boolean;
}
let state: Playback | null = null;
let timer: number | null = null;
export function stopSpatialPlayback(): void {
  if (timer !== null) window.clearInterval(timer);
  timer = null;
}
function original<K extends keyof HTMLElementTagNameMap>(tag: K, value = "", className = ""): HTMLElementTagNameMap[K] {
  const result = node(tag, "", className); result.textContent = value; return result;
}
function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}
function score(value: number | null | undefined): string {
  return value == null ? "Pending" : `${(100 * value).toFixed(1)}%`;
}
function lastFrame(network: SpatialNetwork): SpatialFrame | undefined {
  return network.frames[network.frames.length - 1];
}
function matchingReview(report: EvaluationReport, frame: SpatialFrame): EvaluationCase | undefined {
  return report.cases.find(row => row.case_id === frame.review_case_id
    && row.source_seconds === frame.source_seconds
    && row.snapshot_id === frame.snapshot_id && row.input_hash === frame.input_hash);
}
/** Release only source/snapshot/hash-matched accepted reports with completed extraction. */
export function releasedReview(report: EvaluationReport, frame: SpatialFrame, reviewed: boolean): EvaluationCase | undefined {
  const row = matchingReview(report, frame);
  return reviewed && row?.status === "completed" && row.accepted_report
    && row.extraction?.status === "completed" && row.extraction.mapping ? row : undefined;
}
function resultAdmitted(row: EvaluationCase): boolean {
  return row.status === "failed" || row.status === "completed" && (
    !row.root_count || Boolean(row.accepted_report && row.extraction?.status === "completed"
      && row.extraction.mapping)
  );
}
function checkedWarning(row: EvaluationCase | undefined, frame: SpatialFrame, seconds: number): CheckedFinding | undefined {
  const origin = Date.parse(row?.agent_started_at || row?.agent_tasks?.find(task => task.id === row.root_id)?.created_at || "");
  return row?.agent_tasks?.find(task => {
    const finding = task.checked_finding;
    return task.role === "event_diagnosis" && task.state === "SUCCEEDED"
      && task.root_id === row.root_id && task.snapshot_id === frame.snapshot_id
      && finding?.snapshot_id === frame.snapshot_id && finding.input_hash === frame.input_hash
      && finding.hypothesis === "suspected_leak" && finding.final_report === false
      && (Date.parse(finding.available_at) - origin) / 1000 <= seconds;
  })?.checked_finding || undefined;
}
interface DisplayFindings {
  frame: SpatialFrame; row: EvaluationCase; review: EvaluationCase;
}
// Keep the most recent admitted report through failed/unreviewed periods. A newer
// admitted negative report replaces it; future findings cannot backfill earlier time.
function latestFindings(
  report: EvaluationReport, network: SpatialNetwork, current: SpatialFrame,
  reviewed: boolean,
): DisplayFindings | undefined {
  for (const frame of [...network.frames].reverse()) {
    if (frame !== current && frame.source_seconds >= current.source_seconds) continue;
    const row = matchingReview(report, frame);
    if (!row || row.network_id !== network.id) continue;
    const review = releasedReview(report, frame, frame === current ? reviewed : true);
    if (review) return { frame, row, review };
  }
  return undefined;
}
function findingCounts(expected: string[], reported: string[]): { tp: number; fp: number; fn: number; missed: string[]; falseAlarms: string[] } {
  const truth = new Set(expected), predictions = new Set(reported);
  const missed = [...truth].filter(value => !predictions.has(value));
  const falseAlarms = [...predictions].filter(value => !truth.has(value));
  return { tp: truth.size - missed.length, fp: falseAlarms.length, fn: missed.length, missed, falseAlarms };
}
// Set-based units differ: leak existence, branch, sensor and sensor/type. Missing-only
// issues are not hardware faults; they remain included in the separate issue-type unit.
function snapshotScores(frame: SpatialFrame, review: EvaluationCase | undefined) {
  const mapping = review?.extraction?.mapping;
  const source = frame.truth.leak_source;
  const knownFaults = frame.truth.sensor_issues.filter(item => item.kind !== "missing");
  const reportedFaults = mapping?.sensor_issues.filter(item => item.kind !== "missing") || [];
  return {
    leak_recognition: findingCounts(source ? ["leak"] : [], mapping?.leaks.length ? ["leak"] : []),
    agent_pipeline_identification: findingCounts(source ? [source.segment_id] : [], mapping?.leaks.map(item => item.segment_id) || []),
    agent_sensor_concerns: findingCounts(knownFaults.map(item => item.sensor_id), reportedFaults.map(item => item.sensor_id)),
    issueTypes: findingCounts(
      frame.truth.sensor_issues.map(item => `${item.sensor_id} (${item.kind})`),
      mapping?.sensor_issues.map(item => `${item.sensor_id} (${item.kind})`) || [],
    ),
  };
}
function recall(counts: { tp: number; fn: number }): string {
  return counts.tp + counts.fn ? score(counts.tp / (counts.tp + counts.fn)) : "Not applicable";
}
/** Draw only intervals stated in report mappings; never substitute a numerical fit. */
export function reportedInspectionIntervals(
  mapping: Pick<NonNullable<OutputExtraction["mapping"]>, "leaks"> | null | undefined,
): NonNullable<InvestigationCase["inspection"]>[] {
  return (mapping?.leaks || []).flatMap(leak => leak.interval
    ? [{ segment_id: leak.segment_id, ...leak.interval }] : []);
}
// Scoring uses the first stated interval and rejects empty/>400m bands; drawing
// all report intervals is distinct from qualifying one interval for scoring.
function scoredInspection(review: EvaluationCase | undefined): NonNullable<InvestigationCase["inspection"]> | undefined {
  const interval = reportedInspectionIntervals(review?.extraction?.mapping)[0];
  return interval && interval.end_m > interval.start_m && interval.end_m - interval.start_m <= 400
    ? interval : undefined;
}
function emptyScores() {
  return {
    groups: {
      leak_recognition: findingCounts([], []), agent_pipeline_identification: findingCounts([], []),
      agent_sensor_concerns: findingCounts([], []), issueTypes: findingCounts([], []),
    },
    windows: 0, leakWindows: 0, noLeakWindows: 0, containedWindows: 0, unsupportedIntervals: 0,
  };
}
/**
 * Aggregate every captured frame across networks, carrying only earlier admitted
 * findings. Unreviewed leak windows count as misses; no-leak windows are the false
 * alarm denominator. Correlated overlapping windows are not independent trials.
 */
function overallScores(report: EvaluationReport) {
  const overall = emptyScores();
  const cases = (report.networks || []).map(network => {
    const caseTotals = emptyScores();
    let review: EvaluationCase | undefined;
    const snapshots = [...network.frames].sort((a, b) => a.source_seconds - b.source_seconds).map(frame => {
      const admitted = releasedReview(report, frame, true);
      const currentReview = admitted?.network_id === network.id ? admitted :
        review?.source_seconds != null && review.source_seconds < frame.source_seconds ? review : undefined;
      if (admitted?.network_id === network.id) review = admitted;
      const scores = snapshotScores(frame, currentReview);
      const interval = scoredInspection(currentReview), source = frame.truth.leak_source;
      const contained = Boolean(source && interval && interval.segment_id === source.segment_id
        && interval.start_m <= source.chainage_m && source.chainage_m <= interval.end_m
        && network.pack.segments.some(segment => segment.id === interval.segment_id
          && interval.start_m >= 0 && interval.end_m <= segment.length_m));
      const unsupportedInterval = Boolean(interval && !contained);
      for (const totals of [overall, caseTotals]) {
        for (const key of ["leak_recognition", "agent_pipeline_identification", "agent_sensor_concerns", "issueTypes"] as const) {
          const total = totals.groups[key], result = scores[key];
          total.tp += result.tp; total.fp += result.fp; total.fn += result.fn;
          total.missed.push(...result.missed.map(value => `${network.id}: ${value}`));
          total.falseAlarms.push(...result.falseAlarms.map(value => `${network.id}: ${value}`));
        }
        totals.windows += 1;
        totals.leakWindows += Number(Boolean(source)); totals.containedWindows += Number(contained);
        totals.noLeakWindows += Number(!source);
        totals.unsupportedIntervals += Number(unsupportedInterval);
      }
      return { frame, review: currentReview, scores, contained, unsupportedInterval };
    });
    return { network, totals: caseTotals, snapshots };
  });
  return { ...overall, cases };
}
function renderScoreDetails(report: EvaluationReport, overall: ReturnType<typeof overallScores>): HTMLElement {
  const details = original("details", "", "spatial-metric-details");
  details.open = true;
  details.append(original("summary", "Detailed metrics · case totals and every snapshot"),
    original("p", "TP = correctly reported; FN = missed; FP = false alarm. Recall = TP / (TP + FN); precision = TP / (TP + FP). Sensor recall excludes missing-only readings; issue-type recall includes them. Not applicable means no eligible denominator, not perfect detection. Retained reports are not new investigations; unreviewed no-leak windows are not proof of health.", "muted"));
  function table(title: string, headers: readonly (readonly [string, string])[]) {
    const wrapper = original("div", "", "table-wrap spatial-metric-table");
    wrapper.tabIndex = 0;
    wrapper.setAttribute("role", "region"); wrapper.setAttribute("aria-label", `${title} scroll area`);
    const result = original("table");
    const heading = original("tr");
    for (const [label, explanation] of headers) {
      const cell = original("th", label);
      cell.scope = "col"; cell.title = explanation; cell.tabIndex = 0;
      cell.setAttribute("aria-description", explanation);
      heading.append(cell);
    }
    const head = original("thead"); head.append(heading);
    const body = original("tbody");
    result.append(original("caption", title), head, body);
    wrapper.append(result); details.append(wrapper);
    return body;
  }
  function detectionCells(groups: ReturnType<typeof snapshotScores>, windows: number): HTMLTableCellElement[] {
    return (["leak_recognition", "agent_pipeline_identification", "agent_sensor_concerns", "issueTypes"] as const).map(key => {
      const result = groups[key], cell = original("td");
      cell.dataset.metric = key;
      cell.append(original("strong", windows ? `${recall(result)} (${result.tp}/${result.tp + result.fn})` : "Pending"),
        original("span", windows ? `TP ${result.tp} · FN ${result.fn} · FP ${result.fp}` : "No recorded windows", "muted"),
        original("span", windows ? `Precision: ${result.tp + result.fp ? score(result.tp / (result.tp + result.fp)) : "Not applicable"}` : "", "muted"));
      return cell;
    });
  }
  function rateCell(numerator: number, denominator: number, windows: number): HTMLTableCellElement {
    return original("td", windows ? `${denominator ? score(numerator / denominator) : "Not applicable"} (${numerator}/${denominator})` : "Pending");
  }
  const caseHeader = ["Case", "The recorded network scenario, such as N1, N2 or N3. Each case is scored separately against its own ground truth."] as const;
  const metricHeaders = [
    ["Leak recall", "Leak-present snapshots with an admitted leak report / all leak-present snapshots: TP / (TP + FN). This does not require the correct branch. Unreviewed leak windows count as misses; retained reports count, not as new investigations."],
    ["Correct branch recall", "Correctly reported leaking branches / known leaking branches, counted per snapshot: TP / (TP + FN). Naming P5 or P6 is not locating the exact leak point. Wrong additional branches count as false alarms and lower precision, not recall."],
    ["Fault sensor recall", "Correctly reported faulty sensor IDs / known faulty sensor IDs, counted per snapshot: TP / (TP + FN). Excludes missing-only readings. A sensor can count as identified even if its reported fault type is wrong. FN = missed sensors; FP = false sensor alarms."],
    ["All issue-type recall", "Correct sensor ID AND issue-type matches / all known sensor/type pairs, counted per snapshot: TP / (TP + FN). Includes missing readings. A correct sensor with the wrong type produces a missed true type and a false reported type."],
    ["Leak false-positive rate", "No-leak snapshots with an admitted leak report / all no-leak snapshots. Retained false reports count until a newer admitted reassessment clears them. Not applicable when there are no no-leak windows; zero false alarms in unreviewed windows is not proof of health."],
    ["Source containment", "Leak-present snapshots with the known source inside the incident report's extracted inspection interval of at most 400 m on the correct branch / all leak-present snapshots. This scoring criterion measures interval coverage, not exact leak-point accuracy or site authorization."],
  ] as const;
  const caseBody = table("Metrics by case", [
    caseHeader,
    ["Recorded coverage", "Recorded source windows, fresh admitted reviews, windows using retained earlier reports, and windows without an admitted report. Case totals sum snapshot counts, not unique instruments or independent investigations. Later reports never backfill earlier misses."],
    ...metricHeaders,
  ]);
  const snapshotBody = table("Metrics by snapshot", [
    caseHeader,
    ["Source window", "Replay/simulation source time, not model wall time. The bounds identify the data interval for this snapshot. Source time stays fixed while an investigation and result admission run."],
    ["Agent report used", "The latest final accepted, source-matched mapped report available for this window. Retained means older findings carried forward, not a new investigation. Failed, mismatched and unaccepted reviews do not replace valid earlier findings."],
    ...metricHeaders,
    ["Audit details", "Expand to inspect missed fault sensors, missing or incorrectly reported issue types, wrong branches and false alarms, plus the snapshot ID and input hash. Comparisons use this snapshot's truth and the report listed in Agent report used."],
  ]);
  for (const { network, totals, snapshots } of overall.cases) {
    const fresh = snapshots.filter(item => item.review?.source_seconds === item.frame.source_seconds).length;
    const retained = snapshots.filter(item => item.review && item.review.source_seconds !== item.frame.source_seconds).length;
    const caseRow = original("tr"); caseRow.dataset.network = network.id;
    caseRow.append(original("th", network.id),
      original("td", `${totals.windows} windows · ${fresh} fresh reviews · ${retained} retained · ${totals.windows - fresh - retained} without an admitted report\nRecording: ${network.status}`),
      ...detectionCells(totals.groups, totals.windows),
      rateCell(totals.groups.leak_recognition.fp, totals.noLeakWindows, totals.windows),
      rateCell(totals.containedWindows, totals.leakWindows, totals.windows));
    caseRow.firstElementChild?.setAttribute("scope", "row");
    caseRow.lastElementChild?.append(original("span", `${totals.unsupportedIntervals} unsupported interval windows`, "muted"));
    caseBody.append(caseRow);
    for (const { frame, review, scores, contained, unsupportedInterval } of snapshots) {
      const row = original("tr"); row.dataset.network = network.id; row.dataset.sourceSeconds = String(frame.source_seconds);
      const recorded = matchingReview(report, frame);
      let reviewStatus = "No review at this snapshot";
      if (frame.review_case_id && (!recorded || recorded.network_id !== network.id)) reviewStatus = "Mismatched review; not used";
      else if (recorded?.status === "failed") reviewStatus = `Failed review: ${recorded.error_code || "no error code recorded"}`;
      else if (recorded?.root_count === 0) reviewStatus = "No agent review; numerical monitoring only";
      else if (recorded && recorded !== review) reviewStatus = recorded.status !== "completed" ?
        `Review ${recorded.status}; not admitted` : !recorded.accepted_report ? "Report not accepted" :
          `Mapping ${recorded.extraction?.status || "not recorded"}; not admitted${recorded.extraction?.error_code ? `: ${recorded.extraction.error_code}` : ""}`;
      else if (recorded === review && review) reviewStatus = "New admitted report";
      const provenance = original("td");
      provenance.append(original("strong", review?.source_seconds != null ? `${review.source_seconds === frame.source_seconds ? "Admitted at" : "Retained from"} ${clock(review.source_seconds)}` : "No admitted report"),
        original("span", reviewStatus, reviewStatus.startsWith("Failed") || reviewStatus.startsWith("Mismatched") ? "evaluation-warning" : "muted"));
      if (review) provenance.append(original("code", review.case_id));
      row.append(original("th", network.id), original("td", `${clock(frame.source_seconds)} (${frame.source_seconds}s)\nWindow ${clock(frame.window_start_seconds)}–${clock(frame.source_seconds)}`),
        provenance, ...detectionCells(scores, 1),
        rateCell(scores.leak_recognition.fp, Number(!frame.truth.leak_source), 1),
        rateCell(Number(contained), Number(Boolean(frame.truth.leak_source)), 1));
      row.firstElementChild?.setAttribute("scope", "row");
      row.lastElementChild?.append(original("span", unsupportedInterval ? "Unsupported interval" : "No unsupported interval", "muted"));
      const audit = original("details");
      audit.append(original("summary", `${scores.agent_sensor_concerns.fn} missed · ${scores.agent_sensor_concerns.fp} false sensor alarms`));
      for (const [label, result] of [
        ["Leak", scores.leak_recognition], ["Branch", scores.agent_pipeline_identification],
        ["Fault sensors", scores.agent_sensor_concerns], ["Issue types", scores.issueTypes],
      ] as const) audit.append(original("p", `${label} missed: ${result.missed.join("; ") || "none"}. False alarms: ${result.falseAlarms.join("; ") || "none"}.`));
      audit.append(original("p", `Truth leak: ${frame.truth.leak_source?.segment_id || "none"}. Reported leak branches: ${review?.extraction?.mapping?.leaks.map(item => item.segment_id).join("; ") || "none"}.`),
        original("p", `Snapshot: ${frame.snapshot_id}\nInput hash: ${frame.input_hash}`, "evaluation-hash"));
      const auditCell = original("td"); auditCell.append(audit); row.append(auditCell);
      snapshotBody.append(row);
    }
  }
  if (!overall.windows) {
    const row = original("tr"), cell = original("td", "No recorded source windows. Snapshot metrics are pending.");
    cell.colSpan = 10; row.append(cell); snapshotBody.append(row);
  }
  return details;
}
// Warm-up/no finding means unassessed, never a healthy instrument or a missing-data diagnosis.
export function sensorAssessment(snapshot: WindowSnapshot | null, sensorId: string): {
  assessed: boolean; missing: boolean; anomaly: boolean;
} {
  const findings = snapshot?.quality.findings.filter(item => item.sensor_id === sensorId) || [];
  const assessed = Boolean(snapshot && snapshot.quality.status !== "WARMING_UP" && findings.length);
  return {
    assessed,
    missing: assessed && findings.some(item => item.missing > 0 || item.hard_excluded > 0),
    anomaly: assessed && findings.some(item => item.anomaly_count > 0),
  };
}

export function sensorSymbol(
  point: Point, flags: { anomaly?: boolean; missing?: boolean; issue?: "known" | "agent"; selected?: boolean; unknown?: boolean },
): SVGGElement {
  const group = svg("g", {
    class: `sensor eval-sensor${flags.anomaly ? " anomalous" : ""}${flags.missing ? " missing" : ""}${flags.unknown ? " unknown" : ""}`,
  });
  if (flags.issue) group.append(svg("circle", {
    cx: point.x, cy: point.y, r: 10, class: flags.issue === "known" ? "eval-known-issue" : "eval-agent-issue",
  }));
  group.append(svg("circle", { cx: point.x, cy: point.y, r: 5.5, class: "sensor-dot" }));
  if (flags.selected) group.append(svg("circle", { cx: point.x, cy: point.y, r: 14, class: "eval-selection" }));
  return group;
}
export function mapLegend(truth: boolean, options: {
  label?: string; visibleKinds?: readonly string[]; unknown?: boolean; selectionDetail?: string;
} = {}): HTMLElement {
  const legend = original("div", "", "spatial-legend");
  legend.setAttribute("aria-label", options.label || (truth ? "Ground truth map legend" : "Agent findings map legend"));
  const groups = [
    { title: "Pipeline", entries: truth ?
      [["source", "Leak source", "Known injected point"]] :
      [["pattern", "Suspected leak", "Branch flagged in agent report"],
        ["inspection", "Inspection area", "Section recommended for inspection"]] },
    { title: "Instruments", entries: truth ?
      [["known", "Instrument issue", "Known injected fault"],
        ["anomaly", "Pressure alert", "Measured · not a leak diagnosis"],
        ["missing", "Missing / invalid", "Dashed reading outline"],
        ["normal", "No pressure alert", "Not proof of health"],
        ["selection", "Selected sensor", "Linked across both maps"]] :
      [["agent", "Instrument issue", "Agent-identified problem"],
        ["anomaly", "Pressure alert", "Measured · not a leak diagnosis"],
        ["missing", "Missing / invalid", "Dashed reading outline"],
        ["normal", "No pressure alert", "Not proof of health"],
        ["selection", "Selected sensor", "Linked across both maps"]] },
  ];
  if (options.unknown) groups[1].entries.push(["unknown", "Not assessed", "No completed sensor assessment"]);
  for (const { title, entries } of groups) {
    const section = original("section", "", "spatial-legend-group");
    section.append(original("h4", title));
    const items = original("ul", "", "spatial-legend-items");
    for (const [kind, text, detail] of entries) {
      if (options.visibleKinds && !options.visibleKinds.includes(kind)) continue;
      const item = original("li", "", "spatial-legend-item");
      item.dataset.legend = kind;
      const label = original("div", "", "spatial-legend-label");
      label.append(original("strong", text), original("small", kind === "selection" ? options.selectionDetail || detail : detail));
      const symbol = svg("svg", { viewBox: "0 0 50 44", width: 30, height: 28, "aria-hidden": "true" });
      if (kind === "source") {
        const marker = svg("g", { class: "eval-source" });
        marker.append(svg("circle", { cx: 25, cy: 22, r: 17 }),
          svg("path", { d: "M14 22H36M25 11V33" }));
        symbol.append(marker);
      } else if (kind === "pattern" || kind === "inspection") {
        symbol.append(svg("line", { x1: 6, y1: 22, x2: 44, y2: 22,
          class: kind === "pattern" ? "pipe eval-leak-pattern" : "eval-inspection" }));
      } else {
        symbol.append(sensorSymbol({ x: 25, y: 22 }, {
          anomaly: kind === "anomaly", missing: kind === "missing",
          issue: kind === "known" ? "known" : kind === "agent" ? "agent" : undefined,
          selected: kind === "selection",
          unknown: kind === "unknown",
        }));
      }
      item.append(symbol, label); items.append(item);
    }
    if (items.childElementCount) { section.append(items); legend.append(section); }
  }
  return legend;
}
// Preserve aspect ratio, center the pack and invert Cartesian y for SVG coordinates.
// Paired-instrument screen offsets do not change physical chainage or uncertainty.
function geometry(pack: SitePack): (point: Point) => Point {
  const points = pack.segments.flatMap(segment => segment.points);
  const xmin = Math.min(...points.map(point => point.x)), xmax = Math.max(...points.map(point => point.x));
  const ymin = Math.min(...points.map(point => point.y)), ymax = Math.max(...points.map(point => point.y));
  const scale = Math.min(650 / Math.max(xmax - xmin, 1), 390 / Math.max(ymax - ymin, 1));
  return point => ({
    x: 55 + (point.x - xmin) * scale + (650 - (xmax - xmin) * scale) / 2,
    y: 65 + (ymax - point.y) * scale + (390 - (ymax - ymin) * scale) / 2,
  });
}
/** Interpolate along pack endpoints; reject out-of-range chainage rather than clamp it. */
function pipelinePoint(pack: SitePack, id: string, chainage: number, project: (point: Point) => Point): Point | null {
  const segment = pack.segments.find(item => item.id === id);
  if (!segment || chainage < 0 || chainage > segment.length_m) return null;
  const start = project(segment.points[0]), end = project(segment.points[segment.points.length - 1]);
  const fraction = chainage / segment.length_m;
  return { x: start.x + (end.x - start.x) * fraction, y: start.y + (end.y - start.y) * fraction };
}

interface AcceptedMapFindings {
  leaks: { segment_id: string }[];
  issues: Issue[];
  inspections: NonNullable<InvestigationCase["inspection"]>[];
}
function drawMap(map: SVGSVGElement, pack: SitePack, frame: SpatialFrame, review: EvaluationCase | undefined,
  truth: boolean, selected: string, select: (id: string) => void,
  findingsFrame: SpatialFrame = frame, accepted?: AcceptedMapFindings,
  assessedSensors?: ReadonlySet<string>): void {
  const project = geometry(pack);
  map.replaceChildren(svg("title", {}, truth ? "Known source labels, withheld from agents" :
    `Measured flags at ${clock(frame.source_seconds)}; ${review || accepted ?
      `last released agent findings at ${clock(findingsFrame.source_seconds)}` : "no released agent findings"}`));
  map.dataset.sourceSeconds = String(frame.source_seconds);
  map.dataset.snapshot = frame.snapshot_id;
  if (!truth && (review || accepted)) {
    map.dataset.findingsSourceSeconds = String(findingsFrame.source_seconds);
    map.dataset.findingsSnapshot = findingsFrame.snapshot_id;
  } else {
    delete map.dataset.findingsSourceSeconds; delete map.dataset.findingsSnapshot;
  }
  for (let x = 40; x < 760; x += 40) map.append(svg("line", { x1: x, y1: 30, x2: x, y2: 490, class: "eval-grid" }));
  for (let y = 30; y < 510; y += 40) map.append(svg("line", { x1: 30, y1: y, x2: 730, y2: y, class: "eval-grid" }));
  const leaks = accepted?.leaks || review?.extraction?.mapping?.leaks || [];
  for (const segment of pack.segments) {
    const points = segment.points.map(project);
    const pattern = !truth && leaks.some(item => item.segment_id === segment.id);
    map.append(svg("polyline", {
      points: points.map(point => `${point.x},${point.y}`).join(" "),
      class: `pipe${pattern ? " eval-leak-pattern" : ""}`, "data-segment-id": segment.id,
    }));
    const label = segment.id === "P1" ? points[0] : points[points.length - 1];
    map.append(svg("text", { x: label.x, y: label.y + (segment.id === "P1" ? 30 : -25), "text-anchor": "middle", class: "eval-pipe-label" }, segment.id));
  }
  if (truth && frame.truth.leak_source) {
    const source = frame.truth.leak_source;
    const point = pipelinePoint(pack, source.segment_id, source.chainage_m, project);
    if (point) {
      const marker = svg("g", { class: "eval-source", "data-segment-id": source.segment_id, "data-chainage-m": source.chainage_m });
      marker.append(svg("circle", { cx: point.x, cy: point.y, r: 19 }),
        svg("path", { d: `M${point.x - 11} ${point.y}H${point.x + 11}M${point.x} ${point.y - 11}V${point.y + 11}` }),
        svg("title", {}, `Known leak source: ${source.segment_id}, ${source.chainage_m} m. This label is not given to agents.`));
      map.append(marker);
    }
  }
  const inspections = accepted?.inspections || reportedInspectionIntervals(review?.extraction?.mapping);
  for (const reported of truth ? [] : inspections) {
    const start = pipelinePoint(pack, reported.segment_id, reported.start_m, project);
    const end = pipelinePoint(pack, reported.segment_id, reported.end_m, project);
    if (start && end) {
      const interval = svg("polyline", { points: `${start.x},${start.y} ${end.x},${end.y}`, class: "eval-inspection",
        "data-segment-id": reported.segment_id, "data-start-m": reported.start_m, "data-end-m": reported.end_m });
      interval.append(svg("title", {}, `Incident-report inspection interval at ${clock(findingsFrame.source_seconds)}: ${reported.segment_id}, ${reported.start_m}–${reported.end_m} m; not an exact leak point or site authorization.`));
      map.append(interval);
    }
  }
  const issues = truth ? frame.truth.sensor_issues : accepted?.issues || review?.extraction?.mapping?.sensor_issues || [];
  for (const [index, sensor] of pack.sensors.entries()) {
    const segment = pack.segments.find(item => item.id === sensor.segment_id);
    if (!segment) continue;
    const at = pipelinePoint(pack, segment.id, sensor.chainage_m, project);
    if (!at) continue;
    const a = project(segment.points[0]), b = project(segment.points[segment.points.length - 1]);
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    const side = sensor.id.endsWith("-A") ? -1 : 1;
    const point = { x: at.x - side * (b.y - a.y) / length * 10, y: at.y + side * (b.x - a.x) / length * 10 };
    const kinds = issues.filter(item => item.sensor_id === sensor.id).map(item => item.kind);
    const unknown = assessedSensors !== undefined && !assessedSensors.has(sensor.id);
    const fault = !unknown && kinds.some(kind => kind !== "missing");
    const missing = !unknown && (frame.detector.missing_value_sensors.includes(sensor.id)
      || truth && kinds.some(kind => ["missing", "invalid"].includes(kind)));
    const anomaly = !unknown && frame.detector.pressure_anomaly_sensors.includes(sensor.id);
    const description = unknown ? "Not assessed. Collecting a complete monitoring window; no missing-data or pressure diagnosis yet."
      : `${anomaly ? "Pressure anomaly. " : ""}${missing ? "Missing / invalid readings. " : ""}${truth ?
      kinds.length ? `Known instrument issue: ${kinds.join(", ")}.` : "No injected instrument problem." :
      fault ? `Agent identified ${kinds.join(", ")} at ${clock(findingsFrame.source_seconds)}.` : "No accepted instrument issue recorded."}`;
    const group = sensorSymbol(point, {
      anomaly, missing, unknown, issue: fault ? truth ? "known" : "agent" : undefined, selected: sensor.id === selected,
    });
    group.dataset.sensor = sensor.id; group.dataset.issueKinds = kinds.join(",");
    group.setAttribute("role", "button"); group.setAttribute("tabindex", "0");
    group.setAttribute("aria-label", `${sensor.id}, ${sensor.segment_id}, ${sensor.chainage_m} m. ${description}`);
    group.setAttribute("aria-pressed", String(sensor.id === selected));
    group.append(svg("title", {}, `${sensor.id} / ${sensor.station_id} / ${sensor.failure_domain_id}. ${description}`));
    group.addEventListener("click", () => select(sensor.id));
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(sensor.id); }
      if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? pack.sensors.length - 1 :
          (index + (["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 1) + pack.sensors.length) % pack.sensors.length;
        map.querySelectorAll<SVGGElement>("[data-sensor]")[next]?.focus();
      }
    });
    map.append(group);
  }
  if (!truth) {
    for (const segmentId of new Set(leaks.map(item => item.segment_id))) {
      const segment = pack.segments.find(item => item.id === segmentId);
      if (!segment) continue;
      const anchor = project(segment.points[segment.points.length - 1]);
      map.append(svg("text", { x: anchor.x, y: anchor.y - 43,
        "text-anchor": "middle", class: "eval-leak-label", "data-leak-label": segmentId },
      `Suspected leak · ${segmentId}`));
    }
  }
}

/** Enforce the report's exact immutable basis before layering report findings on measured flags. */
export function drawInvestigationMap(
  map: SVGSVGElement, pack: SitePack, snapshot: WindowSnapshot,
  file: InvestigationCase | null, selected: string, select: (id: string) => void,
  extraction: OutputExtraction | null = null,
): void {
  if (file && (file.snapshot_id !== snapshot.id || file.input_hash !== snapshot.input_hash
    || file.pack_version !== pack.version || file.generation_id !== snapshot.generation_id)) {
    throw new Error("Agent map requires the report's exact immutable evidence");
  }
  const assessments = pack.sensors.map(sensor => ({
    id: sensor.id, ...sensorAssessment(snapshot, sensor.id),
  }));
  const assessedSensors = new Set(assessments.filter(item => item.assessed).map(item => item.id));
  const frame: SpatialFrame = {
    source_seconds: snapshot.end_seconds, window_start_seconds: snapshot.end_seconds - pack.window_seconds,
    snapshot_id: snapshot.id, input_hash: snapshot.input_hash, review_case_id: null,
    truth: { leak_source: null, sensor_issues: [] }, pressure_summaries: {},
    detector: {
      pressure_anomaly_sensors: assessments.filter(item => item.anomaly).map(item => item.id),
      missing_value_sensors: assessments.filter(item => item.missing).map(item => item.id),
      coverage: snapshot.quality.coverage,
    },
  };
  const mapping = file?.state === "SUCCEEDED" && extraction?.status === "completed"
    ? extraction.mapping : null;
  const leakSegments = mapping?.leaks.map(item => item.segment_id) || [];
  const accepted = file?.state === "SUCCEEDED" && mapping && snapshot.quality.status !== "WARMING_UP" ? {
    leaks: leakSegments.map(segment_id => ({ segment_id })),
    issues: mapping?.sensor_issues || [],
    inspections: reportedInspectionIntervals(mapping),
  } : undefined;
  drawMap(map, pack, frame, undefined, false, selected, select, frame, accepted, assessedSensors);
  if (snapshot.quality.status === "WARMING_UP") {
    map.querySelector("title")!.textContent = "Collecting a complete monitoring window. Sensors are not assessed; no missing-data diagnosis or agent findings.";
  }
}

function publicUpdate(event: ConsoleEvent): string {
  const payload = event.payload;
  if (event.type === "agent.handoff_requested") return `Response Coordinator → ${agentName(String(payload.to_role))}: ${payload.reason || "Specialist checks requested"}`;
  if (event.type === "answer.checked") return `Checked handoff: ${payload.public_output || "Findings passed to the next agent"}`;
  if (event.type === "agent.review_requested") return "Grounding Reviewer checks the coordinator's draft against cited evidence.";
  if (event.type === "answer.critique") return payload.decision === "accept" ? "Evidence wording accepted." : "Reviewer requested evidence corrections.";
  if (event.type === "agent.draft") return `Draft, not yet accepted: ${String(payload.text || "").slice(0, 500)}`;
  return `${payload.title || "Evidence check"}: ${payload.observation || payload.purpose || "Recorded check"}`;
}
const journalTypes = new Set(["agent.check_started", "agent.check_completed", "agent.handoff_requested", "agent.draft", "agent.review_requested", "answer.checked", "answer.critique"]);

// Two clocks replay captured source windows and recorded agent wall-time admission.
// Pauses/loading hold evidence at its boundary; replay does not execute the agents.
export function renderSpatialEvaluation(container: HTMLElement, report: EvaluationReport): void {
  stopSpatialPlayback();
  const networks = report.networks || [];
  if (!networks.length) { container.append(original("p", "No extended-network recordings are available.", "empty")); return; }
  if (!state || state.run !== report.run_id) {
    const accepted = report.cases.filter(row => row.network_id === networks[0].id && row.accepted_report
      && row.extraction?.status === "completed");
    state = {
      run: report.run_id || "", network: networks[0].id,
      seconds: accepted[accepted.length - 1]?.source_seconds || lastFrame(networks[0])?.source_seconds || 60, playing: false,
      reviewed: true, investigationSeconds: 0, sourceAccumulator: 0, holdSeconds: 0,
      sensor: "", speed: 30, started: false,
    };
  }
  const playback = state;
  const heading = original("div", "", "spatial-heading");
  // The descriptive scale below is the authored S7 suite contract, not discovered
  // from arbitrary packs. Actual scored counts come from captured frames below.
  heading.append(original("strong", `S7-scale evaluation · ${report.split === "held_out" ? "held-out" : "development"}`),
    original("span", `${networks.length} recordings · 112 instruments each · 7 branches · 11.2 km · 6 minutes`, "muted"));
  container.append(heading);
  const scorecards = original("div", "", "spatial-scorecards");
  scorecards.setAttribute("role", "group");
  scorecards.setAttribute("aria-label", "Overall evaluation scores");
  const overall = overallScores(report);
  const overallCards = ([
    ["leak_recognition", "Leak recognition · recall"],
    ["agent_pipeline_identification", "Correct branch · recall"],
    ["agent_sensor_concerns", "Instrument faults · sensor recall"],
  ] as const).map(([key, title]) => {
    const card = original("div");
    card.dataset.metric = key;
    const result = overall.groups[key];
    const value = original("strong", overall.windows ? recall(result) : "Pending");
    const counts = original("span", overall.windows ?
      `${result.tp}/${result.tp + result.fn} covered · ${result.fn} uncovered · ${result.fp} false alarms · precision ${result.tp + result.fp ? score(result.tp / (result.tp + result.fp)) : "not applicable"}` :
      "No recorded source windows", "muted");
    card.append(original("small", title), value, counts);
    scorecards.append(card);
    return { key, card, value, counts };
  });
  const instrumentTypes = original("span", overall.windows ?
    `All issue-type recall: ${recall(overall.groups.issueTypes)} · ${overall.groups.issueTypes.tp}/${overall.groups.issueTypes.tp + overall.groups.issueTypes.fn} covered (includes missing readings)` :
    "", "spatial-type-score muted");
  overallCards[2].card.append(instrumentTypes);
  const falseLeakCard = original("div");
  falseLeakCard.dataset.metric = "leak_false_positive_rate";
  falseLeakCard.append(original("small", "Leak false-positive rate"),
    original("strong", overall.noLeakWindows ? score(overall.groups.leak_recognition.fp / overall.noLeakWindows) :
      overall.windows ? "Not applicable" : "Pending"),
    original("span", overall.windows ?
      overall.noLeakWindows ? `${overall.groups.leak_recognition.fp}/${overall.noLeakWindows} no-leak windows falsely reported as leakage` :
        "No no-leak windows; false-positive rate cannot be measured" :
      "No recorded source windows", "muted"));
  scorecards.append(falseLeakCard);
  const locationCard = original("div");
  locationCard.dataset.metric = "localization_containment";
  const locationValue = original("strong", overall.windows ? overall.leakWindows ?
    `${overall.containedWindows}/${overall.leakWindows}` : "Not applicable" : "Pending");
  const locationDetail = original("span", overall.windows ?
    `Leak-source windows inside a report-stated ≤400 m interval · ${overall.unsupportedIntervals} unsupported interval windows` :
    "No recorded source windows", "muted");
  locationCard.append(original("small", "Supported localization"), locationValue, locationDetail);
  scorecards.append(locationCard);
  container.append(scorecards);
  const partial = report.status !== "completed" || networks.some(network => network.status !== "completed" || !network.frames.length);
  const scoreBasis = original("p", `Overall results · ${networks.length} cases · ${overall.windows} recorded source windows${partial ? " · partial recording" : ""} · independent of map selection and replay position`, "spatial-score-basis");
  const status = original("p", "Every recorded case/time window is scored against the latest admitted report available at that source time. Unreviewed periods remain in coverage; later reports never backfill earlier misses. Counts are case/snapshot instances, not unique instruments or independent trials. Preliminary warnings and numerical alerts are not scored as final agent reports.", "evaluation-warning spatial-qualification");
  const instrumentAudit = original("details", "", "spatial-instrument-audit");
  instrumentAudit.append(original("summary", "Overall instrument coverage details"));
  const missedIds = [...new Set(overall.groups.agent_sensor_concerns.missed)];
  const falseIds = [...new Set(overall.groups.agent_sensor_concerns.falseAlarms)];
  const missedTypes = [...new Set(overall.groups.issueTypes.missed)];
  const falseTypes = [...new Set(overall.groups.issueTypes.falseAlarms)];
  const missedFaults = original("p", `Fault sensors with uncovered source windows (${missedIds.length} case/sensor pairs): ${missedIds.join("; ") || "none"}.`);
  const falseFaults = original("p", `Reported sensors without a known fault in some source windows (${falseIds.length} case/sensor pairs): ${falseIds.join("; ") || "none"}.`);
  const typeAudit = original("p", `Issue types with uncovered source windows: ${missedTypes.join("; ") || "none"}. Incorrectly reported types: ${falseTypes.join("; ") || "none"}. Sensor recall excludes missing-only readings; issue-type recall includes them.`);
  instrumentAudit.append(missedFaults, falseFaults, typeAudit);
  container.append(scoreBasis, status, instrumentAudit);
  container.append(renderScoreDetails(report, overall));
  const timing = original("p", "", "spatial-timing evaluation-warning");
  container.append(timing);
  const controls = original("div", "", "spatial-controls");
  const select = original("select"); select.setAttribute("aria-label", "Evaluation recording");
  const shortNames = ["N1 · Broad leak + mixed faults", "N2 · Localized leak + mixed faults", "N3 · Faults and operating shift; no leak"];
  networks.forEach((network, index) => { const option = original("option", network.id === `N${index + 1}` ? shortNames[index] : `${network.id} · ${network.name}`); option.value = network.id; select.append(option); });
  select.value = playback.network;
  const play = button("Play recording", () => {
    if (playback.playing) playback.playing = false;
    else {
      if (playback.seconds >= (lastFrame(currentNetwork())?.source_seconds || 360)
        && playback.reviewed && playback.holdSeconds <= 0) {
        playback.seconds = currentNetwork().frames[0]?.source_seconds || 60;
        playback.started = false;
      }
      if (!playback.started) {
        playback.reviewed = false; playback.investigationSeconds = 0;
        playback.sourceAccumulator = 0; playback.holdSeconds = 0;
      }
      playback.playing = true; playback.started = true;
    }
    update();
  });
  const slider = original("input"); slider.type = "range"; slider.min = "60"; slider.max = "360";
  slider.step = String(report.frame_hop_seconds || 15);
  slider.setAttribute("aria-label", "Synchronized recording time");
  const time = original("output", "", "spatial-clock"); time.setAttribute("aria-live", "off");
  const alignment = original("p", "", "spatial-alignment");
  alignment.setAttribute("aria-live", "polite");
  const speed = original("select"); speed.setAttribute("aria-label", "Recording playback speed");
  for (const value of [15, 30, 60]) { const option = original("option", `${value}× replay`); option.value = String(value); speed.append(option); }
  speed.value = String(playback.speed);
  controls.append(select, play, slider, time, speed);
  container.append(controls, alignment);
  const checkpoints = original("div", "", "spatial-checkpoints");
  const maps = original("div", "", "spatial-map-grid");
  const truthPane = original("section", "", "spatial-map-pane pipeline-map");
  const agentPane = original("section", "", "spatial-map-pane pipeline-map");
  const truthCaption = original("p", "", "spatial-map-caption");
  const agentCaption = original("p", "", "spatial-map-caption");
  const truthBasis = original("p", "", "spatial-findings-basis");
  const agentBasis = original("p", "", "spatial-findings-basis");
  const truthMap = svg("svg", { viewBox: "0 0 760 520", role: "group", "aria-label": "Ground truth pipeline map", id: "evaluation-truth-map" });
  const agentMap = svg("svg", { viewBox: "0 0 760 520", role: "group", "aria-label": "Agent findings pipeline map", id: "evaluation-agent-map" });
  truthPane.append(original("h3", "Ground truth"), original("small", "Known labels + measured flags · known labels never given to agents"), truthMap, truthCaption, truthBasis, mapLegend(true),
    original("p", "Symbols combine: orange fill = pressure alert; dashed outline = missing / invalid; purple ring = known fault; blue ring = selection.", "spatial-legend-footnote"));
  agentPane.append(original("h3", "Agent findings"), original("small", "Current measured alerts + latest released agent findings"), agentMap, agentCaption, agentBasis, mapLegend(false),
    original("p", "Symbols combine: orange fill = pressure alert; dashed outline = missing / invalid; purple ring = agent-identified issue; blue ring = selection.", "spatial-legend-footnote"));
  maps.append(truthPane, agentPane);
  container.append(checkpoints, maps);
  const sensorDetail = original("p", "Select the same instrument on either map to compare its labels and findings.", "spatial-sensor-detail muted");
  const progress = original("div", "", "spatial-progress");
  const progressTitle = original("strong");
  const agentCards = original("div", "", "spatial-agent-cards");
  const updateLine = original("p", "", "spatial-public-update");
  progress.append(progressTitle, agentCards, updateLine);
  const agentReport = original("section", "", "spatial-agent-report");
  agentReport.setAttribute("aria-label", "Agent findings report");
  const reportBasis = original("p", "", "spatial-report-basis");
  const reportText = original("p", "", "evaluation-answer spatial-report-text");
  const completeReport = original("details", "", "spatial-complete-report");
  const completeText = original("p", "", "evaluation-answer spatial-report-text");
  completeReport.append(original("summary", "Full recorded answer and checked evidence"), completeText);
  agentReport.append(original("h3", "Agent findings report"), reportBasis, reportText, completeReport);
  container.append(agentReport, progress, sensorDetail);
  container.append(original("p", "Every investigation freezes both maps until result admission. Between reviews, measured data advances together while the latest released agent findings remain visible, labeled with their original review time. An unreviewed window is not a cleared leak; only a newer released agent finding replaces the previous one. Replay does not call models or speed up actual inference.", "spatial-footnote muted"));
  const journal = original("details", "", "spatial-journal");
  journal.append(original("summary", "Recorded agent checks, interim outputs and handoffs"));
  const journalBody = original("ol", "", "agent-public-journal");
  journal.append(journalBody); container.append(journal);

  function currentNetwork(): SpatialNetwork { return networks.find(network => network.id === playback.network) || networks[0]; }
  function currentFrame(): SpatialFrame | undefined {
    return [...currentNetwork().frames].reverse().find(frame => frame.source_seconds <= playback.seconds);
  }
  function seek(seconds: number): void {
    playback.seconds = seconds; playback.playing = false; playback.reviewed = true;
    playback.started = false; playback.investigationSeconds = 0;
    playback.sourceAccumulator = 0; playback.holdSeconds = 0; playback.sensor = ""; update();
  }
  function update(): void {
    const network = currentNetwork(), frame = currentFrame();
    const sourceLabel = network.frames.find(item => item.truth.leak_source)?.truth.leak_source;
    const onset = sourceLabel?.start_seconds;
    const branchSensors = new Set(network.pack.sensors.filter(item => item.segment_id === sourceLabel?.segment_id).map(item => item.id));
    const firstAlert = network.frames.find(item => item.detector.pressure_anomaly_sensors.some(id => branchSensors.has(id)));
    const reviews = report.cases.filter(item => item.network_id === network.id).sort((a, b) => (a.source_seconds || 0) - (b.source_seconds || 0));
    const admission = reviews.find(item => item.root_count && (onset == null || (item.source_seconds || 0) >= onset));
    const correct = reviews.find(item => item.extraction?.mapping?.leaks.some(leak => leak.segment_id === sourceLabel?.segment_id)
      && network.frames.some(candidate => releasedReview(report, candidate, true) === item));
    const earlyWarning = reviews.flatMap(row => network.frames.flatMap(candidate => {
      if (matchingReview(report, candidate) !== row) return [];
      const finding = checkedWarning(row, candidate, Infinity);
      return finding?.segment_ids.includes(sourceLabel?.segment_id || "") ? [{ row, finding }] : [];
    }))[0];
    const warningWallSeconds = earlyWarning ? (Date.parse(earlyWarning.finding.available_at)
      - Date.parse(earlyWarning.row.agent_started_at || earlyWarning.row.agent_tasks?.find(task => task.id === earlyWarning.row.root_id)?.created_at || "")) / 1000 : undefined;
    timing.textContent = sourceLabel ?
      `Leak onset: ${onset == null ? "not recorded" : clock(onset)} · first measured alert on ${sourceLabel.segment_id}: ${firstAlert ? clock(firstAlert.source_seconds) : "not recorded"} · first agent admission: ${admission ? clock(admission.source_seconds || 0) : "not recorded"} · checked specialist warning: ${earlyWarning ? `window ${clock(earlyWarning.row.source_seconds || 0)}, ${warningWallSeconds?.toFixed(1)} s original model wall time (not final)` : "not recorded"} · first accepted correct-branch review: ${correct ? clock(correct.source_seconds || 0) : "not found"}${correct && onset != null ? ` (+${(correct.source_seconds || 0) - onset} s source delay)` : ""} · original model wall time for that review: ${correct?.agent_elapsed_seconds == null ? "not recorded" : `${correct.agent_elapsed_seconds.toFixed(1)} s`} (source frozen).` :
      "No known leak in this recording. Measured pressure alerts must still be distinguished from instrument faults and operating changes.";
    if (!report.admission_policy) timing.textContent += " Legacy recording: agents were only admitted at fixed checkpoints; this run does not measure automatic detection latency.";
    if (report.suite === "recovery") timing.textContent = "Each incident and its recovery are scored separately in the episode table above. Retained findings do not count as a fresh detection of a repeated event.";
    slider.max = String(lastFrame(network)?.source_seconds || 360); slider.value = String(playback.seconds);
    play.textContent = playback.playing ? "Pause recording" : "Play recording";
    time.textContent = `${clock(frame?.source_seconds || 0)} / 6:00`;
    checkpoints.replaceChildren();
    for (const row of report.cases.filter(item => item.network_id === network.id && (item.source_seconds || 0) > 60)) {
      const end = row.source_seconds || 0;
      const control = button(`${clock(end)} review · ${row.status === "completed" ? "recorded" : row.status.replace(/_/g, " ")}`, () => seek(end));
      control.disabled = !network.frames.some(item => item.source_seconds === end);
      checkpoints.append(control);
    }
    if (!frame) {
      truthCaption.textContent = agentCaption.textContent = "Recording has not reached its first complete window.";
      truthBasis.textContent = agentBasis.textContent = "";
      reportBasis.textContent = "No complete source window.";
      reportText.textContent = "No agent output is available yet.";
      completeText.textContent = ""; completeReport.hidden = true;
      agentReport.dataset.caseId = ""; agentReport.dataset.sourceSeconds = "";
      delete agentMap.dataset.findingsSourceSeconds; delete agentMap.dataset.findingsSnapshot;
      truthMap.replaceChildren(); agentMap.replaceChildren(); agentCards.replaceChildren();
      progressTitle.textContent = "Numerical recording in progress"; updateLine.textContent = "";
      return;
    }
    const row = matchingReview(report, frame);
    const requested = report.cases.find(item => item.case_id === frame.review_case_id);
    const admitted = Boolean(row && resultAdmitted(row));
    const mismatch = Boolean(frame.review_case_id && !row);
    const waiting = Boolean(frame.review_case_id && (!admitted || !playback.reviewed));
    alignment.dataset.state = mismatch ? "blocked" : waiting ? "waiting" : row?.root_count ? "admitted" : "monitoring";
    alignment.textContent = `Synchronized data window ${clock(frame.source_seconds)} · ${mismatch ?
      "simulation paused: review does not match this snapshot" : waiting ?
        row?.status === "mapping_output" || row?.status === "judging_explanation" ?
          "simulation paused: admitting investigation results" : "simulation paused: agent investigation" :
        row?.status === "failed" ? `investigation failure admitted: ${row.error_code || "no accepted report"}` :
          row?.root_count ? "results admitted on both maps" : "both maps advance together"}`;
    const currentReview = releasedReview(report, frame, playback.reviewed);
    const elapsed = row?.agent_elapsed_seconds;
    const shownSeconds = playback.reviewed ? Infinity : playback.investigationSeconds;
    const findings = latestFindings(report, network, frame, playback.reviewed);
    const review = findings?.review;
    const carried = Boolean(findings && findings.frame !== frame);
    const chooseSensor = (id: string): void => { playback.sensor = id; update(); };
    drawMap(truthMap, network.pack, frame, undefined, true, playback.sensor, chooseSensor);
    drawMap(agentMap, network.pack, frame, review, false, playback.sensor, chooseSensor, findings?.frame);
    const source = frame.truth.leak_source;
    const issueCount = new Set(frame.truth.sensor_issues.filter(item => item.kind !== "missing").map(item => item.sensor_id)).size;
    truthCaption.textContent = `${source ? `Leak on ${source.segment_id} at ${source.chainage_m} m${source.start_seconds == null ? "" : ` · onset ${clock(source.start_seconds)}`}` : "No leak"} · ${issueCount} instruments with known issues · ${frame.detector.pressure_anomaly_sensors.length} measured pressure alerts${frame.truth.operating_change ? ` · ${frame.truth.operating_change.segment_id} operating shift` : ""}`;
    truthBasis.textContent = `Current source labels · ${clock(frame.source_seconds)}`;
    agentBasis.textContent = findings ?
      `Last admitted report · ${clock(findings.frame.source_seconds)}${carried ?
        ` · retained; current data ${clock(frame.source_seconds)} has no newer admitted report` : " · this data window"}` :
      "No agent finding has been released at or before this source time.";
    const leaks = review?.extraction?.mapping?.leaks || [];
    agentCaption.textContent = review ? (leaks.length ? leaks.map(leak => `${leak.segment_id} leak pattern${leak.interval ? ` · ${leak.interval.start_m}–${leak.interval.end_m} m proposed` : " · interval withheld"}`).join("; ") : "No leak pattern identified") :
      row?.status === "failed" && playback.reviewed ? `Investigation failed: ${row.error_code || "no accepted report"} · no final findings released` :
      requested && !row ? "Review snapshot mismatch · no findings released" :
      row?.root_count ? playback.reviewed && admitted ? "No accepted mapped report; no interpretation overlay released." :
        "Investigation underway · final findings not yet available" :
        `${frame.detector.pressure_anomaly_sensors.length} pressure alerts · no review of this window`;
    if (carried && findings) agentCaption.textContent += ` · retained from ${clock(findings.frame.source_seconds)}`;
    if (findings && row?.status === "failed" && playback.reviewed) {
      agentCaption.textContent += ` · current investigation failed: ${row.error_code || "no accepted report"}`;
    } else if (findings && mismatch) agentCaption.textContent += " · current review snapshot mismatch";
    agentCaption.dataset.accepted = String(Boolean(currentReview));
    agentCaption.dataset.carriedForward = String(carried);
    agentReport.dataset.caseId = findings?.row.case_id || "";
    agentReport.dataset.sourceSeconds = findings ? String(findings.frame.source_seconds) : "";
    reportBasis.textContent = findings ?
      `Original admitted engineering report · ${findings.row.case_id} · window ${clock(findings.frame.window_start_seconds)}–${clock(findings.frame.source_seconds)}${carried ?
        ` · current data ${clock(frame.source_seconds)}; ${row?.status === "failed" ?
          `new investigation failed (${row.error_code || "no accepted report"}); previous output retained` :
          "awaiting a newer admitted report"}` : ""}` :
      "No released agent output for this recording time. Unreviewed data is not a no-leak finding.";
    const output = review?.interpretation?.answer.text || review?.answer || "";
    const text = output || (review ? "This report's original text was not recorded." : "No agent output has been released yet.");
    if (reportText.textContent !== text) reportText.textContent = text;
    completeReport.hidden = !review?.answer || review.answer === output;
    if (completeText.textContent !== (review?.answer || "")) completeText.textContent = review?.answer || "";
    const origin = Date.parse(row?.agent_started_at || row?.agent_tasks?.find(task => task.id === row.root_id)?.created_at || "");
    const visibleEvents = (row?.activity || []).filter(event => journalTypes.has(event.type)
      && (playback.reviewed || (Date.parse(event.created_at) - origin) / 1000 <= shownSeconds));
    progressTitle.textContent = row?.root_count ?
      `${playback.reviewed && admitted ? "Recorded investigation" : "Source paused for investigation"} · window ${clock(frame.window_start_seconds)}–${clock(frame.source_seconds)} · ${elapsed === undefined ? "original model wall time pending" : `${elapsed.toFixed(0)} s original model wall time`}${row.investigation_elapsed_seconds === undefined ? "" : ` · ${row.investigation_elapsed_seconds.toFixed(0)} s through result admission`} · ${playback.speed}× playback, not faster inference` :
      `Numerical monitoring · window ${clock(frame.window_start_seconds)}–${clock(frame.source_seconds)} · ${frame.detector.pressure_anomaly_sensors.length} pressure alerts`;
    agentCards.replaceChildren();
    for (const role of ["sensor_quality", "event_diagnosis", "operator_response"]) {
      const task = row?.agent_tasks?.find(item => item.role === role && item.root_id === row.root_id);
      const begun = task && (playback.reviewed || (Date.parse(task.created_at) - origin) / 1000 <= shownSeconds);
      const complete = task && ["SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"].includes(task.state)
        && (playback.reviewed || (Date.parse(task.updated_at) - origin) / 1000 <= shownSeconds);
      const card = original("div", "", `spatial-agent${complete ? " completed" : begun ? " active" : ""}`);
      card.append(original("small", agentName(role)),
        original("strong", complete ? task.state === "FAILED" ? "Failed" : "Completed" : begun ? "Checking evidence" : "Not started"));
      const descriptions: Record<string, string> = {
        sensor_quality: "Checks usable readings and instrument inconsistencies.",
        event_diagnosis: "Compares joint pressure patterns, quiet neighbors and operating records.",
        operator_response: "Coordinates checks and submits an evidence-grounded report for review.",
      };
      card.append(original("span", descriptions[role], "muted"));
      agentCards.append(card);
    }
    updateLine.textContent = visibleEvents.length ? publicUpdate(visibleEvents[visibleEvents.length - 1]) :
      row?.root_count ? "The full recorded public journal is available below. Private model reasoning is not displayed." :
        frame.detector.pressure_anomaly_sensors.length ? report.admission_policy ?
          "Pressure anomalies are visible. The first review uses bounded pressure context; later reviews are recorded checkpoints." :
          "Pressure anomalies are visible. This legacy benchmark investigates only its predeclared checkpoints." : "No pressure anomalies: no agent investigation.";
    journalBody.replaceChildren();
    for (const event of visibleEvents) {
      const item = original("li");
      item.dataset.kind = event.type;
      const role = String(event.payload.role || row?.agent_tasks?.find(task => task.id === event.task_id)?.role || "agent");
      item.append(original("small", `${Math.max(0, (Date.parse(event.created_at) - origin) / 1000).toFixed(0)} s · ${agentName(role)}`),
        original("p", publicUpdate(event)));
      journalBody.append(item);
    }
    if (!visibleEvents.length) journalBody.append(original("li", "No recorded public agent updates for this selected window."));
    if (playback.sensor) {
      const known = frame.truth.sensor_issues.filter(item => item.sensor_id === playback.sensor).map(item => item.kind);
      const mapped = review?.extraction?.mapping?.sensor_issues.filter(item => item.sensor_id === playback.sensor).map(item => item.kind) || [];
      const summary = frame.pressure_summaries[playback.sensor];
      sensorDetail.textContent = `${playback.sensor} · known issue: ${known.join(", ") || "none"} · current pressure alert: ${frame.detector.pressure_anomaly_sensors.includes(playback.sensor) ? "yes" : "no"} · missing / invalid readings: ${frame.detector.missing_value_sensors.includes(playback.sensor) || known.some(kind => ["missing", "invalid"].includes(kind)) ? "yes" : "no"} · agent${findings ? ` (review ${clock(findings.frame.source_seconds)})` : ""}: ${mapped.join(", ") || "none recorded"}${summary?.recent_pressure_drop_bar != null ? ` · recent pressure change from normal: ${(-summary.recent_pressure_drop_bar).toFixed(2)} bar` : ""}`;
    } else sensorDetail.textContent = "Select the same instrument on either map to compare its labels and findings.";
  }
  select.addEventListener("change", () => {
    playback.network = select.value; seek(lastFrame(currentNetwork())?.source_seconds || 60);
  });
  slider.addEventListener("input", () => seek(Number(slider.value)));
  speed.addEventListener("change", () => { playback.speed = Number(speed.value); });
  update();
  let previousTick = performance.now();
  timer = window.setInterval(() => {
    const now = performance.now(), delta = Math.min((now - previousTick) / 1000, 1); previousTick = now;
    if (!playback.playing) return;
    if (document.getElementById("panel-evaluation")?.hidden) { playback.playing = false; update(); return; }
    const frame = currentFrame();
    if (!frame) { playback.playing = false; update(); return; }
    const row = matchingReview(report, frame);
    if (frame.review_case_id && !playback.reviewed) {
      if (!row) { playback.playing = false; update(); return; }
      playback.investigationSeconds += delta * playback.speed;
      const elapsed = row.root_count ? row.investigation_elapsed_seconds ?? row.agent_elapsed_seconds : 0;
      if (resultAdmitted(row) && (elapsed === undefined || playback.investigationSeconds >= elapsed)) {
        playback.reviewed = true; playback.holdSeconds = row.root_count || row.status === "failed" ? 2 : 0;
        playback.sourceAccumulator = 0;
      }
    } else if (playback.holdSeconds > 0) playback.holdSeconds -= delta;
    else {
      playback.sourceAccumulator += delta * playback.speed;
      const next = currentNetwork().frames.find(item => item.source_seconds > frame.source_seconds);
      if (!next || playback.sourceAccumulator >= next.source_seconds - frame.source_seconds) {
        if (!next) playback.playing = false;
        else {
          playback.sourceAccumulator -= next.source_seconds - frame.source_seconds;
          playback.seconds = next.source_seconds; playback.reviewed = false; playback.investigationSeconds = 0;
        }
      }
    }
    update();
  }, 250);
}
