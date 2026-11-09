import { box, node } from "./dom";
import { agentName } from "./agentwork";
import { renderSpatialEvaluation, stopSpatialPlayback } from "./evaluation_maps";
import type { SpatialNetwork } from "./evaluation_maps";
import type { ConsoleEvent } from "./types";

interface Rate {
  value: number | null;
  numerator?: number;
  denominator?: number;
  wilson95?: [number, number] | null;
}
interface Detection {
  tp: number; fp: number; fn: number;
  precision: Rate; recall: Rate; f1: Rate;
}
interface Quote { path: string; text: string }
interface Issue { sensor_id: string; kind: string; assertion?: string; quote?: Quote }
interface Interval { start_m: number; end_m: number }
interface Leak { segment_id: string; assertion: string; interval: Interval | null; quote: Quote }
interface Mapping { leaks: Leak[]; sensor_issues: Issue[]; instrumentation_concern: boolean; instrumentation_quote?: Quote | null }
export interface CheckedFinding {
  hypothesis: "suspected_leak"; segment_ids: string[]; snapshot_id: string; input_hash: string;
  available_at: string; final_report: false;
}
export interface EvaluationCase {
  case_id: string; name: string; status: string; dataset_sha256: string;
  truth: {
    leak_source: { segment_id: string; chainage_m: number; start_seconds?: number } | null;
    sensor_issues: Issue[]; pressure_anomaly_sensors: string[];
    missing_value_sensors: string[]; pressure_trigger: boolean;
  };
  extraction?: { status: string; mapping: Mapping | null; source_text_scope?: string; error_code?: string; trace?: Trace; model_receipt?: { observed_model?: string } };
  judge?: { status: string; passed: boolean; verdict: { dimensions: Record<string, { score: number; reason: string }> } | null; trace?: Trace; model_receipt?: { observed_model?: string } };
  interpretation?: { answer: { text: string } };
  answer?: string;
  root_count?: number; state?: string; error_code?: string;
  agent_elapsed_seconds?: number; agent_calls?: number;
  investigation_elapsed_seconds?: number; result_admitted_at?: string;
  traces?: { role: string; trace: Trace | null }[];
  model_receipts?: { observed_model?: string }[];
  network_id?: string; source_seconds?: number; snapshot_id?: string; input_hash?: string;
  accepted_report?: boolean; root_id?: string; agent_started_at?: string;
  authorized_inspection?: { segment_id: string; start_m: number; end_m: number } | null;
  activity?: ConsoleEvent[];
  agent_tasks?: {
    id: string; role: string; state: string; root_id: string; snapshot_id: string;
    created_at: string; updated_at: string; summary: string | null;
    checked_finding?: CheckedFinding | null;
  }[];
}
interface Trace { trace_id?: string; langfuse_url?: string }
interface AgentProcess {
  planned_agent_reviews: number; attempted_reviews: number; not_attempted_reviews: number;
  terminal_reviews: number; accepted_reports: number; mapped_reports: number;
  failed_reviews: number; timeouts: number; model_calls: number; model_calls_not_recorded: number;
  latency_samples: number; p50_wall_seconds: number | null; p95_wall_seconds: number | null;
  max_wall_seconds: number | null; basis: string;
  checks: Record<string, { label: string; passed: number; failed: number; not_recorded: number; denominator: number }>;
  roles: { role: string; assigned: number; succeeded: number; abstained: number; failed: number; pending: number }[];
}
interface AnswerQualityMetrics {
  planned: number; reviewed: number; execution_failed: number; not_reviewed: number;
  no_concerns: number; with_concerns: number; insufficient_evidence: number;
  dimensions: Record<string, {
    average: number | null; scored: number; concerns: number;
    insufficient_evidence: number; not_applicable: number;
  }>;
}
interface AgentReferenceReport {
  version: string; status: string; run_id: string; split: string;
  dataset_sha256: string; policy_version: string; policy_sha256: string;
  implementation_unchanged?: boolean; requested_model: string;
  scope: string; reference_origin: string; ground_truth_supplied_to_agent: boolean;
  dataset_file_sha256?: string; dataset_unchanged?: boolean;
  answer_quality?: {
    policy_version: string; requested_judge_model: string; rubric_sha256: string;
    dimensions: Record<string, string>; advisory: boolean; limitations: string[];
    metrics: AnswerQualityMetrics & { by_split?: Record<string, AnswerQualityMetrics> };
  };
  metrics: {
    planned: number; completed: number; failed: number; all_checks_passed: number;
    checks: Record<string, { passed: number; denominator: number }>;
  };
  cases: {
    id: string; name: string; family: string; split: string; status: string;
    input: object; expected: object; actual: object | null;
    checks: Record<string, boolean>; elapsed_seconds: number | null; error_code?: string;
    model_receipt?: { observed_model?: string; mode?: string };
    answer?: { facts: object; explanation: string; next_steps: string[]; limitations: string[] } | null;
    judge?: {
      status: string; error_code?: string | null; reason?: string;
      elapsed_seconds?: number; model_receipt?: { observed_model?: string };
      verdict?: { summary: string; dimensions: {
        dimension: string; status: string; score: number | null; rationale: string;
        evidence_ids: string[]; answer_excerpt: string | null;
      }[] } | null;
    };
  }[];
}
interface LifecycleMetrics {
  basis: string;
  episodes: {
    network_id: string; episode: number; segment_id: string; onset_seconds: number;
    stop_seconds: number | null; first_fresh_correct_review_seconds: number | null;
    detection_delay_source_seconds: number | null; active_windows: number;
    uncovered_active_windows: number; clean_recovery_start_seconds: number | null;
    first_clear_review_seconds: number | null; clearance_delay_source_seconds: number | null;
    clean_recovery_windows: number; false_leak_recovery_windows: number;
    unassessed_recovery_windows: number;
  }[];
  controls: {
    network_id: string; name: string; windows: number; assessed_windows: number;
    unassessed_windows: number; false_leak_windows: number; inspection_windows: number;
  }[];
}
export interface EvaluationReport {
  evaluation_history?: { entries: ArchivedEvaluation[]; warnings: string[] };
  historical_archive_id?: string; historical_archive_label?: string;
  agent_reference_evaluation?: AgentReferenceReport;
  remapped_at?: string;
  suite?: string; suite_name?: string; additional_evaluations?: EvaluationReport[];
  agent_process?: AgentProcess;
  agent_process_audit?: {
    run_id: string; source_run_id: string; created_at: string; validator_implementation_sha256: string;
  };
  version?: string; networks?: SpatialNetwork[]; duration_seconds?: number;
  frame_hop_seconds?: number; admission_policy?: string;
  simulation_policy?: string;
  status: string; cases: EvaluationCase[]; split?: string; seed?: number;
  run_id?: string; agent_model?: string; evaluator_model?: string; planned_cases?: number;
  implementation_sha256?: string; implementation_unchanged?: boolean;
  previous_runs?: { run_id: string; split: string; seed: number; status: string; metrics: EvaluationReport["metrics"] }[];
  limitations?: string[];
  mapping_calibration?: { name: string; passed: boolean }[];
  judge_calibration?: { identity: string; status: string; passed: boolean; expected_pass: boolean }[];
  metrics: {
    temporal?: LifecycleMetrics;
    completed_cases: number; target_met: boolean; calibration_passed: boolean;
    groups: Record<string, Detection>; rates: Record<string, Rate>;
    localization_mean_midpoint_error_m: number | null;
    localization_mean_width_m: number | null; confirmed_cause_claims: number;
  } | null;
}

