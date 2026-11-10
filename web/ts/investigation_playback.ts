/**
 * Load-aware local playback of preserved terminal investigations. Navigating a saved
 * timeline loads original measurements/reports, makes no inference calls and cannot
 * expose a future checkpoint. Fresh work is an explicit separate live-here action.
 */
import { box, node, svg } from "./dom";
import { renderAgentWork, renderIdleAgentWork } from "./agentwork";
import { drawInvestigationMap, mapLegend, sensorAssessment } from "./evaluation_maps";
import type { AgentTask, ExecutionUsage, Projection, SitePack, TaskDetail, WindowSnapshot } from "./types";

export interface SavedInvestigation {
  task_id: string; source_seconds: number; created_at: string;
  snapshot_id: string; input_hash: string; state: string; origin: "library" | "saved";
}
interface RecordedFrame { pack: SitePack; snapshot: WindowSnapshot; detail: TaskDetail }
interface PlaybackServices {
  get<T>(path: string): Promise<T>;
  pauseLive(): Promise<void>;
  liveHere(seconds: number): Promise<void>;
  changed(): void;
  ready(): boolean;
  error(error: unknown): void;
  metrics(root: AgentTask | null, usage: ExecutionUsage | null, recorded: boolean, serverTime: string): void;
}
/** Latest terminal checkpoint at or before selection; newest trial wins a same-time tie. */
export function availableRecording(rows: SavedInvestigation[], seconds: number): SavedInvestigation | undefined {
  return rows.filter(row => ["SUCCEEDED", "ABSTAINED", "FAILED"].includes(row.state)
    && row.source_seconds <= seconds)
    .sort((a, b) => b.source_seconds - a.source_seconds || b.created_at.localeCompare(a.created_at))[0];
}

export class InvestigationPlayback {
  enabled = false;
  playing = false;
  seconds = 0;
  speed = 5;
  loading = false;
  description = "";
  private projection: Projection | null = null;
  private liveOverride = false;
  private rows: SavedInvestigation[] = [];
  private frames = new Map<string, RecordedFrame>();
  private requested = "";
  private version = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private anchor = 0;
  private frameLoading = false;
  private wasWaiting = false;
  private manifestKey = "";
  private manifestFetchedAt = 0;
  private selectedSensor = "";
  constructor(private services: PlaybackServices) {}
  get waiting(): boolean {
    return this.loading || this.frameLoading || !this.services.ready();
  }
  dataChanged(): void {
    const waiting = this.waiting;
    if (waiting || this.wasWaiting) this.anchor = performance.now();
    this.wasWaiting = waiting;
  }

  selectRun(recorded: boolean): void {
    this.stop(); this.enabled = false; this.liveOverride = !recorded;
    this.requested = ""; this.version++; this.manifestKey = ""; this.frameLoading = false;
    this.seconds = 0;
    this.loading = recorded;
  }

  load(projection: Projection): void {
    const changed = this.projection?.replay.id !== projection.replay.id;
    this.projection = projection;
    if (changed) {
      this.stop(); this.seconds = 0; this.requested = ""; this.version++; this.frameLoading = false;
      this.enabled = false; this.rows = [];
    }
    const key = JSON.stringify([projection.replay.id,
      projection.tasks.filter(task => !task.parent_id).map(task => [task.id, task.state])]);
    if (key !== this.manifestKey || performance.now() - this.manifestFetchedAt >= 10000) {
      this.manifestFetchedAt = performance.now();
      this.manifestKey = key; this.loading = !this.liveOverride && !this.enabled;
      void this.loadManifest(projection, key);
    }
  }

  private async loadManifest(projection: Projection, key: string): Promise<void> {
    try {
      const result = await this.services.get<{ recordings: SavedInvestigation[] }>(
        `/api/replays/${encodeURIComponent(projection.replay.id)}/recordings`);
      if (this.manifestKey !== key) return;
      if (!Array.isArray(result.recordings)) throw new Error("Invalid recording manifest; no results substituted.");
      this.rows = result.recordings;
      if (!this.liveOverride) await this.enable();
      else this.description = this.rows.length
        ? `${this.rows.length} preserved runs available. Live results are saved separately.`
        : "No compatible saved investigations. Live monitoring remains available.";
    } catch (error) {
      if (this.manifestKey !== key) return;
      this.description = "Recording library unavailable; no results substituted.";
      this.services.error(error);
    } finally {
      if (this.manifestKey === key) {
        this.loading = false; this.services.changed();
      }
    }
  }

