import { box, bounds, button, element, friendly, node, svg, text, time } from "./dom";
import { renderCharts } from "./charts";
import { renderCasefile, renderWorkflowComparison } from "./casefile";
import { renderAgentActivity, renderAgentWork, renderIdleAgentWork } from "./agentwork";
import type { AgentTask, CanonicalObservation, ConsoleEvent, InvestigationCase, Json, Mode, MonitoringEpisode, Point, Projection, ReplaySession, Sensor, Session, Speed, TaskDetail, WindowSnapshot, Workflow } from "./types";

const select = (id: string): HTMLSelectElement => element(id, HTMLSelectElement);
const input = (id: string): HTMLInputElement => element(id, HTMLInputElement);
const controlButton = (id: string): HTMLButtonElement => element(id, HTMLButtonElement);
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
let observations: CanonicalObservation[] = [];
let sensorLoadingKey: string | null = null;
let sensorLoadedKey: string | null = null;
let displayedSensorId: string | null = null;
let source: EventSource | null = null;
let cursor = 0, generationToken = 0, sensorToken = 0, windowToken = 0, taskToken = 0;
let projectionWork: Promise<void> | null = null;
let projectionDirty = false, commandBusy = false, asking = false;
let feedPaused = false, newEvents = 0;
let events: ConsoleEvent[] = [];
let seenEvents = new Set<number>();
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelay = 2000;
let projectionReceivedAt = 0;
let currentReplayId: string | null = null;
let cursorInitialized = false;
let connectionState = "Not connected";
let questionRetry: { bodyKey: string; id: string } | null = null;
let createRetry: { bodyKey: string; id: string } | null = null;
let controlRetry: { bodyKey: string; id: string } | null = null;
let activeTab = "live";
let comparisonWindowId: string | null = null;
let mapSegment = "";
let comparisonToken = 0;
const comparisonSensorIds = new Set<string>();
const currentSource = "pressure-v3";

