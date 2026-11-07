import { button, node, svg } from "./dom";
import { agentName } from "./agentwork";
import type { EvaluationCase, EvaluationReport } from "./evaluation";
import type { ConsoleEvent, Point, SitePack } from "./types";

interface Issue { sensor_id: string; kind: string }
interface Source { segment_id: string; chainage_m: number; start_seconds?: number }
export interface SpatialFrame {
  source_seconds: number; window_start_seconds: number; snapshot_id: string; input_hash: string;
  review_case_id: string | null;
  truth: { leak_source: Source | null; sensor_issues: Issue[]; operating_change?: { segment_id: string } | null };
  detector: { pressure_anomaly_sensors: string[]; missing_value_sensors: string[]; coverage: number };
  pressure_summaries: Record<string, { baseline_median?: number; recent_pressure_drop_bar?: number; max_score?: number }>;
}
export interface SpatialNetwork {
  id: string; name: string; status: string; pack: SitePack; dataset_sha256: string;
  frames: SpatialFrame[];
}
interface Playback {
  run: string; network: string; seconds: number; playing: boolean; reviewed: boolean;
  investigationSeconds: number; sourceAccumulator: number; holdSeconds: number;
  sensor: string; speed: number;
}
let state: Playback | null = null;
let timer: number | null = null;
export function stopSpatialPlayback(): void {
  if (timer !== null) window.clearInterval(timer);
  timer = null;
}
function original<K extends keyof HTMLElementTagNameMap>(tag: K, value = "", className = ""): HTMLElementTagNameMap[K] {
  const result = node(tag, "", className); result.textContent = value; return result;
}
function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}
function score(value: number | null | undefined): string {
  return value == null ? "Pending" : `${(100 * value).toFixed(1)}%`;
}
function lastFrame(network: SpatialNetwork): SpatialFrame | undefined {
  return network.frames[network.frames.length - 1];
}
function matchingReview(report: EvaluationReport, frame: SpatialFrame): EvaluationCase | undefined {
  return report.cases.find(row => row.case_id === frame.review_case_id
    && row.source_seconds === frame.source_seconds
    && row.snapshot_id === frame.snapshot_id && row.input_hash === frame.input_hash);
}
export function releasedReview(report: EvaluationReport, frame: SpatialFrame, reviewed: boolean): EvaluationCase | undefined {
  const row = matchingReview(report, frame);
  return reviewed && row?.accepted_report && row.extraction?.status === "completed" ? row : undefined;
}
function geometry(pack: SitePack): (point: Point) => Point {
  const points = pack.segments.flatMap(segment => segment.points);
  const xmin = Math.min(...points.map(point => point.x)), xmax = Math.max(...points.map(point => point.x));
  const ymin = Math.min(...points.map(point => point.y)), ymax = Math.max(...points.map(point => point.y));
  const scale = Math.min(650 / Math.max(xmax - xmin, 1), 390 / Math.max(ymax - ymin, 1));
  return point => ({
    x: 55 + (point.x - xmin) * scale + (650 - (xmax - xmin) * scale) / 2,
    y: 65 + (ymax - point.y) * scale + (390 - (ymax - ymin) * scale) / 2,
  });
}
function pipelinePoint(pack: SitePack, id: string, chainage: number, project: (point: Point) => Point): Point | null {
  const segment = pack.segments.find(item => item.id === id);
  if (!segment || chainage < 0 || chainage > segment.length_m) return null;
  const start = project(segment.points[0]), end = project(segment.points[segment.points.length - 1]);
  const fraction = chainage / segment.length_m;
  return { x: start.x + (end.x - start.x) * fraction, y: start.y + (end.y - start.y) * fraction };
}

