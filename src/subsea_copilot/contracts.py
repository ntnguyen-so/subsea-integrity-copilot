"""Shared data contracts: scope and numerical evidence are application-owned."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Channel = Literal["pressure", "acoustic", "methane", "temperature"]
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
    return ["pressure"]


def default_scales() -> dict[Channel, float]:
    return {"pressure": 0.04, "acoustic": 0.03, "methane": 0.015, "temperature": 0.03}


class Point(Contract):
    x: float
    y: float


class PipelineSegment(Contract):
    id: str
    name: str = ""
    points: list[Point]
    length_m: float
    diameter_m: float = Field(default=0.6, gt=0)


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
    name: str = "NorthSea Pressure Monitoring Network"
    version: str = "pressure-pack-v3"
    sensors: list[Sensor]
    segments: list[PipelineSegment]
    sample_seconds: int = 1
    window_seconds: int = 60
    hop_seconds: int = 5
    lateness_seconds: int = 5
    revision_seconds: int = 120
    min_observers: int = 3
    min_failure_domains: int = 2
    min_stations: int = 2
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
    peer_disagreement: bool = False
    anomaly_count: int = 0
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
    criteria_id: str = "pressure-investigation-v2"


class LocationCandidate(Contract):
    segment_id: str
    chainage_m: float
    position: Point
    residual: float | None = None
    strength: float | None = None


class LocationFit(Contract):
    status: Literal["located", "ambiguous", "withheld"]
    best: LocationCandidate | None = None
    compatible: list[LocationCandidate] = Field(default_factory=list)
    reason: str
    method: str = "pressure-alert-bracket-v2"
    grid_m: float = 0
    inspection_start_m: float | None = None
    inspection_end_m: float | None = None
    station_bracket_m: list[float] = Field(default_factory=list)


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
    baseline_version: str = "pressure-median-mad-v2"
    parameter_version: str = "pressure-window-v2"
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
    source_version: Literal["legacy-v1", "pressure-v2", "pressure-v3"] = "legacy-v1"
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


class HistoryInvestigation(Contract):
    assessment: Literal["operating_change_plausible", "instrumentation_context", "unresolved"]
    document_ids: list[str] = Field(default_factory=list, max_length=3)
    rejected_document_ids: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Only successfully history.read documents with admissible=false. "
            "Search-only hits must not appear here; use an empty list if none were fully read."
        ),
    )
    comparison_call_ids: list[str] = Field(default_factory=list, max_length=2)
    next_action: Literal[
        "check_operating_records",
        "review_instrumentation",
        "inspect_supported_interval",
        "restore_telemetry",
        "human_review",
    ] = "human_review"


class CitedExplanation(Contract):
    text: str = Field(min_length=1, max_length=600)
    references: list[str] = Field(min_length=1, max_length=6)


class CauseExplanation(CitedExplanation):
    cause: Literal["leak", "operating_change", "instrumentation_or_telemetry"]
    stance: Literal["possible", "not_established", "not_testable"]


class EngineerInterpretation(Contract):
    focus: Literal[
        "root_cause",
        "operating_context",
        "sensor_quality",
        "inspection_rationale",
        "evidence_gaps",
    ]
    answer: CitedExplanation
    competing_causes: list[CauseExplanation] = Field(min_length=1, max_length=3)
    follow_up_questions: list[
        Annotated[str, Field(min_length=1, max_length=200, pattern=r"\?\s*$")]
    ] = Field(min_length=1, max_length=3)


class AgentResult(Contract):
    outcome: Literal["supported", "insufficient_evidence"]
    claim_refs: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str]
    hypothesis: Hypothesis | None = None
    recommendation_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    investigation: HistoryInvestigation | None = None
    interpretation: EngineerInterpretation | None = None


class GroundingSupport(Contract):
    reference: str
    quote: str = Field(min_length=8, max_length=500)


class GroundingCheck(Contract):
    paragraph_id: str = Field(min_length=1, max_length=50)
    verdict: Literal["supported", "unsupported", "uncertain"]
    reason: str = Field(min_length=1, max_length=350)
    support: list[GroundingSupport] = Field(default_factory=list, max_length=4)


class GroundingAssessment(Contract):
    decision: Literal["accept", "revise"]
    checks: list[GroundingCheck] = Field(min_length=3, max_length=7)


class GroundingRound(Contract):
    candidate_hash: str
    assessment: GroundingAssessment


class InterpretationReview(Contract):
    protocol: Literal["grounding-v1"] = "grounding-v1"
    source_hash: str
    rounds: list[GroundingRound] = Field(min_length=1, max_length=2)


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
    history_version: str | None = None
    response_protocol: Literal["engineer-v1", "engineer-v2"] | None = None
    interpretation_review: InterpretationReview | None = None


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
