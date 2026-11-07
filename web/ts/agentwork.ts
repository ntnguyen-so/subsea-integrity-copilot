import { button, friendly, node, text, time } from "./dom";
import type { AgentTask, ConsoleEvent, Json, TaskDetail, WindowSnapshot } from "./types";

function record(value: Json | undefined): Record<string, Json> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function duration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
function accepted(task: AgentTask): boolean {
  return ["SUCCEEDED", "ABSTAINED"].includes(task.state) && task.result !== null && task.answer !== null;
}
function linked(root: AgentTask, tasks: AgentTask[]): AgentTask[] {
  return tasks.filter(task => task.id === root.id || task.root_id === root.id);
}
export function renderAgentActivity(root: AgentTask | null, tasks: AgentTask[], events: ConsoleEvent[],
  now: number, current: boolean, triage: boolean, enabled: boolean): void {
  const stages = document.getElementById("agent-live-stages")!;
  const log = document.getElementById("agent-progress-log")!;
  stages.replaceChildren();
  log.replaceChildren();
  if (!root) {
    text("agent-activity-state", !enabled ? "Agent execution off · sensor evidence remains available"
      : triage ? "Detectors flagged an unresolved pattern; gathering context" : "Detectors monitoring · agents start automatically on a qualifying incident");
    text("agent-elapsed", "No LLM investigation admitted yet");
    text("agent-last-action", "Sensor flags are detector outputs. Leak assessment and inspection overlays require a reviewed agent report for the displayed window.");
    for (const [role, label] of [["sensor_quality", "1. Quality checks"], ["event_diagnosis", "2. Joint investigation"],
      ["operator_response", "Coordinator / report + critic"]]) {
      const stage = node("span", `${label}: ${enabled ? "Not started" : "Not enabled"}`);
      stage.dataset.role = role; stage.dataset.state = "NOT_STARTED"; stages.append(stage);
    }
    log.append(node("li", "No agent actions recorded."));
    return;
  }
  const done = accepted(root), active = ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(root.state);
  const elapsed = ((done || !active ? Date.parse(root.updated_at) : now) - Date.parse(root.created_at)) / 1000;
  const members = linked(root, tasks), ids = new Set(members.map(task => task.id));
  const calls = members.reduce((sum, task) => sum + task.model_calls, 0);
  const tools = members.reduce((sum, task) => sum + task.tool_calls, 0);
  text("agent-activity-state", !current ? "Connection unavailable · last recorded agent status below"
    : done ? "Recorded agent report · review findings and next checks"
      : active ? `Agents ${root.state === "QUEUED" ? "queued" : "investigating"} · no reviewed report yet`
        : "Agent report withheld · detector warnings remain active");
  text("agent-elapsed", `${duration(elapsed)} real processing ${done || !active ? "elapsed" : "since admission"} · ${calls} ${root.mode === "live" ? "hosted" : "SCRIPTED"} calls · ${tools} tool calls`);
  for (const [role, label] of [["sensor_quality", "1. Quality checks"], ["event_diagnosis", "2. Joint investigation"],
    ["operator_response", "Coordinator / report + critic"]]) {
    const member = role === "operator_response" ? root : members.find(task => task.role === role);
    const state = member?.state || "NOT_STARTED";
    const stage = node("span", `${label}: ${friendly(state)}${member ? ` · ${member.model_calls} model / ${member.tool_calls} tool calls` : ""}`);
    stage.dataset.role = role; stage.dataset.state = state;
    stages.append(stage);
  }
  for (const event of events.filter(event => event.task_id && ids.has(event.task_id)
    && ["task.started", "model.started", "model.completed", "tool.completed", "answer.critique", "task.finished"].includes(event.type)).slice(-12)) {
    const role = friendly(members.find(task => task.id === event.task_id)?.role || "agent");
    const phase = typeof event.payload.phase === "string" ? ` · ${friendly(event.payload.phase)}` : "";
    log.append(node("li", `${time(event.created_at)} · ${role} · ${friendly(event.type.replace(".", " "))}${phase}`));
  }
  if (!log.children.length) log.append(node("li", "No public actions received in this connection yet. Persisted stage counts above remain authoritative; saved receipts are under See agent work."));
  const last = [...events].reverse().find(event => event.task_id && ids.has(event.task_id)
    && ["model.started", "model.completed", "tool.completed", "answer.critique"].includes(event.type));
  if (root.mode === "scripted") {
    text("agent-last-action", "Offline workflow fixture, not real LLM speed. Detector results are separate from this report.");
  } else if (done) {
    text("agent-last-action", `Run ${root.id} · admitted ${time(root.created_at)} · report recorded ${time(root.updated_at)}. This is a saved result, not a new inference. Simulation speed does not accelerate the LLM.`);
  } else if (last) {
    const phase = typeof last.payload.phase === "string" ? last.payload.phase : "";
    const label = phase.startsWith("critic") ? "separate grounding critic"
      : phase === "reflection" ? "author revising after criticism"
        : phase === "plan" ? "coordinator planning specialist work"
          : last.type === "answer.critique" ? `critic decision: ${String(last.payload.decision)}`
            : last.type === "tool.completed" ? "evidence tool read"
              : friendly(members.find(task => task.id === last.task_id)?.role || "agent");
    text("agent-last-action", `Last recorded action: ${label} · ${time(last.created_at)}. Only executed public actions are shown.`);
  } else {
    text("agent-last-action", `Automatically admitted ${time(root.created_at)}. The detector's initial diagnosis is not a completed LLM investigation.`);
  }
}

