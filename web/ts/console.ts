/**
 * Browser composition root: authenticated API projections drive monitoring, received
 * sensor evidence, saved investigations and evaluation views. This client renders
 * backend diagnoses and accepted reports; it never runs inference or invents samples.
 * Walkthrough: initialize -> chooseReplay -> runProjection -> renderProjection.
 * SSE invalidates the projection; focused reads load immutable window/task details.
 */
import { box, bounds, button, element, friendly, node, svg, text, time } from "./dom";
import { renderCharts, sharedPressureRange } from "./charts";
import { renderSensorInspection, type InspectionReadings } from "./sensor_inspection";
import { renderCasefile, renderWorkflowComparison } from "./casefile";
import { agentName, renderAgentWork, renderIdleAgentWork } from "./agentwork";
import { renderEvaluation, type EvaluationReport } from "./evaluation";
import { reportText } from "./presentation";
import { mapLegend, reportedInspectionIntervals, sensorAssessment, sensorSymbol } from "./evaluation_maps";
import { InvestigationPlayback } from "./investigation_playback";
import { ExecutionMetrics } from "./execution_metrics";
import type { AgentTask, CanonicalObservation, ConsoleEvent, InvestigationCase, Json, Mode, Point, Projection, ReplaySession, Sensor, Session, Speed, TaskDetail, WindowSnapshot, Workflow } from "./types";

const select = (id: string): HTMLSelectElement => element(id, HTMLSelectElement);
const input = (id: string): HTMLInputElement => element(id, HTMLInputElement);
const controlButton = (id: string): HTMLButtonElement => element(id, HTMLButtonElement);
// Selection is independent of the current monitor: explicit inspection can pin an
// older window while the server keeps monitoring. Tokens reject obsolete async reads.
let session: Session = { authenticated: false, csrf_token: null, username: null };
let projection: Projection | null = null;
let replays: ReplaySession[] = [];
let windows: WindowSnapshot[] = [];
let selectedWindow: WindowSnapshot | null = null;
let followCurrent = true;
let selectedSensorId: string | null = null;
let selectedEpisodeId: string | null = null;
let selectedEvidenceId: string | null = null;
let selectedTaskId: string | null = null;
let taskDetail: TaskDetail | null = null;
let automaticDetail: TaskDetail | null = null;
let automaticReadKey: string | null = null;
let automaticReading = false;
let automaticReadError: string | null = null;
let automaticTraceKey: string | null = null;
let observations: CanonicalObservation[] = [];
let sensorLoadingKey: string | null = null;
let sensorLoadedKey: string | null = null;
let displayedSensorId: string | null = null;
let sensorReadError: string | null = null;
let inspectionPipeline = "", inspectionPrimaryId: string | null = null;
let inspectionPeerId: string | null = null, inspectionPeerKey: string | null = null;
let inspectionPeer: InspectionReadings | null = null, inspectionPeerLoading = false;
let inspectionPeerError: string | null = null, inspectionPeerToken = 0;
let inspectionReport: TaskDetail | null = null, inspectionReportKey: string | null = null;
let inspectionReportError: string | null = null;
let source: EventSource | null = null;
let cursor = 0, generationToken = 0, sensorToken = 0, windowToken = 0, taskToken = 0;
let projectionWork: Promise<void> | null = null;
let projectionDirty = false, commandBusy = false, catalogLoading = false;
let events: ConsoleEvent[] = [];
let seenEvents = new Set<number>();
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelay = 2000;
let projectionReceivedAt = 0;
let currentReplayId: string | null = null;
let cursorInitialized = false;
let connectionState = "Not connected";
let createRetry: { bodyKey: string; id: string } | null = null;
let controlRetry: { bodyKey: string; id: string } | null = null;
let liveHereRetry: { bodyKey: string; id: string } | null = null;
let activeTab = "live";
let recordedAnchor: { id: string; seconds: number; speed: number } | null = null;
let liveSelection: number | null = null;
let sourceHistory = false;
let timelineWindowKey = "", timelineWindowToken = 0;
let timelineWindowLoading = false;
let timelineWarning: Projection["warning"] | null = null;
let evaluationLoading = false;
let evaluationKey = "";
let evaluationError = false;
let comparisonWindowId: string | null = null;
let mapSegment = "";
let comparisonToken = 0;
const comparisonSensorIds = new Set<string>();
const currentSource = "pressure-v3";
const executionMetrics = new ExecutionMetrics();
// Recorded playback is local navigation over preserved outputs. "Live here" is an
// explicit server mutation creating separate work, not a reinterpretation of a recording.
const playback = new InvestigationPlayback({
  get: request,
  pauseLive: async () => {
    if (!projection || projection.replay.state !== "PLAYING") return;
    await request(`/api/replays/${enc(projection.replay.id)}/control`,
      { action: "pause", idempotency_key: crypto.randomUUID() });
  },
  changed: () => { if (projection) renderProjection(); },
  ready: () => !timelineWindowLoading && sensorLoadingKey === null,
  error: showError,
  metrics: (root, usage, recorded, serverTime) => executionMetrics.set(root, usage, recorded, serverTime),
  liveHere: async seconds => {
    if (!currentReplayId) return;
    const bodyKey = JSON.stringify([currentReplayId, seconds]);
    if (liveHereRetry?.bodyKey !== bodyKey) liveHereRetry = { bodyKey, id: crypto.randomUUID() };
    commandBusy = true; updateControls();
    try {
      const result = await request<{ replay: ReplaySession; task: AgentTask }>(
        `/api/replays/${enc(currentReplayId)}/investigate-here`,
        { source_seconds: seconds, idempotency_key: liveHereRetry.id });
      liveHereRetry = null;
      await chooseReplay(result.replay.id, false, true);
      liveSelection = seconds;
      notify("Fresh agents are investigating this fixed window. The new run is preserved separately.");
    } finally { commandBusy = false; updateControls(); }
  },
});

const eventTypes = [
  "replay.investigation_paused", "replay.state", "window.completed", "window.revised",
  "episode.changed", "task.started", "task.updated", "model.started", "model.completed", "mapping.completed",
  "tool.completed", "answer.critique", "answer.checked", "task.finished", "health.changed",
  "harness.started", "model.context_compacted", "validation.rejected",
  "validation.repair_requested", "validation.passed", "tool.rejected",
];
const publicReceiptFields = ["id", "call_id", "name", "task_id", "tool", "tool_name", "action", "status", "summary", "validation", "outcome", "evidence_ids", "claim_refs", "duration_ms", "error", "error_code", "snapshot_id", "created_at"];
const publicTraceFields = ["trace_id", "span_id", "attempt_id", "session_id", "trace_layout", "task_id", "status", "mode", "model", "model_calls", "tool_calls", "usage", "duration_ms", "export_status", "stored", "stored_trace_visible", "content_capture", "langfuse_url", "url"];

function notify(message: string, error = false): void {
  text("notice", message);
  box("notice").classList.toggle("error", error);
}
function errorMessage(error: unknown): string { return error instanceof Error ? error.message : "Unexpected backend response"; }
function showError(error: unknown): void { notify(errorMessage(error), true); }
function short(id: string): string { return id.length > 22 ? `${id.slice(0, 10)}…${id.slice(-8)}` : id; }
function enc(id: string): string { return encodeURIComponent(id); }
function modeName(mode: Mode): string { return mode === "live" ? "COPILOT HOSTED" : "SCRIPTED"; }
function sensorAlertsOnly(): boolean { return projection?.replay.workflow === "sensor_alerts"; }
function automaticRoot(): AgentTask | null {
  if (liveSelection !== null) {
    const snapshot = projection?.latest_window;
    if (snapshot?.end_seconds !== liveSelection) return null;
    return [...projection?.tasks || []].filter(task =>
      !task.parent_id && task.snapshot_id === snapshot.id)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null;
  }
  const held = projection?.replay.investigation_window_id;
  return [...projection?.tasks || []].filter(task => !task.parent_id && (held ? task.snapshot_id === held : task.automatic))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null;
}
function investigationHold(): { waiting: boolean; unavailable: boolean } {
  const held = projection?.replay.investigation_window_id;
  if (!held) return { waiting: false, unavailable: false };
  const roots = projection!.tasks.filter(task => !task.parent_id && task.snapshot_id === held);
  const blocked = projection!.episodes.some(episode => episode.current_window_id === held
    && ["agent_unavailable", "knowledge_unavailable", "budget_blocked", "no_pressure_anomaly"].includes(episode.dispatch_status || ""));
  return {
    waiting: roots.some(task => ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(task.state)) || !roots.length && !blocked,
    unavailable: blocked || roots.some(task => ["FAILED", "CANCELLED"].includes(task.state)),
  };
}
function jsonText(value: Json | undefined): string {
  return value === undefined ? "not reported" : typeof value === "string" ? value : JSON.stringify(value);
}
function plainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
/**
 * Same-origin transport boundary: mutations require an authenticated CSRF token.
 * T describes the expected wire contract, not runtime schema validation; scope and
 * event checks below guard evidence joins. API failures never create fallback data.
 */
async function request<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  if (body) {
    if (path !== "/api/login" && (!session.authenticated || !session.csrf_token)) throw new Error("Sign in before changing replay state.");
    headers.set("Content-Type", "application/json");
    if (path !== "/api/login" && session.csrf_token) headers.set("X-CSRF-Token", session.csrf_token);
  }
  let response: Response;
  try { response = await fetch(path, { method: body ? "POST" : "GET", credentials: "same-origin", headers, body: body ? JSON.stringify(body) : undefined, signal }); }
  catch { throw new Error("Local API unavailable. Monitoring values are not fabricated; reconnect after the backend starts."); }
  if (!response.ok) {
    const detail: unknown = await response.json().catch(() => null);
    if (response.status === 401) {
      session = { authenticated: false, csrf_token: null, username: null };
      updateSession();
      closeStream();
      setConnection("Authentication required");
    }
    const message = plainObject(detail) && typeof detail.detail === "string" ? detail.detail : response.statusText;
    throw new Error(`HTTP ${response.status}: ${message || "Request failed"}`);
  }
  if (!(response.headers.get("content-type") || "").includes("application/json")) throw new Error("API returned a non-JSON response. Verify that the local API is running.");
  const data: T = await response.json();
  return data;
}
function updateSession(): void {
  box("login-panel").hidden = session.authenticated;
  text("operator", session.authenticated ? session.username || "Operator" : "Signed out");
  updateControls();
}
function setConnection(value: string): void {
  connectionState = value;
  text("connection-state", value); text("system-connection", value);
  renderMonitoringWarning();
}
function updateControls(): void {
  const replay = projection?.replay;
  const allowed = session.authenticated && !commandBusy && !catalogLoading;
  const hold = investigationHold();
  controlButton("create-replay").disabled = !allowed || !select("scenario").value;
  controlButton("play").disabled = !allowed || !replay || hold.waiting || replay.state === "COMPLETED" || replay.state === "FAILED";
  controlButton("play").textContent = replay?.state === "PLAYING" ? "Pause" : replay?.investigation_window_id
    ? hold.waiting ? "Waiting for agents" : hold.unavailable ? "Continue without report" : "Continue monitoring" : "Play";
  controlButton("step").disabled = !allowed || replay?.state !== "PAUSED" || Boolean(replay.investigation_window_id);
  if (playback.enabled) {
    controlButton("play").disabled = !allowed;
    controlButton("play").textContent = playback.playing ? "Pause" : "Play";
    controlButton("step").disabled = !allowed || playback.playing
      || playback.seconds >= (replay?.duration_seconds || 360);
  }
  select("speed").disabled = !allowed || !replay || (!playback.enabled
    && liveSelection === null && (replay.state === "COMPLETED" || replay.state === "FAILED"));
  if (playback.loading) {
    controlButton("play").disabled = true; controlButton("step").disabled = true;
    select("speed").disabled = true;
  }
  const selectedTime = Math.floor(timelineSeconds() / (projection?.pack.hop_seconds || 5))
    * (projection?.pack.hop_seconds || 5);
  const selectedRoot = automaticRoot();
  const selectedRunning = selectedRoot
    && ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(selectedRoot.state);
  controlButton("investigate-live-here").hidden = playback.enabled || !replay;
  controlButton("investigate-live-here").disabled = !allowed || playback.loading
    || selectedTime < 60 || Boolean(selectedRunning);
  controlButton("investigate-live-here").textContent = `Run agents at +${selectedTime}s`;
  controlButton("investigation-mode").disabled = !allowed || !replay || playback.loading;
  controlButton("load-recording").disabled = !allowed;
  if (liveSelection !== null && !playback.enabled) {
    controlButton("play").disabled = true;
    controlButton("step").disabled = !allowed || playback.loading
      || replay?.state === "PLAYING" || liveSelection >= (
        sourceHistory ? confirmedEndpoint() : replay?.duration_seconds || 360
      );
  }
  controlButton("step-back").disabled = !allowed || !replay || playback.loading
    || (playback.enabled ? playback.playing : replay.state === "PLAYING")
    || (playback.enabled ? playback.seconds : timelineSeconds()) <= 0;
  if ((playback.enabled || liveSelection !== null) && playback.waiting) {
    controlButton("step").disabled = true;
    controlButton("step-back").disabled = true;
  }
  controlButton("compare-sensors").disabled = !session.authenticated || !selectedWindow;
}
function switchTab(name: string, focus = false): void {
  const tabs = [...document.querySelectorAll<HTMLButtonElement>(".rail [role=tab]")];
  activeTab = name;
  document.body.classList.toggle("evaluation-active", name === "evaluation");
  for (const tab of tabs) {
    const selected = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    box(`panel-${tab.dataset.tab}`).hidden = !selected;
    if (selected && focus) tab.focus();
  }
  if (name === "evaluation") void loadEvaluation();
  box("evidence-selection").hidden = name === "live"
    && (playback.enabled || liveSelection !== null);
  if (name === "evidence") {
    pinVisibleWindow();
    const sensor = projection?.pack.sensors.find(item => item.id === selectedSensorId && item.channels.includes("pressure"))
      || projection?.pack.sensors.find(item => item.channels.includes("pressure"));
    if (sensor && sensor.id !== selectedSensorId) selectSensor(sensor.id);
    else if (sensor) void loadSensor();
    renderInspectionWorkspace();
  }
}
async function loadEvaluation(): Promise<void> {
  if (evaluationLoading) return;
  if (!session.authenticated) {
    box("evaluation-results").replaceChildren(node("p", "Sign in to view recorded evaluation results.", "empty"));
    return;
  }
  evaluationLoading = true;
  try {
    const report = await request<EvaluationReport>("/api/evaluation");
    const key = JSON.stringify(report);
    if (key !== evaluationKey || evaluationError) renderEvaluation(report, (id, signal) =>
      request<EvaluationReport>(`/api/evaluation?archive_id=${encodeURIComponent(id)}`, undefined, signal));
    evaluationKey = key; evaluationError = false;
  } catch (error) {
    evaluationError = true;
    box("evaluation-results").replaceChildren(node("p", `Evaluation unavailable: ${errorMessage(error)}. No accuracy score is inferred.`, "error"));
  } finally { evaluationLoading = false; }
}
function bindTabs(): void {
  const tabs = [...document.querySelectorAll<HTMLButtonElement>(".rail [role=tab]")];
  tabs.forEach(tab => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab || "live"));
    tab.addEventListener("keydown", event => {
      const visible = tabs.filter(item => !item.hidden), current = visible.indexOf(tab);
      let next: number | null = null;
      if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (current + 1) % visible.length;
      if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = (current + visible.length - 1) % visible.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = visible.length - 1;
      if (next !== null) { event.preventDefault(); switchTab(visible[next].dataset.tab || "live", true); }
    });
  });
}