function drawMap(map: SVGSVGElement, pack: SitePack, frame: SpatialFrame, review: EvaluationCase | undefined,
  truth: boolean, selected: string, select: (id: string) => void): void {
  const project = geometry(pack);
  map.replaceChildren(svg("title", {}, truth ? "Known source labels, withheld from agents" : "Recorded numerical flags and accepted agent findings"));
  map.dataset.sourceSeconds = String(frame.source_seconds);
  map.dataset.snapshot = frame.snapshot_id;
  for (let x = 40; x < 760; x += 40) map.append(svg("line", { x1: x, y1: 30, x2: x, y2: 490, class: "eval-grid" }));
  for (let y = 30; y < 510; y += 40) map.append(svg("line", { x1: 30, y1: y, x2: 730, y2: y, class: "eval-grid" }));
  const leaks = review?.extraction?.mapping?.leaks || [];
  for (const segment of pack.segments) {
    const points = segment.points.map(project);
    const pattern = !truth && leaks.some(item => item.segment_id === segment.id);
    map.append(svg("polyline", {
      points: points.map(point => `${point.x},${point.y}`).join(" "),
      class: `pipe${pattern ? " eval-leak-pattern" : ""}`, "data-segment-id": segment.id,
    }));
    const label = segment.id === "P1" ? points[0] : points[points.length - 1];
    map.append(svg("text", { x: label.x, y: label.y + (segment.id === "P1" ? 30 : -25), "text-anchor": "middle", class: "eval-pipe-label" }, segment.id));
  }
  if (truth && frame.truth.leak_source) {
    const source = frame.truth.leak_source;
    const point = pipelinePoint(pack, source.segment_id, source.chainage_m, project);
    if (point) {
      const marker = svg("g", { class: "eval-source", "data-segment-id": source.segment_id, "data-chainage-m": source.chainage_m });
      marker.append(svg("circle", { cx: point.x, cy: point.y, r: 19 }),
        svg("path", { d: `M${point.x - 11} ${point.y}H${point.x + 11}M${point.x} ${point.y - 11}V${point.y + 11}` }),
        svg("title", {}, `Known leak source: ${source.segment_id}, ${source.chainage_m} m. This label is not given to agents.`));
      map.append(marker);
    }
  }
  const authorized = review?.authorized_inspection;
  if (!truth && authorized && leaks.some(item => item.segment_id === authorized.segment_id
    && item.interval?.start_m === authorized.start_m && item.interval.end_m === authorized.end_m)
    && authorized.end_m > authorized.start_m && authorized.end_m - authorized.start_m <= 400) {
    const start = pipelinePoint(pack, authorized.segment_id, authorized.start_m, project);
    const end = pipelinePoint(pack, authorized.segment_id, authorized.end_m, project);
    if (start && end) {
      const interval = svg("polyline", { points: `${start.x},${start.y} ${end.x},${end.y}`, class: "eval-inspection",
        "data-segment-id": authorized.segment_id, "data-start-m": authorized.start_m, "data-end-m": authorized.end_m });
      interval.append(svg("title", {}, `Accepted inspection interval: ${authorized.segment_id}, ${authorized.start_m}–${authorized.end_m} m; not an exact leak point.`));
      map.append(interval);
    }
  }
  const issues = truth ? frame.truth.sensor_issues : review?.extraction?.mapping?.sensor_issues || [];
  for (const [index, sensor] of pack.sensors.entries()) {
    const segment = pack.segments.find(item => item.id === sensor.segment_id);
    if (!segment) continue;
    const at = pipelinePoint(pack, segment.id, sensor.chainage_m, project);
    if (!at) continue;
    const a = project(segment.points[0]), b = project(segment.points[segment.points.length - 1]);
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    const side = sensor.id.endsWith("-A") ? -1 : 1;
    const point = { x: at.x - side * (b.y - a.y) / length * 10, y: at.y + side * (b.x - a.x) / length * 10 };
    const kinds = issues.filter(item => item.sensor_id === sensor.id).map(item => item.kind);
    const fault = kinds.some(kind => kind !== "missing");
    const missing = truth ? kinds.some(kind => ["missing", "invalid"].includes(kind)) : frame.detector.missing_value_sensors.includes(sensor.id);
    const anomaly = !truth && frame.detector.pressure_anomaly_sensors.includes(sensor.id);
    const description = truth ? kinds.join(", ") || "No injected instrument problem" :
      `${anomaly ? "Pressure anomaly. " : ""}${missing ? "Missing value. " : ""}${fault ? `Agent identified ${kinds.join(", ")}.` : "No accepted instrument issue recorded."}`;
    const group = svg("g", {
      class: `sensor eval-sensor${anomaly ? " anomalous" : ""}${missing ? " missing" : ""}${truth && fault ? " eval-known-issue" : ""}`,
      "data-sensor": sensor.id, "data-issue-kinds": kinds.join(","), role: "button", tabindex: 0,
      "aria-label": `${sensor.id}, ${sensor.segment_id}, ${sensor.chainage_m} m. ${description}`,
      "aria-pressed": String(sensor.id === selected),
    });
    if (!truth && fault) group.append(svg("circle", { cx: point.x, cy: point.y, r: 10, class: "eval-agent-issue" }));
    group.append(svg("circle", { cx: point.x, cy: point.y, r: 5.5, class: "sensor-dot" }),
      svg("title", {}, `${sensor.id} / ${sensor.station_id} / ${sensor.failure_domain_id}. ${description}`));
    if (sensor.id === selected) group.append(svg("circle", { cx: point.x, cy: point.y, r: 14, class: "eval-selection" }));
    group.addEventListener("click", () => select(sensor.id));
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(sensor.id); }
      if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? pack.sensors.length - 1 :
          (index + (["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 1) + pack.sensors.length) % pack.sensors.length;
        map.querySelectorAll<SVGGElement>("[data-sensor]")[next]?.focus();
      }
    });
    map.append(group);
  }
}

