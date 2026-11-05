"""Shared data contracts: scope and numerical evidence are application-owned."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Channel = Literal["acoustic", "methane", "temperature"]
Hypothesis = Literal[
    "suspected_leak",
    "sensor_or_telemetry_issue",
    "environmental_disturbance",
    "no_event",
    "insufficient_evidence",
]
AgentRole = Literal["sensor_quality", "event_diagnosis", "operator_response"]
Mode = Literal["scripted", "live"]
TaskState = Literal[
    "QUEUED", "RUNNING", "WAITING_ON_CHILD", "SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def content_hash(value: JsonValue) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def default_channels() -> list[Channel]:
    return ["acoustic", "methane", "temperature"]


def default_scales() -> dict[Channel, float]:
    return {"acoustic": 0.03, "methane": 0.015, "temperature": 0.03}


class Point(Contract):
    x: float
    y: float


class PipelineSegment(Contract):
    id: str
    points: list[Point]
    length_m: float


class Sensor(Contract):
    id: str
    station_id: str
    segment_id: str
    chainage_m: float
    position: Point
    failure_domain_id: str
    channels: list[Channel] = Field(default_factory=default_channels)


class SitePack(Contract):
    id: str = "northsea"
    name: str = "NorthSea Synthetic Gas Network"
    version: str = "pack-v1"
    sensors: list[Sensor]
    segments: list[PipelineSegment]
    sample_seconds: int = 1
    window_seconds: int = 60
    hop_seconds: int = 5
    lateness_seconds: int = 5
    revision_seconds: int = 120
    min_observers: int = 3
    min_failure_domains: int = 2
    min_coverage: float = 0.6
    persistence_seconds: int = 15
    quiet_seconds: int = 30
    neighborhood_m: float = 400
    methane_lag_seconds: int = 25
    anomaly_threshold: float = 5
    minimum_scales: dict[Channel, float] = Field(default_factory=default_scales)
    location_grid_m: float = 25
    location_r0_m: float = 40
    compatible_residual_tolerance: float = 2
    max_location_width_m: float = 400


class RawRecord(Contract):
    sensor_id: str
    channel: Channel
    observed_at: str
    received_at: str
    value: float | str | None
    unit: str
    source_id: str = "synthetic-gateway"
    source_record_id: str


class CanonicalObservation(Contract):
    id: str
    identity: str
    sensor_id: str
    channel: Channel
    observed_at: datetime
    received_at: datetime
    value: float | None
    unit: str
    validity: Literal["usable", "missing", "malformed", "conflicted", "impossible"]
    source_id: str
    source_record_id: str
    original: RawRecord
    transformations: list[str] = Field(default_factory=list)


class QualityFinding(Contract):
    sensor_id: str
    channel: Channel
    expected: int
    received: int
    usable: int
    missing: int
    hard_excluded: int = 0
    spike_count: int = 0
    drift_suspected: bool = False
    max_score: float = 0
    persistence_seconds: float = 0
    evidence_ids: list[str] = Field(default_factory=list)


class QualityReport(Contract):
    status: Literal["WARMING_UP", "NORMAL", "DEGRADED", "COVERAGE_LOST"]
    expected_samples: int
    received_samples: int
    usable_samples: int
    coverage: float
    failure_domains_available: int
    findings: list[QualityFinding]
    conflicts: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class EventAssessment(Contract):
    hypothesis: Hypothesis
    eligible_hypotheses: list[Hypothesis]
    supporting_sensor_ids: list[str] = Field(default_factory=list)
    failure_domain_count: int = 0
    persistence_seconds: float = 0
    segment_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    counterevidence: list[str] = Field(default_factory=list)
    eligible_location: bool = False
    criteria_id: str = "event-rules-v1"


class LocationCandidate(Contract):
    segment_id: str
    chainage_m: float
    position: Point
    residual: float
    strength: float


class LocationFit(Contract):
    status: Literal["located", "ambiguous", "withheld"]
    best: LocationCandidate | None = None
    compatible: list[LocationCandidate] = Field(default_factory=list)
    reason: str
    method: str = "acoustic-excess-distance-decay-v1"
    grid_m: float = 25


class EvidenceItem(Contract):
    id: str
    kind: str
    sensor_id: str | None = None
    channel: Channel | None = None
    value: JsonValue


class Claim(Contract):
    id: str
    kind: Literal["coverage", "sensor_health", "hypothesis", "location", "limitation"]
    value: JsonValue
    evidence_ids: list[str] = Field(default_factory=list)


class WindowSnapshot(Contract):
    id: str
    tenant_id: str = "demo"
    site_id: str
    generation_id: str
    window_start: datetime
    window_end: datetime
    end_seconds: int
    revision: int = 1
    predecessor_id: str | None = None
    input_hash: str
    pack_version: str
    baseline_version: str = "baseline-v1"
    parameter_version: str = "window-v1"
    clock_seconds: float
    watermark_seconds: float
    created_at: datetime = Field(default_factory=utc_now)
    canonical_count: int
    quality: QualityReport
    event: EventAssessment
    location: LocationFit | None = None
    evidence: dict[str, EvidenceItem] = Field(default_factory=dict)
    claims: dict[str, Claim] = Field(default_factory=dict)


class ReplaySession(Contract):
    id: str
    tenant_id: str = "demo"
    site_id: str = "northsea"
    scenario: str
    seed: int = 2026
    mode: Mode = "scripted"
    state: Literal["PAUSED", "PLAYING", "COMPLETED", "FAILED"] = "PAUSED"
    clock_seconds: float = 0
    speed: Literal[1, 2, 5, 10] = 1
    duration_seconds: int = 360
    epoch: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    latest_window_id: str | None = None
    last_endpoint: int = 0
    version: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    error: str | None = None


class MonitoringEpisode(Contract):
    id: str
    tenant_id: str = "demo"
    site_id: str
    generation_id: str
    state: Literal["CANDIDATE", "ACTIVE", "QUIET", "COVERAGE_LOST", "SUPERSEDED_BY_REVISION"]
    hypothesis: Hypothesis
    basis_window_id: str
    current_window_id: str
    segment_ids: list[str] = Field(default_factory=list)
    first_seen_seconds: int
    last_qualified_seconds: int
    material_revision: int = 1
    pending_window_id: str | None = None
    auto_roots: int = 0
    dispatch_status: str | None = None


class AgentResult(Contract):
    outcome: Literal["supported", "insufficient_evidence"]
    claim_refs: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str]
    hypothesis: Hypothesis | None = None
    recommendation_ids: list[str] = Field(default_factory=list)
    summary: str = ""


class AgentTask(Contract):
    id: str
    root_id: str
    tenant_id: str = "demo"
    site_id: str
    generation_id: str
    snapshot_id: str
    episode_id: str | None = None
    parent_id: str | None = None
    role: AgentRole
    purpose: str
    question: str
    mode: Mode
    state: TaskState = "QUEUED"
    version: int = 1
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    deadline: datetime
    model_calls: int = 0
    tool_calls: int = 0
    plan: list[Literal["quality", "diagnosis", "answer", "reuse"]] = Field(default_factory=list)
    result: AgentResult | None = None
    answer: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    automatic: bool = False
    idempotency_key: str | None = None


class ConsoleEvent(Contract):
    id: int
    tenant_id: str
    site_id: str
    generation_id: str
    type: str
    created_at: datetime
    simulated_seconds: float | None = None
    snapshot_id: str | None = None
    task_id: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