async function initialize(): Promise<void> {
  try {
    session = await request<Session>("/api/session");
    updateSession();
    if (!session.authenticated) { notify("Sign in to load the monitoring site, recorded runs and scoped evidence."); return; }
    await loadCatalog();
    notify("Timeline loaded. Scrub saved investigations, or switch to live and run agents at the selected time.");
  } catch (error) { showError(error); setConnection("API unavailable"); }
}
async function loadCatalog(): Promise<void> {
  catalogLoading = true; updateControls();
  try { await loadCatalogData(); }
  finally { catalogLoading = false; updateControls(); }
}
async function loadCatalogData(): Promise<void> {
  const [catalog, history] = await Promise.all([
    request<{ scenarios: { id: string; name: string }[] }>("/api/scenarios"),
    request<{ replays: ReplaySession[] }>("/api/replays"),
  ]);
  const scenario = select("scenario");
  scenario.replaceChildren(...catalog.scenarios.map(item => new Option(`${item.id} · ${item.name}`, item.id)));
  replays = history.replays;
  const requested = new URLSearchParams(location.search).get("replay");
  if (requested && replays.some(replay => replay.id === requested)) {
    const chosen = replays.find(replay => replay.id === requested)!;
    if ([...scenario.options].some(option => option.value === chosen.scenario)) {
      scenario.value = chosen.scenario;
    }
    input("seed").value = String(chosen.seed);
    await chooseReplay(requested, new URLSearchParams(location.search).get("view") !== "live");
  } else {
    scenario.value = "S7";
    await loadScenarioRecording();
  }
  updateControls();
}
async function loadScenarioRecording(): Promise<void> {
  const scenario = select("scenario").value, seed = Number(input("seed").value);
  if (!scenario || !Number.isSafeInteger(seed)) throw new Error("Choose a scenario and integer seed.");
  const matches = replays.filter(replay => replay.scenario === scenario && replay.seed === seed
    && replay.source_version === currentSource);
  let replay = matches.filter(row => row.workflow === "agent_assisted")
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0] || matches[0];
  if (!replay) {
    replay = await request<ReplaySession>("/api/replays", {
      scenario, seed, mode: "live", workflow: "agent_assisted",
      idempotency_key: crypto.randomUUID(),
    });
    replays.unshift(replay);
  }
  playback.setSpeed(5);
  await chooseReplay(replay.id);
}
function closeStream(): void {
  source?.close(); source = null;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
}
function timelineSeconds(): number {
  if (playback.enabled) return Math.floor(playback.seconds);
  return liveSelection ?? confirmedEndpoint();
}
// Prefer the actual completed window; otherwise use the lateness-adjusted five-second
// endpoint. This is source-time navigation, not a wall-clock prediction of telemetry.
function confirmedEndpoint(): number {
  return projection?.latest_window?.end_seconds ?? Math.max(0, Math.floor(
    ((projection?.replay.clock_seconds || 0) - (projection?.pack.lateness_seconds || 0)) / 5,
  ) * 5);
}
function navigationSpeed(): number {
  return playback.enabled || liveSelection !== null ? playback.speed : projection?.replay.speed || 5;
}
function moveTime(direction: -1 | 1): void {
  if (!projection || commandBusy || playback.loading
    || ((playback.enabled || liveSelection !== null) && playback.waiting)
    || (playback.enabled ? playback.playing : projection.replay.state === "PLAYING")) return;
  const seconds = navigationSpeed();
  if (playback.enabled) {
    playback.seek(Math.min(projection.replay.duration_seconds, Math.max(0, playback.seconds + direction * seconds)));
  } else if (direction === 1 && liveSelection === null) {
    void command("step");
  } else {
    if (liveSelection === null) {
      sourceHistory = true;
      playback.setSpeed(projection.replay.speed);
    }
    const target = direction === 1
      ? Math.min(sourceHistory ? confirmedEndpoint() : projection.replay.duration_seconds,
        (liveSelection ?? confirmedEndpoint()) + seconds)
      : Math.max(0, (liveSelection ?? confirmedEndpoint()) - seconds);
    liveSelection = sourceHistory && target === confirmedEndpoint() ? null : target;
    if (liveSelection === null) sourceHistory = false;
    if (recordedAnchor && liveSelection !== null) recordedAnchor.seconds = liveSelection;
    renderProjection();
  }
}
function renderInvestigationTime(): void {
  const seconds = timelineSeconds(), slider = input("investigation-time");
  slider.disabled = !projection || commandBusy || playback.loading;
  slider.value = String(seconds);
  text("investigation-time-label", `+${seconds}s`);
  const toggle = controlButton("investigation-mode");
  toggle.setAttribute("aria-checked", String(!playback.enabled));
  toggle.textContent = playback.enabled
    ? "Recorded results · switch to live" : "Live investigation · switch to recorded";
  text("investigation-time-basis", playback.enabled ? playback.description
    : `Selected +${seconds}s. Run fresh agents for this fixed window; switching back to recorded results does not cancel live work.`);
  const points = [...new Set(playback.checkpoints().map(row => row.source_seconds))];
  const key = points.join(",");
  const marks = element("investigation-checkpoints", HTMLDataListElement);
  if (marks.dataset.points !== key) {
    marks.dataset.points = key;
    marks.replaceChildren(...points.map(point => new Option(`+${point}s`, String(point))));
  }
}
async function switchInvestigationMode(): Promise<void> {
  if (!projection || !currentReplayId || commandBusy) return;
  if (playback.enabled) {
    recordedAnchor = { id: currentReplayId, seconds: playback.seconds, speed: playback.speed };
    liveSelection = timelineSeconds();
    sourceHistory = false;
    playback.useLive(); renderProjection();
  } else {
    const anchor = recordedAnchor || {
      id: currentReplayId, seconds: timelineSeconds(), speed: 5,
    };
    if (currentReplayId !== anchor.id) await chooseReplay(anchor.id, true, true);
    await playback.enable();
    liveSelection = null;
    playback.setSpeed(anchor.speed); playback.seek(anchor.seconds);
    renderProjection();
  }
}
/** Change evidence generation atomically from the UI's perspective; invalidate all pending reads. */
async function chooseReplay(id: string, recorded = true, preserveTimeline = false): Promise<void> {
  if (!preserveTimeline) { recordedAnchor = null; liveSelection = null; }
  playback.selectRun(recorded);
  sourceHistory = false;
  timelineWindowKey = ""; timelineWindowToken++; timelineWindowLoading = false; timelineWarning = null;
  closeStream();
  currentReplayId = id;
  generationToken++; windowToken++; sensorToken++; taskToken++;
  projection = null; selectedWindow = null; followCurrent = true;
  windows = []; observations = []; sensorLoadingKey = null; sensorLoadedKey = null;
  displayedSensorId = null;
  comparisonSensorIds.clear(); comparisonToken++;
  selectedSensorId = null; selectedEpisodeId = null;
  selectedEvidenceId = null; selectedTaskId = null; taskDetail = null;
  cursor = 0; cursorInitialized = false; events = []; seenEvents = new Set();
  projectionDirty = true;
  setConnection("Loading coherent projection");
  resetView();
  notify("");
  await refreshProjection();
  if (currentReplayId === id && projection) connectStream(id, generationToken);
}
function resetView(): void {
  executionMetrics.set(null, null, false, new Date().toISOString());
  text("agent-investigation-map", "Loading selected run evidence.");
  mapSegment = ""; select("map-focus").value = "";
  automaticDetail = null; automaticReadKey = null; automaticReadError = null;
  delete box("automatic-progress").dataset.renderKey; delete box("automatic-progress").dataset.task;
  box("agent-findings").replaceChildren();
  sensorReadError = null; inspectionPipeline = ""; inspectionPrimaryId = null;
  inspectionPeerToken++; inspectionPeerId = null; inspectionPeerKey = null;
  inspectionPeer = null; inspectionPeerLoading = false; inspectionPeerError = null;
  inspectionReport = null; inspectionReportKey = null; inspectionReportError = null;
  element("source-audit", HTMLDetailsElement).open = false;
  renderInspectionWorkspace();
  element("investigation-technical", HTMLDetailsElement).open = false;
  renderMonitoringWarning();
  text("source-clock", "Not reported"); text("server-clock", "Not reported");
  text("clock-basis", "No received telemetry"); text("trend-basis", "No received telemetry");
  for (const id of ["stream-stage", "detector-stage", "agent-stage", "automatic-state"]) text(id, "Awaiting telemetry");
  for (const id of ["automatic-timeline", "automatic-progress", "automatic-actions", "sensor-list"]) box(id).replaceChildren();
  box("comparison-charts").replaceChildren();
  text("sensor-list-basis", "Awaiting a completed window");
  text("comparison-basis", "Pins the visible window. Up to four histories share UTC time and a common pressure scale.");
  text("automatic-conclusion", "No investigation loaded for this replay.");
  box("automatic-conclusion").hidden = false;
  box("trace-view").replaceChildren(node("p", "Select an investigation to view its Langfuse run.", "muted"));
  controlButton("view-langfuse").disabled = true;
  automaticTraceKey = null;
  const traceLink = element("automatic-langfuse", HTMLAnchorElement);
  traceLink.hidden = true; traceLink.removeAttribute("href"); delete traceLink.dataset.task;
  text("automatic-trace-status", "");
  delete box("automatic-state").dataset.task;
  text("live-bounds", "Awaiting telemetry"); text("health-state", "Not reported");
  text("event-summary", "Waiting for backend assessment.");
  text("location-summary", ""); text("sensor-title", "Select a sensor"); text("sensor-meta", "No sensor selected");
  box("channel-charts").replaceChildren(node("p", "No observations loaded.", "empty"));
  box("evidence-detail").replaceChildren(node("p", "No evidence selected."));
  box("evidence-chips").replaceChildren(); box("raw-table").replaceChildren();
  box("task-tree").replaceChildren(); box("task-detail").replaceChildren();
  text("answer-preview", "No accepted answer loaded.");
  for (const id of ["sample-coverage", "domain-count", "window-state", "budget-usage"]) text(id, "Not reported");
  const map = document.getElementById("topology");
  if (map) delete map.dataset.snapshot;
  delete box("channel-charts").dataset.snapshot;
  map?.replaceChildren(svg("text", { x: 380, y: 185, "text-anchor": "middle" }, "Awaiting site geometry"));
  box("map-legend").replaceChildren();
  renderWindowHistory(); renderBasis(); updateControls();
}
// Coalesce bursts of SSE invalidations into one reader, then rerun if dirtied mid-read.
// Versions cannot move backward and responses must belong to the selected generation.
function refreshProjection(): Promise<void> {
  if (!currentReplayId) return Promise.resolve();
  projectionDirty = true;
  if (projectionWork) return projectionWork;
  projectionWork = runProjection().finally(() => { projectionWork = null; });
  return projectionWork;
}
async function runProjection(): Promise<void> {
    while (projectionDirty && currentReplayId) {
      projectionDirty = false;
      const id: string = currentReplayId;
      const token: number = generationToken;
      try {
        const data = await request<Projection>(`/api/replays/${enc(id)}/projection`);
        if (token !== generationToken || id !== currentReplayId) { projectionDirty = true; continue; }
        if (data.replay.id !== id || data.latest_window && data.latest_window.generation_id !== id) throw new Error("Projection scope mismatch; refusing cross-generation evidence.");
        if (projection && data.replay.version < projection.replay.version) { projectionDirty = true; continue; }
        const newReplay = projection === null;
        projection = data;
        if (newReplay) {
          select("workflow").value = data.replay.workflow;
          select("scenario").value = data.replay.scenario;
          input("seed").value = String(data.replay.seed);
        }
        selectedSensorId ||= data.pack.sensors[0]?.id || null;
        if (!cursorInitialized) { cursor = data.cursor; cursorInitialized = true; }
        projectionReceivedAt = Date.now();
        if (source?.readyState === EventSource.OPEN) setConnection("Connected · SSE");
        replays = replays.map(replay => replay.id === id ? data.replay : replay);
        if (!replays.some(replay => replay.id === id)) replays.unshift(data.replay);
        if (followCurrent && !selectedWindow) selectedWindow = data.latest_window;
        if (!selectedEpisodeId && data.episodes.length) selectedEpisodeId = data.episodes[0].id;
        renderProjection();
        await refreshWindows(id, token);
        if (selectedSensorId) void loadSensor();
        if (selectedTaskId) void loadTask(selectedTaskId, false);
      } catch (error) {
        if (token === generationToken) { showError(error); setConnection("Stale / projection unavailable"); }
      }
    }
}
async function refreshWindows(id: string, token: number): Promise<void> {
  try {
    const data = await request<{ windows: WindowSnapshot[] }>(`/api/replays/${enc(id)}/windows`);
    if (token !== generationToken) return;
    windows = data.windows.filter(window => window.generation_id === id).sort((a, b) => b.end_seconds - a.end_seconds || b.revision - a.revision);
    renderWindowHistory();
    renderAutomaticInvestigation();
  } catch (error) { if (token === generationToken) showError(error); }
}
/**
 * Durable event cursor + deduplication support reconnects. Events are activity signals,
 * not patches to apply speculatively: each accepted signal requests coherent server state.
 */
