import { button, friendly, node } from "./dom";
import type { InvestigationCase, Json } from "./types";

function display(value: Json | undefined): string {
  return value === undefined || value === null ? "unknown" : typeof value === "object" ? JSON.stringify(value) : String(value);
}
function object(value: Json): value is Record<string, Json> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
export function renderCasefile(container: HTMLElement, file: InvestigationCase, actions: {
  draft: (question: string) => void; claim: (id: string) => void;
}): void {
  const card = node("section", "", "investigation-case");
  card.id = "investigation-case";
  card.dataset.snapshot = file.snapshot_id;
  card.dataset.task = file.task_id;
  card.append(node("h3", "Investigation handoff - for engineer review"));
  card.append(node("p", file.disposition, "case-disposition"));
  card.append(node("p", `Question: ${file.question}`));
  if (file.inspection) card.append(node("p",
    `${file.inspection.segment_id}: ${file.inspection.start_m}-${file.inspection.end_m} m supported inspection interval. Not an exact leak position.`,
    "case-interval"));
  else card.append(node("p", "Inspection location withheld / not established by this answer.", "case-interval"));
  card.append(node("p", `Next review step: ${file.next_action}`, "case-next-action"));
  card.append(node("p", file.authority, "muted"));
  const references = (ids: string[]): HTMLElement => {
    const chips = node("div", "", "chips");
    for (const id of ids) chips.append(button(id, () => {
      const target = [...card.querySelectorAll<HTMLElement>("[data-case-reference]")].find(item => item.dataset.caseReference === id);
      if (target instanceof HTMLDetailsElement) { target.open = true; target.scrollIntoView({ block: "center" }); target.focus(); }
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
        for (const check of round.assessment.checks) {
          review.append(node("p", `${check.paragraph_id}: ${check.verdict}. ${check.reason}`));
          for (const support of check.support) {
            review.append(node("blockquote", `${support.reference}: ${support.quote}`), references([support.reference]));
          }
        }
      }
      review.append(node("p", "Separate critic context, same underlying model. Exact quotes and review coverage checked by code; humans retain review authority.", "muted"));
      card.append(review);
    } else card.append(node("p", "Archived explanation: predates independent grounding review. Do not treat it as reviewed by the current protocol.", "summary"));
    card.append(node("h3", "Engineer interpretation - model-written, verify against sources"));
    card.append(node("p", file.interpretation.answer.text));
    card.append(references(file.interpretation.answer.references));
    const causes = node("div", "", "case-causes");
    for (const cause of file.interpretation.competing_causes) {
      const panel = node("article");
      panel.append(node("h4", `${friendly(cause.cause)}: ${friendly(cause.stance)}`), node("p", cause.text), references(cause.references));
      causes.append(panel);
    }
    card.append(causes, node("h3", "Questions to resolve with the engineer"));
    const followups = node("div", "", "case-followups");
    for (const question of file.interpretation.follow_up_questions) {
      const item = node("div");
      item.append(node("p", question), button("Draft this follow-up on the same evidence", () => actions.draft(question)));
      followups.append(item);
    }
    card.append(followups, node("p", "Drafting does not run inference. Review the question, then explicitly submit. External evidence may still be unavailable.", "muted"));
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
  card.append(trail);
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
  card.append(sources);
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
    const wrapper = node("div", "", "table-wrap"); wrapper.append(table); item.append(wrapper); card.append(item);
  }
  const checked = node("details");
  checked.append(node("summary", "Checked numerical claims and unresolved limitations"));
  checked.append(node("p", file.limitations.map(friendly).join("; "), "case-limitations"));
  for (const claim of file.checked_claims) checked.append(button(`${claim.id}: ${friendly(claim.kind)}`, () => actions.claim(claim.id), "chip rule"));
  card.append(checked);
  card.append(node("p",
    `${file.fresh_model_calls} fresh ${file.mode === "scripted" ? "SCRIPTED adapter calls (no hosted inference)" : "hosted model calls"} / ${file.fresh_tool_calls} fresh tool calls; recorded task span ${file.recorded_elapsed_seconds.toFixed(1)}s including queue. ${file.reused_task_ids.length} reused specialists (prior calls excluded from fresh counts). Provider monetary cost unknown.`,
    "case-work-summary"));
  card.append(node("p", `${file.report_target_seconds}s report-processing target: ${file.report_target_met ? "MET" : "MISSED"}. Measured from question admission to accepted result, not sensor onset or browser receipt. Correctness checks are not relaxed.`, "case-report-target"));
  card.append(node("p", `Evidence basis: ${file.snapshot_id}; ${file.window_start} to ${file.window_end}; ${file.mode.toUpperCase()}. Synthetic evidence; not field reliability.`, "muted"));
  const download = node("a", "Download this investigation handoff (JSON)");
  download.href = `/api/tasks/${encodeURIComponent(file.task_id)}/casefile`; download.download = `investigation-${file.task_id}.json`;
  download.id = "download-casefile"; card.append(download); container.append(card);
}