  // Pause backend ingestion before starting the independent local navigation clock.
  async enable(): Promise<void> {
    const replayId = this.projection?.replay.id;
    try {
      await this.services.pauseLive();
      if (this.projection?.replay.id !== replayId) return;
      this.enabled = true; this.liveOverride = false;
      this.services.changed(); this.render();
    } catch (error) {
      this.description = "Could not pause live ingestion; recording playback has not started.";
      this.services.error(error);
    }
  }
  useLive(): void {
    this.stop(); this.enabled = false; this.liveOverride = true;
    this.requested = ""; this.version++; this.frameLoading = false;
  }
  checkpoints(): SavedInvestigation[] {
    return this.rows;
  }
  currentFrame(): RecordedFrame | null {
    return this.enabled ? this.frames.get(this.requested) || null : null;
  }
  stop(): void {
    this.advance();
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null; this.playing = false;
  }
  // Stop at each measurement hop/checkpoint and discard loading time instead of
  // catching up later. Speed is a maximum navigation pace, not model acceleration.
  private advance(): void {
    if (!this.playing) return;
    this.dataChanged();
    const now = performance.now();
    if (!this.waiting) {
      const hop = this.projection?.pack.hop_seconds || 5;
      const nextWindow = (Math.floor(this.seconds / hop) + 1) * hop;
      const nextRecording = Math.min(...this.rows.filter(row => row.source_seconds > this.seconds)
        .map(row => row.source_seconds));
      // The walkthrough is the authored six-minute timeline, not a live clock.
      this.seconds = Math.min(360, nextWindow, nextRecording,
        this.seconds + (now - this.anchor) * this.speed / 1000);
    }
    this.anchor = now;
  }
  setSpeed(speed: number): void {
    this.advance();
    this.speed = speed;
  }
  play(): void {
    if (this.playing) this.stop();
    else {
      if (this.seconds >= 360) this.seconds = 0;
      this.anchor = performance.now();
      this.playing = true;
      this.timer = setInterval(() => {
        this.advance();
        this.render(); this.services.changed();
        if (this.seconds >= 360) { this.stop(); this.services.changed(); }
      }, 250);
    }
    this.services.changed();
  }
  seek(seconds: number): void {
    this.stop(); this.seconds = Math.max(0, Math.min(360, seconds));
    this.render(); this.services.changed();
  }
  render(): void {
    if (!this.enabled) return;
    const row = availableRecording(this.rows, this.seconds);
    const counts = `${new Set(this.rows.map(item => item.source_seconds)).size} checkpoints · ${this.rows.length} preserved attempts`;
    this.description = row
      ? `5× base recording · ${counts} · showing ${row.state} +${row.source_seconds}s evidence. Between checkpoints the original evidence time is retained. Playback makes no model calls.`
      : `No saved investigation at or before +${this.seconds.toFixed(1)}s. Later findings are withheld. Playback makes no model calls.`;
    if (row) {
      void this.show(row);
    } else {
      this.services.metrics(null, null, true, this.projection?.server_time || new Date().toISOString());
      this.requested = ""; this.version++; this.frameLoading = false;
      box("automatic-state").textContent = "RECORDED · awaiting first saved checkpoint";
      delete box("automatic-state").dataset.task;
      box("automatic-timeline").replaceChildren();
      box("automatic-actions").replaceChildren();
      renderIdleAgentWork(box("automatic-progress"), box("agent-findings"), true);
      box("agent-investigation-map").replaceChildren(node("p", "No earlier accepted evidence. Advance to a recorded checkpoint."));
      box("automatic-conclusion").textContent = "No accepted report at this recording time.";
      box("automatic-conclusion").hidden = false;
    }
  }
  /** Fetch/cache one preserved frame; version checks prevent late reads replacing a new selection. */
  private async show(row: SavedInvestigation): Promise<void> {
    if (!this.projection || this.requested === row.task_id) return;
    this.requested = row.task_id;
    this.frameLoading = true;
    const version = ++this.version, replay = this.projection.replay;
    box("automatic-state").textContent = `RECORDED · loading ${row.state} evidence +${row.source_seconds}s`;
    delete box("automatic-state").dataset.task;
    this.services.metrics(null, null, true, this.projection.server_time);
    renderIdleAgentWork(box("automatic-progress"), box("agent-findings"), true);
    box("agent-investigation-map").replaceChildren(node("p", "Loading timestamp-bound evidence. Previous findings withheld."));
    box("automatic-actions").replaceChildren();
    box("automatic-conclusion").hidden = false;
    box("automatic-conclusion").textContent = "No report shown while the selected evidence loads.";
    try {
      let frame = this.frames.get(row.task_id);
      if (!frame) {
        frame = await this.services.get<RecordedFrame>(
          `/api/replays/${encodeURIComponent(replay.id)}/recordings/${encodeURIComponent(row.task_id)}`);
        if (frame.snapshot.id !== row.snapshot_id || frame.snapshot.input_hash !== row.input_hash
          || frame.detail.task.id !== row.task_id || frame.detail.task.snapshot_id !== frame.snapshot.id
          || frame.pack.version !== this.projection.pack.version) throw new Error("Recorded investigation scope mismatch");
        this.frames.set(row.task_id, frame);
      }
      if (version !== this.version || !this.enabled) return;
      const tasks = [frame.detail.task, ...frame.detail.children];
      renderAgentWork(box("automatic-progress"), box("agent-findings"), frame.detail.task,
        tasks, frame.detail, frame.snapshot, null, () => {});
      for (const control of box("automatic-progress").querySelectorAll("button")) {
        if (control.textContent === "Open executed receipts") control.hidden = true;
      }
      box("automatic-conclusion").hidden = Boolean(frame.detail.casefile);
      box("automatic-conclusion").textContent = frame.detail.casefile ? ""
        : `No accepted report: ${frame.detail.task.error_message || frame.detail.task.state}. Saved trial only; not safety clearance.`;
      box("automatic-timeline").replaceChildren();
      box("automatic-state").dataset.task = frame.detail.task.id;
      box("automatic-state").textContent = `RECORDED · ${frame.detail.task.state} · evidence +${row.source_seconds}s`;
      this.services.metrics(frame.detail.task, frame.detail.execution_usage || null, true,
        this.projection.server_time);
      box("automatic-actions").replaceChildren(node("p",
        "Preserved source-specific investigation. This is not a new live decision.", "muted"));
      this.draw(frame.pack, frame.snapshot, frame.detail);
      this.services.changed();
    } catch (error) {
      if (version !== this.version) return;
      this.stop();
      this.services.metrics(null, null, true, this.projection.server_time);
      box("automatic-state").textContent = "RECORDED · evidence unavailable";
      delete box("automatic-state").dataset.task;
      box("automatic-conclusion").hidden = false;
      box("automatic-conclusion").textContent = "Recorded evidence could not be loaded; no report or safety clearance is implied.";
      box("agent-investigation-map").replaceChildren(node("p", "Recorded evidence unavailable. No map inferred."));
      renderIdleAgentWork(box("automatic-progress"), box("agent-findings"), true);
      this.services.error(error);
    } finally {
      if (version === this.version) {
        this.frameLoading = false;
        this.services.changed();
      }
    }
  }
  draw(pack: SitePack, snapshot: WindowSnapshot | null, detail: TaskDetail | null): void {
    const container = box("agent-investigation-map");
    if (!snapshot) { container.replaceChildren(node("p", "Awaiting investigation evidence.")); return; }
    const map = svg("svg", { viewBox: "0 0 760 520", role: "group", "aria-label": "Dedicated agent investigation pipeline map" });
    const warming = snapshot.quality.status === "WARMING_UP";
    const basis = node("p", warming
      ? `Collecting a complete ${pack.window_seconds}-second monitoring window · sensors not assessed yet · no agent findings`
      : `Evidence +${snapshot.end_seconds}s · ${detail?.task.state === "ABSTAINED"
        ? "abstained report; cause and location not established"
        : detail?.casefile ? "accepted report" : "no accepted report; measured flags only"}`, "spatial-findings-basis");
    const extraction = detail?.output_mapping;
    const mapping = extraction?.status === "completed" ? extraction.mapping : null;
    const mappingStatus = node("p", !detail?.casefile ? ""
      : detail.task.state === "ABSTAINED"
        ? "No diagnosis overlay: this report abstained. Measurement gaps remain visible; no map extraction is pending."
      : extraction?.status === "failed"
        ? `Agent-label extraction failed (${extraction.error_code || "invalid output"}). No instrument findings inferred from detector flags.`
        : !mapping ? "Agent-label extraction is not available yet. Measured alerts are not agent instrument diagnoses."
          : `Agent-text extraction · ${mapping.sensor_issues.length} instrument issue labels · exact quoted findings; no detector-based fault inference.`, "spatial-findings-basis");
    const selected = node("p", "Select an instrument for the agent's quoted finding and measured pressure evidence.", "muted");
    const draw = (): void => drawInvestigationMap(map, pack, snapshot, detail?.casefile || null,
      this.selectedSensor, id => {
        this.selectedSensor = id; draw();
        const issues = mapping?.sensor_issues.filter(issue => issue.sensor_id === id) || [];
        const agentText = issues.length ? issues.map(issue =>
          `Agent finding: ${issue.kind} (${issue.assertion}) — ${issue.quote.text}`).join(" ") : "No extracted agent instrument issue.";
        if (!sensorAssessment(snapshot, id).assessed) {
          selected.textContent = `${id} · not assessed; waiting for a complete sensor assessment. ${agentText}`;
          return;
        }
        const evidence = Object.values(snapshot.evidence).find(item => item.kind === "channel_summary" && item.sensor_id === id);
        const value = evidence?.value;
        selected.textContent = value && typeof value === "object" && !Array.isArray(value)
          ? `${id} · normal reference ${value.baseline_median ?? "unavailable"} bar · final-five-second deficit ${value.recent_5s_pressure_drop_bar ?? "unavailable"} bar. ${agentText}`
          : `${id} · no pressure summary supplied. ${agentText}`;
      }, extraction || null);
    draw();
    const legendKinds = warming ? ["unknown", "selection"] : [
      "anomaly", "missing", "normal", "selection", "unknown",
      ...(map.querySelector(".eval-leak-pattern") ? ["pattern"] : []),
      ...(map.querySelector(".eval-inspection") ? ["inspection"] : []),
      ...(map.querySelector(".eval-agent-issue") ? ["agent"] : []),
    ];
    container.replaceChildren(node("h3", "Agent findings · pipeline map"), basis, mappingStatus, map,
      mapLegend(false, { label: "Agent investigation map legend", unknown: true,
        visibleKinds: legendKinds }), selected, node("p",
        "Orange dots = measured alerts; red pipe = extracted suspected-leak finding; purple rings = extracted instrument issues. Missing-only readings are not a hardware-fault diagnosis. Green band = report-stated inspection interval, not a confirmed leak point or site authorization.", "muted"));
    const usage = extraction?.execution_usage;
    if (usage) container.append(node("p",
      `Presentation extraction: ${usage.reported_calls ? `${usage.total_tokens.toLocaleString()} additional tokens (${usage.reported_calls}/${usage.reserved_calls} calls report usage)` : "token usage unavailable"} · ${usage.cost_usd == null ? "cost unavailable" : `$${usage.cost_usd.toFixed(4)} OpenAI Standard API equivalent`}. Separate from investigation counters; recorded playback makes no new calls.`, "muted"));
  }
  async investigate(seconds = this.seconds): Promise<void> {
    if (seconds < 60) return;
    this.stop(); this.services.changed();
    try { await this.services.liveHere(Math.floor(seconds / 5) * 5); }
    catch (error) {
      this.services.error(new Error(`Live investigation could not start; saved runs remain preserved. ${error instanceof Error ? error.message : "Backend unavailable"}`));
    }
  }
}