function connectStream(id: string, token: number): void {
  closeStream();
  if (!session.authenticated || token !== generationToken) return;
  setConnection("Connecting / explicit resync");
  const stream = new EventSource(`/api/replays/${enc(id)}/events?after=${cursor}`, { withCredentials: true });
  source = stream;
  stream.onopen = () => {
    if (token !== generationToken) return;
    reconnectDelay = 2000;
    setConnection("Connected · SSE");
    void refreshProjection();
  };
  const handle = (event: MessageEvent<string>): void => {
    if (token !== generationToken) return;
    try {
      const decoded: unknown = JSON.parse(event.data);
      if (!isConsoleEvent(decoded)) throw new Error("Malformed backend event; fetching a coherent projection.");
      if (decoded.generation_id !== id || decoded.site_id !== projection?.replay.site_id) throw new Error("Event scope mismatch; ignored.");
      if (seenEvents.has(decoded.id)) return;
      seenEvents.add(decoded.id);
      cursor = Math.max(cursor, decoded.id);
      events.push(decoded);
      if (events.length > 250) events.shift();
      if (seenEvents.size > 1000) seenEvents = new Set(events.map(item => item.id));
      void refreshProjection();
    } catch (error) { showError(error); void refreshProjection(); }
  };
  for (const type of eventTypes) stream.addEventListener(type, handle);
  stream.onmessage = handle;
  stream.addEventListener("resync_required", () => {
    if (token !== generationToken) return;
    notify("Live event updates were interrupted. Refreshing the dashboard from the current server state.", true);
    setConnection("Resync required");
    stream.close();
    void refreshProjection().then(() => {
      if (token === generationToken && session.authenticated) {
        cursor = projection?.cursor || cursor;
        connectStream(id, token);
      }
    });
  });
  stream.onerror = () => {
    if (token !== generationToken) return;
    stream.close();
    setConnection("Disconnected / reconnecting · stale");
    notify("Event stream disconnected. Retrying with the durable cursor and refreshing actual backend state; the source clock is not extrapolated.", true);
    reconnectTimer = setTimeout(() => {
      if (token !== generationToken) return;
      void refreshProjection();
      connectStream(id, token);
    }, reconnectDelay);
    reconnectDelay = Math.min(30000, reconnectDelay * 2);
  };
}
function isJson(value: unknown): value is Json {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJson);
  return plainObject(value) && Object.values(value).every(isJson);
}
// Check the public event envelope before trusting identifiers, cursor or payload.
function isConsoleEvent(value: unknown): value is ConsoleEvent {
  return plainObject(value) && typeof value.id === "number" && Number.isSafeInteger(value.id)
    && typeof value.site_id === "string" && typeof value.generation_id === "string" && typeof value.type === "string"
    && typeof value.created_at === "string" && (value.simulated_seconds === null || typeof value.simulated_seconds === "number")
    && (value.snapshot_id === null || typeof value.snapshot_id === "string") && (value.task_id === null || typeof value.task_id === "string")
    && plainObject(value.payload) && Object.values(value.payload).every(isJson);
}

