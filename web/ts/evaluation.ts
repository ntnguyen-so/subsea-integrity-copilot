import { box, node } from "./dom";
import { agentName } from "./agentwork";

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
interface EvaluationCase {
  case_id: string; name: string; status: string; dataset_sha256: string;
  truth: {
    leak_source: { segment_id: string; chainage_m: number } | null;
    sensor_issues: Issue[]; pressure_anomaly_sensors: string[];
    missing_value_sensors: string[]; pressure_trigger: boolean;
  };
  extraction?: { status: string; mapping: Mapping | null; error_code?: string; trace?: Trace; model_receipt?: { observed_model?: string } };
  judge?: { status: string; passed: boolean; verdict: { dimensions: Record<string, { score: number; reason: string }> } | null; trace?: Trace; model_receipt?: { observed_model?: string } };
  interpretation?: { answer: { text: string } };
  answer?: string;
  root_count?: number; state?: string; error_code?: string;
  agent_elapsed_seconds?: number; agent_calls?: number;
  traces?: { role: string; trace: Trace | null }[];
  model_receipts?: { observed_model?: string }[];
}
interface Trace { trace_id?: string; langfuse_url?: string }
export interface EvaluationReport {
  status: string; cases: EvaluationCase[]; split?: string; seed?: number;
  run_id?: string; agent_model?: string; evaluator_model?: string; planned_cases?: number;
  implementation_sha256?: string; implementation_unchanged?: boolean;
  previous_runs?: { run_id: string; split: string; seed: number; status: string; metrics: EvaluationReport["metrics"] }[];
  limitations?: string[];
  mapping_calibration?: { name: string; passed: boolean }[];
  judge_calibration?: { identity: string; status: string; passed: boolean; expected_pass: boolean }[];
  metrics: {
    completed_cases: number; target_met: boolean; calibration_passed: boolean;
    groups: Record<string, Detection>; rates: Record<string, Rate>;
    localization_mean_midpoint_error_m: number | null;
    localization_mean_width_m: number | null; confirmed_cause_claims: number;
  } | null;
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
function table(headers: string[], rows: string[][]): HTMLElement {
  const wrapper = raw("div", "", "table-wrap");
  const result = raw("table");
  const head = raw("tr");
  headers.forEach(value => head.append(raw("th", value)));
  const body = raw("tbody");
  rows.forEach(values => {
    const row = raw("tr");
    values.forEach(value => row.append(raw("td", value)));
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

export function renderEvaluation(report: EvaluationReport): void {
  const container = box("evaluation-results");
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
    container.append(raw("strong", metrics.target_met ? "Observed reference metrics exceed 95%." : "The >95% target is not yet met.", metrics.target_met ? "evaluation-pass" : "evaluation-warning"));
    container.append(raw("p", "These are small-sample synthetic reference results, not 95% field reliability. A withheld location or failed run is not removed from recall or coverage."));
    container.append(raw("p", "Precision: how many reported findings are correct. Recall: how many known findings were found. F1 balances both. TP means correctly found; FP means incorrectly reported; FN means missed. The displayed proportion intervals assume independent binomial observations; these related reference patterns do not establish population reliability."));
    container.append(table(
      ["Measured task / unit", "Precision", "Recall", "F1", "TP / FP / FN"],
      Object.entries(metrics.groups).map(([name, value]) => [
        labels[name] || name, rate(value.precision), rate(value.recall), rate(value.f1),
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
      [`Pressure anomalies: ${item.truth.pressure_anomaly_sensors.join(", ") || "none"}`, item.root_count === 0 ? "No agent invoked" : `Root state: ${item.state || "running"}`],
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
