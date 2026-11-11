/**
 * Public agent-work presentation: specialist/coordinator states, critic corrections
 * and report-to-map receipts. All activity comes from tasks/events; rendering starts
 * no model work. Acceptance is distinct from physical correctness.
 */
import { button, friendly, node } from "./dom";
import { reportText } from "./presentation";
import type { AgentResult, AgentTask, ConsoleEvent, Json, TaskDetail, WindowSnapshot } from "./types";

const agents = [
  ["sensor_quality", "Sensor Quality Agent", "Are the readings usable? Missing values stay unknown."],
  ["event_diagnosis", "Event Diagnosis Agent", "What explains the pressure changes? Compare sensors and operating records."],
  ["operator_response", "Response Coordinator", "Assign specialist checks, then combine findings into an inspection recommendation or abstention."],
] as const;
export function agentName(role: string): string {
  return role === "grounding_reviewer" ? "Grounding Reviewer"
    : role === "report_mapper" ? "Report-to-map Mapper"
    : agents.find(agent => agent[0] === role)?.[1] || friendly(role);
}
// Mapping is a backend presentation step after successful live report acceptance.
// Its labels/quotes are not a second diagnosis or a fallback to numerical detector flags.
function mapperCard(root: AgentTask | null, extraction: TaskDetail["output_mapping"],
  enabled: boolean, events: ConsoleEvent[] = [], quotesOpen = false): HTMLElement {
  const card = node("div", "", "agent-role"); card.dataset.role = "report_mapper";
  card.append(node("strong", "Report-to-map Mapper"),
    node("p", "LLM presentation step: extracts quoted leak branches, inspection intervals and instrument findings from the accepted report; performs no new diagnosis."),
    node("small", "Backend-triggered after acceptance, outside the coordinator workflow. No measurements, detector flags or ground truth are supplied."));
  const output = node("div", "", "agent-handoff-output");
  output.append(node("h4", "Report-to-map presentation"));
  const completion = root ? [...events].reverse().find(event =>
    event.task_id === root.id && event.type === "mapping.completed") : undefined;
  let status: string;
  if (!enabled) {
    status = "Not enabled";
    output.append(node("p", "Agent execution is off; no hosted map extraction is started."));
  } else if (!root || ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(root.state)) {
    status = "Waiting for accepted report";
    output.append(node("p", "Provisional drafts do not populate the agent map. Extraction follows report acceptance."));
  } else if (root.state !== "SUCCEEDED" || !root.result?.interpretation || root.mode !== "live") {
    status = "Not run";
    output.append(node("p", "Hosted map extraction requires a successful live coordinator incident report. No labels are inferred from detector flags."));
  } else if (extraction?.status === "failed" || completion?.payload.status === "failed") {
    status = "Failed";
    const code = extraction?.error_code || completion?.payload.error_code || "invalid output";
    output.append(node("p", `Map extraction failed (${code}). The accepted report remains available; no replacement diagnoses are inferred.`));
  } else if (extraction?.status === "completed" && extraction.mapping) {
    status = "Ready";
    const mapping = extraction.mapping;
    output.append(node("p", `${mapping.leaks.length} leak branch finding(s) · ${mapping.leaks.filter(item => item.interval).length} report-stated inspection interval(s) · ${mapping.sensor_issues.length} instrument issue label(s), including missing readings where stated.`),
      node("p", "Red branches show reported leak findings; green bands show inspection intervals, not exact leak points. Purple rings show instrument issues other than missing readings alone.", "muted"));
    const details = node("details");
    details.dataset.section = "mapper:quotes"; details.open = quotesOpen;
    details.append(node("summary", "Saved map labels and exact report quotations"));
    const labels = node("ul", "", "agent-mapping-findings");
    for (const leak of mapping.leaks) {
      const item = node("li");
      item.append(node("strong", `${leak.segment_id}: ${leak.assertion} leak${leak.interval ? ` · inspect ${leak.interval.start_m}–${leak.interval.end_m} m` : " · no inspection interval stated"}`),
        node("p", leak.quote.text));
      labels.append(item);
    }
    for (const issue of mapping.sensor_issues) {
      const item = node("li");
      item.append(node("strong", `${issue.sensor_id}: ${issue.kind} · ${issue.assertion}${issue.kind === "missing" ? " · not a hardware-fault diagnosis" : ""}`),
        node("p", issue.quote.text));
      labels.append(item);
    }
    if (!mapping.leaks.length && !mapping.sensor_issues.length) labels.append(node("li", "No positive leak or instrument labels extracted; this is not a healthy-pipeline clearance."));
    details.append(labels); output.append(details);
    if (extraction.execution_usage) output.append(node("p",
      `Presentation extraction: ${extraction.execution_usage.total_tokens.toLocaleString()} reported tokens. Separate from investigation usage; saved playback makes no new calls.`, "muted"));
  } else {
    status = "Not available yet";
    output.append(node("p", "The accepted report is available, but no saved map extraction is loaded yet. This does not establish that a model call is running. Older recordings may need their mapping prepared separately; no detector-based diagnoses are substituted."));
  }
  card.append(node("span", status), output);
  return card;
}
function reviewerState(root: AgentTask | null, events: ConsoleEvent[]): string {
  if (!root) return "Not started";
  if (root.error_code === "grounding_rejected") return "Rejected · report withheld";
  if (root.interpretation_review?.rounds.length) return "Completed";
  const verdict = [...events].reverse().find(event => event.task_id === root.id && event.type === "answer.critique");
  if (verdict?.payload.decision === "accept") return "Completed";
  if (verdict?.payload.decision === "revise") return "Changes requested";
  return events.some(event => event.task_id === root.id && event.type === "agent.review_requested")
    ? "Checking the draft" : "Not started";
}
function correctionChecklist(container: HTMLElement, corrections: unknown): void {
  if (!Array.isArray(corrections) || !corrections.length) return;
  const list = node("ol", "", "agent-review-corrections");
  for (const entry of corrections) {
    if (!entry || typeof entry !== "object" || !("excerpt" in entry) || !("instruction" in entry)
      || typeof entry.excerpt !== "string" || typeof entry.instruction !== "string") continue;
    const item = node("li");
    item.append(node("blockquote", entry.excerpt), node("p", entry.instruction));
    if ("source_references" in entry && Array.isArray(entry.source_references)) {
      const references = entry.source_references.filter((ref: unknown): ref is string => typeof ref === "string");
      item.append(node("small", `Verify against: ${references.join(", ")}`));
    }
    list.append(item);
  }
  container.append(list);
}
function record(value: Json | undefined): Record<string, Json> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function accepted(task: AgentTask): boolean {
  return ["SUCCEEDED", "ABSTAINED"].includes(task.state) && task.result !== null && task.answer !== null;
}
// Explicit reuse is allowed only for the same site, generation and immutable snapshot.
function linked(root: AgentTask, tasks: AgentTask[], reusedIds: readonly string[] = []): AgentTask[] {
  return tasks.filter(task => task.id === root.id || task.root_id === root.id
    || reusedIds.includes(task.id) && task.site_id === root.site_id
      && task.generation_id === root.generation_id && task.snapshot_id === root.snapshot_id);
}
function sourceWindow(task: AgentTask, basis: WindowSnapshot | null): WindowSnapshot | null {
  return basis?.id === task.snapshot_id && basis.site_id === task.site_id
    && basis.generation_id === task.generation_id ? basis : null;
}
function readableOutput(container: HTMLElement, text: string, references: readonly string[] = [],
  extraction: TaskDetail["output_mapping"] = null): void {
  const headings = new Set(["Leak assessment", "Why this location", "Instrument findings",
    "Operating and other pressure changes", "Limits of this result"]);
  for (const paragraph of reportText(text, references).split(/\n\s*\n/).filter(value => value.trim())) {
    const lines = paragraph.trim().split("\n");
    if (headings.has(lines[0])) {
      container.append(node("h4", lines[0]));
      if (lines[0] === "Instrument findings" && extraction?.status === "completed" && extraction.mapping) {
        const inventory = node("ul", "", "reported-instrument-inventory");
        inventory.setAttribute("aria-label", "Instrument issues extracted from this incident report");
        const groups = new Map<string, string[]>();
        for (const issue of extraction.mapping.sensor_issues) {
          const ids = groups.get(issue.kind) || [];
          if (!ids.includes(issue.sensor_id)) ids.push(issue.sensor_id);
          groups.set(issue.kind, ids);
        }
        for (const [kind, ids] of groups) inventory.append(node("li",
          `${kind === "missing" ? "Missing readings · not diagnosed hardware faults" : `Suspected measurement problem · ${kind}`}: ${ids.join(", ")}`));
        if (!groups.size) inventory.append(node("li",
          "No concrete instrument issue identified in this incident report; this is not proof that every sensor is healthy."));
        container.append(inventory);
      }
      if (lines.length > 1) container.append(node("p", lines.slice(1).join("\n")));
    } else container.append(node("p", paragraph));
  }
}
function readingCounts(value: Record<string, Json>, expectedKey: string, receivedKey: string,
  usableKey: string): { expected: number; received: number; usable: number } | null {
  const expected = value[expectedKey], received = value[receivedKey], usable = value[usableKey];
  if (typeof expected !== "number" || typeof received !== "number" || typeof usable !== "number"
    || ![expected, received, usable].every(Number.isSafeInteger)
    || usable < 0 || received < usable || expected < received) return null;
  return { expected, received, usable };
}
function specialistOutput(container: HTMLElement, task: AgentTask, result: AgentResult, basis: WindowSnapshot | null,
  opened: Set<string | undefined>): void {
  const references = [...result.claim_refs, ...result.evidence_ids,
    ...(result.interpretation?.answer.references || [])];
  if (task.state === "ABSTAINED") container.append(node("p",
    "The agent could not reach a supported conclusion. Its bounded findings are retained; this is not an all-clear.", "summary"));
  const scoped = sourceWindow(task, basis);
  if (task.role === "sensor_quality") {
    container.append(node("h4", "Reading quality at a glance"));
    if (scoped) {
      container.append(node("p", `Source window: ${scoped.window_start} to ${scoped.window_end}. Counts describe this saved window, not a current outage.`, "muted"));
      const claims = result.claim_refs.flatMap(id => scoped.claims[id] ? [scoped.claims[id]] : []);
      const coverage = claims.find(claim => claim.kind === "coverage");
      const value = coverage && record(coverage.value);
      const counts = value && readingCounts(value, "expected_samples", "received_samples", "usable_samples");
      if (counts) container.append(node("p",
        `${counts.usable} of ${counts.expected} expected readings could be used${counts.expected ? ` (${(100 * counts.usable / counts.expected).toFixed(1)}%)` : ""}. `
        + `${counts.expected - counts.received} did not arrive; ${counts.received - counts.usable} arrived but could not be used.`));
      else container.append(node("p", "No complete coverage counts are included in this agent's cited findings."));
      const health = claims.filter(claim => claim.kind === "sensor_health");
      container.append(node("p", `${health.length} sensor-level finding${health.length === 1 ? "" : "s"} cited in this handoff. This is not a full instrument audit; sensors not covered here are not declared healthy.`));
      if (health.length) {
        const sensors = node("details");
        sensors.dataset.section = `specialist-sensors:${task.id}`; sensors.open = opened.has(sensors.dataset.section);
        sensors.append(node("summary", "Sensor-by-sensor readings cited by this agent"));
        const wrap = node("div", "", "table-wrap");
        const table = node("table");
        table.append(node("caption", "Cited measurement-quality evidence, not diagnosed hardware faults"));
        const head = node("thead"), headings = node("tr");
        for (const label of ["Sensor / channel", "Readings usable", "Readings not received", "Received but unusable", "Anomalous readings"]) {
          const cell = node("th", label); cell.scope = "col"; headings.append(cell);
        }
        head.append(headings); table.append(head);
        const body = node("tbody");
        for (const claim of health) {
          const finding = record(claim.value);
          const counts = finding && readingCounts(finding, "expected", "received", "usable");
          const row = node("tr");
          const sensor = node("th", finding && typeof finding.sensor_id === "string"
            ? `${finding.sensor_id}${typeof finding.channel === "string" ? ` / ${finding.channel}` : ""}` : "Sensor not specified");
          sensor.scope = "row"; row.append(sensor);
          row.append(node("td", counts ? `${counts.usable} / ${counts.expected}` : "Not reported"),
            node("td", counts ? String(counts.expected - counts.received) : "Not reported"),
            node("td", counts ? String(counts.received - counts.usable) : "Not reported"),
            node("td", typeof finding?.anomaly_count === "number" ? String(finding.anomaly_count) : "Not reported"));
          body.append(row);
        }
        table.append(body); wrap.append(table); sensors.append(wrap,
          node("p", "Anomalous readings can still be usable. A gap or unusual value alone does not establish a failed sensor or a leak.", "muted"));
        container.append(sensors);
      }
    } else container.append(node("p", "The exact source window is not loaded. Coverage and sensor counts are not inferred from another window."));
  }
  container.append(node("h4", "What this agent found"));
  const narrative = node("div", "", "agent-specialist-findings");
  readableOutput(narrative, result.summary.trim() || result.interpretation?.answer.text
    || task.answer || "No narrative findings were included in this accepted handoff.", references);
  container.append(narrative);
  if (task.role === "event_diagnosis" && result.investigation) {
    const history = result.investigation;
    const assessments = {
      operating_change_plausible: "An operating change is a plausible explanation; this is not a confirmed cause.",
      instrumentation_context: "Instrument or maintenance context was found; this is not confirmation of hardware failure.",
      unresolved: "The operating-history check did not settle the cause.",
    };
    const actions: Record<string, string> = {
      check_operating_records: "Verify operating records.",
      review_instrumentation: "Review instrument readings and maintenance records.",
      inspect_supported_interval: "Plan an engineering inspection of the supported interval.",
      restore_telemetry: "Restore telemetry before drawing stronger conclusions.",
      human_review: "Request engineering review.",
    };
    container.append(node("h4", "Operating-history check"),
      node("p", assessments[history.assessment]),
      node("p", `${history.document_ids.length} source document(s) cited; ${history.rejected_document_ids.length} read document(s) excluded as inadmissible; ${history.comparison_call_ids.length} executed sensor comparison(s) cited.`),
      node("p", `Suggested next step: ${actions[history.next_action] || friendly(history.next_action)} This is advice, not an authorized action.`));
  }
  container.append(node("h4", "Limits and handoff"));
  const limits: Record<string, string> = {
    partial_health_review: "Only part of the instrument population was reviewed; other sensors are not cleared.",
    missing_data: "Some readings are missing or unusable. Unknown values are not filled in.",
    read_only: "Read-only assessment: no dispatch, repair or operating change is authorized.",
    SYNTHETIC_UNCALIBRATED: "Demonstration evidence and an uncalibrated model; not safety clearance.",
  };
  const list = node("ul");
  for (const limit of result.limitations) list.append(node("li", limits[limit] || `Recorded limit: ${friendly(limit).toLowerCase()}`));
  container.append(list, node("p", task.role === "sensor_quality"
    ? "Passed to Event Diagnosis and the Response Coordinator as measurement-quality evidence, not a leak or hardware diagnosis."
    : "Passed to the Response Coordinator to combine with measurement-quality findings. An inspection focus is not a confirmed leak location."));
}
function organizeAgentWorkspace(progress: HTMLElement, reviewOpen = false): void {
  const reviewer = progress.querySelector<HTMLElement>('.agent-role[data-role="grounding_reviewer"]');
  const reviewStatus = reviewer?.querySelector(":scope > span")?.textContent || "Not started";
  const cards = [...progress.querySelectorAll<HTMLElement>('.agent-role:not([data-role="grounding_reviewer"])')];
  const selector = node("div", "", "agent-selector");
  selector.setAttribute("role", "tablist"); selector.setAttribute("aria-label", "Choose an agent output");
  const reader = node("div", "", "agent-output-reader");
  const requested = progress.dataset.activeRole || progress.dataset.defaultRole || "operator_response";
  const preferred = cards.some(card => card.dataset.role === requested) ? requested : "operator_response";
  const tabs: HTMLButtonElement[] = [];
  const panels: HTMLElement[] = [];
  const select = (role: string, focus = false): void => {
    progress.dataset.activeRole = role;
    for (const [index, card] of cards.entries()) {
      const active = card.dataset.role === role;
      card.classList.toggle("active", active);
      tabs[index].setAttribute("aria-selected", String(active)); tabs[index].tabIndex = active ? 0 : -1;
      panels[index].hidden = !active;
      if (active && focus) tabs[index].focus();
    }
  };
  for (const [index, card] of cards.entries()) {
    const role = card.dataset.role!;
    const label = card.querySelector("strong")?.textContent || agentName(role);
    const tab = button("", () => select(role));
    tab.append(node("strong", label), node("span",
      card.querySelector(":scope > span")?.textContent?.split(" · ")[0] || "Not started",
      "agent-tab-status"));
    if (role === "operator_response") tab.append(node("small", `Review: ${reviewStatus}`, "agent-review-status"));
    tab.id = `agent-output-tab-${role}`; tab.setAttribute("role", "tab");
    tab.setAttribute("aria-label", `${label} output`); tab.setAttribute("aria-controls", `agent-output-panel-${role}`);
    tab.addEventListener("keydown", event => {
      if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? cards.length - 1
        : (index + (["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 1) + cards.length) % cards.length;
      select(cards[next].dataset.role!, true);
    });
    const panel = node("section", "", "agent-output-panel");
    panel.id = `agent-output-panel-${role}`; panel.dataset.role = role;
    panel.setAttribute("role", "tabpanel"); panel.setAttribute("aria-labelledby", tab.id); panel.tabIndex = 0;
    panel.append(node("h3", label), node("p", card.querySelector("p")?.textContent || "", "muted"));
    const metadata = node("div", "", "agent-output-meta");
    metadata.append(...card.querySelectorAll(":scope > span, :scope > small"));
    panel.append(metadata);
    const output = card.querySelector(".agent-handoff-output");
    if (output) panel.append(output);
    else panel.append(node("p", "No accepted output is available yet. The agent's status is shown above.", "agent-output-empty"));
    if (role === "operator_response" && reviewer) {
      const review = node("details", "", "agent-grounding-review");
      review.dataset.section = "grounding-review"; review.open = reviewOpen;
      review.append(node("summary", `Grounding Reviewer · ${reviewStatus}`),
        ...reviewer.querySelectorAll(":scope > p, :scope > small, :scope > .agent-handoff-output"));
      panel.append(review);
    }
    card.replaceChildren(tab); tabs.push(tab); panels.push(panel);
    selector.append(card); reader.append(panel);
  }
  progress.replaceChildren(selector, reader);
  select(preferred);
}
export function renderIdleAgentWork(progress: HTMLElement, findings: HTMLElement, enabled: boolean): void {
  progress.replaceChildren(); findings.replaceChildren();
  delete progress.dataset.renderKey; delete progress.dataset.task;
  delete progress.dataset.activeRole;
  delete progress.dataset.defaultRole;
  for (const [role, label, purpose] of agents) {
    const card = node("div", "", "agent-role"); card.dataset.role = role;
    card.append(node("strong", label), node("p", purpose), node("span", enabled ? "Not started" : "Not enabled"));
    progress.append(card);
  }
  const reviewer = node("div", "", "agent-role");
  reviewer.dataset.role = "grounding_reviewer";
  reviewer.append(node("strong", "Grounding Reviewer"), node("p", "A separate model call checks whether the draft matches its sources."),
    node("span", enabled ? "Not started" : "Not enabled"));
  progress.append(reviewer);
  progress.append(mapperCard(null, null, enabled));
  organizeAgentWorkspace(progress);
}

/**
 * Rebuild only when public evidence changes; retain open audit sections and selected
 * role so projection refreshes do not interrupt a reader. Merge durable and live events by ID.
 */
export function renderAgentWork(progress: HTMLElement, findings: HTMLElement, root: AgentTask,
  tasks: AgentTask[], detail: TaskDetail | null, basis: WindowSnapshot | null,
  error: string | null, open: (taskId: string) => void, events: ConsoleEvent[] = []): void {
  const key = JSON.stringify([root.id, root.state, root.updated_at, root.plan,
    linked(root, tasks).map(task => [task.id, task.updated_at, task.state, task.model_calls, task.tool_calls]),
    detail?.task.updated_at, detail?.investigation_receipts.map(receipt => receipt.call_id),
    detail?.output_mapping,
    Boolean(detail?.casefile), basis?.id, error, events[events.length - 1]?.id,
    detail?.activity?.[detail.activity.length - 1]?.id]);
  if (progress.dataset.renderKey === key) return;
  const opened = new Set(progress.dataset.task === root.id
    ? [...progress.querySelectorAll<HTMLDetailsElement>("details[open]"), ...findings.querySelectorAll<HTMLDetailsElement>("details[open]")]
      .map(item => item.dataset.section) : []);
  if (progress.dataset.task !== root.id) delete progress.dataset.activeRole;
  const focusedRole = progress.querySelector<HTMLElement>('[role="tab"]:focus')?.closest<HTMLElement>(".agent-role")?.dataset.role;
  progress.dataset.task = root.id; progress.dataset.renderKey = key;
  progress.replaceChildren();
  findings.replaceChildren();
  const reusedIds = detail?.casefile?.reused_task_ids || [];
  const members = linked(root, tasks, reusedIds);
  progress.dataset.defaultRole = accepted(root) ? "operator_response"
    : members.find(task => task.role !== "operator_response" && task.state === "RUNNING")?.role || "operator_response";
  const journalEvents = [...new Map(
    [...(detail?.activity || []), ...events].map(event => [event.id, event])
  ).values()].sort((a, b) => a.id - b.id);
  if (root.state === "FAILED") {
    const failure = node("section", "", "agent-failure-summary summary");
    failure.dataset.stage = root.error_code === "grounding_rejected" ? "grounding_reviewer" : root.role;
    failure.append(node("h3", root.error_code === "grounding_rejected"
      ? "Report withheld at Grounding Reviewer" : `Investigation stopped at ${agentName(root.role)}`),
      node("p", members.filter(task => task.id !== root.id)
        .map(task => `${agentName(task.role)}: ${friendly(task.state)}`).join(" · ")
        || "No completed specialist handoffs are loaded."));
    const rejected = journalEvents.filter(event =>
      event.task_id === root.id && event.type === "answer.critique" && event.payload.decision === "revise");
    for (const event of rejected) {
      if (!Array.isArray(event.payload.checks)) continue;
      for (const entry of event.payload.checks) {
        const check = record(entry);
        if (check && check.verdict !== "supported" && typeof check.reason === "string") {
          failure.append(node("p", `Round ${event.payload.round} · ${check.paragraph_id}: ${check.reason}`));
          correctionChecklist(failure, check.corrections);
        }
      }
    }
    if (!rejected.length) failure.append(node("p", root.error_message || root.error_code || "Failure details are not loaded."));
    failure.append(node("p", "No report or map diagnosis was accepted. Completed checks remain available; do not treat this as safety clearance."),
      button("Open failed coordinator receipts and trace", () => open(root.id)));
    findings.append(failure);
  }
  for (const [role, label, purpose] of agents) {
    const task = role === "operator_response" ? root : members.find(item => item.role === role);
    const card = node("div", "", "agent-role");
    card.dataset.role = role;
    card.append(node("strong", label), node("p", purpose));
    const reused = !task && root.plan.includes("reuse");
    card.append(node("span", task ? `${friendly(task.state)} · ${task.model_calls} model / ${task.tool_calls} tool calls`
      : reused ? "Reuse selected · inspect linked receipts" : "Not started"));
    if (task && reusedIds.includes(task.id)) card.append(node("span", "Reused recorded handoff · no new specialist calls"));
    if (task && accepted(task) && task.result) {
      const source = sourceWindow(task, basis);
      const count = task.result.claim_refs.filter(id => source?.claims[id]?.kind === "sensor_health").length;
      if (role === "sensor_quality") card.append(node("span",
        `${source ? `${count} sensor-health claims cited` : "Source window not loaded"}${task.result.limitations.includes("partial_health_review") ? " · partial, not exhaustive" : ""}`));
      const result = node("div", "", "agent-handoff-output");
      result.append(node("h4", role === "operator_response" ? "Accepted incident assessment" : "Checked specialist output"));
      const answer = task.result.interpretation?.answer;
      if (role === "operator_response") readableOutput(result,
        answer?.text || task.answer || "Checked findings are loading.", answer?.references, detail?.output_mapping);
      else specialistOutput(result, task, task.result, basis, opened);
      result.append(button("Open executed receipts", () => open(task.id)));
      card.append(result);
    }
    progress.append(card);
  }
  const reviewer = node("div", "", "agent-role");
  reviewer.dataset.role = "grounding_reviewer";
  const reviewerRounds = detail?.casefile?.interpretation_review?.rounds || root.interpretation_review?.rounds || [];
  reviewer.append(node("strong", "Grounding Reviewer"), node("p", "Checks explanations against sources before the coordinator releases a report."),
    node("span", reviewerRounds.length ? "Completed" : reviewerState(root, journalEvents)),
    node("small", "A separate review call, not a fourth sensor-investigation agent."));
  const reviewOutput = node("div", "", "agent-handoff-output");
  reviewOutput.append(node("h4", "Grounding review"));
  const lastReview = reviewerRounds[reviewerRounds.length - 1];
  if (lastReview) {
    reviewOutput.append(node("p", `Latest review: ${friendly(lastReview.assessment.decision)}. ${reviewerRounds.length} review round(s) recorded.`));
    const checks = node("ul", "", "agent-review-checks");
    for (const check of lastReview.assessment.checks) {
      const item = node("li");
      item.append(node("strong", `${check.paragraph_id}: ${friendly(check.verdict)}`), node("p", reportText(check.reason)));
      correctionChecklist(item, check.corrections);
      checks.append(item);
    }
    reviewOutput.append(checks);
  } else {
    const latest = [...journalEvents].reverse().find(event =>
      event.task_id === root.id && event.type === "answer.critique");
    if (latest && Array.isArray(latest.payload.checks)) {
      reviewOutput.append(node("p", `Recorded review round ${latest.payload.round}: ${latest.payload.decision}.`));
      const checks = node("ul", "", "agent-review-checks");
      for (const entry of latest.payload.checks) {
        const check = record(entry);
        if (!check || typeof check.paragraph_id !== "string"
          || typeof check.verdict !== "string" || typeof check.reason !== "string") continue;
        const item = node("li");
        item.append(node("strong", `${check.paragraph_id}: ${friendly(check.verdict)}`),
          node("p", reportText(check.reason)));
        correctionChecklist(item, check.corrections);
        checks.append(item);
      }
      reviewOutput.append(checks);
    } else reviewOutput.append(node("p", "No detailed grounding review has been recorded for this run yet."));
  }
  reviewOutput.append(node("p", "This checks whether explanations match their sources; it does not confirm a physical leak.", "muted"));
  reviewer.append(reviewOutput);
  progress.append(reviewer);
  progress.append(mapperCard(root, detail?.output_mapping, true, journalEvents, opened.has("mapper:quotes")));
  organizeAgentWorkspace(progress, opened.has("grounding-review") || root.error_code === "grounding_rejected");
  if (focusedRole) progress.querySelector<HTMLButtonElement>(`#agent-output-tab-${focusedRole}`)?.focus();
  if (error) {
    findings.append(node("p", `Work record unavailable: ${error}. No source checks are inferred. Reconnect to reload.`, "summary"));
  }
}