interface ArchivedEvaluation {
  archive_id: string; run_id: string; suite: string; created_at?: string;
  status: string; split?: string; label: string; available: boolean;
}

function raw<K extends keyof HTMLElementTagNameMap>(tag: K, value = "", className = ""): HTMLElementTagNameMap[K] {
  const result = node(tag, "", className);
  result.textContent = value;
  return result;
}
function percent(value: number | null): string { return value === null ? "Not measurable" : `${(value * 100).toFixed(1)}%`; }
function rate(value: Rate): string {
  const count = value.denominator === undefined ? "" : ` (${value.numerator}/${value.denominator})`;
  const confidence = value.wilson95 ? ` · 95% interval ${percent(value.wilson95[0])}–${percent(value.wilson95[1])}` : "";
  return percent(value.value) + count + confidence;
}
function issueText(issues: Issue[]): string {
  return issues.length ? issues.map(item => `${item.sensor_id}: ${item.kind.replace(/_/g, " ")}`).join("; ") : "None identified";
}
function intervalText(leaks: Leak[]): string {
  return leaks.length ? leaks.map(item => `${item.segment_id}: ${item.assertion}; ${item.interval ? `${item.interval.start_m}–${item.interval.end_m} m inspection interval` : "no interval proposed"}`).join("; ") : "No leak pattern identified";
}
function table(headers: string[], rows: (string | Node)[][], descriptions?: string[]): HTMLElement {
  const wrapper = raw("div", "", "table-wrap");
  const result = raw("table");
  const head = raw("tr");
  headers.forEach((value, index) => {
    const cell = raw("th", value); cell.scope = "col";
    if (descriptions?.[index]) {
      cell.title = descriptions[index]; cell.tabIndex = 0;
      cell.setAttribute("aria-description", descriptions[index]);
    }
    head.append(cell);
  });
  const body = raw("tbody");
  rows.forEach(values => {
    const row = raw("tr");
    values.forEach(value => {
      const cell = raw("td");
      if (typeof value === "string") cell.textContent = value;
      else cell.append(value);
      row.append(cell);
    });
    body.append(row);
  });
  const heading = raw("thead"); heading.append(head);
  result.append(heading, body); wrapper.append(result);
  return wrapper;
}
function traceLine(label: string, trace: Trace | null | undefined): HTMLElement {
  const paragraph = raw("p", `${label}: `, "muted");
  paragraph.append(raw("code", trace?.trace_id || "Not reported"));
  if (trace?.langfuse_url) {
    try {
      const url = new URL(trace.langfuse_url, location.origin);
      if (["http:", "https:"].includes(url.protocol) && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) {
        const link = raw("a", " Open Langfuse");
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
        paragraph.append(link);
      } else paragraph.append(raw("span", " Non-local viewer link withheld."));
    } catch { paragraph.append(raw("span", " Invalid viewer link withheld.")); }
  }
  return paragraph;
}
const labels: Record<string, string> = {
  leak_recognition: "Agent leak-pattern recognition · cases",
  agent_pipeline_identification: "Agent affected-pipeline identification · case/pipeline",
  instrumentation_recognition: "Agent instrumentation concerns · cases",
  agent_sensor_concerns: "Agent suspect-instrument identification · sensor/windows",
  agent_issue_types: "Agent issue-type mapping · sensor/window/type",
  detector_pressure_anomalies: "Numerical pressure anomalies · sensor/windows",
  detector_missing_values: "Numerical missing values · sensor/windows",
  localization_containment: "Source contained in an agent-proposed interval, maximum 400 m",
  accepted_report_coverage: "Accepted report coverage · pressure-triggered cases",
  judge_pass_rate: "External explanation judge pass rate · pressure-triggered cases",
  correct_withholding: "No inspection interval on cases without a leak",
  no_pressure_no_agent: "No agent invocation on stable or missing-only controls",
};

let selectedSuite = "current";
let selectedEvaluationTab = "detection";
let selectedArchive = "";
let archivedReport: EvaluationReport | null = null;
let archiveLoading = false;
let archiveError = "";
let archiveRequest = 0;
let latestReport: EvaluationReport;
let readArchive: (id: string, signal: AbortSignal) => Promise<EvaluationReport>;
let archiveController: AbortController | null = null;
const approachOpen = { detection: false, agent: false, provenance: false };
const qualityNames: Record<string, string> = {
  grounding: "Grounding", numeric_accuracy: "Numerical accuracy",
  causal_support: "Causal reasoning", scope: "Scope control",
  uncertainty: "Uncertainty calibration", usefulness: "Actionable usefulness",
};
let referenceRecordsOpen = false;

function approachDetails(key: keyof typeof approachOpen, title: string): HTMLDetailsElement {
  const details = raw("details", "", "evaluation-scope");
  details.open = approachOpen[key];
  details.addEventListener("toggle", () => { approachOpen[key] = details.open; });
  details.append(raw("summary", title));
  return details;
}

const suiteNames: Record<string, string> = {
  current: "Leak and sensor-issue detection", recovery: "Leak recovery and new leaks",
  non_leak: "No-leak scenarios and false alarms",
};

