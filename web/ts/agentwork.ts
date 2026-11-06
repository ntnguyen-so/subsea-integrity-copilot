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
  now: number, current: boolean, triage: boolean): void {
  if (!root) {
    text("agent-activity-state", triage ? "Detectors flagged an unresolved pattern; gathering context" : "Detectors monitoring · agents start automatically on a qualifying incident");
    text("agent-elapsed", "No LLM investigation admitted yet");
    text("agent-last-action", "Map flags and the initial inspection interval are numerical detector outputs, not an agent report.");
    return;
  }
  const done = accepted(root), active = ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(root.state);
  const elapsed = ((done || !active ? Date.parse(root.updated_at) : now) - Date.parse(root.created_at)) / 1000;
  const members = linked(root, tasks), ids = new Set(members.map(task => task.id));
  const calls = members.reduce((sum, task) => sum + task.model_calls, 0);
  const tools = members.reduce((sum, task) => sum + task.tool_calls, 0);
  text("agent-activity-state", !current ? "Connection unavailable · last recorded agent status below"
    : done ? "Agent report ready · review findings beyond the detector"
      : active ? `Agents ${root.state === "QUEUED" ? "queued" : "investigating"} · no reviewed report yet`
        : "Agent report withheld · detector warnings remain active");
  text("agent-elapsed", `${duration(elapsed)} real processing ${done || !active ? "elapsed" : "since admission"} · ${calls} ${root.mode === "live" ? "hosted" : "SCRIPTED"} calls · ${tools} tool calls`);
  const last = [...events].reverse().find(event => event.task_id && ids.has(event.task_id)
    && ["model.started", "model.completed", "tool.completed", "answer.critique"].includes(event.type));
  if (root.mode === "scripted") {
    text("agent-last-action", "Offline workflow fixture, not real LLM speed. Detector results are separate from this report.");
  } else if (done) {
    text("agent-last-action", `Automatically admitted ${time(root.created_at)} · report recorded ${time(root.updated_at)}. Simulation speed does not accelerate the LLM.`);
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
  findings.append(node("h3", "What the agents checked beyond the detector"));
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
  findings.append(node("p", `${documents.size} historical records read · ${comparisons.length} pressure comparisons recorded${file?.interpretation_review ? ` · ${file.interpretation_review.rounds.length} grounding-review round(s); final decision accepted` : " · no reviewed interpretation yet"}.`, "agent-work-counts"));
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
    findings.append(node("p", `Engineer verification needed: ${file.interpretation.follow_up_questions[0]}`, "agent-next-question"));
  }
  findings.append(node("p", `${file.next_action} ${file.interpretation_review
    ? "Same-model critic and exact-source checks are not a correctness guarantee."
    : "Archived report: no current-protocol grounding review."}`, "muted"));
}
