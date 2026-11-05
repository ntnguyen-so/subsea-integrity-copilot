export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Channel = "acoustic" | "methane" | "temperature";
export type Mode = "scripted" | "live";
export type Speed = 1 | 2 | 5 | 10;
export interface Point { x: number; y: number }
export interface Sensor { id: string; station_id: string; segment_id: string; chainage_m: number; position: Point; failure_domain_id: string; channels: Channel[] }
export interface SitePack {
  id: string; name: string; version: string; sensors: Sensor[];
  segments: { id: string; points: Point[]; length_m: number }[];
  sample_seconds: number; window_seconds: number; hop_seconds: number; lateness_seconds: number;
  min_observers: number; min_failure_domains: number; min_coverage: number;
}
export interface RawRecord { sensor_id: string; channel: Channel; observed_at: string; received_at: string; value: number | string | null; unit: string; source_id: string; source_record_id: string }
export interface CanonicalObservation { id: string; identity: string; sensor_id: string; channel: Channel; observed_at: string; received_at: string; value: number | null; unit: string; validity: string; source_id: string; source_record_id: string; original: RawRecord; transformations: string[] }
export interface QualityFinding { sensor_id: string; channel: Channel; expected: number; received: number; usable: number; missing: number; hard_excluded: number; spike_count: number; drift_suspected: boolean; max_score: number; persistence_seconds: number; evidence_ids: string[] }
export interface EvidenceItem { id: string; kind: string; sensor_id: string | null; channel: Channel | null; value: Json }
export interface Claim { id: string; kind: string; value: Json; evidence_ids: string[] }
export interface LocationCandidate { segment_id: string; chainage_m: number; position: Point; residual: number; strength: number }
export interface WindowSnapshot {
  id: string; site_id: string; generation_id: string; window_start: string; window_end: string;
  end_seconds: number; revision: number; predecessor_id: string | null; input_hash: string;
  pack_version: string; baseline_version: string; parameter_version: string;
  clock_seconds: number; watermark_seconds: number; created_at: string; canonical_count: number;
  quality: { status: string; expected_samples: number; received_samples: number; usable_samples: number; coverage: number; failure_domains_available: number; findings: QualityFinding[]; conflicts: string[]; issues: string[] };
  event: { hypothesis: string; eligible_hypotheses: string[]; supporting_sensor_ids: string[]; failure_domain_count: number; persistence_seconds: number; segment_ids: string[]; evidence_ids: string[]; counterevidence: string[]; eligible_location: boolean; criteria_id: string };
  location: { status: string; best: LocationCandidate | null; compatible: LocationCandidate[]; reason: string; method: string; grid_m: number } | null;
  evidence: Record<string, EvidenceItem>; claims: Record<string, Claim>;
}
export interface ReplaySession { id: string; site_id: string; scenario: string; seed: number; mode: Mode; state: "PAUSED" | "PLAYING" | "COMPLETED" | "FAILED"; clock_seconds: number; speed: Speed; duration_seconds: number; epoch: string; latest_window_id: string | null; version: number; updated_at: string; error: string | null }
export interface MonitoringEpisode { id: string; site_id: string; generation_id: string; state: string; hypothesis: string; basis_window_id: string; current_window_id: string; segment_ids: string[]; material_revision: number; pending_window_id: string | null; auto_roots: number; dispatch_status: string | null }
export interface AgentResult { outcome: string; claim_refs: string[]; evidence_ids: string[]; limitations: string[]; hypothesis: string | null; recommendation_ids: string[]; summary: string }
export interface AgentTask { id: string; root_id: string; site_id: string; generation_id: string; snapshot_id: string; episode_id: string | null; parent_id: string | null; role: string; purpose: string; question: string; mode: Mode; state: string; created_at: string; updated_at: string; model_calls: number; tool_calls: number; result: AgentResult | null; answer: string | null; error_code: string | null; error_message: string | null; automatic: boolean }
export interface ConsoleEvent { id: number; site_id: string; generation_id: string; type: string; created_at: string; simulated_seconds: number | null; snapshot_id: string | null; task_id: string | null; payload: Record<string, Json> }
export interface Session { authenticated: boolean; csrf_token: string | null; username: string | null }
export interface Projection { replay: ReplaySession; pack: SitePack; latest_window: WindowSnapshot | null; episodes: MonitoringEpisode[]; tasks: AgentTask[]; cursor: number; health: { agent: string; observability: Record<string, Json>; monitor: string }; server_time: string }
export interface TaskDetail { task: AgentTask; children: AgentTask[]; receipts: Record<string, Json>[] }