export function renderEvaluation(
  report: EvaluationReport, loader?: (id: string, signal: AbortSignal) => Promise<EvaluationReport>,
): void {
  latestReport = report;
  if (loader) readArchive = loader;
  box("evaluation-scope-label").textContent = selectedEvaluationTab === "agent" ?
    "FROZEN REFERENCES / RECORDED ANSWERS" : "GROUND TRUTH / AGENT FINDINGS";
  const container = box("evaluation-results");
  const openedReferences = new Set([...container.querySelectorAll<HTMLDetailsElement>(
    "details[data-reference-case][open]",
  )].map(item => item.dataset.referenceCase));
  const openedInputs = new Set([...container.querySelectorAll<HTMLDetailsElement>(
    "details[data-reference-input][open]",
  )].map(item => item.dataset.referenceInput));
  const referenceRecords = container.querySelector<HTMLDetailsElement>("details[data-reference-records]");
  if (referenceRecords) referenceRecordsOpen = referenceRecords.open;
  container.replaceChildren();
  const tabs = raw("div", "", "evaluation-suite-selector");
  tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Evaluation approaches");
  for (const [key, label] of [["detection", "Detection"], ["agent", "Agent reliability"]]) {
    const button = raw("button", label); button.type = "button";
    button.tabIndex = key === selectedEvaluationTab ? 0 : -1;
    button.setAttribute("role", "tab"); button.setAttribute("aria-selected", String(key === selectedEvaluationTab));
    button.id = `evaluation-${key}-tab`;
    button.setAttribute("aria-controls", "evaluation-approach-panel");
    button.addEventListener("click", () => {
      selectedEvaluationTab = key; renderEvaluation(report);
      document.getElementById(button.id)?.focus();
    });
    button.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      selectedEvaluationTab = event.key === "Home" ? "detection" :
        event.key === "End" ? "agent" : key === "detection" ? "agent" : "detection";
      renderEvaluation(report);
      document.getElementById(`evaluation-${selectedEvaluationTab}-tab`)?.focus();
    });
    tabs.append(button);
  }
  container.append(tabs);
  const panel = raw("section"); panel.id = "evaluation-approach-panel";
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-labelledby", `evaluation-${selectedEvaluationTab}-tab`);
  container.append(panel);
  if (selectedEvaluationTab === "agent") {
    stopSpatialPlayback();
    renderAgentReferences(report.agent_reference_evaluation, panel, openedReferences, openedInputs);
    return;
  }
  const selector = raw("select"); selector.setAttribute("aria-label", "Evaluation suite");
  for (const [key, label] of Object.entries(suiteNames)) {
    const option = raw("option", label); option.value = key; selector.append(option);
  }
  selector.value = selectedSuite;
  selector.addEventListener("change", () => {
    selectedSuite = selector.value; resetArchive(); renderEvaluation(latestReport);
  });
  const controls = raw("div", "", "evaluation-suite-selector");
  controls.append(raw("label", "Evaluation suite"), selector);
  panel.append(controls);
  const current = selectedSuite === "current" ? report :
    report.additional_evaluations?.find(item => item.suite === selectedSuite);
  const history = raw("select"); history.setAttribute("aria-label", "Evaluation run");
  const latest = raw("option", "Latest result"); latest.value = ""; history.append(latest);
  const archives = report.evaluation_history?.entries.filter(item =>
    item.suite === selectedSuite && item.status === "completed") || [];
  for (const entry of archives) {
    const stamp = Date.parse(entry.created_at || "");
    const date = Number.isFinite(stamp) ? `${new Date(stamp).toISOString().slice(0, 19).replace("T", " ")} UTC` : "Date not recorded";
    const option = raw("option", `${date} · ${entry.status} · ${entry.split || "split not recorded"} · ${entry.run_id.slice(0, 8)} · ${entry.label}`);
    option.value = entry.archive_id; option.disabled = !entry.available; history.append(option);
  }
  for (const previous of current?.previous_runs || []) {
    if (previous.status !== "completed") continue;
    if (archives.some(item => item.run_id === previous.run_id)) continue;
    const option = raw("option", `${previous.run_id.slice(0, 8)} · ${previous.status} · summary only — full archive unavailable`);
    option.disabled = true; history.append(option);
  }
  if (selectedArchive && !archives.some(item => item.archive_id === selectedArchive)) {
    const option = raw("option", "Selected archived snapshot · no longer listed");
    option.value = selectedArchive; option.disabled = true; history.append(option);
  }
  history.value = selectedArchive;
  history.addEventListener("change", () => {
    resetArchive(); selectedArchive = history.value;
    if (!selectedArchive) { renderEvaluation(latestReport); return; }
    const requested = selectedArchive, suite = selectedSuite, token = archiveRequest;
    archiveController = new AbortController();
    archiveLoading = true; renderEvaluation(latestReport);
    void readArchive(requested, archiveController.signal).then(result => {
      if (token !== archiveRequest || suite !== selectedSuite || requested !== selectedArchive) return;
      if (result.historical_archive_id !== requested) throw new Error("The running API needs a reload before it can load archived evaluations.");
      if ((result.suite || "current") !== suite) throw new Error("The archived result belongs to a different evaluation suite.");
      if (result.status !== "completed") throw new Error("The selected archived evaluation is not completed.");
      archivedReport = result;
    }).catch((error: unknown) => {
      if (token === archiveRequest) archiveError = error instanceof Error ? error.message : "Unexpected archive response";
    }).finally(() => {
      if (token !== archiveRequest) return;
      archiveLoading = false; renderEvaluation(latestReport);
      box("evaluation-results").querySelector<HTMLSelectElement>('select[aria-label="Evaluation run"]')?.focus();
    });
  });
  const historyControls = raw("div", "", "evaluation-suite-selector");
  const historyLabel = raw("label", "Evaluation run"); history.id = "evaluation-history";
  historyLabel.htmlFor = history.id; historyControls.append(historyLabel, history); panel.append(historyControls);
  renderDetectionApproach(panel);
  if (report.evaluation_history?.warnings.length) {
    panel.append(raw("p", "Some archive files could not be indexed. They are unavailable, not scored as successful.", "evaluation-warning"));
  }
  if (selectedArchive && (archiveLoading || archiveError || !archivedReport)) {
    stopSpatialPlayback();
    panel.append(raw("p", archiveLoading ? "Loading the original archived result; no agents are running…" :
      `Archived result unavailable: ${archiveError || "Choose an available archive"}. No score is inferred.`, archiveError ? "error" : "muted"));
    return;
  }
  const selected = selectedArchive ? archivedReport : current;
  if (selectedArchive && selected) {
    panel.append(raw("p", `Historical result · ${selected.run_id} · saved status: ${selected.status} · ${selected.historical_archive_label}. Original predictions and recorded review-checkpoint metrics are loaded unchanged. Snapshot coverage is a display of those archived predictions; current prompts are not evaluated.`, "evaluation-warning"));
  }
  const cohorts = selected ? [selected] : [];
  const accepted = cohorts.flatMap(cohort => cohort.cases.filter(item => item.accepted_report));
  const reportOnly = accepted.filter(item => item.extraction?.status === "completed"
    && item.extraction.source_text_scope === "incident-answer-only-v1").length;
  const provenance = raw("section", "", "evaluation-warning");
  provenance.setAttribute("aria-label", "Evaluation provenance and limits");
  provenance.append(raw("h3", "What these results measure"),
    raw("p", "Final red leak findings, purple instrument findings and their detection scores use a separate LLM extraction from accepted agent incident reports. Orange pressure alerts and preliminary screening warnings remain deterministic. Ground truth supplies comparison labels, never predictions; scoring arithmetic is deterministic, not the source of agent fault labels."),
    raw("p", accepted.length
      ? `${reportOnly}/${accepted.length} accepted reports have recorded incident-report-only extraction provenance. Each positive label is linked to its quoted report explanation.`
      : "No accepted agent reports in this suite; report-based detection performance is not established."));
  if (cohorts.some(cohort => cohort.remapped_at)) {
    provenance.append(raw("p", "Archived agent reports · refreshed extraction and scores, not fresh agent runs. The original reports are unchanged, so their wording can still look old. This is not a full-cohort evaluation of the revised prompts; the separate fresh S7 +110s run does not establish their full-cohort performance."));
  } else provenance.append(raw("p",
    "Recorded results, not new inference. Current-prompt full-cohort performance is not established by opening this tab."));
  panel.append(provenance);
  if (!selected || selected.status === "not_run") {
    stopSpatialPlayback();
    panel.append(raw("h3", suiteNames[selectedSuite]),
      raw("p", "Not run: no live agent results or scores are available for this suite. Opening Evaluation never starts inference.", "evaluation-warning"),
      raw("p", selectedSuite === "recovery" ?
        "Scenarios: a leak stops and pressure recovers; a leak clears before a second incident starts on another branch. Recovery is assessed after a full clean data window, and repeat detection requires a fresh admitted report." :
        selectedSuite === "non_leak" ?
          "Scenarios: paired operating shift, shared gateway offset and restoration, and recovering telemetry gaps/invalid values, all without leakage. Unassessed windows are shown separately from false alarms." :
          "The original network evaluation has no recording yet."));
    if (selectedSuite !== "current") panel.append(raw("code",
      `subsea spatial-evaluation --suite ${selectedSuite} --split development --output <fresh-directory>`));
    return;
  }
  const body = raw("div"); panel.append(body);
  if (selected.version === "spatial-evaluation-v1" && selected.networks) {
    renderLifecycle(selected, body);
    renderSpatialEvaluation(body, selected);
    const evidence = raw("details", "", "spatial-evidence");
    evidence.append(raw("summary", "Whole-run review-checkpoint metrics, known labels, original reports and Langfuse traces"));
    const evidenceBody = raw("div");
    renderEvidence(selected, evidenceBody);
    evidence.append(evidenceBody);
    body.append(evidence);
    return;
  }
  stopSpatialPlayback();
  renderEvidence(selected, body);
}

