import { bounds, button, friendly, node } from "./dom";
import { reportText } from "./presentation";
import type { AgentTask, InvestigationCase, Json, WindowSnapshot } from "./types";

function display(value: Json | undefined): string {
  return value === undefined || value === null ? "unknown" : typeof value === "object" ? JSON.stringify(value) : String(value);
}
function object(value: Json): value is Record<string, Json> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function reportGoal(file: InvestigationCase): { seconds: number; met: boolean } {
  return file.interpretation_review?.protocol === "semantic-grounding-v2"
    ? { seconds: 300, met: file.recorded_elapsed_seconds < 300 }
    : { seconds: file.report_target_seconds, met: file.report_target_met };
}
export function renderWorkflowComparison(container: HTMLElement, snapshot: WindowSnapshot, task: AgentTask,
  file: InvestigationCase | null, scenario: string, inspect: () => void): void {
  const section = node("section", "", "workflow-comparison");
  section.id = "workflow-comparison";
  section.dataset.snapshot = snapshot.id;
  section.dataset.inputHash = snapshot.input_hash;
  section.append(node("h3", "Same alert. What does the product add?"));
  section.append(node("p", "Keep individual sensor alerts. Add classification, a supported inspection area and a reviewable investigation."));
  section.append(node("p", `Both columns use ${bounds(snapshot.window_start, snapshot.window_end)} · source +${snapshot.end_seconds}s. Same immutable measurements and detector versions.`, "muted"));
  const columns = node("div", "", "workflow-columns");
  const baseline = node("article", "", "workflow-existing");
  baseline.dataset.snapshot = snapshot.id;
  baseline.append(node("h4", "Existing monitoring + engineer"));
  baseline.append(node("p", "Individual alerts with engineer-led investigation.", "muted"));
  const metric = (card: HTMLElement, title: string, value: string, key: string): void => {
    const item = node("div", "", "workflow-row");
    item.dataset.value = key;
    item.append(node("strong", title), node("p", value));
    card.append(item);
  };
  const flagged = new Set(snapshot.quality.findings.filter(f => f.anomaly_count || f.missing
    || f.hard_excluded || f.spike_count || f.drift_suspected || f.peer_disagreement).map(f => f.sensor_id));
  metric(baseline, "Individual alerts available",
    `${flagged.size} instruments flagged. Inspect their histories one by one. No combined leak/malfunction classification.`, "detection");
  metric(baseline, "Inspection area",
    "Engineer to determine by connecting the timing and location of individual sensor alerts.", "interval");
  metric(baseline, "Investigation still needed",
    "An engineer retrieves operating and maintenance records, checks their validity, compares histories and tests leak, operating-change and shared-failure explanations.", "manual-work");
  metric(baseline, "Knowledge and handover",
    "An experienced engineer applies procedures, records uncertainty and prepares a handover for the next engineer.", "handover");
  metric(baseline, "Investigation time",
    "Not yet measured. Include evidence gathering, interpretation and handover.", "timing");
  baseline.append(button("Inspect this exact detector window", inspect));
  const assisted = node("article", "", "workflow-added");
  assisted.dataset.snapshot = snapshot.id;
  assisted.dataset.mode = task.mode;
  assisted.append(node("h4", task.mode === "live" ? "With Copilot hosted agents" : "Agent workflow preview · SCRIPTED"));
  assisted.append(node("p", task.mode === "live"
    ? "Recorded hosted execution, not a new inference call when this view opens."
    : "Offline contract example. No hosted inference; not the customer's current solution or evidence of LLM performance.", "muted"));
  if (file) {
    metric(assisted, "Leak or malfunction?",
      file.decision_policy === "llm-diagnosis-v1"
        ? "See the agent's source-grounded incident report below. No numerical classifier selects its cause assessment."
        : file.hypothesis === "suspected_leak"
        ? `Possible leak, not confirmed: ${snapshot.event.supporting_sensor_ids.length} instruments support a related pattern across ${snapshot.event.failure_domain_count} failure domains. Other individual alerts may coexist.`
        : file.hypothesis === "sensor_or_telemetry_issue"
          ? "Sensor/telemetry issue supported; review the affected instruments. This does not clear the pipeline of a concurrent leak."
          : "Cause unresolved. Do not force a leak/malfunction choice when the evidence is insufficient.", "classification");
    metric(assisted, "Inspection recommendation",
      file.decision_policy === "llm-diagnosis-v1"
        ? "Only inspection areas explicitly stated in the incident report appear on the agent map; no numerical fit supplies or vetoes them."
        : file.inspection ? `${file.inspection.segment_id} ${file.inspection.start_m}-${file.inspection.end_m}m. The product correlates sensors using numerical tools; the LLM does not invent leak coordinates.`
        : "Location withheld in this report. Review the unresolved evidence, not a presumed leak coordinate.", "interval");
    const cited = file.sources.filter(source => source.use === "cited");
    const rejected = file.sources.filter(source => source.use === "rejected");
    metric(assisted, "Historical evidence actually checked",
      `${file.sources.length} documents read; ${cited.length} cited; ${rejected.length} rejected. ${file.comparisons.length} measured pressure comparisons included. ${cited.length ? `Cited: ${cited.map(source => display(source.document.id)).join(", ")}.` : "No fully read historical source cited."}`, "sources");
    metric(assisted, "Competing explanations",
      file.interpretation ? file.interpretation.competing_causes.map(cause =>
        `${friendly(cause.cause)}: ${friendly(cause.stance)}`).join("; ") + ". Read the source-linked rationale below."
        : "No model-written interpretation in this archived report.", "causes");
    metric(assisted, "Reusable, checked handover",
      file.interpretation_review
        ? `${file.interpretation_review.rounds.length} grounding-review round(s); ${file.interpretation_review.protocol === "semantic-grounding-v2" ? "review coverage and exact source-material binding" : "exact quotes and review coverage"} checked by code. Sources, limitations, follow-ups and a downloadable evidence packet below. Same-model critic, not a correctness guarantee.`
        : "This archived report has no current-protocol grounding review. Do not treat it as newly qualified.", "handover");
    metric(assisted, "Report processing time",
      file.mode === "live"
        ? `${file.recorded_elapsed_seconds.toFixed(1)}s from admission to recorded report; ${reportGoal(file).seconds}s demo goal ${reportGoal(file).met ? "met" : "missed"}. ${file.fresh_model_calls} fresh hosted calls; human review time is additional.`
        : "Not a live-model latency measurement. Scripted adapter calls cannot establish agent speed or reliability.", "timing");
    const link = node("a", "Review the sources, rationale and handoff below");
    link.href = "#investigation-case";
    assisted.append(link);
  } else {
    const failed = !["QUEUED", "RUNNING", "WAITING_ON_CHILD", "SUCCEEDED", "ABSTAINED"].includes(task.state);
    metric(assisted, "No accepted investigation handoff loaded",
      failed ? `Report withheld: ${task.error_code || friendly(task.state)}. No completed investigation or savings claimed. Numerical warnings remain active.`
        : "Investigation pending or handoff unavailable. No completed source review, reviewed explanation or performance benefit is inferred.", "unavailable");
  }
  columns.append(baseline, assisted); section.append(columns);
  if (scenario === "S1") section.append(node("p",
    "Same sensor evidence and interface: without agents, the engineer connects the dots. Agents add knowledge-guided joint checks, leak-versus-instrumentation assessment, a supported inspection interval and a transferable handoff. A possible leak is not a confirmed leak.", "workflow-value-note"));
  section.append(node("p",
    "Validation scope: compare answer quality, engineer review effort, failures and latency against a fixed workflow. Field accuracy and time savings remain unmeasured.", "muted"));
  container.append(section);
}
export function renderCasefile(container: HTMLElement, file: InvestigationCase, actions: {
  claim: (id: string) => void;
}): void {
  const card = node("section", "", "investigation-case");
  card.id = "investigation-case";
  card.dataset.snapshot = file.snapshot_id;
  card.dataset.task = file.task_id;
  card.append(node("h3", "Incident assessment"));
  const audit = node("details", "", "case-audit");
  audit.append(node("summary", "Evidence and agent-run audit"));
  audit.append(node("p", file.disposition, "case-disposition"));
  audit.append(node("p", `Question: ${file.question}`));
  if (file.inspection) audit.append(node("p",
    `${file.inspection.segment_id}: ${file.inspection.start_m}-${file.inspection.end_m} m supported inspection interval. Not an exact leak position.`,
    "case-interval"));
  else audit.append(node("p", "Inspection location withheld / not established by this answer.", "case-interval"));
  audit.append(node("p", `Recorded workflow recommendation: ${file.next_action}`, "case-next-action"));
  audit.append(node("p", file.authority, "muted"));
  if (!file.interpretation) {
    card.append(node("p", file.disposition));
    card.append(node("p", file.inspection
      ? `${file.inspection.segment_id}: ${file.inspection.start_m}-${file.inspection.end_m} m inspection interval, not an exact leak point.`
      : "No supported inspection interval in this recorded result."));
  }
  const references = (ids: string[]): HTMLElement => {
    const chips = node("div", "", "chips");
    for (const id of ids) chips.append(button(id, () => {
      const target = [...card.querySelectorAll<HTMLElement>("[data-case-reference]")].find(item => item.dataset.caseReference === id);
      if (target instanceof HTMLDetailsElement) { audit.open = true; target.open = true; target.scrollIntoView({ block: "center" }); target.focus(); }
      else actions.claim(id);
    }, "chip rule"));
    return chips;
  };
  if (file.interpretation) {
    if (file.interpretation_review) {
      const review = node("details", "", "case-grounding-review");
      review.append(node("summary", `Independent grounding review accepted: ${file.interpretation_review.rounds.length} round(s). Not a correctness guarantee.`));
      for (const [index, round] of file.interpretation_review.rounds.entries()) {
        review.append(node("h4", `Review ${index + 1}: ${round.assessment.decision}`));
        if (round.material_hash) review.append(node("p", `Task, candidate and original-source material SHA256: ${round.material_hash}`, "muted"));
        for (const check of round.assessment.checks) {
          review.append(node("p", `${check.paragraph_id}: ${check.verdict}. ${check.reason}`));
          for (const support of check.support) {
            review.append(node("blockquote", `${support.reference}: ${support.quote}`), references([support.reference]));
          }
        }
      }
      review.append(node("p", file.interpretation_review.protocol === "semantic-grounding-v2"
        ? "Separate critic context, same underlying model. Semantic verdicts cover every explanation; code checks coverage and exact material binding, not physical correctness. Humans retain review authority."
        : "Separate critic context, same underlying model. Exact quotes and review coverage checked by code; humans retain review authority.", "muted"));
      audit.append(review);
    } else audit.append(node("p", "Archived explanation: predates independent grounding review. Do not treat it as reviewed by the current protocol.", "summary"));
    card.append(node("p", reportText(file.interpretation.answer.text, file.interpretation.answer.references), "case-assessment"));
    audit.append(node("h4", "Assessment references"), references(file.interpretation.answer.references));
    const causes = node("div", "", "case-causes");
    for (const cause of file.interpretation.competing_causes) {
      const panel = node("article");
      panel.append(node("h4", cause.cause === "instrumentation_or_telemetry"
        ? "Instrument and connection assessment" : cause.cause === "operating_change"
          ? "Operating-change assessment" : "Leak assessment"), node("p", reportText(cause.text, cause.references)));
      audit.append(node("h4", `${friendly(cause.cause)}: ${friendly(cause.stance)} references`), references(cause.references));
      causes.append(panel);
    }
    card.append(causes);
    for (const region of file.interpretation.regional_assessments || []) {
      const detail = node("details", "", "case-region");
      const pipes = [...new Set(region.sensor_ids.map(id => id.split("-")[0]))];
      detail.append(node("summary", `${pipes.join(" / ")}: detailed assessment`),
        node("p", reportText(region.text, region.references)));
      card.append(detail);
      audit.append(node("h4", `${pipes.join(" / ")} regional references`), references(region.references));
    }
  }
  const trail = node("details", "", "case-trail");
  trail.append(node("summary", "Executed investigation checks (public actions, not hidden thoughts)"));
  for (const step of file.steps) {
    const row = node("details", "", "public-record");
    row.append(node("summary", `${step.tool}: ${friendly(step.intent)} - ${step.error || "executed"}`));
    row.append(node("p", `Recorded arguments: ${JSON.stringify(step.arguments)}`));
    trail.append(row);
  }
  if (!file.steps.length) trail.append(node("p", "No historical tool steps in this archived answer."));
  audit.append(trail);
  const sources = node("section", "", "case-sources");
  sources.append(node("h3", "Reviewed historical sources"));
  for (const source of file.sources) {
    const doc = source.document;
    const item = node("details", "", "case-source");
    item.dataset.caseReference = display(doc.id); item.tabIndex = -1;
    item.append(node("summary", `${display(doc.id)} - ${display(doc.title)} (${friendly(source.use)})`));
    item.append(node("p", `Revision ${display(doc.revision)}; status ${display(doc.status)}; current authority: ${display(doc.admissible)}`));
    item.append(node("p", `Available ${display(doc.available_at)}; effective ${display(doc.effective_from)} to ${doc.effective_to === null ? "open-ended" : display(doc.effective_to)}; assets ${display(doc.asset_ids)}`, "muted"));
    item.append(node("p", display(doc.body), "case-source-body"));
    sources.append(item);
  }
  if (!file.sources.length) sources.append(node("p", "No fully read historical documents cited. Missing records do not establish absence of an event.", "muted"));
  audit.append(sources);
  for (const comparison of file.comparisons) {
    const item = node("details", "", "case-comparison");
    item.dataset.caseReference = display(comparison.call_id); item.tabIndex = -1;
    item.append(node("summary", `Measured pressure comparison: ${display(comparison.start_seconds)}-${display(comparison.end_seconds)}s, split ${display(comparison.split_seconds)}s`));
    item.append(node("p", "Code-computed medians; missing periods stay unknown. Association is not causation.", "muted"));
    const table = node("table");
    const header = node("tr");
    for (const title of ["Sensor / gateway", "Before (bar)", "After (bar)", "Change (bar)", "Usable / expected"]) header.append(node("th", title));
    table.append(header);
    const sensors = comparison.sensors;
    if (Array.isArray(sensors)) for (const sensor of sensors) {
      if (!object(sensor)) continue;
      const row = node("tr");
      for (const value of [
        `${display(sensor.sensor_id)} / ${display(sensor.failure_domain)}`,
        display(sensor.before_median_bar), display(sensor.after_median_bar), display(sensor.change_bar),
        `${display(sensor.before_usable)}/${display(sensor.before_expected)} before; ${display(sensor.after_usable)}/${display(sensor.after_expected)} after`,
      ]) row.append(node("td", value));
      table.append(row);
    }
    const wrapper = node("div", "", "table-wrap"); wrapper.append(table); item.append(wrapper); audit.append(item);
  }
  const checked = node("details");
  checked.append(node("summary", file.decision_policy === "llm-diagnosis-v1"
    ? "Cited measurements and unresolved limitations"
    : "Archived numerical claims and unresolved limitations"));
  checked.append(node("p", file.limitations.map(friendly).join("; "), "case-limitations"));
  for (const claim of file.checked_claims) checked.append(button(`${claim.id}: ${friendly(claim.kind)}`, () => actions.claim(claim.id), "chip rule"));
  audit.append(checked);
  audit.append(node("p",
    `${file.fresh_model_calls} fresh ${file.mode === "scripted" ? "SCRIPTED adapter calls (no hosted inference)" : "hosted model calls"} / ${file.fresh_tool_calls} fresh tool calls; recorded task span ${file.recorded_elapsed_seconds.toFixed(1)}s including queue. ${file.reused_task_ids.length} reused specialists (prior calls excluded from fresh counts). Provider monetary cost unknown.`,
    "case-work-summary"));
  audit.append(node("p", `${reportGoal(file).seconds}s report-processing demo goal: ${reportGoal(file).met ? "MET" : "MISSED"}. Measured from question admission to accepted result, not sensor onset or browser receipt. Correctness checks are not relaxed.`, "case-report-target"));
  audit.append(node("p", `Evidence basis: ${file.snapshot_id}; ${file.window_start} to ${file.window_end}; ${file.mode.toUpperCase()}. Synthetic evidence; not field reliability.`, "muted"));
  const download = node("a", "Download this investigation handoff (JSON)");
  download.href = `/api/tasks/${encodeURIComponent(file.task_id)}/casefile`; download.download = `investigation-${file.task_id}.json`;
  download.id = "download-casefile"; audit.append(download); card.append(audit); container.append(card);
}