function publicUpdate(event: ConsoleEvent): string {
  const payload = event.payload;
  if (event.type === "agent.handoff_requested") return `Response Coordinator → ${agentName(String(payload.to_role))}: ${payload.reason || "Specialist checks requested"}`;
  if (event.type === "answer.checked") return `Checked handoff: ${payload.public_output || "Findings passed to the next agent"}`;
  if (event.type === "agent.review_requested") return "Grounding Reviewer checks the coordinator's draft against cited evidence.";
  if (event.type === "answer.critique") return payload.decision === "accept" ? "Evidence wording accepted." : "Reviewer requested evidence corrections.";
  if (event.type === "agent.draft") return `Draft, not yet accepted: ${String(payload.text || "").slice(0, 500)}`;
  return `${payload.title || "Evidence check"}: ${payload.observation || payload.purpose || "Recorded check"}`;
}
const journalTypes = new Set(["agent.check_started", "agent.check_completed", "agent.handoff_requested", "agent.draft", "agent.review_requested", "answer.checked", "answer.critique"]);

export function renderSpatialEvaluation(container: HTMLElement, report: EvaluationReport): void {
  stopSpatialPlayback();
  const networks = report.networks || [];
  if (!networks.length) { container.append(original("p", "No extended-network recordings are available.", "empty")); return; }
  if (!state || state.run !== report.run_id) {
    const accepted = report.cases.filter(row => row.network_id === networks[0].id && row.accepted_report
      && row.extraction?.status === "completed");
    state = {
      run: report.run_id || "", network: networks[0].id,
      seconds: accepted[accepted.length - 1]?.source_seconds || lastFrame(networks[0])?.source_seconds || 60, playing: false,
      reviewed: true, investigationSeconds: 0, sourceAccumulator: 0, holdSeconds: 0,
      sensor: "", speed: 30,
    };
  }
  const playback = state;
  const heading = original("div", "", "spatial-heading");
  heading.append(original("strong", `S7-scale evaluation · ${report.split === "held_out" ? "held-out" : "development"}`),
    original("span", `${networks.length} recordings · 112 instruments each · 7 branches · 11.2 km · 6 minutes`, "muted"));
  container.append(heading);
  const metrics = report.metrics;
  const scorecards = original("div", "", "spatial-scorecards");
  for (const [key, title] of [["leak_recognition", "Leak recognition"], ["agent_pipeline_identification", "Correct branch"], ["agent_sensor_concerns", "Instrument issues"]] as const) {
    const value = metrics?.groups[key];
    const card = original("div");
    card.append(original("small", title), original("strong", score(value?.recall.value)),
      original("span", value ? `${value.tp} found · ${value.fn} missed · ${value.fp} false alarms` : "Runs pending", "muted"));
    scorecards.append(card);
  }
  const localizations = metrics?.rates.localization_containment;
  const locationCard = original("div");
  locationCard.append(original("small", "Supported localization"), original("strong", localizations?.denominator ? `${localizations.numerator}/${localizations.denominator}` : "Pending"),
    original("span", "Source inside a ≤400 m inspection interval", "muted"));
  scorecards.append(locationCard);
  container.append(scorecards);
  const status = original("p", report.status === "running" ? "Real agent recordings are in progress; completed findings appear as they arrive." :
    metrics?.target_met ? "Recorded metrics exceed 95%; field reliability is not established." : "The >95% target is not met on these extended networks. Misses and withheld locations remain in the scores.",
    metrics?.target_met ? "evaluation-pass spatial-qualification" : "evaluation-warning spatial-qualification");
  container.append(status);
  const controls = original("div", "", "spatial-controls");
  const select = original("select"); select.setAttribute("aria-label", "Evaluation recording");
  const shortNames = ["N1 · Broad leak + mixed faults", "N2 · Localized leak + mixed faults", "N3 · Faults and operating shift; no leak"];
  networks.forEach((network, index) => { const option = original("option", shortNames[index] || network.name); option.value = network.id; select.append(option); });
  select.value = playback.network;
  const play = button("Play recording", () => {
    if (playback.playing) playback.playing = false;
    else {
      if (playback.seconds >= (lastFrame(currentNetwork())?.source_seconds || 360)) playback.seconds = currentNetwork().frames[0]?.source_seconds || 60;
      playback.playing = true; playback.reviewed = false; playback.investigationSeconds = 0;
      playback.sourceAccumulator = 0; playback.holdSeconds = 0;
    }
    update();
  });
  const slider = original("input"); slider.type = "range"; slider.min = "60"; slider.max = "360"; slider.step = "15";
  slider.setAttribute("aria-label", "Synchronized recording time");
  const time = original("output", "", "spatial-clock"); time.setAttribute("aria-live", "off");
  const speed = original("select"); speed.setAttribute("aria-label", "Recording playback speed");
  for (const value of [15, 30, 60]) { const option = original("option", `${value}× replay`); option.value = String(value); speed.append(option); }
  speed.value = String(playback.speed);
  controls.append(select, play, slider, time, speed);
  container.append(controls);
  const checkpoints = original("div", "", "spatial-checkpoints");
  const maps = original("div", "", "spatial-map-grid");
  const truthPane = original("section", "", "spatial-map-pane");
  const agentPane = original("section", "", "spatial-map-pane");
  const truthCaption = original("p", "", "spatial-map-caption");
  const agentCaption = original("p", "", "spatial-map-caption");
  const truthMap = svg("svg", { viewBox: "0 0 760 520", role: "group", "aria-label": "Ground truth pipeline map", id: "evaluation-truth-map" });
  const agentMap = svg("svg", { viewBox: "0 0 760 520", role: "group", "aria-label": "Agent findings pipeline map", id: "evaluation-agent-map" });
  truthPane.append(original("h3", "Ground truth"), original("small", "Known labels · never given to agents"), truthMap, truthCaption);
  agentPane.append(original("h3", "Agent findings"), original("small", "Measured flags + accepted, source-matched review"), agentMap, agentCaption);
  maps.append(truthPane, agentPane);
  container.append(checkpoints, maps);
  const legend = original("div", "", "spatial-legend");
  for (const [name, text] of [["source", "Known leak source"], ["issue", "Instrument issue"], ["anomaly", "Pressure anomaly"], ["missing", "Missing value"], ["inspection", "Inspection interval"]]) {
    const item = original("span", text); item.prepend(original("i", "", `eval-key-${name}`)); legend.append(item);
  }
  container.append(legend);
  const sensorDetail = original("p", "Select the same instrument on either map to compare its labels and findings.", "spatial-sensor-detail muted");
  const progress = original("div", "", "spatial-progress");
  const progressTitle = original("strong");
  const agentCards = original("div", "", "spatial-agent-cards");
  const updateLine = original("p", "", "spatial-public-update");
  progress.append(progressTitle, agentCards, updateLine);
  container.append(progress, sensorDetail);
  container.append(original("p", "Both maps use the same source window. Replay pauses at each recorded investigation; source time and real model time are separate. Viewing or scrubbing does not call the models.", "spatial-footnote muted"));
  const journal = original("details", "", "spatial-journal");
  journal.append(original("summary", "Recorded agent checks, interim outputs and handoffs"));
  const journalBody = original("ol", "", "agent-public-journal");
  journal.append(journalBody); container.append(journal);

  function currentNetwork(): SpatialNetwork { return networks.find(network => network.id === playback.network) || networks[0]; }
  function currentFrame(): SpatialFrame | undefined {
    return [...currentNetwork().frames].reverse().find(frame => frame.source_seconds <= playback.seconds);
  }
  function seek(seconds: number): void {
    playback.seconds = seconds; playback.playing = false; playback.reviewed = true;
    playback.investigationSeconds = 0; playback.sensor = ""; update();
  }
  function update(): void {
    const network = currentNetwork(), frame = currentFrame();
    slider.max = String(lastFrame(network)?.source_seconds || 360); slider.value = String(playback.seconds);
    play.textContent = playback.playing ? "Pause recording" : "Play recording";
    time.textContent = `${clock(frame?.source_seconds || 0)} / 6:00`;
    checkpoints.replaceChildren();
    for (const row of report.cases.filter(item => item.network_id === network.id && (item.source_seconds || 0) > 60)) {
      const end = row.source_seconds || 0;
      const control = button(`${clock(end)} review · ${row.status === "completed" ? "recorded" : row.status.replace(/_/g, " ")}`, () => seek(end));
      control.disabled = !network.frames.some(item => item.source_seconds === end);
      checkpoints.append(control);
    }
    if (!frame) {
      truthCaption.textContent = agentCaption.textContent = "Recording has not reached its first complete window.";
      truthMap.replaceChildren(); agentMap.replaceChildren(); agentCards.replaceChildren();
      progressTitle.textContent = "Numerical recording in progress"; updateLine.textContent = "";
      return;
    }
    const row = matchingReview(report, frame);
    const review = releasedReview(report, frame, playback.reviewed);
    const chooseSensor = (id: string): void => { playback.sensor = id; update(); };
    drawMap(truthMap, network.pack, frame, undefined, true, playback.sensor, chooseSensor);
    drawMap(agentMap, network.pack, frame, review, false, playback.sensor, chooseSensor);
    const source = frame.truth.leak_source;
    const issueCount = new Set(frame.truth.sensor_issues.filter(item => item.kind !== "missing").map(item => item.sensor_id)).size;
    truthCaption.textContent = `${source ? `Leak on ${source.segment_id} at ${source.chainage_m} m` : "No leak"} · ${issueCount} instruments with known issues${frame.truth.operating_change ? ` · ${frame.truth.operating_change.segment_id} operating shift` : ""}`;
    const leaks = review?.extraction?.mapping?.leaks || [];
    agentCaption.textContent = review ? (leaks.length ? leaks.map(leak => `${leak.segment_id} leak pattern${leak.interval ? ` · ${leak.interval.start_m}–${leak.interval.end_m} m proposed` : " · interval withheld"}`).join("; ") : "No leak pattern identified") :
      row?.root_count ? playback.reviewed ? "No accepted mapped report; no interpretation overlay released." : "Investigation underway · final findings not yet available" :
        `${frame.detector.pressure_anomaly_sensors.length} pressure alerts · no review of this window`;
    agentCaption.dataset.accepted = String(Boolean(review));
    const elapsed = row?.agent_elapsed_seconds;
    const shownSeconds = playback.reviewed ? elapsed || 0 : playback.investigationSeconds;
    const origin = Date.parse(row?.agent_started_at || row?.agent_tasks?.find(task => task.id === row.root_id)?.created_at || "");
    const visibleEvents = (row?.activity || []).filter(event => journalTypes.has(event.type)
      && (playback.reviewed || (Date.parse(event.created_at) - origin) / 1000 <= shownSeconds));
    progressTitle.textContent = row?.root_count ?
      `${playback.reviewed ? "Recorded investigation" : "Source paused for investigation"} · window ${clock(frame.window_start_seconds)}–${clock(frame.source_seconds)} · ${elapsed === undefined ? "real model time pending" : `${elapsed.toFixed(0)} s real model time`}` :
      `Numerical monitoring · window ${clock(frame.window_start_seconds)}–${clock(frame.source_seconds)} · ${frame.detector.pressure_anomaly_sensors.length} pressure alerts`;
    agentCards.replaceChildren();
    for (const role of ["sensor_quality", "event_diagnosis", "operator_response"]) {
      const task = row?.agent_tasks?.find(item => item.role === role && item.root_id === row.root_id);
      const begun = task && (playback.reviewed || (Date.parse(task.created_at) - origin) / 1000 <= shownSeconds);
      const complete = task && ["SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"].includes(task.state)
        && (playback.reviewed || (Date.parse(task.updated_at) - origin) / 1000 <= shownSeconds);
      const card = original("div", "", `spatial-agent${complete ? " completed" : begun ? " active" : ""}`);
      card.append(original("small", agentName(role)),
        original("strong", complete ? task.state === "FAILED" ? "Failed" : "Completed" : begun ? "Checking evidence" : "Not started"));
      const descriptions: Record<string, string> = {
        sensor_quality: "Checks usable readings and instrument inconsistencies.",
        event_diagnosis: "Compares joint pressure patterns, quiet neighbors and operating records.",
        operator_response: "Coordinates checks and submits an evidence-grounded report for review.",
      };
      card.append(original("span", descriptions[role], "muted"));
      agentCards.append(card);
    }
    updateLine.textContent = visibleEvents.length ? publicUpdate(visibleEvents[visibleEvents.length - 1]) :
      row?.root_count ? "The full recorded public journal is available below. Private model reasoning is not displayed." :
        frame.detector.pressure_anomaly_sensors.length ? "Pressure anomalies are visible. This benchmark investigates only its predeclared checkpoints." : "No pressure anomalies: no agent investigation.";
    journalBody.replaceChildren();
    for (const event of visibleEvents) {
      const item = original("li");
      item.dataset.kind = event.type;
      const role = String(event.payload.role || row?.agent_tasks?.find(task => task.id === event.task_id)?.role || "agent");
      item.append(original("small", `${Math.max(0, (Date.parse(event.created_at) - origin) / 1000).toFixed(0)} s · ${agentName(role)}`),
        original("p", publicUpdate(event)));
      journalBody.append(item);
    }
    if (!visibleEvents.length) journalBody.append(original("li", "No recorded public agent updates for this selected window."));
    if (playback.sensor) {
      const known = frame.truth.sensor_issues.filter(item => item.sensor_id === playback.sensor).map(item => item.kind);
      const mapped = review?.extraction?.mapping?.sensor_issues.filter(item => item.sensor_id === playback.sensor).map(item => item.kind) || [];
      const summary = frame.pressure_summaries[playback.sensor];
      sensorDetail.textContent = `${playback.sensor} · known issue: ${known.join(", ") || "none"} · agent: ${mapped.join(", ") || "none recorded"}${summary?.recent_pressure_drop_bar != null ? ` · recent pressure change from normal: ${(-summary.recent_pressure_drop_bar).toFixed(2)} bar` : ""}`;
    } else sensorDetail.textContent = "Select the same instrument on either map to compare its labels and findings.";
  }
  select.addEventListener("change", () => {
    playback.network = select.value; seek(lastFrame(currentNetwork())?.source_seconds || 60);
  });
  slider.addEventListener("input", () => seek(Number(slider.value)));
  speed.addEventListener("change", () => { playback.speed = Number(speed.value); });
  update();
  let previousTick = performance.now();
  timer = window.setInterval(() => {
    const now = performance.now(), delta = Math.min((now - previousTick) / 1000, 1); previousTick = now;
    if (!playback.playing) return;
    if (document.getElementById("panel-evaluation")?.hidden) { playback.playing = false; update(); return; }
    const frame = currentFrame();
    if (!frame) { playback.playing = false; update(); return; }
    const row = matchingReview(report, frame);
    if (row?.root_count && !playback.reviewed) {
      if (row.agent_elapsed_seconds === undefined) { playback.playing = false; update(); return; }
      playback.investigationSeconds += delta * playback.speed;
      if (playback.investigationSeconds >= row.agent_elapsed_seconds) { playback.reviewed = true; playback.holdSeconds = 2; }
    } else if (playback.holdSeconds > 0) playback.holdSeconds -= delta;
    else {
      playback.sourceAccumulator += delta * playback.speed;
      if (playback.sourceAccumulator >= 15) {
        const next = currentNetwork().frames.find(item => item.source_seconds > frame.source_seconds);
        if (!next) playback.playing = false;
        else { playback.seconds = next.source_seconds; playback.reviewed = false; playback.investigationSeconds = 0; playback.sourceAccumulator = 0; }
      }
    }
    update();
  }, 250);
}