function resetArchive(): void {
  archiveController?.abort(); archiveController = null;
  ++archiveRequest; selectedArchive = ""; archivedReport = null;
  archiveLoading = false; archiveError = "";
}

function renderLifecycle(report: EvaluationReport, container: HTMLElement): void {
  const metrics = report.metrics?.temporal;
  if (!metrics) return;
  container.append(raw("h3", suiteNames[report.suite || "current"] || report.suite_name || "Evaluation"),
    raw("p", metrics.basis, "evaluation-warning"));
  if (report.implementation_unchanged === false) container.append(raw("p",
    "Implementation changed during this run. These observations are not a controlled comparison.", "evaluation-warning"));
  if (report.networks?.length) container.append(table(
    ["Case", "Recording status", "Source recorded through", "Recorded / planned windows"],
    report.networks.map(network => {
      const planned = report.duration_seconds == null ? null :
        Math.max(0, Math.floor((report.duration_seconds - network.pack.window_seconds) / network.pack.hop_seconds) + 1);
      const through = network.frames[network.frames.length - 1]?.source_seconds;
      return [network.id, network.status,
        through == null ? "Not recorded" : `${through}s`,
        `${network.frames.length}/${planned == null ? "not recorded" : planned}`];
    }),
    ["Synthetic case identifier.", "Failed recordings cannot establish performance for unrecorded events.",
      "Last captured source snapshot, not model wall time.", "Only recorded windows are scored. Missing future windows and episodes are not successful negative controls."],
  ), raw("p", "Events outside the recorded source period are not assessed; zero recorded windows is not zero misses.", "evaluation-warning"));
  if (metrics.episodes.length) container.append(table(
    ["Case / episode", "Leak period", "Fresh detection", "Active coverage misses", "Recovery", "Post-recovery false alarms"],
    metrics.episodes.map(item => [
      `${item.network_id} / ${item.episode} · ${item.segment_id}`,
      `${item.onset_seconds}s → ${item.stop_seconds == null ? "ongoing" : `${item.stop_seconds}s`}`,
      item.first_fresh_correct_review_seconds == null ? "No fresh correct report recorded" :
        `${item.first_fresh_correct_review_seconds}s · delay ${item.detection_delay_source_seconds}s`,
      `${item.uncovered_active_windows}/${item.active_windows} active windows uncovered`,
      item.stop_seconds == null ? "Not applicable: ongoing leak" :
        item.first_clear_review_seconds == null ? `No admitted clearance · ${item.clean_recovery_windows} clean windows recorded` :
          `${item.first_clear_review_seconds}s · ${item.clearance_delay_source_seconds}s after stop`,
      `${item.false_leak_recovery_windows}/${item.clean_recovery_windows} clean windows falsely reported · ${item.unassessed_recovery_windows} unassessed`,
    ]),
    ["Each injected leak episode is scored separately, even within the same case.",
      "Synthetic source onset and stop, not agent or wall-clock timing.",
      "First fresh final report identifying the correct branch after this episode starts. Old retained findings cannot count as a new detection.",
      "Leak-present snapshots without a correct-branch report, including unreviewed windows.",
      "Requires an admitted no-leak report after one full window without leakage. Failed reviews cannot prove recovery.",
      "Retained false leak reports in clean recovery windows. Windows without an admitted report remain explicitly unassessed."],
  ));
  if (metrics.controls.length) container.append(table(
    ["Control", "Recorded windows", "With report / without report", "False leak alarms", "Inspection recommendations"],
    metrics.controls.map(item => [
      `${item.network_id} · ${item.name}`, String(item.windows),
      `${item.assessed_windows} report-covered · ${item.unassessed_windows} without a report`,
      item.assessed_windows ? `${percent(item.false_leak_windows / item.windows)} (${item.false_leak_windows}/${item.windows})` :
        "Not assessed: no admitted reports",
      item.assessed_windows ? `${item.inspection_windows}/${item.windows} windows with an inspection interval` :
        "Not assessed: no admitted reports",
    ]),
    ["A synthetic scenario with no injected leak.", "Overlapping source snapshots, not independent trials.",
      "Snapshots using a latest admitted report, possibly retained, versus snapshots without one. This is not a count of fresh investigations or proof of health.",
      "Snapshots falsely reported as leakage / all recorded no-leak snapshots. Retained false reports count until reassessed.",
      "No-leak snapshots retaining a proposed inspection interval. This is an unnecessary recommendation, not equipment actuation."],
  ));
}

function renderDetectionApproach(container: HTMLElement): void {
  const approach = approachDetails("detection", "Detection: approach and ground truth");
  approach.setAttribute("aria-label", "Detection evaluation approach");
  approach.append(
    raw("h4", "What this evaluates"),
    raw("p", "Whether agents detect leaks and sensor issues from available measurements and permitted context at the correct source time. The benchmark uses synthetic pipeline scenarios with known injected events, including recovery, repeated leaks and no-leak controls."),
    raw("h4", "Goal"),
    raw("p", "Identify the correct leak branch, affected instrument and issue type promptly; avoid false alarms and unnecessarily broad inspection recommendations; and recognize when a leak clears or a new episode starts. A later correct report must not conceal an earlier missed detection."),
    raw("h4", "Ground truth and scoring"),
    raw("p", "Reference labels are defined independently by synthetic scenario recipes before the agents run. They specify injected leak branches, chainages, onset/stop times and sensor fault IDs/types. A successful agent answer is never used as ground truth."),
    table(["Stage", "How it works"], [
      ["Dataset first", "Seeded measurements and hidden source labels are frozen together. Current detection, recovery/repeated-leak and no-leak stress recordings remain separate cohorts."],
      ["Agent input", "Agents receive numerical snapshots and permitted context, not injected source labels. Source time pauses through investigation, mapping and result admission; 30× replay does not accelerate model inference."],
      ["Predictions", "A separate LLM maps accepted incident reports to leak branches, instrument IDs/types and exact supporting quotations. This extraction can err; original reports and mapping quotations remain inspectable."],
      ["Causal scoring", "Only source/snapshot/hash-matched admitted reports are used. Later reports cannot repair earlier misses. Valid retained reports persist until a newer admitted reassessment; failures do not fabricate negative findings."],
      ["Accuracy", "Precision = TP/(TP+FP); recall = TP/(TP+FN). Branch recall is correct branch identification, not exact leak position. Inspection interval containment and width are separate measures."],
      ["Timing and controls", "Each repeated episode requires fresh detection. Clearance requires a fresh negative after a full clean window. No-leak windows measure false reports; uncovered and unrecorded windows are disclosed separately."],
      ["Limits", "Related overlapping snapshots are not independent field trials. Pressure-alert markers are numerical detector outputs, not independent anomaly ground truth. Synthetic hydraulic behaviour and engineering judgment are not field validated."],
    ], ["Evaluation stage.", "Reference construction, observed prediction and deterministic scoring are distinct."]));
  container.append(approach);
}