/** Fan out one coherent projection to the view modules; detailed evidence loads remain scoped. */
function renderProjection(): void {
  if (!projection) return;
  const { replay, pack, latest_window: latest, health } = projection;
  playback.load(projection);
  document.querySelector<HTMLElement>(".live-grid")!.hidden = false;
  syncTimelineWindow();
  text("inference-mode", "EVIDENCE → ENGINEER REVIEW");
  const hold = investigationHold();
  box("investigation-hold").hidden = playback.enabled || !replay.investigation_window_id;
  text("investigation-hold", replay.investigation_window_id
    ? `Simulation paused at +${replay.clock_seconds.toFixed(1)}s · evidence ${short(replay.investigation_window_id)}. ${
      hold.waiting ? "Fresh agents are checking this fixed window; simulated ingestion and stepping are locked."
        : hold.unavailable ? "No reviewed agent report is available. Detector alerts remain active; continuing does not clear them."
          : "Agent checks finished. Review the report, then Continue monitoring."} Only the simulation pauses, never a production safety feed.`
    : "");
  text("simulation-policy", playback.enabled
    ? playback.description
    : replay.workflow === "sensor_alerts"
    ? "Pressure monitoring only; no agents are launched."
    : replay.pending_pressure_alert_seconds != null && !replay.investigation_window_id
      ? `Pressure anomaly detected. Collecting up to ${replay.investigation_context_seconds ?? 0} additional source seconds to assess persistence before pausing for agents.`
      : replay.pause_on_anomaly && (replay.investigation_context_seconds ?? 0) > 0
        ? `Alerts appear immediately. Agents pause the source once pressure persistence is established, or after at most ${replay.investigation_context_seconds} additional source seconds.`
        : "Agent investigations pause the simulated source; recorded runs retain their playback policy.");
  renderClocks();
  renderInvestigationTime();
  text("live-bounds", latest ? `${bounds(latest.window_start, latest.window_end)} · ${latest.quality.status}` : `WARMING_UP / no completed window · width ${pack.window_seconds}s + lateness ${pack.lateness_seconds}s`);
  text("health-state", `${health.monitor} / ${health.agent} / export: ${jsonText(health.observability.status)} · stored visibility: ${jsonText(health.observability.stored_trace_visibility)}`);
  select("speed").value = String(navigationSpeed());
  const stepSeconds = navigationSpeed();
  controlButton("step-back").textContent = `Back ${stepSeconds}s`;
  controlButton("step").textContent = `Forward ${stepSeconds}s`;
  renderMonitoringWarning(); renderBasis(); renderMap(); renderSensorList(); renderAutomaticInvestigation(); syncComparisonWindow(); renderEvidenceChips(); renderTasks(); renderAnswer(); renderMetrics();
  playback.dataChanged(); renderClocks(); updateControls();
  if (replay.error) notify(`Replay ${replay.state}: ${replay.error}`, true);
}
// Quantize navigation to the pack hop and fetch that exact endpoint. Withhold old
// readings while loading; generation, endpoint and warning snapshot must all agree.
function syncTimelineWindow(): void {
  if (!projection) return;
  if (!playback.enabled && liveSelection === null) {
    if (timelineWindowKey) {
      timelineWindowKey = ""; timelineWindowToken++; timelineWindowLoading = false; timelineWarning = null;
      followCurrent = true; selectedWindow = projection.latest_window;
      sensorToken++; sensorLoadingKey = null; sensorLoadedKey = null;
      void loadSensor();
    }
    return;
  }
  const replayId = projection.replay.id;
  const seconds = Math.floor(timelineSeconds() / projection.pack.hop_seconds)
    * projection.pack.hop_seconds;
  const key = JSON.stringify([replayId, seconds]);
  if (timelineWindowKey === key) return;
  timelineWindowKey = key;
  const token = ++timelineWindowToken;
  timelineWindowLoading = true; timelineWarning = null;
  followCurrent = false; selectedWindow = null;
  sensorToken++; sensorLoadingKey = null; sensorLoadedKey = null; sensorReadError = null;
  observations = [];
  box("channel-charts").replaceChildren(node("p", seconds
    ? `Loading received measurements at +${seconds}s. Previous readings withheld.`
    : "Select a source time to view received sensor measurements.", "empty"));
  delete box("channel-charts").dataset.snapshot;
  box("raw-table").replaceChildren();
  text("trend-basis", seconds ? `Loading measurements at +${seconds}s` : "No completed measurement window at +0s");
  void request<{ snapshot: WindowSnapshot | null; warning: Projection["warning"] }>(
    `/api/replays/${enc(replayId)}/timeline-window?source_seconds=${seconds}`,
  ).then(data => {
    if (token !== timelineWindowToken || currentReplayId !== replayId) return;
    if ((seconds === 0 ? data.snapshot !== null
      : !data.snapshot || data.snapshot.generation_id !== replayId || data.snapshot.end_seconds !== seconds)
      || data.warning.snapshot_id !== (data.snapshot?.id || null)) {
      throw new Error("Timeline measurement scope mismatch; no readings substituted.");
    }
    selectedWindow = data.snapshot;
    timelineWarning = data.warning;
    renderBasis(); renderMap(); renderSensorList(); renderEvidenceChips();
    void loadSensor();
  }).catch(error => {
    if (token !== timelineWindowToken) return;
    playback.stop();
    showError(error);
    text("map-time-basis", `Measurements unavailable at +${seconds}s. No previous readings substituted.`);
    text("channel-charts", "Recorded measurements unavailable; no readings substituted.");
  }).finally(() => {
    if (token !== timelineWindowToken) return;
    timelineWindowLoading = false;
    playback.dataChanged(); renderMonitoringWarning(); renderClocks(); updateControls();
  });
}
// Three distinct clocks: server-confirmed simulated source, local recorded navigation,
// and real server/projection age. Only execution_metrics extrapolates live elapsed work.
function renderClocks(): void {
  if (!projection || !projectionReceivedAt) return;
  const { replay, pack } = projection;
  const age = Math.max(0, Date.now() - projectionReceivedAt);
  const current = navigator.onLine && connectionState.startsWith("Connected") && (replay.state !== "PLAYING" || age <= 15000) && projection.health.monitor === "running";
  const seconds = playback.enabled ? playback.seconds : liveSelection ?? replay.clock_seconds;
  const sourceTime = new Date(Date.parse(replay.epoch) + seconds * 1000).toISOString();
  text("source-clock", playback.enabled
    ? `${time(sourceTime)} · +${seconds.toFixed(1)}s · RECORDED ${playback.playing ? "PLAYING" : "PAUSED"} · ${playback.speed}×`
    : liveSelection !== null
      ? `${time(sourceTime)} · +${seconds.toFixed(1)}s · LIVE SELECTION`
      : `${time(sourceTime)} · +${seconds.toFixed(1)}s · ${friendly(replay.state)} · target ${replay.speed}×`);
  box("source-clock").dataset.seconds = String(seconds);
  box("source-clock").dataset.confirmedSeconds = String(replay.clock_seconds);
  text("clock-basis", playback.enabled
    ? playback.waiting
      ? "Waiting for measurements, pressure trends and saved investigation evidence to finish loading. Playback resumes when ready; loading time is not fast-forwarded."
      : "Load-aware recorded playback. Selected speed is the maximum pace; every measurement window loads before advancing. No new model calls."
    : liveSelection !== null
      ? `Selected fixed investigation endpoint. Underlying source last confirmed at +${replay.clock_seconds}s; selecting a time does not create telemetry or launch agents.`
      : `${current ? "Server-confirmed source time" : "NOT CURRENT; last confirmed source time"} · ${pack.sample_seconds}s samples / ${pack.hop_seconds}s window hop. No browser-generated telemetry. Processing load can slow the target pace; agent execution stays real time.`);
  text("server-clock", `${time(projection.server_time)} · projection received ${Math.floor(age / 1000)}s ago`);
}
function renderMonitoringWarning(): void {
  const banner = box("monitoring-warning");
  const timeline = playback.enabled || liveSelection !== null;
  const current = projection, warning = timeline ? timelineWarning : current?.warning;
  const prefix = timeline ? `${playback.enabled ? "Recorded" : "Selected"} measurements · +${
    Math.floor(timelineSeconds() / (current?.pack.hop_seconds || 5)) * (current?.pack.hop_seconds || 5)
  }s · ` : "";
  let message: string, severity = "warning", kind = "unavailable";
  if (timeline && timelineWindowLoading) {
    message = `${prefix}Loading sensor assessment. Previous warnings withheld.`;
    severity = "info"; kind = "waiting";
  } else if (timeline && !warning) {
    message = `${prefix}Sensor assessment unavailable; no previous warning or safety clearance substituted.`;
  } else if (!timeline && (!navigator.onLine || !current || !warning || current.health.monitor !== "running" || (current.replay.state === "PLAYING" && Date.now() - projectionReceivedAt > 15000) || !connectionState.startsWith("Connected"))) {
    message = `MONITORING NOT CURRENT: verify the monitoring connection. ${warning ? `Last recorded assessment: ${warning.title}. ${warning.message}` : "No current assessment."} Do not treat unavailable monitoring as safety clearance.`;
  } else if (warning) {
    message = `${prefix}${warning.title}. ${warning.message}`;
    severity = warning.severity; kind = warning.kind;
  } else {
    message = "Monitoring assessment unavailable; no safety clearance is implied.";
  }
  if (banner.textContent !== message) banner.textContent = message;
  banner.className = `monitoring-warning ${severity}`;
  banner.dataset.kind = kind;
  banner.dataset.snapshot = warning?.snapshot_id || "";
  banner.title = timeline
    ? `${playback.enabled ? "Recorded" : "Selected"} numerical monitoring window: ${selectedWindow?.window_end || "warming up"}. Not current monitoring; independent of AI analysis.`
    : `Latest numerical monitoring window: ${current?.latest_window?.window_end || "warming up"}. Independent of selected historical evidence and AI analysis.`;
}
function renderWindowHistory(): void {
  const dropdown = select("window-history");
  dropdown.replaceChildren(new Option("Follow current window", ""), ...windows.map(window => new Option(`${time(window.window_end)} · r${window.revision} · ${window.quality.status}`, window.id)));
  if (!followCurrent && selectedWindow && !windows.some(window => window.id === selectedWindow?.id)) dropdown.add(new Option(`${time(selectedWindow.window_end)} · r${selectedWindow.revision} · pinned`, selectedWindow.id));
  dropdown.value = followCurrent ? "" : selectedWindow?.id || "";
}
function renderBasis(): void {
  const window = selectedWindow, latest = projection?.latest_window;
  const newer = window && latest && window.id !== latest.id;
  const held = Boolean(projection?.replay.investigation_window_id);
  box("evidence-selection").hidden = activeTab === "live"
    && (playback.enabled || liveSelection !== null);
  box("evidence-selection").dataset.following = String(followCurrent);
  box("evidence-selection").dataset.updating = String(Boolean(newer));
  box("evidence-selection").dataset.snapshotId = window?.id || "";
  text("selected-basis", window ? `${followCurrent ? "CURRENT VIEW" : "PINNED"} · ${bounds(window.window_start, window.window_end)} · revision ${window.revision}` : "No completed window selected");
  text("basis-warning", newer ? followCurrent
    ? `${held ? "Loading the paused investigation window." : "Live inspector updating."} Map and trend retain one coherent received window; the latest warning remains independent.`
    : "Historical evidence pinned. Newer monitoring telemetry is available; this inspector will not change."
    : held ? "Simulation paused for investigation. Map and trend show fixed received evidence; inspecting it does not resume the source."
      : followCurrent ? "Following current telemetry. Trends stay live; comparisons and raw evidence pin this snapshot." : "Visible snapshot pinned. Stream continues independently.");
  text("sensor-list-basis", window ? `${time(window.window_end)} · ${followCurrent ? "following stream" : "pinned review"}` : "Awaiting a completed window");
  if (window && sensorLoadedKey === JSON.stringify([window.id, selectedSensorId])) {
    text("trend-basis", `${followCurrent ? "LIVE TREND" : "PINNED TREND"} · window ending ${time(window.window_end)}`);
  }
  updateControls();
  renderInspectionWorkspace();
}
function pinVisibleWindow(): boolean {
  if (!selectedWindow) return false;
  followCurrent = false;
  renderWindowHistory(); renderBasis();
  return true;
}
async function chooseWindow(id: string): Promise<void> {
  const clearDifferentTask = (snapshotId: string | undefined): void => {
    if (selectedTaskId && taskDetail?.task.snapshot_id !== snapshotId) {
      taskToken++; selectedTaskId = null; taskDetail = null;
      box("task-detail").replaceChildren();
    }
  };
  if (!id) {
    windowToken++;
    followCurrent = true; selectedEvidenceId = null;
    selectedWindow ||= projection?.latest_window || null;
    clearDifferentTask(projection?.latest_window?.id);
    renderProjection(); renderWindowHistory();
    if (selectedSensorId) void loadSensor();
    return;
  }
  followCurrent = false;
  const token = ++windowToken, generation = generationToken;
  try {
    const window = windows.find(item => item.id === id) || await request<WindowSnapshot>(`/api/windows/${enc(id)}`);
    if (token !== windowToken || generation !== generationToken) return;
    if (window.generation_id !== currentReplayId) throw new Error("Selected window is outside this replay generation.");
    selectedWindow = window; selectedEvidenceId = null;
    clearDifferentTask(window.id);
    renderProjection(); renderWindowHistory();
    if (selectedSensorId) void loadSensor();
  } catch (error) { if (token === windowToken) showError(error); }
}
function reviewedCaseForWindow(): InvestigationCase | null {
  if (!projection || !selectedWindow || automaticReadError) return null;
  const active = automaticRoot();
  if (active?.snapshot_id === selectedWindow.id
    && !["SUCCEEDED", "ABSTAINED"].includes(active.state)) return null;
  for (const detail of [automaticDetail, taskDetail]) {
    const file = detail?.casefile;
    const task = projection.tasks.find(item => item.id === file?.task_id);
    if (file && task && ["SUCCEEDED", "ABSTAINED"].includes(task.state)
      && task.result !== null && task.answer !== null && file.state === task.state
      && file.snapshot_id === selectedWindow.id && file.generation_id === selectedWindow.generation_id
      && file.input_hash === selectedWindow.input_hash && file.pack_version === selectedWindow.pack_version
      && file.baseline_version === selectedWindow.baseline_version && file.parameter_version === selectedWindow.parameter_version) return file;
  }
  return null;
}
function sensorFlags(window: WindowSnapshot | null, id: string): { assessed: boolean; missing: boolean; anomaly: boolean; support: boolean } {
  const flags = sensorAssessment(window, id);
  const sensor = projection?.pack.sensors.find(item => item.id === id);
  return {
    ...flags,
    support: flags.assessed && Boolean(sensor && reviewedLabelsForWindow()?.leaks.some(
      leak => leak.segment_id === sensor.segment_id
        && (leak.quote.text.includes(id) || leak.quote.text.includes(sensor.station_id)))),
  };
}
function reviewedLabelsForWindow(): NonNullable<TaskDetail["output_mapping"]>["mapping"] {
  if (playback.enabled) {
    const frame = playback.currentFrame();
    return frame?.detail.task.state === "SUCCEEDED" && frame.detail.casefile
      && frame.snapshot.input_hash === selectedWindow?.input_hash
      && frame.snapshot.end_seconds === selectedWindow.end_seconds
      && frame.detail.output_mapping?.status === "completed" ? frame.detail.output_mapping.mapping : null;
  }
  const review = reviewedCaseForWindow();
  if (!review || review.state !== "SUCCEEDED") return null;
  const detail = [automaticDetail, taskDetail].find(item => item?.task.id === review.task_id);
  return detail?.output_mapping?.status === "completed" ? detail.output_mapping.mapping : null;
}
// Geometry is a schematic projection of pack coordinates, not a hydraulic solution.
// Measured sensor flags and reviewed report labels remain separate evidence layers.
function renderMap(): void {
  if (!projection) return;
  const map = document.getElementById("topology");
  if (!(map instanceof SVGSVGElement)) return;
  const focusedId = document.activeElement?.getAttribute("data-sensor");
  const { pack } = projection;
  const window = selectedWindow;
  text("map-time-basis", window
    ? `${playback.enabled ? "Recorded" : "Selected"} measurements · +${window.end_seconds}s · ${time(window.window_end)}. Agent overlays require this exact evidence; the saved investigation below retains its own timestamp.`
    : "No completed measurement window selected. Grey instruments are unassessed, not healthy.");
  map.dataset.sourceSeconds = window ? String(window.end_seconds) : "";
  const extended = pack.sensors.length > 32;
  box("map-focus-control").hidden = !extended;
  box("network-scale").hidden = !extended;
  const focus = select("map-focus");
  if (focus.dataset.pack !== pack.version) {
    focus.replaceChildren(new Option("Entire network", ""), ...pack.segments.map(segment => new Option(`${segment.id} · ${segment.name}`, segment.id)));
    focus.dataset.pack = pack.version; focus.value = mapSegment;
  }
  const segments = pack.segments.filter(segment => !mapSegment || segment.id === mapSegment);
  const sensors = pack.sensors.filter(sensor => !mapSegment || sensor.segment_id === mapSegment);
  if (extended) {
    const flags = pack.sensors.filter(sensor => sensorFlags(window, sensor.id).anomaly || sensorFlags(window, sensor.id).missing).length;
    text("network-scale", `${(pack.segments.reduce((sum, segment) => sum + segment.length_m, 0) / 1000).toFixed(1)} km · ${pack.segments.length} segments · ${pack.sensors.length} instruments · ${flags} flagged in the inspected window. Compare timing and shared gateways; choose a branch for station labels.`);
  }
  map.dataset.snapshot = window?.id || "";
  const evidence = selectedEvidenceId && window ? window.evidence[selectedEvidenceId] : null;
  // Fit the visible pack/focused branch with one aspect-preserving scale and flip
  // Cartesian y. This display transformation does not change physical evidence.
  const points = segments.flatMap(segment => segment.points);
  if (!points.length) return;
  const xmin = Math.min(...points.map(point => point.x)), xmax = Math.max(...points.map(point => point.x));
  const ymin = Math.min(...points.map(point => point.y)), ymax = Math.max(...points.map(point => point.y));
  const scale = Math.min(650 / Math.max(xmax - xmin, 1), 390 / Math.max(ymax - ymin, 1));
  const project = (point: Point): Point => ({ x: 55 + (point.x - xmin) * scale + (650 - (xmax - xmin) * scale) / 2, y: 65 + (ymax - point.y) * scale + (390 - (ymax - ymin) * scale) / 2 });
  map.replaceChildren(svg("title", {}, "Pipeline network; measured alerts and reviewed agent findings encoded separately"));
  for (let xx = 40; xx < 760; xx += 40) map.append(svg("line", { x1: xx, y1: 30, x2: xx, y2: 490, class: "eval-grid" }));
  for (let yy = 30; yy < 510; yy += 40) map.append(svg("line", { x1: 30, y1: yy, x2: 730, y2: yy, class: "eval-grid" }));
  const labels = reviewedLabelsForWindow();
  const leakSegments = new Set(labels?.leaks.map(item => item.segment_id) || []);
  for (const segment of segments) {
    const coords = segment.points.map(project);
    map.append(svg("polyline", { points: coords.map(point => `${point.x},${point.y}`).join(" "), class: `pipe${leakSegments.has(segment.id) ? " eval-leak-pattern" : ""}`, "data-segment-id": segment.id }));
    const label = segment.id === "P1" ? coords[0] : coords[coords.length - 1];
    if (label) map.append(svg("text", { x: label.x, y: label.y + (segment.id === "P1" ? 30 : -25), "text-anchor": "middle", class: "eval-pipe-label" }, extended && !mapSegment ? segment.id : `${segment.name} / ${segment.id} / ${segment.length_m}m`));
  }
  for (const inspection of reportedInspectionIntervals(labels)) {
    const segment = segments.find(item => item.id === inspection.segment_id);
    if (segment) {
      const start = project(segment.points[0]), end = project(segment.points[segment.points.length - 1]);
      const at = (chainage: number): string => {
        const fraction = chainage / segment.length_m;
        return `${start.x + (end.x - start.x) * fraction},${start.y + (end.y - start.y) * fraction}`;
      };
      const interval = svg("polyline", { points: `${at(inspection.start_m)} ${at(inspection.end_m)}`, class: "eval-inspection inspection-interval", "data-segment-id": segment.id, "data-start-m": inspection.start_m, "data-end-m": inspection.end_m });
      interval.append(svg("title", {}, `Incident-report inspection interval: ${segment.id}, ${inspection.start_m}–${inspection.end_m} m; not an exact leak point or site authorization.`));
      map.append(interval);
    }
  }
  for (const [index, sensor] of sensors.entries()) {
    const position = project(sensor.position);
    let stationPosition = { ...position };
    const segment = pack.segments.find(item => item.id === sensor.segment_id);
    if (sensor.channels.includes("pressure") && segment) {
      const a = project(segment.points[0]), b = project(segment.points[segment.points.length - 1]);
      const length = Math.hypot(b.x - a.x, b.y - a.y);
      if (length > 0) {
        // Enlarge opposite-wall A/B offsets for legibility; both still share their
        // station chainage. Paired agreement need not be independent evidence.
        const side = sensor.id.endsWith("-A") ? -1 : 1;
        const fraction = sensor.chainage_m / segment.length_m;
        stationPosition = { x: a.x + (b.x - a.x) * fraction, y: a.y + (b.y - a.y) * fraction };
        position.x = stationPosition.x - side * (b.y - a.y) / length * 10;
        position.y = stationPosition.y + side * (b.x - a.x) / length * 10;
      }
    }
    const flags = sensorFlags(window, sensor.id);
    const { missing, support } = flags;
    const selected = selectedSensorId === sensor.id || evidence?.sensor_id === sensor.id;
    const health = !flags.assessed ? "Not assessed" : `${missing ? "Missing value: absent or excluded readings" : "Usable coverage"}${flags.anomaly ? "; pressure anomaly" : ""}`;
    const issues = labels?.sensor_issues.filter(item => item.sensor_id === sensor.id) || [];
    const group = sensorSymbol(position, { anomaly: flags.anomaly, missing, selected, unknown: !flags.assessed,
      issue: flags.assessed && issues.some(item => item.kind !== "missing") ? "agent" : undefined });
    if (selected) { group.classList.add("selected"); group.querySelector(".eval-selection")?.classList.add("selection-ring"); }
    group.setAttribute("role", "button"); group.setAttribute("tabindex", "0");
    group.setAttribute("aria-label", `${sensor.id}, ${sensor.segment_id}, ${sensor.chainage_m}m. ${health}. ${support ? "Agent-reviewed pressure pattern; cause unconfirmed." : "No agent-reviewed pattern recorded."}`);
    group.setAttribute("aria-pressed", String(selectedSensorId === sensor.id)); group.dataset.sensor = sensor.id;
    group.dataset.issueKinds = issues.map(item => item.kind).join(",");
    const labelOnLeft = sensor.segment_id === "P2" || sensor.segment_id === "P4";
    if ((!extended || mapSegment || selected || support) && sensor.id.endsWith(labelOnLeft ? "-B" : "-A")) {
      group.append(svg("text", { x: stationPosition.x + (labelOnLeft ? -27 : 27), y: stationPosition.y + 4,
        "text-anchor": labelOnLeft ? "end" : "start", class: "station-label" }, `${sensor.station_id} A/B`));
    }
    group.append(svg("title", {}, `${sensor.id} / ${sensor.station_id} / domain ${sensor.failure_domain_id}. ${health}. ${issues.map(item => `Agent finding: ${item.kind} (${item.assertion}). ${item.quote.text}`).join(" ")}`));
    group.addEventListener("click", () => selectSensor(sensor.id));
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectSensor(sensor.id); }
      if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? sensors.length - 1 : (index + (event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1) + sensors.length) % sensors.length;
        const target = [...map.querySelectorAll<SVGGElement>("[data-sensor]")][next];
        target?.focus();
      }
    });
    map.append(group);
  }
  if (focusedId) [...map.querySelectorAll<SVGGElement>("[data-sensor]")].find(item => item.dataset.sensor === focusedId)?.focus();
  const legendKinds = ["anomaly", "missing", "normal", "selection"];
  if (map.querySelector(".unknown")) legendKinds.push("unknown");
  if (map.querySelector(".eval-leak-pattern")) legendKinds.push("pattern");
  if (map.querySelector(".eval-inspection")) legendKinds.push("inspection");
  if (map.querySelector(".eval-agent-issue")) legendKinds.push("agent");
  const legend = mapLegend(false, { label: "Pipeline marker legend", visibleKinds: legendKinds,
    unknown: true, selectionDetail: "Shows this sensor's pressure trend" });
  box("map-legend").className = legend.className;
  box("map-legend").replaceChildren(...legend.childNodes);
  const count = pack.sensors.filter(sensor => {
    const flags = sensorFlags(window, sensor.id);
    return flags.anomaly || flags.missing;
  }).length;
  text("event-summary", window ? `${count} instruments with pressure anomalies or missing values in this window. These observations alone do not establish cause or location.` : "No completed assessment. Warm-up is not a normal-pipeline verdict.");
  const inspections = reportedInspectionIntervals(labels);
  text("location-summary", inspections.length
    ? `Report-stated inspection: ${inspections.map(item => `${item.segment_id} ${item.start_m}–${item.end_m}m`).join("; ")}. Not an exact leak point or site authorization.`
    : "No agent-reviewed inspection interval for this window. No confirmed leak location is claimed.");
  text("deployment-summary", `${pack.sensors.length} pipe-mounted pressure instruments at ${new Set(pack.sensors.map(sensor => sensor.station_id)).size} paired stations. A/B taps are on opposite pipe walls and share a gateway; wall offsets enlarged for display. Chainage follows each pipe, not screen distance.`);
}
function renderSensorList(): void {
  if (!projection) return;
  const container = box("sensor-list"), window = selectedWindow;
  const scroll = container.scrollTop;
  const focused = container.contains(document.activeElement) ? document.activeElement?.getAttribute("aria-label") : null;
  const findings = new Map(window?.quality.findings.map(item => [item.sensor_id, item]) || []);
  const rank = (id: string): number => {
    const finding = findings.get(id);
    return finding && (finding.anomaly_count || finding.missing || finding.hard_excluded) ? 1 : 0;
  };
  const table = node("table"), head = node("thead"), headings = node("tr"), body = node("tbody");
  for (const title of ["Compare", "Instrument", "Window condition", "Anomalous samples", "Usable / expected"]) headings.append(node("th", title));
  head.append(headings); table.append(head, body);
  for (const sensor of [...projection.pack.sensors].sort((a, b) => rank(b.id) - rank(a.id) || a.id.localeCompare(b.id))) {
    const finding = findings.get(sensor.id), row = node("tr", "", selectedSensorId === sensor.id ? "highlight" : "");
    const flags = sensorFlags(window, sensor.id);
    const compareCell = node("td"), checkbox = node("input");
    checkbox.type = "checkbox"; checkbox.checked = comparisonSensorIds.has(sensor.id);
    checkbox.disabled = !checkbox.checked && comparisonSensorIds.size >= 4;
    checkbox.setAttribute("aria-label", `Compare ${sensor.id}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) comparisonSensorIds.add(sensor.id); else comparisonSensorIds.delete(sensor.id);
      renderSensorList();
    });
    compareCell.append(checkbox);
    const sensorCell = node("td"), open = button(sensor.id, () => selectSensor(sensor.id));
    open.setAttribute("aria-label", `Trend ${sensor.id}`); open.setAttribute("aria-pressed", String(selectedSensorId === sensor.id));
    sensorCell.append(open);
    const conditions = [
      flags.anomaly ? "Pressure anomaly" : "",
      flags.missing ? "Missing value" : "",
    ].filter(Boolean);
    const condition = !flags.assessed ? "Warming up / not assessed"
      : conditions.join("; ") || "No pressure anomaly or missing value";
    row.append(compareCell, sensorCell, node("td", condition), node("td", finding ? String(finding.anomaly_count) : "—"), node("td", finding ? `${finding.usable} / ${finding.expected}` : "—"));
    body.append(row);
  }
  container.replaceChildren(table);
  if (focused) [...container.querySelectorAll<HTMLElement>("[aria-label]")].find(item => item.getAttribute("aria-label") === focused)?.focus({ preventScroll: true });
  container.scrollTop = scroll;
  controlButton("compare-sensors").textContent = comparisonSensorIds.size ? `Compare selected (${comparisonSensorIds.size})`
    : "Compare sensor histories";
  controlButton("clear-comparison").disabled = comparisonSensorIds.size === 0;
}
function localViewerUrl(rawUrl: string): URL {
  const url = new URL(rawUrl, location.href);
  const loopback = url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]";
  if ((url.protocol !== "http:" && url.protocol !== "https:") || (!loopback && url.origin !== location.origin) || url.username || url.password) throw new Error("Unsupported viewer target");
  return url;
}
function investigationViewerUrl(trace: Record<string, Json>): URL | null {
  if (typeof trace.langfuse_url !== "string") return null;
  if (trace.trace_layout === "investigation-v1") return localViewerUrl(trace.langfuse_url);
  if (typeof trace.session_id !== "string") return null;
  if (!/^[a-f0-9]{64}$/.test(trace.session_id)) throw new Error("Invalid investigation session ID");
  const url = localViewerUrl(trace.langfuse_url);
  if (!/^\/project\/[^/]+\/traces\/[a-f0-9]{32}$/.test(url.pathname)) throw new Error("Unsupported Langfuse trace path");
  url.pathname = url.pathname.replace(/\/traces\/[a-f0-9]{32}$/, `/sessions/${trace.session_id}`);
  url.search = ""; url.hash = "";
  return url;
}
function refreshHeaderTrace(task: AgentTask | null): void {
  const link = element("automatic-langfuse", HTMLAnchorElement);
  if (task && link.dataset.task === task.id && !link.hidden) return;
  const generation = generationToken;
  const key = task ? `${generation}|${task.id}|${task.updated_at}` : null;
  if (key === automaticTraceKey) return;
  automaticTraceKey = key;
  link.hidden = true; link.removeAttribute("href"); delete link.dataset.task;
  text("automatic-trace-status", task ? "Loading Langfuse link..." : "");
  if (!task) return;
  void request<Record<string, Json>>(`/api/tasks/${enc(task.id)}/trace`).then(trace => {
    if (generation !== generationToken || automaticTraceKey !== key) return;
    const url = investigationViewerUrl(trace);
    if (!url) {
      text("automatic-trace-status", "Langfuse investigation session not yet recorded.");
      return;
    }
    link.href = url.href;
    link.dataset.task = task.id; link.hidden = false;
    text("automatic-trace-status", "");
  }).catch(error => {
    if (generation === generationToken && automaticTraceKey === key) {
      text("automatic-trace-status", `Langfuse link unavailable: ${errorMessage(error)}`);
    }
  });
}
function renderAutomaticInvestigation(): void {
  if (!projection) return;
  if (liveSelection !== null && !playback.enabled && !automaticRoot()) {
    element("automatic-langfuse", HTMLAnchorElement).hidden = true;
    text("automatic-trace-status", "");
    text("automatic-state", `LIVE · no investigation at +${liveSelection}s`);
    delete box("automatic-state").dataset.task;
    executionMetrics.set(null, null, false, projection.server_time);
    playback.draw(projection.pack, null, null);
    renderIdleAgentWork(box("automatic-progress"), box("agent-findings"), false);
    box("automatic-timeline").replaceChildren(); box("automatic-actions").replaceChildren();
    box("automatic-conclusion").hidden = false;
    text("automatic-conclusion", `No live result for +${liveSelection}s. Run agents at this time, or switch back to recorded results. Older or later findings are not substituted.`);
    return;
  }
  if (playback.enabled) {
    element("automatic-langfuse", HTMLAnchorElement).hidden = true;
    text("automatic-trace-status", "Preserved investigation · original source time");
    playback.render();
    return;
  }
  const { replay, latest_window: latest, pack } = projection;
  text("stream-stage", `${replay.state} · received through +${replay.clock_seconds.toFixed(1)}s · ${pack.sensors.length} instruments`);
  text("detector-stage", latest ? `Pressure / quality screening · window ends +${latest.end_seconds}s` : `Warming up · ${pack.window_seconds}s window / ${pack.hop_seconds}s hop`);
  const root = automaticRoot();
  refreshHeaderTrace(root || [...projection.tasks].filter(task => !task.parent_id)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null);
  const timeline = box("automatic-timeline"), progress = box("automatic-progress"), actions = box("automatic-actions");
  box("automatic-conclusion").hidden = false;
  timeline.replaceChildren(); actions.replaceChildren();
  const incident = root ? projection.episodes.find(item => item.id === root.episode_id) : projection.episodes[0];
  const unavailable = incident?.pending_window_id && incident.dispatch_status && incident.dispatch_status !== "queued"
    ? friendly(incident.dispatch_status) : null;
  if (!root) {
    executionMetrics.set(null, null, false, projection.server_time);
    playback.draw(pack, latest, null);
    renderIdleAgentWork(progress, box("agent-findings"), !sensorAlertsOnly());
    if (incident?.dispatch_status === "gathering_context") {
      text("agent-stage", "Evidence triage · collecting unresolved context");
      text("automatic-state", "TRIAGE · NOT AN LLM REPORT");
      const boundary = new Date(Date.parse(replay.epoch) + (incident.first_seen_seconds + pack.window_seconds) * 1000).toISOString();
      const item = node("div");
      item.append(node("small", "UNRESOLVED-ONLY REVIEW BOUNDARY / SOURCE UTC"), node("strong", time(boundary)));
      timeline.append(item);
      text("automatic-conclusion", `Unresolved pressure anomaly: collect at most one ${pack.window_seconds}s source window before admitting this first LLM report. Pressure anomalies with a qualifying leak pattern or instrumentation/coverage concerns bypass this hold. Missing values alone do not start agents. Numerical warnings and manual review remain immediate; do not wait for AI.`);
      delete box("automatic-state").dataset.task;
      return;
    }
    const state = sensorAlertsOnly() ? "Agent execution off · no model calls" : unavailable ? `Not queued: ${unavailable}` : "Waiting for a pressure anomaly";
    text("agent-stage", state); text("automatic-state", state);
    text("automatic-conclusion", sensorAlertsOnly()
      ? "No agent diagnosis or localization has been produced. The same sensor histories, quality flags, comparisons and evidence remain available for engineer review."
      : unavailable
      ? "No report is available. Numerical warnings and manual investigation remain active; do not treat unavailable analysis as safety clearance."
      : "New pressure anomalies start investigation automatically. Missing values alone do not start agents. Detector warnings and manual review remain available; no healthy-pipeline conclusion is inferred.");
    delete box("automatic-state").dataset.task;
    return;
  }
  box("automatic-state").dataset.task = root.id;
  const accepted = (root.state === "SUCCEEDED" || root.state === "ABSTAINED") && root.result !== null && root.answer !== null;
  const failed = !accepted && !["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(root.state);
  const pending = Boolean(incident?.pending_window_id);
  const state = accepted ? `${modeName(root.mode)} · REPORT AVAILABLE${root.state === "ABSTAINED" ? " · FURTHER EVIDENCE NEEDED" : ""}`
    : failed ? `${modeName(root.mode)} · REPORT WITHHELD (${root.error_code || root.state})`
      : `${modeName(root.mode)} · ${friendly(root.state)}`;
  text("agent-stage", `${state}${pending ? " · newer warning awaiting analysis" : ""}`);
  text("automatic-state", state);
  const basis = windows.find(window => window.id === root.snapshot_id) || (latest?.id === root.snapshot_id ? latest : null);
  const stamp = (label: string, value: string): void => {
    const item = node("div"); item.append(node("small", label), node("strong", value)); timeline.append(item);
  };
  stamp("ALERT EVIDENCE / SOURCE UTC", basis ? `${time(basis.window_end)} · +${basis.end_seconds}s` : `Snapshot ${short(root.snapshot_id)}`);
  stamp("ANALYSIS QUEUED / PROCESSING UTC", time(root.created_at));
  stamp(accepted ? "REPORT RECORDED / PROCESSING UTC" : failed ? "FAILURE RECORDED / PROCESSING UTC" : "LAST TASK UPDATE / PROCESSING UTC", time(root.updated_at));
  const detail = automaticDetail?.task.id === root.id ? automaticDetail : null;
  executionMetrics.set(root, detail?.execution_usage || null, false, projection.server_time);
  renderAgentWork(progress, box("agent-findings"), root, projection.tasks, detail, basis,
    automaticReadError, id => { void loadTask(id); }, events);
  playback.draw(pack, basis, detail);
  refreshAutomaticDetail(root);
  const status = failed ? `No accepted report: ${root.error_message || root.error_code || friendly(root.state)}. Do not wait for AI to act under existing response procedures.`
      : projection.replay.investigation_window_id
        ? "Investigating the pinned alert evidence. Simulated ingestion is paused while real agent checks run; detector warnings remain active."
        : "Investigating the pinned alert evidence. Sensor ingestion, numerical warnings and manual trends continue independently.";
  text("automatic-conclusion", accepted ? "" : status);
  box("automatic-conclusion").hidden = accepted;
  const freshness: string[] = [];
  if (latest && latest.id !== root.snapshot_id) freshness.push("Historical analysis: newer monitoring evidence exists; this report is not rebased.");
  if (pending) freshness.push(`New material warning is pending${unavailable ? `: ${unavailable}` : " until the active investigation finishes and admission permits"}.`);
  if (freshness.length) {
    const warning = node("p", freshness.join(" "), "muted");
    warning.id = "automatic-freshness"; actions.append(warning);
  }
}
function syncComparisonWindow(): void {
  if (comparisonWindowId !== selectedWindow?.id) {
    comparisonWindowId = null;
    box("comparison-panel").hidden = true;
    box("comparison-charts").replaceChildren();
    text("comparison-basis", "Pins the visible window. Up to four histories share UTC time and a common pressure scale.");
  }
}

async function compareSensors(): Promise<void> {
  if (!projection || !selectedWindow || !pinVisibleWindow()) return;
  const window = selectedWindow, generation = generationToken;
  comparisonWindowId = window.id;
  box("comparison-panel").hidden = false;
  const concerns = window.quality.findings.filter(f => f.spike_count || f.drift_suspected || f.peer_disagreement || f.hard_excluded || f.missing > f.expected * .1);
  const examples: string[] = [];
  const segmentOf = (id: string): string | undefined => projection?.pack.sensors.find(sensor => sensor.id === id)?.segment_id;
  for (const kind of ["drift", "spike", "gap"]) {
    const options = concerns.filter(f => kind === "drift" ? f.drift_suspected : kind === "spike" ? f.spike_count > 0 : f.missing > f.expected * .1);
    const used = new Set(examples.map(segmentOf));
    const finding = options.find(f => !used.has(segmentOf(f.sensor_id))) || options[0];
    if (finding) examples.push(finding.sensor_id);
  }
  const candidates = [...examples, ...window.quality.findings.filter(
    f => f.anomaly_count || f.spike_count || f.drift_suspected || f.peer_disagreement || f.missing || f.hard_excluded
  ).map(f => f.sensor_id)];
  const ids = comparisonSensorIds.size ? [...comparisonSensorIds] : [...new Set(candidates)].slice(0, 4);
  const token = ++comparisonToken;
  const container = box("comparison-charts");
  container.replaceChildren(node("p", ids.length ? "Loading scoped pressure histories..." : "No event/fault histories selected by the current evidence."));
  text("comparison-basis", `${bounds(window.window_start, window.window_end)} · ${short(window.id)} · pinned comparison`);
  try {
    const results = await Promise.all(ids.map(async id => {
      const data = await request<{ sensor: Sensor; observations: CanonicalObservation[] }>(`/api/windows/${enc(window.id)}/sensors/${enc(id)}`);
      if (data.sensor.id !== id || data.observations.some(row => row.sensor_id !== id || row.unit !== "bar")) throw new Error("Comparison sensor or unit scope mismatch.");
      return data;
    }));
    if (token !== comparisonToken || generation !== generationToken || selectedWindow?.id !== window.id || comparisonWindowId !== window.id) return;
    if (!results.length) return;
    const range = sharedPressureRange(results, window);
    if (!range) text("comparison-basis", `${bounds(window.window_start, window.window_end)} · no usable pressure or baseline; common pressure scale unavailable.`);
    container.replaceChildren();
    for (const data of results) {
      const card = node("article"), charts = node("div");
      card.append(node("h3", `${data.sensor.id} / ${data.sensor.failure_domain_id}`), charts);
      renderCharts(charts, data.sensor, data.observations, window, projection.pack.sample_seconds, range);
      container.append(card);
    }
  } catch (error) {
    if (token === comparisonToken && generation === generationToken && selectedWindow?.id === window.id) {
      showError(error); container.replaceChildren(node("p", "Comparison unavailable; no histories substituted."));
    }
  }
}
function selectSensor(id: string): void {
  const sensor = projection?.pack.sensors.find(item => item.id === id);
  if (mapSegment && sensor && sensor.segment_id !== mapSegment) {
    mapSegment = sensor.segment_id; select("map-focus").value = mapSegment;
  }
  selectedSensorId = id; selectedEvidenceId = null;
  text("evidence-detail", `${id} · choose an optional calculation reference below to inspect its source.`);
  renderMap(); renderSensorList(); renderEvidenceChips(); void loadSensor(); renderInspectionWorkspace();
}
/** Read canonical received observations for the selected immutable window; stale replies are ignored. */
async function loadSensor(): Promise<void> {
  const live = followCurrent;
  const id = selectedSensorId, window = live ? projection?.latest_window : selectedWindow;
  if (!id || !window || !projection) return;
  const key = JSON.stringify([window.id, id]);
  // Snapshot IDs are immutable. SSE health/task refreshes must not restart this read.
  if (key === sensorLoadingKey) {
    if (!live && sensorLoadedKey !== key) {
      observations = []; sensorLoadedKey = null;
      box("channel-charts").replaceChildren(node("p", "Loading actual canonical observations…", "empty"));
      delete box("channel-charts").dataset.snapshot;
      box("raw-table").replaceChildren(node("p", "Loading source records…", "empty"));
      text("trend-basis", `Loading received measurements · ${bounds(window.window_start, window.window_end)}`);
    }
    return;
  }
  if (live && sensorLoadingKey && displayedSensorId === id) return;
  if (key === sensorLoadedKey) { renderBasis(); renderRawTable(); return; }
  sensorLoadingKey = key;
  sensorReadError = null;
  const token = ++sensorToken, generation = generationToken;
  let committed = false;
  const sensor = projection.pack.sensors.find(item => item.id === id);
  text("sensor-title", sensor ? `${sensor.id} / ${sensor.station_id}` : id);
  text("sensor-meta", sensor ? `${sensor.segment_id} · ${sensor.chainage_m}m · failure domain ${sensor.failure_domain_id}` : "Loading sensor metadata");
  if (!live || displayedSensorId !== id) {
    displayedSensorId = id; sensorLoadedKey = null; observations = [];
    text("trend-basis", `Loading received measurements · ${bounds(window.window_start, window.window_end)}`);
    box("channel-charts").replaceChildren(node("p", "Loading actual canonical observations…", "empty"));
    delete box("channel-charts").dataset.snapshot;
    box("raw-table").replaceChildren(node("p", "Loading source records…", "empty"));
  }
  box("channel-charts").setAttribute("aria-busy", "true");
  renderInspectionWorkspace();
  try {
    const data = await request<{ sensor: Sensor; observations: CanonicalObservation[] }>(`/api/windows/${enc(window.id)}/sensors/${enc(id)}`);
    const adoptLiveWindow = live && followCurrent;
    if (token !== sensorToken || generation !== generationToken || selectedSensorId !== id || (!adoptLiveWindow && selectedWindow?.id !== window.id)) return;
    if (data.sensor.id !== id || data.observations.some(record => record.sensor_id !== id)) throw new Error("Sensor response scope mismatch.");
    if (data.observations.some(record => record.channel === "pressure" && record.unit !== "bar")) throw new Error("Pressure readings are not normalized to bar.");
    if (adoptLiveWindow) selectedWindow = window;
    observations = data.observations;
    sensorLoadedKey = key;
    renderCharts(box("channel-charts"), data.sensor, observations, window, projection.pack.sample_seconds);
    box("channel-charts").dataset.snapshot = window.id;
    renderRawTable();
    committed = true;
    if (adoptLiveWindow) { renderProjection(); renderWindowHistory(); } else renderBasis();
  } catch (error) {
    if (token === sensorToken) {
      if (playback.enabled) playback.stop();
      showError(error);
      sensorLoadedKey = null;
      sensorReadError = errorMessage(error);
      box("channel-charts").replaceChildren(node("p", "Observation API unavailable; no measurements substituted.", "empty"));
      delete box("channel-charts").dataset.snapshot;
      box("raw-table").replaceChildren(node("p", errorMessage(error), "empty"));
      renderInspectionWorkspace();
    }
  } finally {
    if (token === sensorToken) {
      sensorLoadingKey = null;
      box("channel-charts").setAttribute("aria-busy", "false");
      // Coalesce fast hops: commit a coherent received window, then fetch the newest.
      if (committed && followCurrent && projection?.latest_window?.id !== window.id) void loadSensor();
      playback.dataChanged(); renderClocks(); updateControls();
    }
  }
}
function renderInspectionWorkspace(): void {
  const pack = projection?.pack || null, window = selectedWindow;
  const sensor = pack?.sensors.find(item => item.id === selectedSensorId && item.channels.includes("pressure")) || null;
  const pipeline = select("inspection-pipeline"), sensors = select("inspection-sensor"), peers = select("inspection-peer");
  const pipelineKey = JSON.stringify(pack?.segments.map(item => [item.id, item.name]));
  if (pipeline.dataset.key !== pipelineKey) {
    pipeline.dataset.key = pipelineKey;
    pipeline.replaceChildren(new Option("All pipelines", ""),
      ...(pack?.segments || []).map(item => new Option(`${item.id} · ${item.name}`, item.id)));
  }
  if (sensor && inspectionPipeline && sensor.segment_id !== inspectionPipeline) inspectionPipeline = sensor.segment_id;
  pipeline.value = inspectionPipeline; pipeline.disabled = !pack;
  const available = (pack?.sensors || []).filter(item => item.channels.includes("pressure")
    && (!inspectionPipeline || item.segment_id === inspectionPipeline));
  const sensorKey = JSON.stringify(available.map(item => [item.id, item.chainage_m]));
  if (sensors.dataset.key !== sensorKey) {
    sensors.dataset.key = sensorKey;
    sensors.replaceChildren(...available.map(item => new Option(`${item.id} · ${item.chainage_m} m`, item.id)));
    if (!available.length) sensors.add(new Option("No pressure sensors available", ""));
  }
  sensors.disabled = !window || !available.length; sensors.value = sensor?.id || "";
  if (sensor?.id !== inspectionPrimaryId) {
    inspectionPrimaryId = sensor?.id || null; inspectionPeerToken++;
    inspectionPeerId = pack?.sensors.find(item => item.id !== sensor?.id && item.station_id === sensor?.station_id
      && item.segment_id === sensor?.segment_id && item.channels.includes("pressure"))?.id || null;
    inspectionPeerKey = null; inspectionPeer = null; inspectionPeerError = null; inspectionPeerLoading = false;
  }
  const peerOptions = (pack?.sensors || []).filter(item => item.id !== sensor?.id && item.channels.includes("pressure"));
  const peerOptionsKey = JSON.stringify(peerOptions.map(item => [item.id, item.chainage_m]));
  if (peers.dataset.key !== peerOptionsKey) {
    peers.dataset.key = peerOptionsKey;
    peers.replaceChildren(new Option("No comparison", ""),
      ...peerOptions.map(item => new Option(`${item.id} · ${item.chainage_m} m`, item.id)));
  }
  peers.disabled = !window || !sensor; peers.value = inspectionPeerId || "";
  const peerSensor = pack?.sensors.find(item => item.id === inspectionPeerId) || null;
  const key = window && sensor ? JSON.stringify([window.id, sensor.id]) : null;
  const peerKey = window && sensor && peerSensor ? JSON.stringify([window.id, sensor.id, peerSensor.id]) : null;
  if (peerKey !== inspectionPeerKey) {
    inspectionPeerToken++; inspectionPeer = null; inspectionPeerError = null; inspectionPeerLoading = false;
    inspectionPeerKey = peerKey;
    if (activeTab === "evidence" && window && peerSensor && peerKey) {
      inspectionPeerLoading = true;
      void loadInspectionPeer(window, peerSensor, peerKey, inspectionPeerToken);
    }
  } else if (activeTab === "evidence" && window && peerSensor && peerKey && !inspectionPeer
    && !inspectionPeerLoading && !inspectionPeerError) {
    inspectionPeerLoading = true;
    void loadInspectionPeer(window, peerSensor, peerKey, inspectionPeerToken);
  }
  if (activeTab === "evidence" && projection && window) {
    const accepted = [...projection.tasks].filter(task => task.parent_id === null && task.result && task.answer
      && ["SUCCEEDED", "ABSTAINED"].includes(task.state)).sort((a, b) => b.created_at.localeCompare(a.created_at));
    const candidate = accepted.find(task => task.snapshot_id === window.id) || accepted[0];
    if (candidate) {
      const reportKey = `${candidate.id}:${candidate.updated_at}`;
      if (reportKey !== inspectionReportKey) {
        inspectionReportKey = reportKey; inspectionReportError = null;
        void loadInspectionReport(candidate.id, reportKey, generationToken);
      }
    }
  }
  const root = automaticRoot();
  const container = box("sensor-inspection-workspace");
  const reports = [inspectionReport, automaticDetail, taskDetail];
  const pending = Boolean(root && root.snapshot_id === window?.id && ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(root.state));
  const renderKey = JSON.stringify([window?.id, sensor?.id, sensorLoadedKey, sensorReadError,
    peerKey, Boolean(inspectionPeer), inspectionPeerLoading, inspectionPeerError, inspectionReportError, pending,
  reports.map(detail => [detail?.task.id, detail?.task.updated_at, detail?.task.state, detail?.output_mapping])]);
  if (container.dataset.renderKey === renderKey) return;
  renderSensorInspection(container, {
    pack, window, sensor, readings: key === sensorLoadedKey ? observations : [],
    loading: Boolean(key && key !== sensorLoadedKey && !sensorReadError),
    error: sensorReadError, peer: inspectionPeer, peerSensor, peerLoading: inspectionPeerLoading,
    peerError: inspectionPeerError, reportError: inspectionReportError,
    reports, pending,
    openReport: id => { void loadTask(id); },
    inspectWindow: id => { void chooseWindow(id); },
  });
  container.dataset.renderKey = renderKey;
}
async function loadInspectionPeer(window: WindowSnapshot, sensor: Sensor, key: string, token: number): Promise<void> {
  const generation = generationToken;
  try {
    const data = await request<InspectionReadings>(`/api/windows/${enc(window.id)}/sensors/${enc(sensor.id)}`);
    if (generation !== generationToken || token !== inspectionPeerToken || key !== inspectionPeerKey) return;
    if (data.sensor.id !== sensor.id || data.observations.some(row => row.sensor_id !== sensor.id
      || row.channel === "pressure" && row.unit !== "bar")) throw new Error("Comparison sensor or unit scope mismatch.");
    inspectionPeer = data;
  } catch (error) {
    if (generation === generationToken && token === inspectionPeerToken) {
      inspectionPeerError = errorMessage(error); showError(error);
    }
  } finally {
    if (generation === generationToken && token === inspectionPeerToken) {
      inspectionPeerLoading = false; renderInspectionWorkspace();
    }
  }
}
async function loadInspectionReport(id: string, key: string, generation: number): Promise<void> {
  try {
    const detail = await readTaskDetail(id, generation);
    if (generation !== generationToken || key !== inspectionReportKey) return;
    inspectionReport = detail;
  } catch (error) {
    if (generation === generationToken && key === inspectionReportKey) {
      inspectionReport = null; inspectionReportError = errorMessage(error); showError(error);
    }
  } finally {
    if (generation === generationToken && key === inspectionReportKey) renderInspectionWorkspace();
  }
}
function renderRawTable(): void {
  const container = box("raw-table");
  container.replaceChildren();
  if (!observations.length) { container.append(node("p", "No canonical records received for the selected sensor and window. Empty data is a gap, not a zero.", "empty")); return; }
  const table = node("table"), caption = node("caption", `${selectedSensorId} · raw/canonical source records · observed and received times are distinct`);
  const head = node("thead"), row = node("tr");
  for (const title of ["Observation / channel", "Observed UTC / received UTC", "Canonical value / validity", "Original value / unit", "Original timestamps", "Source / transformation"]) {
    const th = node("th", title); th.scope = "col"; row.append(th);
  }
  head.append(row);
  const body = node("tbody");
  const evidence = selectedEvidenceId && selectedWindow ? selectedWindow.evidence[selectedEvidenceId] : null;
  for (const observation of observations) {
    const highlighted = selectedEvidenceId === observation.id || evidence?.channel === observation.channel;
    const tr = node("tr", "", highlighted ? "highlight" : "");
    tr.dataset.observation = observation.id;
    const original = observation.original;
    for (const value of [
      `${observation.id}\n${observation.channel}`,
      `${time(observation.observed_at)}\n${time(observation.received_at)}`,
      `${observation.value ?? "missing"} ${observation.unit}\n${observation.validity}`,
      `${original.value ?? "missing"} ${original.unit}`,
      `${original.observed_at}\n${original.received_at}`,
      `${observation.source_id} / ${observation.source_record_id}\n${observation.transformations.join(" → ") || "No transformation"}`,
    ]) tr.append(node("td", value));
    body.append(tr);
  }
  table.append(caption, head, body); container.append(table);
}
function evidenceChip(id: string, label = id): HTMLButtonElement {
  return button(label, () => { void inspectEvidence(id); }, `chip rule${id === selectedEvidenceId ? " selected" : ""}`);
}
async function inspectEvidence(id: string): Promise<void> {
  if (!pinVisibleWindow() || !selectedWindow) return;
  selectedEvidenceId = id;
  const item = selectedWindow.evidence[id];
  const claim = selectedWindow.claims[id];
  const detail = box("evidence-detail");
  detail.replaceChildren(node("h3", `${claim ? "Claim" : "Evidence"} ${id}`));
  if (item) {
    detail.append(node("p", `${item.kind} · sensor ${item.sensor_id || "network scope"} · channel ${item.channel || "all"}`), node("p", jsonText(item.value)), node("p", `Source window ${selectedWindow.id} / revision ${selectedWindow.revision} / input ${selectedWindow.input_hash}`));
    if (item.sensor_id) {
      selectedSensorId = item.sensor_id;
      await loadSensor();
    }
  } else if (claim) {
    const sensorSource = claim.evidence_ids.map(sourceId => selectedWindow?.evidence[sourceId]).find(source => source?.sensor_id);
    if (sensorSource?.sensor_id) { selectedSensorId = sensorSource.sensor_id; await loadSensor(); }
    detail.append(node("p", `${claim.kind}: ${jsonText(claim.value)}`));
    const chips = node("div", "", "chips");
    chips.append(...claim.evidence_ids.map(sourceId => evidenceChip(sourceId)));
    detail.append(chips, node("p", "Select a source evidence ID to highlight its original sensor and channel."));
  } else {
    detail.append(node("p", "Referenced source is not embedded in this snapshot. No evidence is invented; inspect canonical records or the task’s exact basis."));
    renderRawTable();
  }
  renderMap(); renderEvidenceChips(); switchTab("evidence");
  element("source-audit", HTMLDetailsElement).open = true;
}
function renderEvidenceChips(): void {
  const container = box("evidence-chips");
  container.replaceChildren();
  if (!selectedWindow) return;
  const items = Object.values(selectedWindow.evidence).filter(item => !selectedSensorId || item.sensor_id === selectedSensorId);
  const ids = new Set(items.map(item => item.id));
  const claims = Object.values(selectedWindow.claims).filter(claim => claim.id === selectedEvidenceId
    || claim.evidence_ids.some(id => ids.has(id)));
  for (const claim of claims) container.append(evidenceChip(claim.id, `CLAIM ${claim.kind} / ${claim.id}`));
  for (const item of items) {
    container.append(evidenceChip(item.id, `${item.kind} / ${item.sensor_id || "network"} / ${item.channel || "all"} / ${item.id}`));
  }
  renderInspectionWorkspace();
}
// Coverage is supplied usable/expected samples, not usable/received chart points.
// Domain counts come from the snapshot, stations from pack identities, and queued/
// model-call totals from listed tasks (not an inferred generation budget).
function renderMetrics(): void {
  if (!projection) return;
  const window = selectedWindow;
  text("sample-coverage", window ? `${window.quality.usable_samples} / ${window.quality.expected_samples} · ${(window.quality.coverage * 100).toFixed(1)}%` : "WARMING_UP / not reported");
  text("domain-count", window ? `${window.quality.failure_domains_available} instrument domains available · ${new Set(projection.pack.sensors.map(sensor => sensor.station_id)).size} stations` : "Not reported");
  text("window-state", `${window?.quality.status || "WARMING_UP"}${window ? ` / revision ${window.revision}` : ""}`);
  const queued = projection.tasks.filter(task => task.state === "QUEUED").length;
  const calls = projection.tasks.reduce((sum, task) => sum + task.model_calls, 0);
  text("budget-usage", `${queued} queued · ${calls} model calls in listed tasks · generation model-call limit: unknown · token usage: not reported`);
}
function renderTasks(): void {
  const container = box("task-tree");
  if (!projection) return;
  const focusedId = document.activeElement?.getAttribute("data-task");
  container.replaceChildren();
  const tasks = [...projection.tasks];
  controlButton("view-langfuse").disabled = !tasks.length;
  const renderTask = (task: AgentTask, child = false): void => {
    const card = node("article", "", `task${child ? " child" : ""}`);
    card.append(node("h3", `${agentName(task.role)} · ${task.state}`), node("p", `${short(task.id)} · ${modeName(task.mode)} · basis ${short(task.snapshot_id)}`), node("p", `${task.purpose} · ${task.model_calls} model calls / ${task.tool_calls} tool calls`));
    const open = button(selectedTaskId === task.id ? "Refresh public receipts / trace" : "Inspect public receipts / trace", () => { void loadTask(task.id); });
    open.dataset.task = task.id;
    card.append(open);
    container.append(card);
  };
  for (const root of tasks.filter(task => !task.parent_id || !tasks.some(parent => parent.id === task.parent_id))) {
    renderTask(root);
    const visit = (id: string, visited: Set<string>): void => {
      if (visited.has(id)) return;
      visited.add(id);
      for (const child of tasks.filter(task => task.parent_id === id)) { renderTask(child, true); visit(child.id, visited); }
    };
    visit(root.id, new Set());
  }
  if (!tasks.length) container.append(node("p", "No persisted task yet. Monitoring continues without inference.", "empty"));
  if (focusedId) [...container.querySelectorAll<HTMLButtonElement>("[data-task]")].find(item => item.dataset.task === focusedId)?.focus();
}
/** Join task, report and receipt evidence only within the active generation and task scope. */
async function readTaskDetail(id: string, generation: number): Promise<TaskDetail | null> {
  const detail = await request<TaskDetail>(`/api/tasks/${enc(id)}`);
  if (generation !== generationToken) return null;
  if (detail.task.generation_id !== currentReplayId || detail.task.id !== id
    || detail.children.some(child => child.generation_id !== currentReplayId || child.site_id !== detail.task.site_id || child.parent_id !== id)) throw new Error("Task response scope mismatch.");
  if (detail.casefile && (detail.casefile.task_id !== id || detail.casefile.snapshot_id !== detail.task.snapshot_id)) throw new Error("Investigation handoff scope mismatch.");
  const activityTasks = new Set([detail.task.id, detail.task.root_id,
    ...detail.children.map(child => child.id),
    ...(projection?.tasks.filter(task => task.root_id === detail.task.root_id).map(task => task.id) || [])]);
  if (detail.activity?.some(event => event.generation_id !== currentReplayId
    || event.snapshot_id !== detail.task.snapshot_id || !event.task_id || !activityTasks.has(event.task_id)))
    throw new Error("Agent activity belongs to a different investigation; refusing to combine journals.");
  if (detail.task.role === "operator_response") {
    const basis = windows.find(window => window.id === detail.task.snapshot_id)
      || await request<WindowSnapshot>(`/api/windows/${enc(detail.task.snapshot_id)}`);
    if (generation !== generationToken) return null;
    if (basis.id !== detail.task.snapshot_id || basis.generation_id !== currentReplayId || basis.site_id !== detail.task.site_id) throw new Error("Workflow comparison snapshot scope mismatch.");
    const file = detail.casefile;
    if (file && (file.generation_id !== basis.generation_id || file.input_hash !== basis.input_hash
      || file.pack_version !== basis.pack_version || file.baseline_version !== basis.baseline_version
      || file.parameter_version !== basis.parameter_version || file.mode !== detail.task.mode
      || file.state !== detail.task.state)) throw new Error("Workflow comparison evidence mismatch; refusing an unmatched comparison.");
    if (!windows.some(window => window.id === basis.id)) windows.push(basis);
  }
  return detail;
}
function refreshAutomaticDetail(root: AgentTask): void {
  if (!projection) return;
  const generation = generationToken;
  const key = `${generation}|${root.id}|${projection.tasks.filter(task => task.id === root.id || task.root_id === root.id)
    .map(task => `${task.id}:${task.updated_at}:${task.state}:${task.model_calls}:${task.tool_calls}`).join("|")}|${events.filter(event => ["model.completed", "mapping.completed"].includes(event.type)).slice(-1)[0]?.id || 0}`;
  if (automaticReading || automaticReadKey === key) return;
  automaticReadKey = key; automaticReading = true; automaticReadError = null;
  void readTaskDetail(root.id, generation).then(detail => {
    if (generation === generationToken && detail) automaticDetail = detail;
  }).catch((error: unknown) => {
    if (generation === generationToken) { automaticDetail = null; automaticReadError = errorMessage(error); }
  }).finally(() => {
    automaticReading = false;
    if (projection) { renderAutomaticInvestigation(); renderMap(); }
  });
}
async function loadTask(id: string, focus = true): Promise<void> {
  const changed = selectedTaskId !== id;
  selectedTaskId = id;
  if (changed) { taskDetail = null; renderAnswer(); }
  const token = ++taskToken, generation = generationToken;
  box("trace-view").replaceChildren(node("p", "Loading Langfuse run for the selected investigation...", "muted"));
  if (focus) {
    switchTab("live");
    element("investigation-technical", HTMLDetailsElement).open = true;
  }
  try {
    const detail = await readTaskDetail(id, generation);
    if (!detail || token !== taskToken || generation !== generationToken) return;
    taskDetail = detail;
    renderMap();
    renderTaskDetail();
    renderAnswer();
    if (focus) box("answer-preview").scrollIntoView({ block: "start" });
    try {
      const trace = await request<Record<string, Json>>(`/api/tasks/${enc(id)}/trace`);
      if (token === taskToken && generation === generationToken) renderTrace(trace);
    } catch (error) {
      if (token === taskToken && generation === generationToken) box("trace-view").replaceChildren(node("p", `Trace unavailable: ${errorMessage(error)}. Task result remains visible.`, "summary"));
    }
  } catch (error) {
    if (token === taskToken && generation === generationToken) {
      box("trace-view").replaceChildren(node("p", `Trace unavailable: ${errorMessage(error)}.`, "summary"));
      showError(error);
    }
  }
}
function renderTaskDetail(): void {
  if (!taskDetail) return;
  const { task, children, receipts } = taskDetail;
  const container = box("task-detail");
  container.replaceChildren(node("h3", `Public investigation ${task.id}`));
  container.append(node("p", `State ${task.state} · ${modeName(task.mode)} · pinned basis ${task.snapshot_id}`, "summary"));
  container.append(button("Open this task’s immutable evidence basis", () => { void chooseWindow(task.snapshot_id).then(() => switchTab("evidence")); }));
  for (const child of children) container.append(button(`${agentName(child.role)} / ${child.state} / ${short(child.id)}`, () => { void loadTask(child.id); }));
  if (task.result) {
    container.append(node("p", `Backend accepted result: ${task.result.outcome}. ${task.result.summary}`, "task-result"));
    const chips = node("div", "", "chips");
    for (const id of [...task.result.claim_refs, ...task.result.evidence_ids]) chips.append(button(id, () => {
      void chooseWindow(task.snapshot_id).then(() => inspectEvidence(id));
    }, "chip rule"));
    container.append(chips);
    if (task.result.limitations.length) container.append(node("p", `Limitations: ${task.result.limitations.join("; ")}`, "summary"));
  } else container.append(node("p", "No accepted result. In-flight, failed or abstained work is not an approval.", "muted"));
  if (task.answer) container.append(node("p", task.answer, "task-result"));
  if (task.error_code || task.error_message) container.append(node("p", `${task.error_code || "Agent error"}: ${task.error_message || ""}`, "summary"));
  const history = node("section", "", "history-investigation");
  history.id = "history-investigation";
  history.append(node("h3", "Observe → investigate → check"));
  if (task.result?.investigation) {
    const review = task.result.investigation;
    history.append(node("p", `${friendly(review.assessment)} · next: ${friendly(review.next_action)}`, "summary"));
    history.append(node("p", "Executed evidence checks and operating records. Operating changes can coexist with a leak.", "muted"));
  } else history.append(node("p", "No accepted history review yet. Recorded numerical evidence is not a completed investigation.", "muted"));
  const historyReceipts = [...taskDetail.investigation_receipts].sort((a, b) => {
    const left = plainObject(a.result) ? a.result : null;
    const right = plainObject(b.result) ? b.result : null;
    return Number(left?.investigation_step || 0) - Number(right?.investigation_step || 0);
  });
  for (const receipt of historyReceipts) {
    const result = plainObject(receipt.result) ? receipt.result : null;
    const args = plainObject(receipt.arguments) ? receipt.arguments : null;
    const item = node("details", "", "public-record");
    item.append(node("summary", `${String(receipt.name)} · ${String(args?.intent || "not reported")} · ${receipt.error ? `ERROR ${String(receipt.error)}` : "executed"}`));
    item.append(node("p", `Arguments: ${jsonText(receipt.arguments)}`));
    if (result) item.append(node("pre", jsonText(result)));
    history.append(item);
  }
  container.append(history);
  container.append(node("h3", `Public tool / validation receipts (${receipts.length})`));
  if (!receipts.length) container.append(node("p", "No public receipt available. No completed verification is inferred from animation or task role.", "muted"));
  for (const receipt of receipts) {
    const summary = publicReceiptFields.filter(key => key in receipt).map(key => `${key}: ${jsonText(receipt[key])}`);
    const result = receipt.result;
    if (result && typeof result === "object" && !Array.isArray(result)) {
      for (const key of ["status", "outcome", "validation", "claim_refs", "evidence_ids"]) {
        if (key in result) summary.push(`result.${key}: ${jsonText(result[key])}`);
      }
    }
    container.append(node("div", summary.join("\n") || "Receipt exists; no supported public summary fields reported.", "public-record"));
  }
}
function renderTrace(trace: Record<string, Json>): void {
  const container = box("trace-view");
  container.replaceChildren(node("h3", "Langfuse run"));
  try {
    const sessionUrl = investigationViewerUrl(trace);
    if (sessionUrl) {
      const sessionLink = node("a", "Open whole investigation in Langfuse ↗");
      sessionLink.href = sessionUrl.href;
      sessionLink.target = "_blank"; sessionLink.rel = "noopener noreferrer";
      container.append(sessionLink, node("p", trace.trace_layout === "investigation-v1"
        ? "One investigation trace contains the agent handoffs, resumptions, model calls and tool checks."
        : "This legacy investigation session groups separately recorded agent traces and attempts.", "muted"));
    }
  } catch {
    container.append(node("p", "Investigation link withheld: only valid session IDs and same-origin or loopback HTTP(S) trace links are allowed.", "muted"));
  }
  container.append(node("p", trace.stored_trace_visible === true
    ? "Stored trace verified in Langfuse."
    : trace.stored_trace_visible === false
      ? "Stored trace could not be verified. Export acknowledgement does not prove storage."
      : "Stored trace not yet verified; an active run may still be exporting.", "muted"));
  const metadata = node("details");
  metadata.append(node("summary", "Public trace metadata"), node("div", publicTraceFields.filter(key => key in trace && key !== "url" && key !== "langfuse_url").map(key => `${key}: ${jsonText(trace[key])}`).join("\n") || "Trace metadata not reported", "public-record"));
  container.append(metadata);
  const rawUrl = trace.langfuse_url || trace.url;
  if (typeof rawUrl === "string") {
    try {
      const url = localViewerUrl(rawUrl);
      const link = node("a", "Open this agent attempt in Langfuse ↗");
      link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; metadata.append(link);
    } catch { container.append(node("p", "Viewer link withheld: only same-origin or loopback HTTP(S) trace links are allowed.", "muted")); }
  } else container.append(node("p", "Langfuse viewer link not reported. Export acknowledgement is not proof of a stored trace.", "muted"));
}
// Present persisted answer/check results; acceptance is a backend contract and review
// outcome, not a browser assertion that the engineering conclusion is physically true.
function renderAnswer(): void {
  const selected = taskDetail?.task || projection?.tasks.find(item => item.id === selectedTaskId);
  const explicit = selected?.role === "operator_response" ? selected : null;
  const task = explicit || [...(projection?.tasks || [])]
    .filter(item => item.role === "operator_response" && item.snapshot_id === selectedWindow?.id && (item.answer || item.result))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const container = box("answer-preview");
  container.replaceChildren();
  delete container.dataset.snapshot;
  if (!task) { container.append(node("p", "No accepted answer loaded. Real numerical monitoring does not wait for hosted inference.")); return; }
  container.dataset.snapshot = task.snapshot_id;
  const basis = windows.find(window => window.id === task.snapshot_id) || (selectedWindow?.id === task.snapshot_id ? selectedWindow : null);
  const newer = projection?.latest_window?.id !== task.snapshot_id;
  container.append(node("strong", `Assessment as of ${basis ? time(basis.window_end) : `snapshot ${task.snapshot_id}`}`));
  const terminal = !["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(task.state);
  if (selectedWindow?.id !== task.snapshot_id) container.append(node("p", "Historical task explicitly selected: this answer does not match the visible window. Open its exact basis before using it.", "summary"));
  container.append(node("p", newer ? "Newer monitoring evidence is available. This answer has not been silently rebased." : "Answer basis matches the current monitoring snapshot."));
  const handoff = taskDetail?.task.id === task.id ? taskDetail.casefile : null;
  const workflowAudit = node("details", "", "workflow-audit");
  workflowAudit.append(node("summary", "Monitoring and agent-work comparison"));
  workflowAudit.append(node("p", `${modeName(task.mode)} · ${task.state}. Analysis queued: ${time(task.created_at)}. ${terminal ? "Result recorded" : "Last task update"}: ${time(task.updated_at)}. These are actual processing timestamps, not the simulated sensor clock.`, "answer-timestamps"));
  if (basis && projection) renderWorkflowComparison(workflowAudit, basis, task, handoff, projection.replay.scenario, () => {
    void chooseWindow(task.snapshot_id).then(() => {
      if (selectedWindow?.id === task.snapshot_id) switchTab("live");
    });
  });
  if (handoff) renderCasefile(container, handoff, {
    claim: id => { void chooseWindow(task.snapshot_id).then(() => inspectEvidence(id)); },
  });
  container.append(workflowAudit);
  if (task.answer) {
    const full = node("details", "", "checked-answer");
    full.append(node("summary", "Full recorded answer and checked evidence"), node("p", task.answer));
    container.append(full);
  } else container.append(node("p", "No accepted operator answer; investigation pending or failed."));
  if (task.result?.limitations.length) workflowAudit.append(node("p", `Limitations: ${task.result.limitations.join("; ")}`));
  container.append(button("Open investigation handoff and exact evidence basis", () => { void loadTask(task.id); }));
}
async function createReplay(): Promise<void> {
  const scenario = select("scenario").value, seed = Number(input("seed").value);
  const mode: Mode = "live";
  const workflow: Workflow = select("workflow").value === "sensor_alerts" ? "sensor_alerts" : "agent_assisted";
  if (!scenario || !Number.isSafeInteger(seed) || input("seed").value === "") { notify("Choose a scenario and enter an integer seed.", true); return; }
  const bodyKey = JSON.stringify([scenario, seed, mode, workflow]);
  if (createRetry?.bodyKey !== bodyKey) createRetry = { bodyKey, id: crypto.randomUUID() };
  commandBusy = true; updateControls();
  try {
    const replay = await request<ReplaySession>("/api/replays", { scenario, seed, mode, workflow, idempotency_key: createRetry.id });
    createRetry = null;
    replays.unshift(replay);
    await chooseReplay(replay.id, false);
    notify("New generation created. Prior generations, evidence and tasks remain preserved; press Play to start ingestion.");
  } catch (error) { showError(error); }
  finally { commandBusy = false; updateControls(); }
}
// Retry identities survive transport failures so replay controls are not applied twice.
async function command(action: "play" | "pause" | "step" | "speed", speed?: Speed): Promise<void> {
  if (action === "speed" && speed && liveSelection !== null) {
    playback.setSpeed(speed); renderProjection(); return;
  }
  if (playback.enabled) {
    if (action === "play") playback.play();
    else if (action === "pause") { playback.stop(); renderProjection(); }
    else if (action === "step") playback.seek(playback.seconds + 5);
    else if (speed) { playback.setSpeed(speed); renderProjection(); }
    return;
  }
  if (!projection || !currentReplayId || commandBusy) return;
  const id = currentReplayId, token = generationToken;
  const stepSeconds = action === "step" ? projection.replay.speed : undefined;
  const bodyKey = JSON.stringify([id, action, speed, stepSeconds]);
  if (controlRetry?.bodyKey !== bodyKey) controlRetry = { bodyKey, id: crypto.randomUUID() };
  commandBusy = true; updateControls();
  try {
    const replay = await request<ReplaySession>(`/api/replays/${enc(id)}/control`, {
      action, ...(speed ? { speed } : {}),
      ...(stepSeconds !== undefined ? { step_seconds: stepSeconds } : {}),
      idempotency_key: controlRetry.id,
    });
    controlRetry = null;
    if (token !== generationToken) return;
    if (replay.id !== id) throw new Error("Replay command returned a different generation.");
    if (projection && replay.version >= projection.replay.version) projection.replay = replay;
    renderProjection();
    notify(action === "pause" ? "Source ingestion paused. Already running agent work is not cancelled." : `Server accepted ${action}${speed ? ` ${speed}×` : ""}. Clock values remain server-owned.`);
    void refreshProjection();
  } catch (error) { showError(error); }
  finally { commandBusy = false; updateControls(); }
}
controlButton("view-langfuse").addEventListener("click", () => {
  const task = projection?.tasks.find(item => item.id === selectedTaskId)
    || automaticRoot()
    || [...projection?.tasks || []].filter(item => !item.parent_id)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  if (task) {
    switchTab("live");
    element("investigation-technical", HTMLDetailsElement).open = true;
    void loadTask(task.id, false).then(() => box("trace-view").scrollIntoView({ block: "center" }));
  }
});
bindTabs();
element("login-form", HTMLFormElement).addEventListener("submit", event => {
  event.preventDefault();
  const password = input("password").value;
  const submit = element("login-form", HTMLFormElement).querySelector<HTMLButtonElement>("button");
  if (submit) submit.disabled = true;
  void request<Session>("/api/login", { username: "operator", password }).then(async data => {
    session = data; input("password").value = ""; updateSession();
    if (session.authenticated) { await loadCatalog(); notify("Signed in. Choose a preserved replay or create a new generation."); }
    else notify("Sign-in was not accepted.", true);
  }).catch(showError).finally(() => { if (submit) submit.disabled = false; });
});
controlButton("create-replay").addEventListener("click", () => { void createReplay(); });
controlButton("investigate-live-here").addEventListener("click", () => {
  if (!recordedAnchor && currentReplayId) {
    recordedAnchor = { id: currentReplayId, seconds: timelineSeconds(), speed: playback.speed };
  }
  liveSelection = timelineSeconds();
  void playback.investigate(liveSelection);
});
controlButton("investigation-mode").addEventListener("click", () => {
  void switchInvestigationMode().catch(showError);
});
controlButton("load-recording").addEventListener("click", () => {
  void loadScenarioRecording().catch(showError);
});
input("investigation-time").addEventListener("input", () => {
  const seconds = Number(input("investigation-time").value);
  if (playback.enabled) playback.seek(seconds);
  else {
    liveSelection = seconds;
    sourceHistory = false;
    if (recordedAnchor) recordedAnchor.seconds = seconds;
    renderProjection();
  }
});
controlButton("compare-sensors").addEventListener("click", () => { void compareSensors(); });
controlButton("clear-comparison").addEventListener("click", () => { comparisonSensorIds.clear(); renderSensorList(); });
select("scenario").addEventListener("change", updateControls);
select("map-focus").addEventListener("change", () => { mapSegment = select("map-focus").value; renderMap(); });
controlButton("play").addEventListener("click", () => {
  void command((playback.enabled ? playback.playing : projection?.replay.state === "PLAYING") ? "pause" : "play");
});
controlButton("step-back").addEventListener("click", () => moveTime(-1));
controlButton("step").addEventListener("click", () => moveTime(1));
select("speed").addEventListener("change", () => {
  const value = Number(select("speed").value);
  if (value === 1 || value === 2 || value === 5 || value === 10 || value === 20 || value === 30) void command("speed", value);
});
select("window-history").addEventListener("change", () => { void chooseWindow(select("window-history").value); });
select("inspection-pipeline").addEventListener("change", () => {
  const chosen = select("inspection-pipeline").value;
  pinVisibleWindow();
  inspectionPipeline = chosen;
  const sensor = projection?.pack.sensors.find(item => item.channels.includes("pressure")
    && (!inspectionPipeline || item.segment_id === inspectionPipeline));
  if (sensor) selectSensor(sensor.id);
});
select("inspection-sensor").addEventListener("change", () => {
  const chosen = select("inspection-sensor").value;
  pinVisibleWindow(); selectSensor(chosen);
});
select("inspection-peer").addEventListener("change", () => {
  inspectionPeerId = select("inspection-peer").value || null; inspectionPeerToken++;
  inspectionPeerKey = null; inspectionPeer = null; inspectionPeerError = null; inspectionPeerLoading = false;
  renderInspectionWorkspace();
});
controlButton("follow-live").addEventListener("click", () => { void chooseWindow(""); });
controlButton("inspect-raw").addEventListener("click", () => {
  if (!pinVisibleWindow()) { notify("No completed window to inspect.", true); return; }
  switchTab("evidence");
  text("evidence-detail", selectedSensorId ? `${selectedSensorId} / pinned window ${selectedWindow?.id}. Original records and transformations are available below.` : "Choose a sensor to inspect its original observations.");
});
controlButton("reconnect").addEventListener("click", () => {
  automaticReadKey = null; automaticReadError = null;
  if (!session.authenticated) { void initialize(); return; }
  if (currentReplayId) {
    closeStream();
    const id = currentReplayId, token = generationToken;
    setConnection("Manual projection resync");
    void refreshProjection().then(() => { if (token === generationToken) connectStream(id, token); });
  } else void loadCatalog().then(() => notify("Catalog refreshed. Choose a preserved replay or create a generation.")).catch(showError);
});
document.addEventListener("visibilitychange", () => { if (!document.hidden && currentReplayId) void refreshProjection(); });
window.addEventListener("beforeunload", closeStream);
setInterval(() => {
  renderMonitoringWarning();
  renderClocks();
  executionMetrics.tick();
}, 250);
setInterval(() => { if (activeTab === "evaluation" && session.authenticated) void loadEvaluation(); }, 5000);
updateControls();
void initialize();