const eventTypes = ["replay.investigation_paused", "replay.state", "window.completed", "window.revised", "episode.changed", "task.started", "task.updated", "model.started", "model.completed", "tool.completed", "answer.critique", "answer.checked", "task.finished", "health.changed"];
const publicReceiptFields = ["id", "call_id", "name", "task_id", "tool", "tool_name", "action", "status", "summary", "validation", "outcome", "evidence_ids", "claim_refs", "duration_ms", "error", "error_code", "snapshot_id", "created_at"];
const publicTraceFields = ["trace_id", "span_id", "attempt_id", "session_id", "task_id", "status", "mode", "model", "model_calls", "tool_calls", "usage", "duration_ms", "export_status", "stored", "langfuse_url", "url"];

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
  const held = projection?.replay.investigation_window_id;
  return [...projection?.tasks || []].filter(task => !task.parent_id && (held ? task.snapshot_id === held : task.automatic))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null;
}
function investigationHold(): { waiting: boolean; unavailable: boolean } {
  const held = projection?.replay.investigation_window_id;
  if (!held) return { waiting: false, unavailable: false };
  const roots = projection!.tasks.filter(task => !task.parent_id && task.snapshot_id === held);
  const blocked = projection!.episodes.some(episode => episode.current_window_id === held
    && ["agent_unavailable", "knowledge_unavailable", "budget_blocked"].includes(episode.dispatch_status || ""));
  return {
    waiting: roots.some(task => ["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(task.state)) || !roots.length && !blocked,
    unavailable: blocked || roots.some(task => ["FAILED", "CANCELLED"].includes(task.state)),
  };
}
function renderActivity(): void {
  box("agent-activity").hidden = !projection;
  if (!projection) return;
  const root = automaticRoot();
  renderAgentActivity(root, projection.tasks, events,
    Date.parse(projection.server_time) + Math.max(0, Date.now() - projectionReceivedAt),
    navigator.onLine && connectionState.startsWith("Connected"),
    projection.episodes.some(episode => episode.dispatch_status === "gathering_context"),
    !sensorAlertsOnly());
}
function jsonText(value: Json | undefined): string {
  return value === undefined ? "not reported" : typeof value === "string" ? value : JSON.stringify(value);
}
function plainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
async function request<T>(path: string, body?: object): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  if (body) {
    if (path !== "/api/login" && (!session.authenticated || !session.csrf_token)) throw new Error("Sign in before changing replay state or asking a question.");
    headers.set("Content-Type", "application/json");
    if (path !== "/api/login" && session.csrf_token) headers.set("X-CSRF-Token", session.csrf_token);
  }
  let response: Response;
  try { response = await fetch(path, { method: body ? "POST" : "GET", credentials: "same-origin", headers, body: body ? JSON.stringify(body) : undefined }); }
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
function setConnection(value: string): void { connectionState = value; text("connection-state", value); renderMonitoringWarning(); renderActivity(); }
function updateControls(): void {
  const replay = projection?.replay;
  const allowed = session.authenticated && !commandBusy;
  const hold = investigationHold();
  controlButton("create-replay").disabled = !allowed || !select("scenario").value;
  controlButton("play").disabled = !allowed || !replay || hold.waiting || replay.state === "COMPLETED" || replay.state === "FAILED";
  controlButton("play").textContent = replay?.state === "PLAYING" ? "Pause" : replay?.investigation_window_id
    ? hold.waiting ? "Waiting for agents" : hold.unavailable ? "Continue without report" : "Continue monitoring" : "Play";
  controlButton("step").disabled = !allowed || replay?.state !== "PAUSED" || Boolean(replay.investigation_window_id);
  select("speed").disabled = !allowed || !replay || replay.state === "COMPLETED" || replay.state === "FAILED";
  controlButton("ask-submit").disabled = !session.authenticated || !selectedWindow || asking;
  controlButton("ask-submit").textContent = asking ? "Submitting…" : "Investigate pinned window ↗";
  controlButton("compare-sensors").disabled = !session.authenticated || !selectedWindow;
}
function switchTab(name: string, focus = false): void {
  const tabs = [...document.querySelectorAll<HTMLButtonElement>("[role=tab]")];
  activeTab = name;
  for (const tab of tabs) {
    const selected = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    box(`panel-${tab.dataset.tab}`).hidden = !selected;
    if (selected && focus) tab.focus();
  }
}
function bindTabs(): void {
  const tabs = [...document.querySelectorAll<HTMLButtonElement>("[role=tab]")];
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
    if (!session.authenticated) { notify("Sign in to load the synthetic site, replay generations and scoped evidence."); return; }
    await loadCatalog();
    notify("Connected to local application. Select a preserved generation or explicitly create one.");
  } catch (error) { showError(error); setConnection("API unavailable"); }
}
async function loadCatalog(): Promise<void> {
  const [catalog, history] = await Promise.all([
    request<{ scenarios: { id: string; name: string }[]; questions: string[] }>("/api/scenarios"),
    request<{ replays: ReplaySession[] }>("/api/replays"),
  ]);
  const scenario = select("scenario");
  scenario.replaceChildren(...catalog.scenarios.map(item => new Option(`${item.id} · ${item.name}`, item.id)));
  replays = history.replays;
  renderReplayHistory();
  box("questions").replaceChildren(...catalog.questions.slice(0, 3).map(question => button(question, () => {
    if (!pinVisibleWindow()) { notify("Wait for a completed visible window before asking a question.", true); return; }
    element("question", HTMLTextAreaElement).value = question;
    element("question", HTMLTextAreaElement).focus();
  })));
  updateControls();
}
function renderReplayHistory(): void {
  const history = select("replay-history");
  history.replaceChildren(new Option("Choose preserved generation", ""), ...[...replays].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(replay => {
    const archived = replay.source_version !== currentSource;
    const label = replay.workflow === "sensor_alerts" ? "SENSOR ALERTS ONLY" : `AGENT-ASSISTED · ${modeName(replay.mode)}`;
    const option = new Option(`${archived ? "Archived" : "Saved"} ${replay.scenario} · ${label} · ${time(replay.updated_at)}`, replay.id);
    option.disabled = archived;
    option.title = archived ? "Previous topology/source version; snapshots and audit receipts remain retained." : `${replay.id} · ${replay.source_version}`;
    return option;
  }));
  history.value = currentReplayId || "";
}
function closeStream(): void {
  source?.close(); source = null;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
}
async function chooseReplay(id: string): Promise<void> {
  closeStream();
  currentReplayId = id;
  generationToken++; windowToken++; sensorToken++; taskToken++;
  projection = null; selectedWindow = null; followCurrent = true;
  windows = []; observations = []; sensorLoadingKey = null; sensorLoadedKey = null;
  displayedSensorId = null;
  comparisonSensorIds.clear(); comparisonToken++;
  selectedSensorId = null; selectedEpisodeId = null;
  selectedEvidenceId = null; selectedTaskId = null; taskDetail = null;
  cursor = 0; cursorInitialized = false; events = []; seenEvents = new Set(); newEvents = 0;
  questionRetry = null;
  projectionDirty = true;
  setConnection("Loading coherent projection");
  resetView();
  renderReplayHistory();
  notify("");
  await refreshProjection();
  if (currentReplayId === id && projection) connectStream(id, generationToken);
}
function resetView(): void {
  mapSegment = ""; select("map-focus").value = "";
  automaticDetail = null; automaticReadKey = null; automaticReadError = null;
  delete box("automatic-progress").dataset.renderKey; delete box("automatic-progress").dataset.task;
  box("agent-activity").hidden = true; box("agent-findings").replaceChildren();
  renderMonitoringWarning();
  text("source-clock", "Not reported"); text("server-clock", "Not reported");
  text("clock-basis", "No received telemetry"); text("trend-basis", "No received telemetry");
  for (const id of ["stream-stage", "detector-stage", "agent-stage", "automatic-state"]) text(id, "Awaiting telemetry");
  for (const id of ["automatic-timeline", "automatic-progress", "automatic-actions", "sensor-list"]) box(id).replaceChildren();
  for (const id of ["comparison-charts", "investigation-summary"]) box(id).replaceChildren();
  text("sensor-list-basis", "Awaiting a completed window");
  text("comparison-basis", "Pins the visible window. Up to four histories share UTC time and a common pressure scale.");
  text("automatic-conclusion", "No investigation loaded for this replay.");
  delete box("automatic-state").dataset.task;
  text("live-bounds", "Awaiting telemetry"); text("health-state", "Not reported");
  text("site-name", "Loading site…"); text("event-summary", "Waiting for backend assessment.");
  text("location-summary", ""); text("sensor-title", "Select a sensor"); text("sensor-meta", "No sensor selected");
  box("ontology").replaceChildren(); box("episodes").replaceChildren();
  box("gate-content").replaceChildren(node("p", "Awaiting immutable claims.", "muted"));
  box("channel-charts").replaceChildren(node("p", "No observations loaded.", "empty"));
  box("evidence-detail").replaceChildren(node("p", "No evidence selected."));
  box("evidence-chips").replaceChildren(); box("raw-table").replaceChildren();
  box("task-tree").replaceChildren(); box("task-detail").replaceChildren();
  text("answer-preview", "No accepted answer loaded."); text("episode-count", "—");
  for (const id of ["sample-coverage", "domain-count", "window-state", "budget-usage"]) text(id, "Not reported");
  const map = document.getElementById("topology");
  if (map) delete map.dataset.snapshot;
  delete box("channel-charts").dataset.snapshot;
  map?.replaceChildren(svg("text", { x: 380, y: 185, "text-anchor": "middle" }, "Awaiting site geometry"));
  renderWindowHistory(); renderBasis(); renderFeed(); updateControls();
}
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
        renderReplayHistory();
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
      if (feedPaused) { newEvents++; text("new-events", `${newEvents} new`); }
      else renderFeed();
      void refreshProjection();
    } catch (error) { showError(error); void refreshProjection(); }
  };
  for (const type of eventTypes) stream.addEventListener(type, handle);
  stream.onmessage = handle;
  stream.addEventListener("resync_required", () => {
    if (token !== generationToken) return;
    notify("Event cursor was unavailable. Explicit projection resync; an audit-feed interval may be missing.", true);
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
function isConsoleEvent(value: unknown): value is ConsoleEvent {
  return plainObject(value) && typeof value.id === "number" && Number.isSafeInteger(value.id)
    && typeof value.site_id === "string" && typeof value.generation_id === "string" && typeof value.type === "string"
    && typeof value.created_at === "string" && (value.simulated_seconds === null || typeof value.simulated_seconds === "number")
    && (value.snapshot_id === null || typeof value.snapshot_id === "string") && (value.task_id === null || typeof value.task_id === "string")
    && plainObject(value.payload) && Object.values(value.payload).every(isJson);
}

function renderProjection(): void {
  if (!projection) return;
  const { replay, pack, latest_window: latest, health } = projection;
  text("inference-mode", "EVIDENCE → ENGINEER REVIEW");
  const hold = investigationHold();
  box("investigation-hold").hidden = !replay.investigation_window_id;
  text("investigation-hold", replay.investigation_window_id
    ? `Simulation paused at +${replay.clock_seconds.toFixed(1)}s · evidence ${short(replay.investigation_window_id)}. ${
      hold.waiting ? "Fresh agents are checking this fixed window; simulated ingestion and stepping are locked."
        : hold.unavailable ? "No reviewed agent report is available. Detector alerts remain active; continuing does not clear them."
          : "Agent checks finished. Review the report, then Continue monitoring."} Only the simulation pauses, never a production safety feed.`
    : "");
  text("simulation-policy", "Agent investigations pause the simulated source; recorded runs retain their playback policy.");
  text("site-name", pack.name);
  renderClocks();
  text("live-bounds", latest ? `${bounds(latest.window_start, latest.window_end)} · ${latest.quality.status}` : `WARMING_UP / no completed window · width ${pack.window_seconds}s + lateness ${pack.lateness_seconds}s`);
  text("health-state", `${health.monitor} / ${health.agent} / export: ${jsonText(health.observability.status)} · stored visibility: ${jsonText(health.observability.stored_trace_visibility)}`);
  text("audit-health", `Agent: ${health.agent}. Monitor: ${health.monitor}. Observability: ${Object.entries(health.observability).map(([key, value]) => `${key}=${jsonText(value)}`).join("; ") || "not reported"}. UI connection: ${connectionState}.`);
  select("speed").value = String(replay.speed);
  controlButton("step").textContent = `Step +${pack.hop_seconds}s`;
  renderMonitoringWarning(); renderOntology(); renderEpisodes(); renderBasis(); renderMap(); renderSensorList(); renderAutomaticInvestigation(); renderInvestigation(); renderGate(); renderEvidenceChips(); renderTasks(); renderAnswer(); renderMetrics(); updateControls();
  if (replay.error) notify(`Replay ${replay.state}: ${replay.error}`, true);
}
function renderClocks(): void {
  if (!projection || !projectionReceivedAt) return;
  const { replay, pack } = projection;
  const age = Math.max(0, Date.now() - projectionReceivedAt);
  const current = navigator.onLine && connectionState.startsWith("Connected") && (replay.state !== "PLAYING" || age <= 15000) && projection.health.monitor === "running";
  const seconds = replay.clock_seconds;
  const sourceTime = new Date(Date.parse(replay.epoch) + seconds * 1000).toISOString();
  text("source-clock", `${time(sourceTime)} · +${seconds.toFixed(1)}s · ${friendly(replay.state)} · ${replay.speed}×`);
  box("source-clock").dataset.seconds = String(seconds);
  box("source-clock").dataset.confirmedSeconds = String(replay.clock_seconds);
  text("clock-basis", `${current ? "Server-confirmed source time" : "NOT CURRENT; last confirmed source time"} · ${pack.sample_seconds}s samples / ${pack.hop_seconds}s window hop. No browser-generated telemetry.`);
  text("server-clock", `${time(projection.server_time)} · projection received ${Math.floor(age / 1000)}s ago`);
}
function renderMonitoringWarning(): void {
  const banner = box("monitoring-warning");
  const current = projection, warning = current?.warning;
  let message: string, severity = "warning", kind = "unavailable";
  if (!navigator.onLine || !current || !warning || current.health.monitor !== "running" || (current.replay.state === "PLAYING" && Date.now() - projectionReceivedAt > 15000) || !connectionState.startsWith("Connected")) {
    message = `MONITORING NOT CURRENT: verify the monitoring connection. ${warning ? `Last recorded assessment: ${warning.title}. ${warning.message}` : "No current assessment."} Do not treat unavailable monitoring as safety clearance.`;
  } else {
    message = `${warning.title}. ${warning.message}`;
    severity = warning.severity; kind = warning.kind;
  }
  if (banner.textContent !== message) banner.textContent = message;
  banner.className = `monitoring-warning ${severity}`;
  banner.dataset.kind = kind;
  banner.dataset.snapshot = warning?.snapshot_id || "";
  banner.title = `Latest numerical monitoring window: ${current?.latest_window?.window_end || "warming up"}. Independent of selected historical evidence and AI analysis.`;
}
function renderOntology(): void {
  if (!projection) return;
  const pack = projection.pack;
  const chips = box("ontology");
  chips.replaceChildren();
  for (const segment of pack.segments) chips.append(button(`PIPELINE ${segment.id}`, () => {
    selectedEvidenceId = null;
    text("evidence-detail", `Pipeline ${segment.id} · ${segment.length_m} m · pack ${pack.version}. Geometry is synthetic, not a surveyed asset.`);
    switchTab("evidence");
  }, "chip entity"));
  chips.append(button(`PACK ${pack.version}`, () => {
    text("evidence-detail", `${pack.name} / ${pack.version}. ${pack.sensors.length} declared sensors. Sample ${pack.sample_seconds}s; width ${pack.window_seconds}s; hop ${pack.hop_seconds}s; lateness ${pack.lateness_seconds}s. Minimum observers ${pack.min_observers}; minimum independent domains ${pack.min_failure_domains}; minimum usable coverage ${pack.min_coverage}.`);
    switchTab("evidence");
  }, "chip policy"));
  if (selectedWindow) {
    chips.append(button(selectedWindow.event.criteria_id, () => showCriteria(), "chip rule"));
    if (selectedWindow.location) chips.append(button(selectedWindow.location.method, () => showCriteria(), "chip method"));
  }
}
function showCriteria(): void {
  if (!pinVisibleWindow() || !selectedWindow) return;
  text("evidence-detail", `Criteria ${selectedWindow.event.criteria_id}; ${selectedWindow.location?.method || "location not computed"}. Hypotheses eligible: ${selectedWindow.event.eligible_hypotheses.join(", ")}. Counterevidence: ${selectedWindow.event.counterevidence.join("; ") || "none recorded"}. Claims below are application-owned. This is not calibrated confidence.`);
  switchTab("evidence");
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
  box("evidence-selection").dataset.following = String(followCurrent);
  box("evidence-selection").dataset.updating = String(Boolean(newer));
  box("evidence-selection").dataset.snapshotId = window?.id || "";
  text("selected-basis", window ? `${followCurrent ? "CURRENT VIEW" : "PINNED"} · ${bounds(window.window_start, window.window_end)} · revision ${window.revision}` : "No completed window selected");
  text("basis-warning", newer ? followCurrent
    ? `${held ? "Loading the paused investigation window." : "Live inspector updating."} Map and trend retain one coherent received window; the latest warning remains independent.`
    : "Historical evidence pinned. Newer monitoring telemetry is available; this inspector will not change."
    : held ? "Simulation paused for investigation. Map and trend show fixed received evidence; inspecting it does not resume the source."
      : followCurrent ? "Following current telemetry. Trends stay live; comparisons, raw evidence and questions pin this snapshot." : "Visible snapshot pinned. Stream continues independently.");
  text("sensor-list-basis", window ? `${time(window.window_end)} · ${followCurrent ? "following stream" : "pinned review"}` : "Awaiting a completed window");
  text("ask-basis", window ? `AS OF ${time(window.window_end)} / R${window.revision}` : "PINNED SNAPSHOT REQUIRED");
  text("question-scope", window ? `${modeName(projection?.replay.mode || "scripted")} · ${short(window.id)} · questions never use a hidden later snapshot` : "No visible snapshot");
  if (window && sensorLoadedKey === JSON.stringify([window.id, selectedSensorId])) {
    text("trend-basis", `${followCurrent ? "LIVE TREND" : "PINNED TREND"} · window ending ${time(window.window_end)}`);
  }
  updateControls();
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
function episode(): MonitoringEpisode | undefined { return projection?.episodes.find(item => item.id === selectedEpisodeId); }
function renderEpisodes(): void {
  if (!projection) return;
  const list = box("episodes");
  list.replaceChildren();
  text("episode-count", String(projection.episodes.length));
  for (const item of projection.episodes) {
    const entry = button("", () => {
      selectedEpisodeId = item.id;
      void chooseWindow(item.current_window_id).then(() => { renderEpisodes(); renderMap(); });
    }, item.id === selectedEpisodeId ? "selected" : "");
    entry.append(node("strong", friendly(item.hypothesis)), node("span", `${item.state} / material r${item.material_revision}`), node("span", `${item.segment_ids.join(", ") || "Location withheld"} · ${short(item.id)}`), node("span", `${item.dispatch_status || "No dispatch status"}${item.pending_window_id ? " · newer basis pending" : ""}`));
    list.append(entry);
  }
  if (!projection.episodes.length) list.append(node("p", "No episode recorded in this generation.", "empty"));
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
  const findings = window?.quality.findings.filter(finding => finding.sensor_id === id) || [];
  const assessed = Boolean(window && window.quality.status !== "WARMING_UP" && findings.length);
  return {
    assessed,
    missing: assessed && findings.some(finding => finding.missing > 0 || finding.hard_excluded > 0),
    anomaly: assessed && findings.some(finding => finding.anomaly_count > 0),
    support: assessed && Boolean(reviewedCaseForWindow()?.interpretation?.regional_assessments?.some(
      region => region.hypothesis === "leak_pattern" && region.sensor_ids.includes(id))),
  };
}
function renderMap(): void {
  if (!projection) return;
  const map = document.getElementById("topology");
  if (!(map instanceof SVGSVGElement)) return;
  const focusedId = document.activeElement?.getAttribute("data-sensor");
  const { pack } = projection;
  const window = selectedWindow;
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
  const points = [...sensors.map(sensor => sensor.position), ...segments.flatMap(segment => segment.points)];
  if (!points.length) return;
  const xmin = Math.min(...points.map(point => point.x)), xmax = Math.max(...points.map(point => point.x));
  const ymin = Math.min(...points.map(point => point.y)), ymax = Math.max(...points.map(point => point.y));
  const scale = Math.min(650 / Math.max(xmax - xmin, 1), 390 / Math.max(ymax - ymin, 1));
  const project = (point: Point): Point => ({ x: 55 + (point.x - xmin) * scale + (650 - (xmax - xmin) * scale) / 2, y: 65 + (ymax - point.y) * scale + (390 - (ymax - ymin) * scale) / 2 });
  map.replaceChildren(svg("title", {}, "Synthetic pipeline network; detector flags and reviewed agent patterns encoded separately"));
  for (let xx = 40; xx < 760; xx += 40) map.append(svg("line", { x1: xx, y1: 30, x2: xx, y2: 490, stroke: "var(--grid)", "stroke-width": 1 }));
  for (let yy = 30; yy < 510; yy += 40) map.append(svg("line", { x1: 30, y1: yy, x2: 730, y2: yy, stroke: "var(--grid)", "stroke-width": 1 }));
  for (const segment of segments) {
    const coords = segment.points.map(project);
    map.append(svg("polyline", { points: coords.map(point => `${point.x},${point.y}`).join(" "), class: "pipe", "data-segment-id": segment.id }));
    const label = segment.id === "P1" ? coords[0] : coords[coords.length - 1];
    if (label) map.append(svg("text", { x: label.x, y: label.y + (segment.id === "P1" ? 30 : -25), "text-anchor": "middle" }, extended && !mapSegment ? segment.id : `${segment.name} / ${segment.id} / ${segment.length_m}m`));
  }
  const review = reviewedCaseForWindow();
  const inspection = review?.inspection;
  const location = inspection && window?.location?.status === "located"
    && window.location.best?.segment_id === inspection.segment_id
    && window.location.inspection_start_m === inspection.start_m
    && window.location.inspection_end_m === inspection.end_m ? window.location : null;
  if (location?.status === "located" && location.best && location.inspection_start_m !== null && location.inspection_end_m !== null) {
    const segment = segments.find(item => item.id === location.best?.segment_id);
    if (segment) {
      const start = project(segment.points[0]), end = project(segment.points[segment.points.length - 1]);
      const at = (chainage: number): string => {
        const fraction = chainage / segment.length_m;
        return `${start.x + (end.x - start.x) * fraction},${start.y + (end.y - start.y) * fraction}`;
      };
      map.append(svg("polyline", { points: `${at(location.inspection_start_m)} ${at(location.inspection_end_m)}`, class: "inspection-interval", "data-segment-id": segment.id, "data-start-m": location.inspection_start_m, "data-end-m": location.inspection_end_m }));
    }
  }
  for (const candidate of location?.compatible || []) {
    if (mapSegment && candidate.segment_id !== mapSegment) continue;
    const pos = project(candidate.position);
    const ring = svg("rect", { x: pos.x - 8, y: pos.y - 8, width: 16, height: 16, transform: `rotate(45 ${pos.x} ${pos.y})`, class: "candidate" });
    ring.append(svg("title", {}, `Inspection interval boundary: ${candidate.segment_id}, ${candidate.chainage_m}m; not a leak coordinate`));
    map.append(ring);
  }
  for (const [index, sensor] of sensors.entries()) {
    const position = project(sensor.position);
    let stationPosition = { ...position };
    const segment = pack.segments.find(item => item.id === sensor.segment_id);
    if (sensor.channels.includes("pressure") && segment) {
      const a = project(segment.points[0]), b = project(segment.points[segment.points.length - 1]);
      const length = Math.hypot(b.x - a.x, b.y - a.y);
      if (length > 0) {
        const side = sensor.id.endsWith("-A") ? -1 : 1;
        const fraction = sensor.chainage_m / segment.length_m;
        stationPosition = { x: a.x + (b.x - a.x) * fraction, y: a.y + (b.y - a.y) * fraction };
        position.x = stationPosition.x - side * (b.y - a.y) / length * 11;
        position.y = stationPosition.y + side * (b.x - a.x) / length * 11;
      }
    }
    const flags = sensorFlags(window, sensor.id);
    const { missing, support } = flags;
    const selected = selectedSensorId === sensor.id || evidence?.sensor_id === sensor.id;
    const health = !flags.assessed ? "Not assessed" : `${missing ? "Missing value: absent or excluded readings" : "Usable coverage"}${flags.anomaly ? "; pressure anomaly" : ""}`;
    const group = svg("g", { class: `sensor${!flags.assessed ? " unknown" : ""}${flags.anomaly ? " anomalous" : ""}${missing ? " missing" : ""}${support ? " support" : ""}${selected ? " selected" : ""}`, role: "button", tabindex: 0, "aria-label": `${sensor.id}, ${sensor.segment_id}, ${sensor.chainage_m}m. ${health}. ${support ? "Agent-reviewed pressure pattern; cause unconfirmed." : "No agent-reviewed pattern recorded."}`, "aria-pressed": String(selectedSensorId === sensor.id), "data-sensor": sensor.id });
    if (support) group.append(svg("rect", { x: position.x - 11, y: position.y - 11, width: 22, height: 22, transform: `rotate(45 ${position.x} ${position.y})`, class: "support-ring" }));
    group.append(svg("circle", { cx: position.x, cy: position.y, r: 6, class: "sensor-dot" }));
    if (selected) group.append(svg("circle", { cx: position.x, cy: position.y, r: 10, class: "selection-ring" }));
    const labelOnLeft = sensor.segment_id === "P2" || sensor.segment_id === "P4";
    if ((!extended || mapSegment || selected || support) && sensor.id.endsWith(labelOnLeft ? "-B" : "-A")) {
      group.append(svg("text", { x: stationPosition.x + (labelOnLeft ? -27 : 27), y: stationPosition.y + 4,
        "text-anchor": labelOnLeft ? "end" : "start", class: "station-label" }, `${sensor.station_id} A/B`));
    }
    group.append(svg("title", {}, `${sensor.id} / ${sensor.station_id} / domain ${sensor.failure_domain_id}. ${health}`));
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
  for (const [key, selector] of [["support", ".support-ring"], ["inspection", ".inspection-interval"]] as const) {
    const legend = box("map-legend").querySelector<HTMLElement>(`[data-legend="${key}"]`);
    if (legend) legend.hidden = !map.querySelector(selector);
  }
  const count = pack.sensors.filter(sensor => {
    const flags = sensorFlags(window, sensor.id);
    return flags.anomaly || flags.missing;
  }).length;
  text("event-summary", window ? `${count} instruments with pressure anomalies or missing values in this window. These observations alone do not establish cause or location.` : "No completed assessment. Warm-up is not a normal-pipeline verdict.");
  text("location-summary", location?.status === "located"
    ? `Agent-reviewed priority inspection: ${location.best?.segment_id || "unresolved"} ${location.inspection_start_m}–${location.inspection_end_m}m. Not an exact leak point.`
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
function renderAutomaticInvestigation(): void {
  if (!projection) return;
  renderActivity();
  const { replay, latest_window: latest, pack } = projection;
  text("stream-stage", `${replay.state} · received through +${replay.clock_seconds.toFixed(1)}s · ${pack.sensors.length} instruments`);
  text("detector-stage", latest ? `Pressure / quality screening · window ends +${latest.end_seconds}s` : `Warming up · ${pack.window_seconds}s window / ${pack.hop_seconds}s hop`);
  const root = automaticRoot();
  const timeline = box("automatic-timeline"), progress = box("automatic-progress"), actions = box("automatic-actions");
  const focusedAction = actions.contains(document.activeElement) && document.activeElement instanceof HTMLButtonElement
    ? document.activeElement.dataset.action : undefined;
  timeline.replaceChildren(); actions.replaceChildren();
  const incident = root ? projection.episodes.find(item => item.id === root.episode_id) : projection.episodes[0];
  const unavailable = incident?.pending_window_id && incident.dispatch_status && incident.dispatch_status !== "queued"
    ? friendly(incident.dispatch_status) : null;
  if (!root) {
    renderIdleAgentWork(progress, box("agent-findings"), !sensorAlertsOnly());
    if (incident?.dispatch_status === "gathering_context") {
      text("agent-stage", "Evidence triage · collecting unresolved context");
      text("automatic-state", "TRIAGE · NOT AN LLM REPORT");
      const boundary = new Date(Date.parse(replay.epoch) + (incident.first_seen_seconds + pack.window_seconds) * 1000).toISOString();
      const item = node("div");
      item.append(node("small", "UNRESOLVED-ONLY REVIEW BOUNDARY / SOURCE UTC"), node("strong", time(boundary)));
      timeline.append(item);
      text("automatic-conclusion", `Unresolved pattern: collect at most one ${pack.window_seconds}s source window before admitting this first LLM report. A qualifying leak pattern, sensor/telemetry issue or lost coverage bypasses this hold. Numerical warnings and manual review remain immediate; do not wait for AI.`);
      delete box("automatic-state").dataset.task;
      return;
    }
    const state = sensorAlertsOnly() ? "Agent execution off · no model calls" : unavailable ? `Not queued: ${unavailable}` : "Waiting for a monitoring episode";
    text("agent-stage", state); text("automatic-state", state);
    text("automatic-conclusion", sensorAlertsOnly()
      ? "No agent diagnosis or localization has been produced. The same sensor histories, quality flags, comparisons and evidence remain available for engineer review."
      : unavailable
      ? "No report is available. Numerical warnings and manual investigation remain active; do not treat unavailable analysis as safety clearance."
      : "Anomalies start analysis automatically. Monitoring and manual analysis do not wait for an agent. No healthy-pipeline conclusion is inferred.");
    delete box("automatic-state").dataset.task;
    const buttons = node("div", "", "automatic-action-buttons");
    for (const label of ["Compare with existing workflow", "View investigation"]) {
      const control = button(label, () => {}); control.disabled = true; buttons.append(control);
    }
    actions.append(buttons);
    return;
  }
  box("automatic-state").dataset.task = root.id;
  const accepted = (root.state === "SUCCEEDED" || root.state === "ABSTAINED") && root.result !== null && root.answer !== null;
  const failed = !accepted && !["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(root.state);
  const pending = Boolean(incident?.pending_window_id);
  const state = accepted ? `${modeName(root.mode)} · ${root.state === "ABSTAINED" ? "ABSTENTION" : "REPORT AVAILABLE"}`
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
  renderAgentWork(progress, box("agent-findings"), root, projection.tasks, detail, basis,
    automaticReadError, id => { void loadTask(id); });
  refreshAutomaticDetail(root);
  const conclusion = accepted ? root.result?.interpretation?.answer.text || root.result?.summary || root.answer || ""
    : failed ? `No accepted report: ${root.error_message || root.error_code || friendly(root.state)}. Do not wait for AI to act under existing response procedures.`
      : projection.replay.investigation_window_id
        ? "Investigating the pinned alert evidence. Simulated ingestion is paused while real agent checks run; detector warnings remain active."
        : "Investigating the pinned alert evidence. Sensor ingestion, numerical warnings and manual trends continue independently.";
  text("automatic-conclusion", conclusion);
  const freshness = node("p", `${latest?.id !== root.snapshot_id ? "Historical analysis: newer monitoring evidence exists; this report is not rebased." : "Analysis uses the latest completed monitoring snapshot."}${pending ? ` New material warning is pending${unavailable ? `: ${unavailable}` : " until the active investigation finishes and admission permits"}.` : ""}`, "muted");
  freshness.id = "automatic-freshness"; actions.append(freshness);
  const open = button(accepted ? "Review evidence" : "View investigation", () => {
    void loadTask(root.id).then(() => box("answer-preview").scrollIntoView({ block: "start" }));
  });
  open.dataset.action = "review";
  const compare = button("Compare with existing workflow", () => {
    void loadTask(root.id).then(() => document.getElementById("workflow-comparison")?.scrollIntoView({ block: "start" }));
  });
  compare.dataset.action = "compare";
  const buttons = node("div", "", "automatic-action-buttons");
  buttons.append(compare, open); actions.append(buttons);
  if (focusedAction) [compare, open].find(item => item.dataset.action === focusedAction)?.focus({ preventScroll: true });
}
function renderInvestigation(): void {
  const container = box("investigation-summary"), window = selectedWindow;
  container.replaceChildren();
  if (comparisonWindowId !== window?.id) {
    comparisonWindowId = null;
    box("comparison-panel").hidden = true;
    box("comparison-charts").replaceChildren();
    text("comparison-basis", "Pins the visible window. Up to four histories share UTC time and a common pressure scale.");
  }
  if (!window || !projection) { container.append(node("p", "Awaiting a completed pressure window. No healthy-pipeline conclusion is inferred.", "empty")); return; }
  const pack = projection.pack;
  const faults = window.quality.findings.filter(f => f.spike_count || f.drift_suspected || f.peer_disagreement || f.hard_excluded || f.missing > f.expected * .1);
  const cards: [string, string][] = [
    ["Pressure and quality evidence", `${window.quality.findings.filter(f => f.anomaly_count > 0).length} instrument histories contain pressure anomalies; ${faults.length} contain quality concerns. Flags are observations, not confirmed hardware faults or leak diagnoses.`],
    ["Coverage and time basis", `${window.quality.usable_samples}/${window.quality.expected_samples} usable readings in ${bounds(window.window_start, window.window_end)}. Missing readings remain unknown; excluded values are not imputed.`],
    ["Joint evidence available", `Compare sensor histories on the same UTC axis and pressure scale. Inspect station chainage and shared gateways across ${pack.sensors.length} instruments; screen timing, magnitude and spatial coherence together.`],
    ["Interpretation boundary", "A leak, operating change and instrumentation problem are competing causes. Numerical screening supplies auditable tool evidence, not a reviewed diagnosis or inspection recommendation. Agents must reconcile joint pressure behavior with knowledge and records; human verification remains required."],
  ];
  for (const [title, body] of cards) {
    const card = node("article"); card.append(node("h3", title), node("p", body)); container.append(card);
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
    const values = results.flatMap(data => data.observations.flatMap(row =>
      row.validity === "usable" && row.value !== null && Date.parse(row.observed_at) >= Date.parse(window.window_start) && Date.parse(row.observed_at) < Date.parse(window.window_end) ? [row.value] : []));
    for (const item of Object.values(window.evidence)) {
      if (item.kind !== "channel_summary" || !item.sensor_id || !ids.includes(item.sensor_id) || !plainObject(item.value)) continue;
      const model = item.value;
      if (typeof model.baseline_median === "number" && typeof model.baseline_scale === "number" && typeof model.anomaly_threshold === "number") {
        values.push(model.baseline_median - model.baseline_scale * model.anomaly_threshold, model.baseline_median + model.baseline_scale * model.anomaly_threshold);
      }
    }
    const range: [number, number] | undefined = values.length ? [Math.min(...values), Math.max(...values)] : undefined;
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
  renderMap(); renderSensorList(); void loadSensor();
}
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
  try {
    const data = await request<{ sensor: Sensor; observations: CanonicalObservation[] }>(`/api/windows/${enc(window.id)}/sensors/${enc(id)}`);
    const adoptLiveWindow = live && followCurrent;
    if (token !== sensorToken || generation !== generationToken || selectedSensorId !== id || (!adoptLiveWindow && selectedWindow?.id !== window.id)) return;
    if (data.sensor.id !== id || data.observations.some(record => record.sensor_id !== id)) throw new Error("Sensor response scope mismatch.");
    if (adoptLiveWindow) selectedWindow = window;
    observations = data.observations;
    renderCharts(box("channel-charts"), data.sensor, observations, window, projection.pack.sample_seconds);
    box("channel-charts").dataset.snapshot = window.id;
    renderRawTable();
    sensorLoadedKey = key;
    committed = true;
    if (adoptLiveWindow) { renderProjection(); renderWindowHistory(); } else renderBasis();
  } catch (error) {
    if (token === sensorToken) {
      showError(error);
      sensorLoadedKey = null;
      box("channel-charts").replaceChildren(node("p", "Observation API unavailable; no measurements substituted.", "empty"));
      delete box("channel-charts").dataset.snapshot;
      box("raw-table").replaceChildren(node("p", errorMessage(error), "empty"));
    }
  } finally {
    if (token === sensorToken) {
      sensorLoadingKey = null;
      box("channel-charts").setAttribute("aria-busy", "false");
      // Coalesce fast hops: commit a coherent received window, then fetch the newest.
      if (committed && followCurrent && projection?.latest_window?.id !== window.id) void loadSensor();
    }
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
    detail.append(node("p", `${claim.kind}: ${jsonText(claim.value)}`));
    const chips = node("div", "", "chips");
    chips.append(...claim.evidence_ids.map(sourceId => evidenceChip(sourceId)));
    detail.append(chips, node("p", "Select a source evidence ID to highlight its original sensor and channel."));
  } else {
    detail.append(node("p", "Referenced source is not embedded in this snapshot. No evidence is invented; inspect canonical records or the task’s exact basis."));
    renderRawTable();
  }
  renderMap(); renderEvidenceChips(); switchTab("evidence");
}
function renderEvidenceChips(): void {
  const container = box("evidence-chips");
  container.replaceChildren();
  if (!selectedWindow) return;
  const claims = Object.values(selectedWindow.claims);
  for (const claim of claims) container.append(evidenceChip(claim.id, `CLAIM ${claim.kind} / ${claim.id}`));
  for (const item of Object.values(selectedWindow.evidence)) {
    container.append(evidenceChip(item.id, `${item.kind} / ${item.sensor_id || "network"} / ${item.channel || "all"} / ${item.id}`));
  }
}
function renderGate(): void {
  const gate = box("gate-content");
  gate.replaceChildren();
  const window = selectedWindow;
  if (!window) { gate.append(node("p", "WARMING_UP. No completed-window claim exists yet.", "muted")); return; }
  const dl = node("dl");
  for (const [term, value] of [
    ["Coverage", `${(window.quality.coverage * 100).toFixed(1)}% usable · ${window.quality.status}`],
    ["Watermark", `${window.watermark_seconds}s · source ${window.clock_seconds}s`],
    ["Window lag", `${Math.max(0, window.clock_seconds - window.end_seconds).toFixed(1)} source seconds at computation`],
    ["Basis", `${short(window.id)} / r${window.revision}`],
    ["Versions", `${window.pack_version} / ${window.baseline_version} / ${window.parameter_version}`],
    ["Lineage", window.predecessor_id ? short(window.predecessor_id) : "Initial revision"],
  ]) dl.append(node("dt", term), node("dd", value));
  gate.append(dl);
  const chips = node("div", "", "chips");
  chips.append(button(window.event.criteria_id, showCriteria, "chip rule"));
  for (const claim of Object.values(window.claims).slice(0, 6)) chips.append(evidenceChip(claim.id, `${claim.kind} / ${claim.id}`));
  gate.append(chips);
  if (window.quality.issues.length) gate.append(node("p", window.quality.issues.join("; "), "summary"));
  gate.append(node("p", `Evidence hash: ${window.input_hash}`, "public-record"));
}
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
  const renderTask = (task: AgentTask, child = false): void => {
    const card = node("article", "", `task${child ? " child" : ""}`);
    card.append(node("h3", `${friendly(task.role)} · ${task.state}`), node("p", `${short(task.id)} · ${modeName(task.mode)} · basis ${short(task.snapshot_id)}`), node("p", `${task.purpose} · ${task.model_calls} model calls / ${task.tool_calls} tool calls`));
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
async function readTaskDetail(id: string, generation: number): Promise<TaskDetail | null> {
  const detail = await request<TaskDetail>(`/api/tasks/${enc(id)}`);
  if (generation !== generationToken) return null;
  if (detail.task.generation_id !== currentReplayId || detail.task.id !== id
    || detail.children.some(child => child.generation_id !== currentReplayId || child.site_id !== detail.task.site_id || child.parent_id !== id)) throw new Error("Task response scope mismatch.");
  if (detail.casefile && (detail.casefile.task_id !== id || detail.casefile.snapshot_id !== detail.task.snapshot_id)) throw new Error("Investigation handoff scope mismatch.");
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
    .map(task => `${task.id}:${task.updated_at}:${task.state}:${task.model_calls}:${task.tool_calls}`).join("|")}`;
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
  if (focus) switchTab("agents");
  try {
    const detail = await readTaskDetail(id, generation);
    if (!detail || token !== taskToken || generation !== generationToken) return;
    taskDetail = detail;
    renderMap();
    renderTaskDetail();
    renderAnswer();
    try {
      const trace = await request<Record<string, Json>>(`/api/tasks/${enc(id)}/trace`);
      if (token === taskToken && generation === generationToken) renderTrace(trace);
    } catch (error) {
      if (token === taskToken) box("task-detail").append(node("p", `Trace unavailable: ${errorMessage(error)}. Task result remains visible.`, "summary"));
    }
  } catch (error) { if (token === taskToken) showError(error); }
}
function renderTaskDetail(): void {
  if (!taskDetail) return;
  const { task, children, receipts } = taskDetail;
  const container = box("task-detail");
  container.replaceChildren(node("h3", `Public investigation ${task.id}`));
  container.append(node("p", `State ${task.state} · ${modeName(task.mode)} · pinned basis ${task.snapshot_id}`, "summary"));
  container.append(button("Open this task’s immutable evidence basis", () => { void chooseWindow(task.snapshot_id).then(() => switchTab("evidence")); }));
  for (const child of children) container.append(button(`${friendly(child.role)} / ${child.state} / ${short(child.id)}`, () => { void loadTask(child.id); }));
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
    history.append(node("p", "These are executed read-only tool choices, not a transcript of hidden model reasoning. Documents are synthetic; operating context does not rule out a concurrent leak.", "muted"));
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
  const container = box("task-detail");
  container.append(node("h3", "Observability / public trace metadata"));
  container.append(node("div", publicTraceFields.filter(key => key in trace && key !== "url" && key !== "langfuse_url").map(key => `${key}: ${jsonText(trace[key])}`).join("\n") || "Trace metadata not reported", "public-record"));
  const rawUrl = trace.langfuse_url || trace.url;
  if (typeof rawUrl === "string") {
    try {
      const url = new URL(rawUrl, location.href);
      const loopback = url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]";
      if ((url.protocol !== "http:" && url.protocol !== "https:") || (!loopback && url.origin !== location.origin) || url.username || url.password) throw new Error("Unsupported viewer target");
      const link = node("a", "Open same-session Langfuse trace ↗");
      link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; container.append(link);
    } catch { container.append(node("p", "Viewer link withheld: only same-origin or loopback HTTP(S) trace links are allowed.", "muted")); }
  } else container.append(node("p", "Langfuse viewer link not reported. Export acknowledgement is not proof of a stored trace.", "muted"));
}
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
  container.append(node("strong", `${modeName(task.mode)} · ${task.state} · analysis as of ${basis ? time(basis.window_end) : `snapshot ${task.snapshot_id}`}`));
  const terminal = !["QUEUED", "RUNNING", "WAITING_ON_CHILD"].includes(task.state);
  container.append(node("p", `Analysis queued: ${time(task.created_at)}. ${terminal ? "Result recorded" : "Last task update"}: ${time(task.updated_at)}. These are actual processing timestamps, not the simulated sensor clock.`, "answer-timestamps"));
  if (selectedWindow?.id !== task.snapshot_id) container.append(node("p", "Historical task explicitly selected: this answer does not match the visible window. Open its exact basis before using it.", "summary"));
  container.append(node("p", newer ? "Newer monitoring evidence is available. This answer has not been silently rebased." : "Answer basis matches the current monitoring snapshot."));
  const handoff = taskDetail?.task.id === task.id ? taskDetail.casefile : null;
  if (basis && projection) renderWorkflowComparison(container, basis, task, handoff, projection.replay.scenario, () => {
    void chooseWindow(task.snapshot_id).then(() => {
      if (selectedWindow?.id === task.snapshot_id) switchTab("live");
    });
  });
  if (handoff) renderCasefile(container, handoff, {
    draft: question => {
      void chooseWindow(task.snapshot_id).then(() => {
        if (selectedWindow?.id !== task.snapshot_id) { notify("Follow-up basis could not be pinned.", true); return; }
        element("question", HTMLTextAreaElement).value = question;
        element("question-tools", HTMLDetailsElement).open = true;
        element("question", HTMLTextAreaElement).focus();
        notify("Follow-up drafted against the original evidence. Review and submit to run a new investigation.");
      });
    },
    claim: id => { void chooseWindow(task.snapshot_id).then(() => inspectEvidence(id)); },
  });
  if (task.answer) {
    const full = node("details", "", "checked-answer");
    full.append(node("summary", "Full recorded answer and checked evidence"), node("p", task.answer));
    container.append(full);
  } else container.append(node("p", "No accepted operator answer; investigation pending or failed."));
  if (task.result?.limitations.length) container.append(node("p", `Limitations: ${task.result.limitations.join("; ")}`));
  container.append(button("Open investigation handoff and exact evidence basis", () => { void loadTask(task.id); }));
}
function renderFeed(): void {
  const container = box("event-feed"), filter = select("event-filter").value;
  const scrollTop = container.scrollTop;
  container.replaceChildren();
  for (const event of events.filter(item => filter === "all" || item.type.startsWith(`${filter}.`))) {
    const row = node("div", "", "feed-row");
    const timestamp = node("time", time(event.created_at)); timestamp.dateTime = event.created_at;
    row.append(timestamp, node("strong", event.type));
    const detail = node("div");
    detail.append(node("span", `#${event.id} · source ${event.simulated_seconds === null ? "not reported" : `${event.simulated_seconds}s`}`));
    if (event.snapshot_id) detail.append(button(`Window ${short(event.snapshot_id)}`, () => {
      void chooseWindow(event.snapshot_id || "").then(() => switchTab("evidence"));
    }));
    if (event.task_id) detail.append(button(`Task ${short(event.task_id)}`, () => { if (event.task_id) void loadTask(event.task_id); }));
    // Payloads may contain internal fields: public audit shows only bounded declared summaries.
    const publicPayload = ["summary", "status", "state", "reason", "error_code", "validation", "outcome"];
    const summary = publicPayload.filter(key => key in event.payload).map(key => `${key}: ${jsonText(event.payload[key])}`).join(" · ");
    if (summary) detail.append(node("p", summary));
    row.append(detail); container.append(row);
  }
  if (!events.length) container.append(node("p", "No backend events received yet.", "empty"));
  text("new-events", `${newEvents} new`);
  controlButton("feed-pause").textContent = feedPaused ? "Resume auto-scroll" : "Pause auto-scroll";
  controlButton("feed-pause").setAttribute("aria-pressed", String(feedPaused));
  if (feedPaused) container.scrollTop = scrollTop;
  else if (activeTab === "audit") container.scrollTop = container.scrollHeight;
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
    await chooseReplay(replay.id);
    notify("New generation created. Prior generations, evidence and tasks remain preserved; press Play to start ingestion.");
  } catch (error) { showError(error); }
  finally { commandBusy = false; updateControls(); }
}
async function command(action: "play" | "pause" | "step" | "speed", speed?: Speed): Promise<void> {
  if (!projection || !currentReplayId || commandBusy) return;
  const id = currentReplayId, token = generationToken;
  const bodyKey = JSON.stringify([id, action, speed]);
  if (controlRetry?.bodyKey !== bodyKey) controlRetry = { bodyKey, id: crypto.randomUUID() };
  commandBusy = true; updateControls();
  try {
    const replay = await request<ReplaySession>(`/api/replays/${enc(id)}/control`, { action, ...(speed ? { speed } : {}), idempotency_key: controlRetry.id });
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
async function ask(): Promise<void> {
  const question = element("question", HTMLTextAreaElement).value.trim();
  if (!question || !pinVisibleWindow() || !selectedWindow || !projection || asking) return;
  const snapshot = selectedWindow, replay = projection.replay, token = generationToken;
  const matchingEpisode = projection.episodes.find(item => item.id === selectedEpisodeId && (item.current_window_id === snapshot.id || item.basis_window_id === snapshot.id));
  const path = matchingEpisode ? `/api/incidents/${enc(matchingEpisode.id)}/questions` : `/api/replays/${enc(replay.id)}/questions`;
  const bodyKey = JSON.stringify([path, question, snapshot.id, replay.mode]);
  if (questionRetry?.bodyKey !== bodyKey) questionRetry = { bodyKey, id: crypto.randomUUID() };
  asking = true; updateControls();
  try {
    const task = await request<AgentTask>(path, { question, snapshot_id: snapshot.id, mode: replay.mode, idempotency_key: questionRetry.id });
    if (token !== generationToken) return;
    if (task.snapshot_id !== snapshot.id || task.generation_id !== replay.id) throw new Error("Question task did not retain its requested evidence basis.");
    questionRetry = null;
    notify(`Investigation ${short(task.id)} queued against visible revision ${snapshot.revision}. ${replay.investigation_window_id ? "The simulation remains paused for agent checks." : "Source monitoring continues independently."}`);
    if (projection && !projection.tasks.some(item => item.id === task.id)) projection.tasks.push(task);
    await loadTask(task.id);
    void refreshProjection();
  } catch (error) { showError(error); }
  finally { asking = false; updateControls(); }
}

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
controlButton("show-agent-work").addEventListener("click", () => {
  document.querySelector<HTMLElement>(".agent-status-panel")?.scrollIntoView({ block: "start" });
});
controlButton("compare-sensors").addEventListener("click", () => { void compareSensors(); });
controlButton("clear-comparison").addEventListener("click", () => { comparisonSensorIds.clear(); renderSensorList(); });
select("scenario").addEventListener("change", updateControls);
select("map-focus").addEventListener("change", () => { mapSegment = select("map-focus").value; renderMap(); });
select("replay-history").addEventListener("change", () => { const id = select("replay-history").value; if (id) void chooseReplay(id); });
controlButton("play").addEventListener("click", () => { void command(projection?.replay.state === "PLAYING" ? "pause" : "play"); });
controlButton("step").addEventListener("click", () => { void command("step"); });
select("speed").addEventListener("change", () => {
  const value = Number(select("speed").value);
  if (value === 1 || value === 2 || value === 5 || value === 10) void command("speed", value);
});
select("window-history").addEventListener("change", () => { void chooseWindow(select("window-history").value); });
controlButton("follow-live").addEventListener("click", () => { void chooseWindow(""); });
controlButton("inspect-raw").addEventListener("click", () => {
  if (!pinVisibleWindow()) { notify("No completed window to inspect.", true); return; }
  switchTab("evidence");
  text("evidence-detail", selectedSensorId ? `${selectedSensorId} / pinned window ${selectedWindow?.id}. Canonical values retain original source units and timestamps below.` : "Select a sensor in Live to inspect its original observations.");
});
controlButton("feed-pause").addEventListener("click", () => { feedPaused = !feedPaused; if (!feedPaused) newEvents = 0; renderFeed(); });
select("event-filter").addEventListener("change", renderFeed);
element("ask-form", HTMLFormElement).addEventListener("submit", event => { event.preventDefault(); void ask(); });
element("question", HTMLTextAreaElement).addEventListener("focus", () => { pinVisibleWindow(); });
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
  renderActivity();
}, 250);
updateControls();
void initialize();