function renderAgentReferences(
  report: AgentReferenceReport | undefined, container: HTMLElement, opened: Set<string | undefined>,
  openedInputs: Set<string | undefined>,
): void {
  const approach = approachDetails("agent", "Agent reliability: approach and ground truth");
  approach.id = "agent-reference-method";
  approach.setAttribute("aria-label", "Agent reliability evaluation approach");
  approach.append(
    raw("h4", "What this evaluates"),
    raw("p", "The quality of an operator-facing investigation answer built from a frozen measurement and document packet: its factual findings, explanation, verification steps and stated limitations. This is a controlled answer-quality component benchmark, not a test of the full multi-agent workflow."),
    raw("h4", "Goal"),
    raw("p", "Produce clear, factually supported explanations that respect the available evidence, time boundary and document authority; communicate uncertainty honestly; and recommend proportionate, read-only verification. Unsupported causes, invented evidence and unwarranted safety assurances should be flagged."),
    raw("h4", "Ground truth and scoring"),
    raw("p", "The eight-case ground-truth dataset provides independently authored factual references. Answers are evaluated across grounding, numerical accuracy, causal reasoning, scope, uncertainty and usefulness. The six quality ratings are advisory model judgments, not engineer-authored gold answers.", "evaluation-warning"),
    table(["Stage", "Definition"], [
      ["Dataset and ground truth", "Eight explicit fixtures: two development and six held-out cases. Expected bar values, current evidence IDs, documented instrument issues and warranted leak assertions are written in the dataset, then cross-checked from its raw facts before inference."],
      ["Available information", "The answering model receives only the original input packet and general rules. It returns facts, an explanation, verification steps and limitations. The expected answer and other cases are not sent to it. The reviewer sees the saved answer and original ground-truth facts."],
      ["Authority and uncertainty", "Only approved, available, effective, non-superseded verification records establish documented findings. Conflicts remain not established. Pressure changes alone do not establish a confirmed leak; a fixture-defined approved leak-verification record can."],
      ["Scoring", "Six separate advisory scores out of 5, each with a rationale, evidence IDs and an exact answer excerpt. Insufficient-evidence/not-applicable dimensions are unscored, not zero or passes. The original deterministic factual checks remain supporting diagnostics. A numerical endorsement is rejected if the structured measurement check fails; free-text judgments can still err."],
      ["Failure accounting", "Answer and review failures are shown separately. All selected cases remain in coverage and factual-check denominators. Quality means use only scored opinions; missing reviews never become passing or zero-scored judgments."],
      ["Scope", "A controlled component benchmark of the configured agent model with fixture-supplied evidence. It does not run the production planner/specialist/coordinator workflow, certify open-ended engineering reasoning or establish field reliability."],
      ["Provenance", "The dataset and review rubric are frozen before either model is constructed. Each generated answer is saved before review. Dataset, answer-policy and rubric hashes, observed author/reviewer models and real wall times are recorded. Reviewer opinions may share the author's model/provider bias."],
    ], ["Evaluation stage.", "The machine-checkable reference and declared limitations are independent of agent outputs."]));
  const workspace = raw("div", "", "agent-reference-workspace");
  container.append(approach, workspace);
  if (!report) {
    const empty = raw("section", "", "agent-reference-section");
    empty.append(raw("p", "Evaluation at a glance", "eyebrow"),
      raw("h3", "No answer-quality evaluation recorded"),
      raw("p", "Not run: no dataset-based agent reference results are published.", "empty"),
      raw("code", "subsea agent-evaluation --split held_out --output <fresh-directory>"));
    workspace.append(empty);
    return;
  }
  const metrics = report.metrics;
  const quality = report.answer_quality;
  const reviewed = quality?.metrics.reviewed || 0;
  const names: Record<string, string> = {
    measurement_facts: "Measurement facts", instrument_evidence: "Document-backed instrument facts",
    leak_evidence: "Warranted leak assertions", evidence_references: "Evidence reference correctness",
  };
  const descriptions: Record<string, string> = {
    measurement_facts: "Correct normalized pressure values and valid, invalid or missing measurement states.",
    instrument_evidence: "Only instrument issues established by the current, approved fixture evidence.",
    leak_evidence: "Only leak assertions warranted by the available fixture evidence; pressure alone cannot confirm a leak.",
    evidence_references: "Exact permitted evidence IDs, with no invented references or duplicate subjects.",
  };
  const keys = Object.keys(metrics.checks);
  const passedCase = (item: AgentReferenceReport["cases"][number]): boolean =>
    item.status === "completed" && keys.length > 0 && keys.every(key => item.checks[key] === true);
  const fraction = (count: number, total: number): string => total ? `${count}/${total}` : "Not assessed";
  const overview = raw("section", "", "agent-reference-section agent-reference-overview");
  overview.setAttribute("aria-label", "Agent reference evaluation overview");
  const heading = raw("div", "", "agent-reference-heading");
  heading.append(raw("h3", "How well does the agent explain the findings?"),
    raw("span", `Recorded · ${report.status}`, "agent-reference-status"));
  overview.append(raw("p", "Evaluation at a glance", "eyebrow"), heading,
    raw("p", "Start with the six answer-quality dimensions, then inspect a case for the reasoning, evidence and original ground truth. Factual checks are deterministic; quality judgments are advisory.", "agent-reference-takeaway"));
  const cards = raw("div", "", "agent-reference-metrics");
  for (const [label, value, meaning] of [
    ["Answers reviewed", fraction(reviewed, metrics.planned), "Completed quality reviews / all selected cases."],
    ["Reviews without concerns", fraction(quality?.metrics.no_concerns || 0, reviewed), "At least one supported dimension; no concerns or insufficient evidence."],
    ["Review execution failures", quality ? String(quality.metrics.execution_failed) : "Not assessed", "Failed reviews have no opinion or score."],
    ["Answer execution/output failures", String(metrics.failed), "Undelivered answers remain in selected-case coverage."],
  ]) {
    const card = raw("article"); card.setAttribute("aria-label", label);
    card.append(raw("span", label), raw("strong", value), raw("p", meaning));
    cards.append(card);
  }
  overview.append(cards,
    raw("p", `What needs attention? ${quality?.metrics.with_concerns || 0} reviewed answers have concerns; ${quality?.metrics.insufficient_evidence || 0} have insufficient evidence. ${metrics.planned - reviewed} selected cases have no completed quality review.`, "agent-reference-finding"),
    raw("p", report.scope, "evaluation-warning"),
    raw("p", `Selected split: ${report.split}. Requested model: ${report.requested_model}.`, "muted"));
  if (report.ground_truth_supplied_to_agent) {
    const warning = raw("p", "Invalid evaluation: expected answers were supplied to the agent. These results do not establish independent reference correctness.", "error");
    warning.setAttribute("role", "alert"); overview.append(warning);
  }
  if (report.implementation_unchanged === false) overview.append(raw("p",
    "Implementation changed during this run; do not treat these results as a controlled comparison.", "evaluation-warning"));
  if (!quality) overview.append(raw("p",
    "Not assessed: this recording contains factual results but no six-dimensional answer-quality reviews. Factual results below are supporting diagnostics, not quality scores.", "evaluation-warning"));
  if (report.dataset_unchanged === false) overview.append(raw("p",
    "The source dataset changed during this run. The frozen manifest remains the reference; this is not an unchanged-dataset comparison.", "evaluation-warning"));
  const navigation = raw("nav", "", "agent-reference-navigation");
  navigation.setAttribute("aria-label", "Explore agent evaluation");
  for (const [label, target] of [
    ["Browse individual evaluations", "agent-reference-results"],
    ["How the evaluation works", "agent-reference-method"],
  ]) {
    const link = raw("a", label); link.href = `#${target}`;
    if (target === "agent-reference-method") link.addEventListener("click", () => { approach.open = true; });
    navigation.append(link);
  }
  overview.append(navigation); workspace.append(overview);
  const aggregate = raw("section", "", "agent-reference-section");
  aggregate.setAttribute("aria-label", "Aggregate answer quality");
  aggregate.append(raw("p", "Aggregate answer quality", "eyebrow"),
    raw("h3", "Where the explanations are strong — and where they need work"),
    raw("p", "Mean advisory scores out of 5 for this saved cohort. Unscored dimensions are excluded, not counted as zero or a pass. These are not engineering ground-truth labels or a reliability percentage.", "muted"),
    table(["Quality dimension", "Mean / scored answers", "Concerns", "Unscored"],
      Object.entries(qualityNames).map(([key, name]) => {
        const item = quality?.metrics.dimensions[key];
        const label = raw("span", name); label.tabIndex = 0;
        label.title = quality?.dimensions[key] || "Answer quality is not reviewed for this recording.";
        label.setAttribute("aria-description", label.title);
        return [label, item?.average == null ? "Not scored" : `${item.average.toFixed(2)}/5 · ${item.scored} scored`,
          quality ? String(item?.concerns || 0) : "Not reviewed",
          quality ? `${item?.insufficient_evidence || 0} insufficient · ${item?.not_applicable || 0} N/A` : "Not reviewed"];
      }),
      ["Advisory answer-quality target.", "Only actual scored opinions enter the mean.",
        "Reviews flagging this dimension.", "Insufficient evidence or not applicable; never zero-scored passes."]));
  if (quality?.metrics.by_split) {
    const splits = raw("details", "", "agent-reference-disclosure");
    splits.append(raw("summary", "Development and held-out answer quality"),
      table(["Split", "Reviewed / selected", ...Object.values(qualityNames)],
        Object.entries(quality.metrics.by_split).map(([name, item]) => [
          name, `${item.reviewed}/${item.planned}`,
          ...Object.keys(qualityNames).map(key => {
            const value = item.dimensions[key];
            return value.average == null ? "Not scored" : `${value.average.toFixed(2)}/5 · ${value.scored} scored`;
          }),
        ])));
    aggregate.append(splits);
  }
  const factual = raw("details", "", "agent-reference-disclosure");
  factual.append(raw("summary", "Supporting ground-truth checks · frozen dataset"),
    raw("p", `${metrics.all_checks_passed}/${metrics.planned} selected cases passed every factual check. These checks support the review but do not replace the six answer-quality targets.`),
    table(["Reference check", "Cases passed / selected cases"],
    Object.entries(metrics.checks).map(([key, value]) => {
      const label = raw("span", names[key] || key);
      label.title = descriptions[key] || "Recorded deterministic reference check.";
      label.tabIndex = 0; label.setAttribute("aria-description", label.title);
      return [label, `${fraction(value.passed, value.denominator)}${report.status === "running" ? " so far" : ""}`];
    }), ["Deterministic check against the frozen reference.", "All selected cases, including failed executions, remain in the denominator."]));
  const missed = Object.entries(metrics.checks).map(([key]) => ({
    key, count: report.cases.filter(item => item.status === "completed" && item.checks[key] !== true).length,
  })).filter(item => item.count > 0).sort((a, b) => b.count - a.count);
  factual.append(raw("p", `Most frequent reference misses: ${missed.length
    ? missed.map(item => `${names[item.key] || item.key} (${item.count} delivered ${item.count === 1 ? "answer" : "answers"})`).join("; ")
    : metrics.completed ? "none in the delivered answers." : "no delivered answers yet."}`, "agent-reference-finding"),
    raw("h4", "Development and held-out coverage"),
    table(["Dataset split", "Selected", "Answers delivered", "Reviews completed", "All factual checks passed"],
    [...new Set(report.cases.map(item => item.split))].map(split => {
      const rows = report.cases.filter(item => item.split === split);
      return [split, String(rows.length), String(rows.filter(item => item.status === "completed").length),
        String(rows.filter(item => item.judge?.status === "completed").length),
        String(rows.filter(passedCase).length)];
    }), ["Declared development or held-out split; do not combine them into a held-out claim.",
      "All selected fixtures.", "Structured answers delivered, not necessarily correct.",
      "Completed advisory reviews, not passing grades.", "Original deterministic facts; failures remain in the selected-case denominator."]));
  aggregate.append(factual);
  const coverage = raw("details", "", "agent-reference-disclosure");
  coverage.append(raw("summary", "Coverage and how to read these numbers"),
    raw("p", "The first coverage count uses all selected cases. Quality means use only scored opinions; a review with several concerns counts in several dimensions. Answer failures, review failures and missing opinions stay visible. Development and held-out coverage are separate."),
    raw("p", "The existing synthetic facts are the factual ground truth; there is no engineer-authored gold explanation. Author/reviewer model bias and one answer/review per case do not establish repeated-run stability, full workflow performance or field reliability. Opening this view starts no inference."));
  aggregate.append(coverage); workspace.append(aggregate);
  const individual = raw("section", "", "agent-reference-section");
  individual.id = "agent-reference-results";
  individual.append(raw("p", "Individual evaluations", "eyebrow"),
    raw("h3", "Inspect the results behind the summary"),
    raw("p", "One row per original ground-truth case. Completed means an answer or review was delivered, not that it passed. Inspect the six opinions, rationales and source references beside the unchanged expected facts.", "muted"));
  const records = raw("details", "", "agent-reference-records");
  records.dataset.referenceRecords = "true";
  records.open = referenceRecordsOpen;
  records.addEventListener("toggle", () => { referenceRecordsOpen = records.open; });
  records.append(raw("summary", `Full reference records · ${report.cases.length} cases`));
  const outcome = (item: AgentReferenceReport["cases"][number], key: string): string =>
    item.status === "queued" || item.status === "running" ? "Pending" :
      item.status === "completed" ? item.checks[key] === true ? "Pass" : "Fail" : "Not assessed";
  const rows = report.cases.map(item => {
    const details = raw("details", "", "evaluation-case");
    details.id = `agent-reference-case-${item.id}`;
    details.dataset.referenceCase = item.id; details.open = opened.has(item.id);
    details.append(raw("summary", `${item.id} · ${item.name} · ${item.status}`),
      raw("p", `Split: ${item.split} · observed author: ${item.model_receipt?.observed_model || "not recorded"} · observed reviewer: ${item.judge?.model_receipt?.observed_model || "not recorded"}`));
    if (item.answer) {
      details.append(raw("h4", "Saved investigation answer"),
        raw("p", item.answer.explanation, "evaluation-answer"),
        raw("h4", "Verification steps"), raw("p", item.answer.next_steps.join("\n"), "evaluation-answer"),
        raw("h4", "Stated limitations"), raw("p", item.answer.limitations.join("\n"), "evaluation-answer"));
    }
    if (item.judge?.status === "completed" && item.judge.verdict) {
      details.append(raw("h4", "Advisory answer-quality review"),
        raw("p", item.judge.verdict.summary),
        table(["Quality dimension", "Opinion / score", "Reason and evidence"],
          item.judge.verdict.dimensions.map(dimension => {
            const reason = raw("div");
            if (dimension.answer_excerpt) reason.append(raw("blockquote", dimension.answer_excerpt));
            reason.append(raw("p", dimension.rationale),
              raw("p", `Frozen evidence IDs: ${dimension.evidence_ids.join(", ") || "none cited"}`, "muted"));
            return [qualityNames[dimension.dimension] || dimension.dimension,
              `${dimension.status.replace(/_/g, " ")} · ${dimension.score === null ? "Not scored" : `${dimension.score}/5`}`, reason];
          })));
    } else details.append(raw("p", `Quality review: ${item.judge?.status || "not evaluated"}${item.judge?.error_code ? ` · ${item.judge.error_code}` : ""}. ${item.judge?.reason || "No opinion or score is inferred."}`, "evaluation-warning"));
    details.append(
      raw("h4", "Deterministic reference checks"),
      table(["Reference check", "Result"], keys.map(key => [names[key] || key, outcome(item, key)])));
    if (item.error_code) details.append(raw("p", `Recorded execution/output error: ${item.error_code}`, "error"));
    const comparison = raw("div", "", "agent-reference-comparison");
    const expected = raw("section");
    expected.append(raw("h4", "Ground truth fixed before inference"), raw("pre", JSON.stringify(item.expected, null, 2)));
    const actual = raw("section");
    actual.append(raw("h4", "Actual agent output"),
      item.actual === null ? raw("p", "No structured output recorded. No pass is inferred.", "empty") :
        raw("pre", JSON.stringify(item.actual, null, 2)));
    comparison.append(expected, actual); details.append(comparison);
    const input = raw("details", "", "agent-reference-disclosure");
    input.dataset.referenceInput = item.id; input.open = openedInputs.has(item.id);
    input.append(raw("summary", "Frozen agent input"), raw("pre", JSON.stringify(item.input, null, 2)));
    details.append(input); records.append(details);
    const identity = raw("div");
    identity.append(raw("strong", `${item.id} · ${item.name}`),
      raw("span", `${item.split} · ${item.family}`, "agent-reference-cell-note"));
    const passed = keys.filter(key => item.status === "completed" && item.checks[key] === true).length;
    const checks = item.status === "completed" ? `${passed}/${keys.length} factual checks` :
      item.status === "failed" ? "Facts not assessed" : "Pending";
    const review = raw("div");
    review.append(raw("span", item.judge?.status.replace(/_/g, " ") || "not evaluated"));
    if (item.judge?.verdict) {
      const flags = item.judge.verdict.dimensions.filter(dimension =>
        ["concern", "insufficient_evidence"].includes(dimension.status));
      review.append(raw("span", flags.map(dimension =>
        `${qualityNames[dimension.dimension] || dimension.dimension}: ${dimension.status.replace(/_/g, " ")}`)
        .join("; ") || (item.judge.verdict.dimensions.some(dimension => dimension.score !== null)
          ? "No concerns flagged" : "All dimensions unscored"), "agent-reference-cell-note"));
    }
    if (item.judge?.error_code) review.append(raw("span", item.judge.error_code, "error"));
    const link = raw("a", "Inspect case"); link.href = `#${encodeURIComponent(details.id)}`;
    link.setAttribute("aria-label", `Inspect reference case ${item.id}`);
    link.addEventListener("click", () => {
      records.open = true; details.open = true;
      details.querySelector("summary")?.focus();
    });
    return [identity, `${item.status}${item.error_code ? `: ${item.error_code}` : ""}`, review, checks,
      item.elapsed_seconds == null ? "Pending" : `${item.elapsed_seconds.toFixed(1)} s`, link];
  });
  individual.append(table(["Reference case", "Answer execution", "Quality review", "Supporting facts", "Answer wall time", "Explore"], rows,
    ["Independent case name and dataset split.", "Answer delivery status, not correctness.",
      "Advisory review status and flagged dimensions; completed does not mean passed.",
      "Original ground-truth checks, not the answer-quality grade.",
      "Real recorded model/transport time; replay speed does not compress it.", "Open the exact recorded case and reference comparison."]),
    records);
  workspace.append(individual);
  const provenance = approachDetails("provenance", "Recorded run, model and dataset provenance");
  provenance.append(
    raw("p", `Recorded run ${report.run_id}. Requested model: ${report.requested_model}. Reference origin: ${report.reference_origin}.`),
    raw("p", `Expected answers supplied to the agent: ${report.ground_truth_supplied_to_agent ? "YES — invalid evaluation" : "no"}.`),
    raw("p", `Dataset SHA-256: ${report.dataset_sha256} · policy ${report.policy_version} / ${report.policy_sha256}`, "evaluation-hash"),
    raw("p", `Dataset file SHA-256: ${report.dataset_file_sha256 || "not recorded"} · review rubric SHA-256: ${quality?.rubric_sha256 || "not evaluated"} · requested reviewer: ${quality?.requested_judge_model || "not evaluated"}`, "evaluation-hash"),
    raw("p", "This report describes the saved reference inputs and answers, not today's prompts or a fresh model run. Viewing it never starts inference.", "muted"));
  workspace.append(provenance);
}

