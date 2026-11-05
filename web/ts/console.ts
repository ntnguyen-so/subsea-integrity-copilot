import { box, bounds, button, element, friendly, node, svg, text, time } from "./dom";
import { renderCharts } from "./charts";
import type { AgentTask, CanonicalObservation, ConsoleEvent, Json, Mode, MonitoringEpisode, Point, Projection, ReplaySession, Sensor, Session, Speed, TaskDetail, WindowSnapshot } from "./types";

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
let observations: CanonicalObservation[] = [];
let sensorLoadingKey: string | null = null;
let sensorLoadedKey: string | null = null;
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

const eventTypes = ["replay.state", "window.completed", "window.revised", "episode.changed", "task.started", "task.updated", "tool.completed", "answer.checked", "task.finished", "health.changed"];
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
function setConnection(value: string): void { connectionState = value; text("connection-state", value); }
function updateControls(): void {
  const replay = projection?.replay;
  const allowed = session.authenticated && !commandBusy;
  controlButton("create-replay").disabled = !allowed || !select("scenario").value;
  controlButton("play").disabled = !allowed || !replay || replay.state === "COMPLETED" || replay.state === "FAILED";
  controlButton("play").textContent = replay?.state === "PLAYING" ? "Pause" : "Play";
  controlButton("step").disabled = !allowed || replay?.state !== "PAUSED";
  select("speed").disabled = !allowed || !replay || replay.state === "COMPLETED" || replay.state === "FAILED";
  controlButton("ask-submit").disabled = !session.authenticated || !selectedWindow || asking;
  controlButton("ask-submit").textContent = asking ? "Submitting…" : "Investigate pinned window ↗";
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
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab || "live"));
    tab.addEventListener("keydown", event => {
      let next: number | null = null;
      if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (index + 1) % tabs.length;
      if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabs.length - 1;
      if (next !== null) { event.preventDefault(); switchTab(tabs[next].dataset.tab || "live", true); }
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
  history.replaceChildren(new Option("Choose preserved generation", ""), ...replays.map(replay => new Option(`${replay.scenario} · ${short(replay.id)} · ${replay.state} · ${modeName(replay.mode)}`, replay.id)));
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
  selectedSensorId = null; selectedEpisodeId = null;
  selectedEvidenceId = null; selectedTaskId = null; taskDetail = null;
  cursor = 0; cursorInitialized = false; events = []; seenEvents = new Set(); newEvents = 0;
  questionRetry = null;
  projectionDirty = true;
  setConnection("Loading coherent projection");
  resetView();
  renderReplayHistory();
  await refreshProjection();
  if (currentReplayId === id && projection) connectStream(id, generationToken);
}
function resetView(): void {
  text("source-clock", "Not reported"); text("server-clock", "Not reported");
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
        projection = data;
        if (!cursorInitialized) { cursor = data.cursor; cursorInitialized = true; }
        projectionReceivedAt = Date.now();
        replays = replays.map(replay => replay.id === id ? data.replay : replay);
        if (!replays.some(replay => replay.id === id)) replays.unshift(data.replay);
        renderReplayHistory();
        if (followCurrent) selectedWindow = data.latest_window;
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
      if (decoded.type === "episode.changed") notify("Monitoring episode changed. Review current evidence separately from any older agent answer.");
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
  text("inference-mode", modeName(replay.mode));
  text("site-name", pack.name);
  text("source-clock", `${replay.clock_seconds.toFixed(1)} / ${replay.duration_seconds}s · ${replay.state} · ${replay.speed}×`);
  text("server-clock", `${time(projection.server_time)} · received now`);
  text("live-bounds", latest ? `${bounds(latest.window_start, latest.window_end)} · ${latest.quality.status}` : `WARMING_UP / no completed window · width ${pack.window_seconds}s + lateness ${pack.lateness_seconds}s`);
  text("health-state", `${health.monitor} / ${health.agent} / export: ${jsonText(health.observability.status)} · stored visibility: ${jsonText(health.observability.stored_trace_visibility)}`);
  text("audit-health", `Agent: ${health.agent}. Monitor: ${health.monitor}. Observability: ${Object.entries(health.observability).map(([key, value]) => `${key}=${jsonText(value)}`).join("; ") || "not reported"}. UI connection: ${connectionState}.`);
  select("speed").value = String(replay.speed);
  controlButton("step").textContent = `Step +${pack.hop_seconds}s`;
  renderOntology(); renderEpisodes(); renderBasis(); renderMap(); renderGate(); renderEvidenceChips(); renderTasks(); renderAnswer(); renderMetrics(); updateControls();
  if (replay.error) notify(`Replay ${replay.state}: ${replay.error}`, true);
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
  dropdown.replaceChildren(new Option("Follow current window", ""), ...windows.map(window => new Option(`${time(window.window_end)} · r${window.revision} · ${window.quality.status} · ${short(window.id)}`, window.id)));
  if (!followCurrent && selectedWindow && !windows.some(window => window.id === selectedWindow?.id)) dropdown.add(new Option(`${time(selectedWindow.window_end)} · r${selectedWindow.revision} · pinned`, selectedWindow.id));
  dropdown.value = followCurrent ? "" : selectedWindow?.id || "";
}
function renderBasis(): void {
  const window = selectedWindow, latest = projection?.latest_window;
  const newer = window && latest && window.id !== latest.id;
  text("selected-basis", window ? `${followCurrent ? "CURRENT VIEW" : "PINNED"} · ${bounds(window.window_start, window.window_end)} · revision ${window.revision} · ${short(window.id)}` : "No completed window selected");
  text("basis-warning", newer ? "Historical evidence pinned. Newer monitoring telemetry is available; this inspector will not change." : followCurrent ? "Following current telemetry. Selecting evidence or drafting a question pins this visible snapshot." : "Visible snapshot pinned. Stream continues independently.");
  text("ask-basis", window ? `AS OF ${time(window.window_end)} / R${window.revision}` : "PINNED SNAPSHOT REQUIRED");
  text("question-scope", window ? `${modeName(projection?.replay.mode || "scripted")} · ${short(window.id)} · questions never use a hidden later snapshot` : "No visible snapshot");
  updateControls();
}
function pinVisibleWindow(): boolean {
  if (!selectedWindow) return false;
  followCurrent = false;
  renderWindowHistory(); renderBasis();
  return true;
}
async function chooseWindow(id: string): Promise<void> {
  if (!id) {
    windowToken++;
    followCurrent = true; selectedWindow = projection?.latest_window || null; selectedEvidenceId = null;
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
function renderMap(): void {
  if (!projection) return;
  const map = document.getElementById("topology");
  if (!(map instanceof SVGSVGElement)) return;
  const focusedId = document.activeElement?.getAttribute("data-sensor");
  const { pack } = projection;
  const window = selectedWindow;
  const evidence = selectedEvidenceId && window ? window.evidence[selectedEvidenceId] : null;
  const points = [...pack.sensors.map(sensor => sensor.position), ...pack.segments.flatMap(segment => segment.points)];
  if (!points.length) return;
  const xmin = Math.min(...points.map(point => point.x)), xmax = Math.max(...points.map(point => point.x));
  const ymin = Math.min(...points.map(point => point.y)), ymax = Math.max(...points.map(point => point.y));
  const scale = Math.min(650 / Math.max(xmax - xmin, 1), 250 / Math.max(ymax - ymin, 1));
  const project = (point: Point): Point => ({ x: 55 + (point.x - xmin) * scale + (650 - (xmax - xmin) * scale) / 2, y: 65 + (point.y - ymin) * scale + (250 - (ymax - ymin) * scale) / 2 });
  map.replaceChildren(svg("title", {}, "Synthetic pipeline network; sensor health and event support encoded separately"));
  for (let xx = 40; xx < 760; xx += 40) map.append(svg("line", { x1: xx, y1: 30, x2: xx, y2: 340, stroke: "#242a22", "stroke-width": 1 }));
  for (let yy = 30; yy < 370; yy += 40) map.append(svg("line", { x1: 30, y1: yy, x2: 730, y2: yy, stroke: "#242a22", "stroke-width": 1 }));
  const selectedEpisode = episode();
  const scopedEpisodeSections = window && selectedEpisode && (selectedEpisode.current_window_id === window.id || selectedEpisode.basis_window_id === window.id) ? selectedEpisode.segment_ids : [];
  const sections = new Set([...(window?.event.segment_ids || []), ...(window?.location?.compatible.map(candidate => candidate.segment_id) || []), ...scopedEpisodeSections]);
  for (const segment of pack.segments) {
    const coords = segment.points.map(project);
    map.append(svg("polyline", { points: coords.map(point => `${point.x},${point.y}`).join(" "), class: `pipe${sections.has(segment.id) ? " compatible" : ""}` }));
    const midpoint = coords[Math.floor(coords.length / 2)];
    if (midpoint) map.append(svg("text", { x: midpoint.x, y: midpoint.y - 27, "text-anchor": "middle" }, `${segment.id} / ${segment.length_m}m`));
  }
  for (const candidate of window?.location?.compatible || []) {
    const pos = project(candidate.position);
    const ring = svg("rect", { x: pos.x - 8, y: pos.y - 8, width: 16, height: 16, transform: `rotate(45 ${pos.x} ${pos.y})`, class: "candidate" });
    ring.append(svg("title", {}, `Compatible candidate: ${candidate.segment_id}, ${candidate.chainage_m}m, residual ${candidate.residual}; not a confirmed leak`));
    map.append(ring);
  }
  for (const [index, sensor] of pack.sensors.entries()) {
    const position = project(sensor.position);
    const findings = window?.quality.findings.filter(finding => finding.sensor_id === sensor.id) || [];
    const missing = findings.some(finding => finding.missing > 0 || finding.hard_excluded > 0);
    const fault = findings.some(finding => finding.spike_count > 0 || finding.drift_suspected);
    const support = window?.event.supporting_sensor_ids.includes(sensor.id) || false;
    const selected = selectedSensorId === sensor.id || evidence?.sensor_id === sensor.id;
    const health = !window ? "Health not yet reported" : !findings.length ? "No quality findings reported" : `${missing ? "Missing or excluded channel readings" : "Usable coverage"}${fault ? "; spikes or drift suspected" : ""}`;
    const group = svg("g", { class: `sensor${missing ? " missing" : ""}${fault ? " fault" : ""}${support ? " support" : ""}${selected ? " selected" : ""}`, role: "button", tabindex: 0, "aria-label": `${sensor.id}, ${sensor.segment_id}, ${sensor.chainage_m}m. ${health}. ${support ? "Event supporting sensor." : "No event support recorded."}`, "aria-pressed": String(selectedSensorId === sensor.id), "data-sensor": sensor.id });
    if (support) group.append(svg("rect", { x: position.x - 11, y: position.y - 11, width: 22, height: 22, transform: `rotate(45 ${position.x} ${position.y})`, class: "support-ring" }));
    group.append(svg("circle", { cx: position.x, cy: position.y, r: 6 }));
    group.append(svg("text", { x: position.x, y: position.y + (index % 2 ? 24 : -17), "text-anchor": "middle" }, `${sensor.id}${fault ? " △" : ""}${missing ? " ◌" : ""}`));
    group.append(svg("title", {}, `${sensor.id} / ${sensor.station_id} / domain ${sensor.failure_domain_id}. ${health}`));
    group.addEventListener("click", () => selectSensor(sensor.id));
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectSensor(sensor.id); }
      if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? pack.sensors.length - 1 : (index + (event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1) + pack.sensors.length) % pack.sensors.length;
        const target = [...map.querySelectorAll<SVGGElement>("[data-sensor]")][next];
        target?.focus();
      }
    });
    map.append(group);
  }
  if (focusedId) [...map.querySelectorAll<SVGGElement>("[data-sensor]")].find(item => item.dataset.sensor === focusedId)?.focus();
  text("event-summary", window ? `${friendly(window.event.hypothesis)} · ${window.event.persistence_seconds}s qualifying persistence · alternatives: ${window.event.eligible_hypotheses.map(friendly).join(", ") || "none recorded"}. Counterevidence: ${window.event.counterevidence.join("; ") || "none recorded"}` : "No completed assessment. Warm-up is not a normal-pipeline verdict.");
  text("location-summary", window?.location ? `${window.location.status.toUpperCase()} · ${window.location.reason} · ${window.location.compatible.length} compatible candidate${window.location.compatible.length === 1 ? "" : "s"}. ${window.location.compatible.map(candidate => `${candidate.segment_id} @ ${candidate.chainage_m}m (residual ${candidate.residual.toFixed(3)})`).join("; ")}` : "Location not computed / not eligible. No confirmed leak location is claimed.");
}
function selectSensor(id: string): void {
  pinVisibleWindow();
  selectedSensorId = id; selectedEvidenceId = null;
  renderMap(); void loadSensor();
}
async function loadSensor(): Promise<void> {
  const id = selectedSensorId, window = selectedWindow;
  if (!id || !window || !projection) return;
  const key = JSON.stringify([window.id, id]);
  // Snapshot IDs are immutable. SSE health/task refreshes must not restart this read.
  if (key === sensorLoadingKey) return;
  if (key === sensorLoadedKey) { renderRawTable(); return; }
  sensorLoadingKey = key;
  sensorLoadedKey = null;
  const token = ++sensorToken, generation = generationToken;
  const sensor = projection.pack.sensors.find(item => item.id === id);
  text("sensor-title", sensor ? `${sensor.id} / ${sensor.station_id}` : id);
  text("sensor-meta", sensor ? `${sensor.segment_id} · ${sensor.chainage_m}m · failure domain ${sensor.failure_domain_id}` : "Loading sensor metadata");
  box("channel-charts").replaceChildren(node("p", "Loading actual canonical observations…", "empty"));
  box("raw-table").replaceChildren(node("p", "Loading source records…", "empty"));
  try {
    const data = await request<{ sensor: Sensor; observations: CanonicalObservation[] }>(`/api/windows/${enc(window.id)}/sensors/${enc(id)}`);
    if (token !== sensorToken || generation !== generationToken || selectedWindow?.id !== window.id || selectedSensorId !== id) return;
    if (data.sensor.id !== id || data.observations.some(record => record.sensor_id !== id)) throw new Error("Sensor response scope mismatch.");
    observations = data.observations;
    renderCharts(box("channel-charts"), data.sensor, observations, window, projection.pack.sample_seconds);
    renderRawTable();
    sensorLoadedKey = key;
  } catch (error) {
    if (token === sensorToken) {
      showError(error);
      box("channel-charts").replaceChildren(node("p", "Observation API unavailable; no measurements substituted.", "empty"));
      box("raw-table").replaceChildren(node("p", errorMessage(error), "empty"));
    }
  } finally {
    if (token === sensorToken) sensorLoadingKey = null;
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
  for (const item of Object.values(selectedWindow.evidence)) container.append(evidenceChip(item.id, `${item.kind} / ${item.sensor_id || "network"} / ${item.channel || "all"} / ${item.id}`));
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
  text("domain-count", window ? `${window.event.supporting_sensor_ids.length} supporting observers · ${window.event.failure_domain_count} event domains / ${window.quality.failure_domains_available} available` : "Not reported");
  text("window-state", `${window?.quality.status || "WARMING_UP"} / ${episode()?.state || "no episode"}`);
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
async function loadTask(id: string, focus = true): Promise<void> {
  selectedTaskId = id;
  const token = ++taskToken, generation = generationToken;
  try {
    const detail = await request<TaskDetail>(`/api/tasks/${enc(id)}`);
    if (token !== taskToken || generation !== generationToken) return;
    if (detail.task.generation_id !== currentReplayId || detail.task.id !== id || detail.children.some(child => child.generation_id !== currentReplayId)) throw new Error("Task response scope mismatch.");
    taskDetail = detail;
    renderTaskDetail();
    renderAnswer();
    if (focus) switchTab("agents");
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
  const task = taskDetail?.task || projection?.tasks.find(item => item.snapshot_id === selectedWindow?.id && (item.answer || item.result)) || projection?.tasks.find(item => item.answer || item.result);
  const container = box("answer-preview");
  container.replaceChildren();
  if (!task) { container.append(node("p", "No accepted answer loaded. Real numerical monitoring does not wait for hosted inference.")); return; }
  const basis = windows.find(window => window.id === task.snapshot_id) || (selectedWindow?.id === task.snapshot_id ? selectedWindow : null);
  const newer = projection?.latest_window?.id !== task.snapshot_id;
  container.append(node("strong", `${modeName(task.mode)} · ${task.state} · analysis as of ${basis ? time(basis.window_end) : `snapshot ${task.snapshot_id}`}`));
  container.append(node("p", newer ? "Newer monitoring evidence is available. This answer has not been silently rebased." : "Answer basis matches the current monitoring snapshot."));
  container.append(node("p", task.answer || task.result?.summary || "No accepted answer; investigation pending."));
  if (task.result?.limitations.length) container.append(node("p", `Limitations: ${task.result.limitations.join("; ")}`));
  container.append(button("Inspect task and exact answer basis", () => { void loadTask(task.id); }));
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
  const mode: Mode = select("mode").value === "live" ? "live" : "scripted";
  if (!scenario || !Number.isSafeInteger(seed) || input("seed").value === "") { notify("Choose a scenario and enter an integer seed.", true); return; }
  const bodyKey = JSON.stringify([scenario, seed, mode]);
  if (createRetry?.bodyKey !== bodyKey) createRetry = { bodyKey, id: crypto.randomUUID() };
  commandBusy = true; updateControls();
  try {
    const replay = await request<ReplaySession>("/api/replays", { scenario, seed, mode, idempotency_key: createRetry.id });
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
    notify(`Investigation ${short(task.id)} queued against visible revision ${snapshot.revision}. Source monitoring continues independently.`);
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
select("scenario").addEventListener("change", updateControls);
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
  if (!projection || !projectionReceivedAt) return;
  const age = Math.floor((Date.now() - projectionReceivedAt) / 1000);
  text("server-clock", `${time(projection.server_time)} · projection received ${age}s ago`);
}, 1000);
updateControls();
void initialize();