export function renderIdleAgentWork(progress: HTMLElement, findings: HTMLElement, enabled: boolean): void {
  progress.replaceChildren(); findings.replaceChildren();
  delete progress.dataset.renderKey; delete progress.dataset.task;
  for (const [role, label] of [["sensor_quality", "1 · Data-quality agent"],
    ["event_diagnosis", "2 · Investigation agent"], ["operator_response", "3 · Reporting agent + critic"]]) {
    const card = node("div", "", "agent-role"); card.dataset.role = role;
    card.append(node("strong", label), node("span", enabled ? "Not started" : "Not enabled"));
    progress.append(card);
  }
}

export function renderAgentWork(progress: HTMLElement, findings: HTMLElement, root: AgentTask,
  tasks: AgentTask[], detail: TaskDetail | null, basis: WindowSnapshot | null,
  error: string | null, open: (taskId: string) => void): void {
  const key = JSON.stringify([root.id, root.state, root.updated_at, root.plan,
    linked(root, tasks).map(task => [task.id, task.updated_at, task.state, task.model_calls, task.tool_calls]),
    detail?.task.updated_at, detail?.investigation_receipts.map(receipt => receipt.call_id),
    Boolean(detail?.casefile), basis?.id, error]);
  if (progress.dataset.renderKey === key) return;
  const opened = new Set(progress.dataset.task === root.id
    ? [...progress.querySelectorAll<HTMLDetailsElement>("details[open]"), ...findings.querySelectorAll<HTMLDetailsElement>("details[open]")]
      .map(item => item.dataset.section) : []);
  const section = (id: string): HTMLDetailsElement => {
    const item = node("details");
    item.dataset.section = id; item.open = opened.has(id);
    return item;
  };
  progress.dataset.task = root.id; progress.dataset.renderKey = key;
  progress.replaceChildren();
  findings.replaceChildren();
  const members = linked(root, tasks);
  for (const [role, label] of [["sensor_quality", "1 · Data-quality agent"],
    ["event_diagnosis", "2 · Investigation agent"], ["operator_response", "3 · Reporting agent + critic"]]) {
    const task = role === "operator_response" ? root : members.find(item => item.role === role);
    const card = node("div", "", "agent-role");
    card.dataset.role = role;
    card.append(node("strong", label));
    const reused = !task && root.plan.includes("reuse");
    card.append(node("span", task ? `${friendly(task.state)} · ${task.model_calls} model / ${task.tool_calls} tool calls`
      : reused ? "Reuse selected · inspect linked receipts" : "Not started"));
    if (task?.result) {
      const count = task.result.claim_refs.filter(id => basis?.claims[id]?.kind === "sensor_health").length;
      if (role === "sensor_quality") card.append(node("span",
        `${basis ? `${count} sensor-health claims checked` : "Loading checked claim scope"}${task.result.limitations.includes("partial_health_review") ? " · partial, not exhaustive" : ""}`));
      const result = section(`role:${role}`);
      result.append(node("summary", "Read specialist handoff"), node("p", task.result.summary));
      result.append(button("Open executed receipts", () => open(task.id)));
      card.append(result);
    }
    progress.append(card);
  }
  findings.append(node("h3", "Investigation evidence · beyond individual sensor alerts"));
  if (error) {
    findings.append(node("p", `Work record unavailable: ${error}. No source checks are inferred. Reconnect to reload.`, "summary"));
    return;
  }
  if (!detail) {
    findings.append(node("p", "Loading the executed work record; no historical findings claimed yet.", "muted"));
    return;
  }
  const file = accepted(root) && detail.task.state === root.state ? detail.casefile : null;
  const receipts = detail.investigation_receipts;
  const reads = receipts.filter(receipt => receipt.name === "history.read" && !receipt.error);
  const documents = new Set(reads.flatMap(receipt => {
    const result = record(receipt.result);
    return Array.isArray(result?.documents) ? result.documents.flatMap(value => {
      const doc = record(value); return typeof doc?.id === "string" ? [doc.id] : [];
    }) : [];
  }));
  const comparisons = receipts.filter(receipt => receipt.name === "history.compare" && !receipt.error);
  const search = [...receipts].reverse().find(receipt => receipt.name === "history.search" && !receipt.error);
  const args = search ? record(search.arguments) : null;
  const review = file?.interpretation_review;
  const decision = review?.rounds[review.rounds.length - 1]?.assessment.decision;
  const decisionLabel = decision === "accept" ? "accepted" : decision;
  const reviewStatus = review
    ? `${review.rounds.length} source-grounding review round(s) completed${decisionLabel ? ` · final decision ${decisionLabel}` : ""}`
    : "no reviewed interpretation yet";
  findings.append(node("p", `${documents.size} operational records read · ${comparisons.length} pressure comparisons recorded · ${reviewStatus}.`, "agent-work-counts"));
  if (file?.reused_task_ids.length) findings.append(node("p",
    `${file.reused_task_ids.length} compatible specialist handoffs reused; their recorded reads are not new model calls.`, "muted"));
  if (args && typeof args.query === "string") findings.append(node("p",
    `Investigation agent chose to ${friendly(typeof args.intent === "string" ? args.intent : "seek context")}: “${args.query}”.`, "agent-search"));
  if (!file) {
    if (documents.size) findings.append(node("p", `Records actually opened: ${[...documents].join(", ")}. Reads are not yet a reviewed conclusion.`, "muted"));
    if (!["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(root.state)) findings.append(node("p",
      accepted(root) ? "Loading the completed handoff; source-backed findings are not displayed until it matches this report."
        : "Investigation failed or abstained without an accepted handoff. No new cause is established.", "muted"));
    return;
  }
  const regions = file.interpretation?.regional_assessments;
  if (regions?.length) {
    const panel = node("section", "", "agent-regions");
    panel.append(node("h3", "Agent conclusions by sensor group"),
      node("p", file.interpretation_review
        ? "Model-written explanations with source-grounding review; separate from numerical detector flags. Physical causes remain unconfirmed."
        : "Model-written explanations from an archived handoff; no current-protocol grounding review. Separate from detector flags; physical causes remain unconfirmed.", "muted"));
    const groups = node("div", "", "agent-region-grid");
    const labels = {
      leak_pattern: "Leak-compatible pressure pattern",
      instrumentation_or_telemetry: "Instrumentation or telemetry explanation",
      operating_change: "Operating-change explanation",
      unresolved: "Cause unresolved",
    };
    for (const [index, region] of regions.entries()) {
      const item = node("article", "", "agent-region");
      item.dataset.region = String(index);
      item.dataset.hypothesis = region.hypothesis;
      item.append(node("h4", labels[region.hypothesis]),
        node("p", `${region.sensor_ids.length} sensor(s) · ${region.sensor_ids.join(", ")}`, "agent-region-sensors"),
        node("p", region.text),
        node("p", `Review references: ${region.references.join(", ") || "None recorded"}`, "muted"));
      groups.append(item);
    }
    panel.append(groups);
    findings.append(panel);
  }
  const historySteps = file.steps.filter(step => step.tool.startsWith("history."));
  if (historySteps.length) {
    const panel = section("why-these-checks");
    panel.className = "agent-checks";
    panel.append(node("summary", `Why these checks · ${historySteps.length} recorded history call(s)`),
      node("p", "Recorded tool arguments, not proposed checks. Review the call IDs alongside the conclusion references above.", "muted"));
    const checks = node("ol");
    for (const step of [...historySteps].sort((a, b) => a.sequence - b.sequence)) {
      const ids = step.arguments.knowledge_ids;
      const knowledgeIds = Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : [];
      const question = step.arguments.check_question;
      const item = node("li");
      item.dataset.callId = step.call_id;
      item.append(node("strong", knowledgeIds.length ? knowledgeIds.join(", ") : "No knowledge IDs recorded"),
        node("p", `→ ${typeof question === "string" && question.trim() ? question : "No check question recorded"}`),
        node("code", `→ ${step.tool} · ${step.call_id}`));
      if (step.error) item.append(node("p", `Call failed: ${step.error}. No successful check is inferred.`, "muted"));
      checks.append(item);
    }
    panel.append(checks);
    findings.append(panel);
  }
  for (const source of file.sources) {
    const id = source.document.id;
    if (typeof id !== "string") continue;
    const row = section(`source:${id}`); row.className = "agent-source";
    row.dataset.document = id;
    row.append(node("summary", `${id} · ${source.use === "cited" ? "read and cited" : friendly(source.use)}`));
    if (typeof source.document.title === "string") row.append(node("strong", source.document.title));
    if (typeof source.document.body === "string") row.append(node("p", source.document.body));
    findings.append(row);
  }
  const knowledge = file.knowledge_packet;
  if (knowledge) {
    const applied = knowledge.cards.filter(card => file.knowledge_used_ids.includes(card.id));
    const panel = section("domain-knowledge");
    panel.className = "agent-knowledge";
    panel.append(node("summary", `Domain guidance · ${applied.length} card(s) cited with case evidence`));
    if (!applied.length) panel.append(node("p", "No domain guidance was cited in this handoff.", "muted"));
    for (const card of applied) {
      const item = node("article", "", "knowledge-card");
      item.dataset.knowledge = card.id;
      item.append(node("h4", card.title), node("p", card.guidance));
      if (card.applies_when) item.append(node("p", `Applies when: ${card.applies_when}`, "muted"));
      for (const [label, entries] of [
        ["Recommended verification · not execution receipts", card.verification_steps],
        ["Counterexamples to check", card.counterexamples],
      ] as const) {
        if (!entries?.length) continue;
        item.append(node("strong", label));
        const checks = node("ul");
        for (const entry of entries) checks.append(node("li", entry));
        item.append(checks);
      }
      if (card.limitations.length) {
        item.append(node("strong", "When not to rely on this guidance"));
        const limits = node("ul");
        for (const limitation of card.limitations) limits.append(node("li", limitation));
        item.append(limits);
      }
      const provenance = section(`knowledge-provenance:${card.id}`);
      provenance.append(node("summary", "Sources, review basis and authority"),
        node("p", `${card.id} · ${knowledge.version} · pinned ${time(knowledge.selected_at)} at investigation time, not incident time.`, "muted"),
        node("p", "Curated for this synthetic workspace and research-derived; not pipeline-SME approved. Guidance supports review, not a confirmed leak or hardware diagnosis.", "muted"),
        node("p", `Review basis: ${card.review_basis}`, "muted"));
      for (const source of card.sources) provenance.append(node("p",
        `${source.reference} · ${source.locator}. ${source.boundary}`, "muted"));
      item.append(provenance);
      panel.append(item);
    }
    if (Object.keys(knowledge.excluded).length) panel.append(node("p",
      `Withheld guidance: ${Object.entries(knowledge.excluded).map(([id, reason]) => `${id}: ${friendly(reason)}`).join("; ")}`, "muted"));
    findings.append(panel);
  } else {
    findings.append(node("p", "Archived handoff: no pinned domain-knowledge packet.", "muted"));
  }
  const quotes = new Set<string>();
  const cited = new Set(file.sources.filter(source => source.use === "cited").map(source => source.document.id));
  const rounds = file.interpretation_review?.rounds || [];
  for (const check of rounds[rounds.length - 1]?.assessment.checks || []) {
    for (const support of check.support) {
      if (check.verdict !== "supported" || !cited.has(support.reference) || quotes.has(support.reference)) continue;
      quotes.add(support.reference);
      if (quotes.size <= 2) findings.append(node("blockquote", `${support.reference}: “${support.quote}”`, "agent-source-finding"));
    }
  }
  if (file.interpretation) {
    const causes = node("div", "", "agent-causes");
    for (const cause of file.interpretation.competing_causes) {
      const item = section(`cause:${cause.cause}`);
      item.dataset.cause = cause.cause;
      item.append(node("summary", `${friendly(cause.cause)}: ${friendly(cause.stance)}`),
        node("p", cause.text), node("p", `Checked references: ${cause.references.join(", ")}`, "muted"));
      causes.append(item);
    }
    findings.append(causes);
    const nextCheck = file.interpretation.follow_up_questions[0];
    if (nextCheck) findings.append(node("p", `Engineer verification needed: ${nextCheck}`, "agent-next-question"));
  }
  findings.append(node("p", `${file.next_action} ${file.interpretation_review
    ? "Same-model critic and exact-source checks are not a correctness guarantee."
    : "Archived report: no current-protocol grounding review."}`, "muted"));
}