function renderEvidence(report: EvaluationReport, container: HTMLElement): void {
  const opened = new Set([...container.querySelectorAll<HTMLDetailsElement>("details[open]")].map(item => item.dataset.case));
  container.replaceChildren();
  if (report.status === "not_run") {
    container.append(raw("p", "No recorded reference evaluation is available. Opening this tab never runs inference.", "empty"));
    return;
  }
  const metrics = report.metrics;
  container.append(
    raw("h3", `${report.split === "held_out" ? "Held-out measurements" : "Development measurements"} · ${report.status.replace(/_/g, " ")}`),
    raw("p", `${metrics?.completed_cases || 0}/${report.planned_cases} cases finished. Requested agent: ${report.agent_model}; requested extractor and separate explanation judge: ${report.evaluator_model}. Seed ${report.seed}.`),
    raw("p", "Ground truth → agents without labels → truth-blind output mapping → deterministic comparison. The separate LLM judge does not award precision, recall or F1.", "summary"),
    raw("p", "Sensor problems and leakage are scored independently because they can coexist. The original answer and exact supporting quotes remain available below."),
  );
  if (metrics) {
    const measuredLabels: Record<string, string> = report.version === "spatial-evaluation-v1" ? {
      ...labels,
      leak_recognition: "Agent leak-pattern recognition · network/review",
      agent_pipeline_identification: "Agent affected-pipeline identification · network/review/pipeline",
      instrumentation_recognition: "Agent instrumentation concerns · network/review",
      agent_sensor_concerns: "Agent suspect-instrument identification · network/review/sensor",
      agent_issue_types: "Agent issue-type mapping · network/review/sensor/type",
    } : labels;
    if (report.version === "spatial-evaluation-v1") container.append(raw("p",
      "Whole-run review-checkpoint scores across all networks and completed reviews, including later reports. These checkpoint-only scores are not the overall time-window coverage shown above; unreviewed windows and detection delays are not measured by this aggregate.",
      "evaluation-warning"));
    container.append(raw("strong", metrics.target_met ?
      report.version === "spatial-evaluation-v1" ? "Observed review-checkpoint metrics exceed 95%; this is not continuous coverage." :
        "Observed reference metrics exceed 95%." : "The >95% target is not yet met.", metrics.target_met ? "evaluation-pass" : "evaluation-warning"));
    container.append(raw("p", "These are small-sample synthetic reference results, not 95% field reliability. A withheld location or failed run is not removed from recall or coverage."));
    container.append(raw("p", "Precision: how many reported findings are correct. Recall: how many known findings were found. F1 balances both. TP means correctly found; FP means incorrectly reported; FN means missed. The displayed proportion intervals assume independent binomial observations; these related reference patterns do not establish population reliability."));
    container.append(table(
      ["Measured task / unit", "Precision", "Recall", "F1", "TP / FP / FN"],
      Object.entries(metrics.groups).map(([name, value]) => [
        measuredLabels[name] || name, rate(value.precision), rate(value.recall), rate(value.f1),
        `${value.tp} / ${value.fp} / ${value.fn}`,
      ]),
    ));
    container.append(table(
      ["Additional measure", "Observed result"],
      Object.entries(metrics.rates).map(([name, value]) => [labels[name] || name, rate(value)]),
    ));
    container.append(raw("p", `Interval midpoint error: ${metrics.localization_mean_midpoint_error_m === null ? "not measurable" : `${metrics.localization_mean_midpoint_error_m.toFixed(1)} m`}; mean proposed width: ${metrics.localization_mean_width_m === null ? "not measurable" : `${metrics.localization_mean_width_m.toFixed(1)} m`}. Midpoint error is not an exact leak-point prediction.`));
    container.append(raw("p", `Extractor/judge calibration: ${metrics.calibration_passed ? "passed" : "not passed or incomplete"}. Confirmed physical-cause assertions: ${metrics.confirmed_cause_claims}.`));
  }
  container.append(raw("h3", "Labelled datasets and recorded answers"));
  for (const item of report.cases) {
    const details = raw("details", "", "evaluation-case");
    details.dataset.case = item.case_id;
    details.open = opened.has(item.case_id);
    details.append(raw("summary", `${item.case_id} · ${item.name} · ${item.status.replace(/_/g, " ")}`));
    const source = item.truth.leak_source;
    const mapping = item.extraction?.mapping;
    details.append(table(["Known source labels · evaluation only", "Extracted agent statements"], [
      [source ? `Leak source on ${source.segment_id} at ${source.chainage_m} m` : "No injected leak", mapping ? intervalText(mapping.leaks) : "No valid mapping available"],
      [issueText(item.truth.sensor_issues), mapping ? issueText(mapping.sensor_issues) : "No valid mapping available"],
      [report.version === "spatial-evaluation-v1" ? "Numerical pressure flags are shown on the map; continuous physical influence is not a binary source label." : `Pressure anomalies: ${item.truth.pressure_anomaly_sensors.join(", ") || "none"}`, item.root_count === 0 ? "No agent invoked" : `Root state: ${item.state || "running"}`],
      [`Missing/invalid values: ${item.truth.missing_value_sensors.join(", ") || "none"}`, item.judge ? `Explanation judge: ${item.judge.status}; ${item.judge.passed ? "passed" : "not passed"}` : "Explanation judge not completed"],
    ]));
    details.append(raw("p", `Agent time: ${item.agent_elapsed_seconds === undefined ? "not reported" : `${item.agent_elapsed_seconds.toFixed(1)} s`}; agent model calls: ${item.agent_calls === undefined ? (item.root_count === 0 ? "0" : "not reported") : item.agent_calls}.`));
    const observed = [...new Set((item.model_receipts || []).flatMap(value => value.observed_model ? [value.observed_model] : []))];
    details.append(raw("p", `Observed agent models: ${observed.join(", ") || (item.root_count === 0 ? "no model invoked" : "not yet reported")}.`));
    details.append(raw("p", `Observed extractor: ${item.extraction?.model_receipt?.observed_model || "not reported"}; observed explanation judge: ${item.judge?.model_receipt?.observed_model || "not reported"}.`));
    if (item.error_code || item.extraction?.error_code) details.append(raw("p", `Recorded error: ${item.error_code || item.extraction?.error_code}`, "error"));
    if (item.interpretation) details.append(raw("h4", "Original accepted engineering briefing"), raw("p", item.interpretation.answer.text, "evaluation-answer"));
    if (item.answer) {
      const complete = raw("details");
      complete.dataset.case = `${item.case_id}:report`;
      complete.open = opened.has(complete.dataset.case);
      complete.append(raw("summary", "Complete accepted report · sensor groups and checked evidence"), raw("p", item.answer, "evaluation-answer"));
      details.append(complete);
    }
    if (mapping) {
      details.append(raw("h4", "Mapping evidence · verbatim agent quotations"));
      const quotes = [...mapping.leaks.map(value => value.quote), ...mapping.sensor_issues.flatMap(value => value.quote ? [value.quote] : []), ...(mapping.instrumentation_quote ? [mapping.instrumentation_quote] : [])];
      quotes.forEach(quote => details.append(raw("p", `${quote.path}: “${quote.text}”`, "evaluation-quote")));
    }
    if (item.judge?.verdict) details.append(table(
      ["Explanation dimension", "Score / 2", "Judge rationale"],
      Object.entries(item.judge.verdict.dimensions).map(([name, value]) => [name.replace(/_/g, " "), String(value.score), value.reason]),
    ));
    (item.traces || []).forEach(value => details.append(traceLine(agentName(value.role), value.trace)));
    details.append(traceLine("Truth-blind extraction", item.extraction?.trace), traceLine("External explanation judge", item.judge?.trace));
    details.append(raw("p", `Immutable dataset SHA-256: ${item.dataset_sha256}`, "evaluation-hash"));
    container.append(details);
  }
  container.append(raw("h3", "Calibration controls"));
  container.append(table(["Extractor control", "Deterministic expected mapping"], (report.mapping_calibration || []).map(item => [item.name, item.passed ? "Matched" : "Not matched"])));
  container.append(table(["Explanation judge control", "Expected verdict", "Observed verdict"], (report.judge_calibration || []).map(item => [item.identity, item.expected_pass ? "Accept" : "Reject", item.status === "completed" ? (item.passed ? "Accept" : "Reject") : "No valid verdict"])));
  const scope = raw("details", "", "evaluation-scope"); scope.dataset.case = "scope"; scope.open = opened.has("scope");
  scope.append(raw("summary", "Measurement scope and limitations"));
  scope.append(raw("p", `Implementation SHA-256: ${report.implementation_sha256 || "not recorded"}. Code unchanged throughout execution: ${report.implementation_unchanged === undefined ? "not yet verified" : report.implementation_unchanged ? "verified" : "not verified"}.`));
  (report.limitations || []).forEach(value => scope.append(raw("p", value)));
  container.append(scope, raw("p", `Recorded run: ${report.run_id}. Viewing these results never invokes agents or changes monitoring evidence.`, "muted"));
  if (report.previous_runs?.length) {
    container.append(raw("h3", "Retained prior cohorts · no failed attempts erased"));
    container.append(table(
      ["Run / split / seed", "Leak recall", "Instrumentation precision / recall", "Accepted coverage", "Explanation judge pass rate"],
      report.previous_runs.map(previous => [
        `${previous.run_id} · ${previous.split} · ${previous.seed} · ${previous.status}`,
        previous.metrics ? rate(previous.metrics.groups.leak_recognition.recall) : "Not measured",
        previous.metrics ? `${rate(previous.metrics.groups.instrumentation_recognition.precision)} / ${rate(previous.metrics.groups.instrumentation_recognition.recall)}` : "Not measured",
        previous.metrics ? rate(previous.metrics.rates.accepted_report_coverage) : "Not measured",
        previous.metrics ? rate(previous.metrics.rates.judge_pass_rate) : "Not measured",
      ]),
    ));
    container.append(raw("p", "Development cohorts may use different prompts or extraction protocols. Prior measurements are retained as recorded, not silently regraded.", "muted"));
  }
}
