"""Synthetic, read-only inspection prioritization; never changes production leak claims."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, SitePack, WindowSnapshot
from .diagnostics import analyze_window
from .ingest import normalize_records
from .localization import locate
from .synthetic import generate_scenario
from .validation import ValidationError

CASE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "synthetic"
    / ("localization-context-cases.json")
)


class ContextRecord(Contract):
    id: str
    assets: list[str]
    available: int = Field(ge=0)
    effective: int = Field(ge=0)
    status: Literal["approved", "draft", "superseded"]
    body: str
    supersedes: str | None = None


class InspectionCase(Contract):
    id: str
    split: Literal["development", "held_out"]
    segments: list[Literal["P1", "P2", "P3"]]
    expected_first: list[Literal["P1", "P2", "P3"]]
    records: list[ContextRecord]
    missing_sensors: list[str] = Field(default_factory=list)
    affected_sensors: list[str] | None = None
    fault_sensor: str | None = None

    @model_validator(mode="after")
    def consistent_expectation(self) -> InspectionCase:
        if not set(self.expected_first) <= set(self.segments):
            raise ValueError("Expected inspection areas must have a simulated pressure signal")
        if len(set(self.segments)) != len(self.segments):
            raise ValueError("Duplicate signal segment")
        if len({record.id for record in self.records}) != len(self.records):
            raise ValueError("Duplicate context record")
        return self


class InspectionSuite(Contract):
    version: str
    scope: str
    cases: list[InspectionCase]


class InspectionCandidate(Contract):
    segment_id: str
    inspection_start_m: float
    inspection_end_m: float
    supporting_sensors: list[str]


class Demotion(Contract):
    segment_id: str
    document_ids: list[str] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=1, max_length=600)


class InspectionDecision(Contract):
    first_priority: list[str] = Field(max_length=3)
    deprioritized: list[Demotion] = Field(max_length=3)
    explanation: str = Field(min_length=1, max_length=1500)


def load_inspection_suite() -> InspectionSuite:
    return InspectionSuite.model_validate_json(CASE_PATH.read_text(encoding="utf-8"))


def case_snapshot(case: InspectionCase) -> tuple[SitePack, WindowSnapshot]:
    source = generate_scenario("S6", duration_seconds=180)
    sensors = {sensor.id: sensor for sensor in source.pack.sensors}
    unknown = (
        set(case.missing_sensors)
        | set(case.affected_sensors or [])
        | ({case.fault_sensor} if case.fault_sensor else set())
    ) - sensors.keys()
    if unknown:
        raise ValueError(f"Unknown benchmark sensors: {sorted(unknown)}")
    records = []
    factors = {"bar": 1.0, "kPa": 0.01, "MPa": 10.0}
    for row in source.records:
        # Source clocks and dirty values retain the existing ingestion path.
        sensor = sensors[row.sensor_id]
        second = int(row.source_record_id.split(":")[1])
        if second >= 90 and row.sensor_id in case.missing_sensors:
            continue
        value = row.value
        active = (
            row.sensor_id in case.affected_sensors
            if case.affected_sensors is not None
            else sensor.segment_id in case.segments and sensor.chainage_m in {300, 500}
        )
        if second >= 90 and active and value is not None:
            value = float(value) - 1.0 / factors[row.unit]
        if row.sensor_id == case.fault_sensor and second >= 90 and second % 4 == 0:
            value = "-9999"
        records.append(
            row.model_copy(
                update={"value": value, "source_record_id": case.id + ":" + row.source_record_id}
            )
        )
    return source.pack, analyze_window(
        source.pack,
        normalize_records(source.baseline, source.pack),
        normalize_records(records, source.pack),
        case.id,
        180,
        185,
        source.epoch,
    )


def inspection_candidates(pack: SitePack, snapshot: WindowSnapshot) -> list[InspectionCandidate]:
    """Conditional per-segment fits; not an override of the global event/claim gate."""
    summaries = {
        evidence.sensor_id: evidence.value
        for evidence in snapshot.evidence.values()
        if evidence.kind == "channel_summary" and isinstance(evidence.value, dict)
    }
    deficits, scales, weights = {}, {}, {}
    for finding in snapshot.quality.findings:
        summary = summaries.get(finding.sensor_id)
        if not isinstance(summary, dict) or finding.peer_disagreement:
            continue
        deficit = summary.get("median_pressure_drop_bar")
        scale = summary.get("baseline_scale")
        persistence = summary.get("pressure_drop_persistence_seconds")
        if (
            not isinstance(deficit, (int, float))
            or not isinstance(scale, (int, float))
            or not isinstance(persistence, (int, float))
            or (
                persistence < pack.persistence_seconds
                and finding.persistence_seconds >= pack.persistence_seconds
            )
        ):
            continue
        deficits[finding.sensor_id] = float(deficit)
        scales[finding.sensor_id] = float(scale)
        weights[finding.sensor_id] = finding.usable / finding.expected
    candidates = []
    for segment in pack.segments:
        fit = locate(pack, deficits, scales, [segment.id], weights)
        if (
            fit.status == "located"
            and fit.inspection_start_m is not None
            and fit.inspection_end_m is not None
        ):
            candidates.append(
                InspectionCandidate(
                    segment_id=segment.id,
                    inspection_start_m=fit.inspection_start_m,
                    inspection_end_m=fit.inspection_end_m,
                    supporting_sensors=[
                        sensor.id
                        for sensor in pack.sensors
                        if sensor.segment_id == segment.id
                        and weights.get(sensor.id, 0) >= pack.min_coverage
                        and deficits.get(sensor.id, 0)
                        >= pack.anomaly_threshold * scales.get(sensor.id, float("inf"))
                    ],
                )
            )
    return candidates


def visible_records(case: InspectionCase) -> list[ContextRecord]:
    return [
        record for record in case.records if record.available <= 185 and record.effective <= 185
    ]


def authoritative_records(records: list[ContextRecord]) -> list[ContextRecord]:
    records = [record for record in records if record.available <= 185 and record.effective <= 185]
    replaced = {record.supersedes for record in records if record.status == "approved"}
    return [
        record for record in records if record.status == "approved" and record.id not in replaced
    ]


# Frozen, conservative lexical policy. No test-set-specific document IDs or outcomes.
EXECUTED = re.compile(r"\b(performed|executed|completed|carried out|applied|implemented)\b")
COUNTEREVIDENCE = re.compile(
    r"\b(not performed|not executed|not carried out|cancelled|canceled|pending|proposed|"
    r"planned|unchanged|untouched|held constant|last week|isolated|cannot account|"
    r"cannot explain|conflict|contradict|skid|transcription error)\b"
)


def fixed_inspection_baseline(
    candidates: list[InspectionCandidate], records: list[ContextRecord]
) -> InspectionDecision:
    current = authoritative_records(records)
    first, demotions = [], []
    for candidate in candidates:
        relevant = [record for record in current if candidate.segment_id in record.assets]
        conflicting = any(COUNTEREVIDENCE.search(record.body.lower()) for record in relevant)
        executed = [record for record in relevant if EXECUTED.search(record.body.lower())]
        if executed and not conflicting:
            demotions.append(
                Demotion(
                    segment_id=candidate.segment_id,
                    document_ids=[record.id for record in executed],
                    reason="Current matching approved operation with explicit execution language.",
                )
            )
        else:
            first.append(candidate.segment_id)
    return InspectionDecision(
        first_priority=first,
        deprioritized=demotions,
        explanation=(
            "Frozen context-aware policy checks visibility, approval, supersession, asset tags, "
            "execution phrases and counterevidence. Ambiguity retains priority; no leak clearance."
        ),
    )


def validate_inspection_decision(
    decision: InspectionDecision,
    candidates: list[InspectionCandidate],
    records: list[ContextRecord],
) -> None:
    eligible = {candidate.segment_id for candidate in candidates}
    first = set(decision.first_priority)
    demoted = {item.segment_id for item in decision.deprioritized}
    if (
        len(first) != len(decision.first_priority)
        or len(demoted) != len(decision.deprioritized)
        or first & demoted
        or first | demoted != eligible
    ):
        raise ValidationError("inspection_partition", "Partition exactly the computed candidates")
    approved = {record.id: record for record in authoritative_records(records)}
    for item in decision.deprioritized:
        if len(set(item.document_ids)) != len(item.document_ids):
            raise ValidationError("inspection_citation", "Duplicate document citation")
        if any(
            doc_id not in approved or item.segment_id not in approved[doc_id].assets
            for doc_id in item.document_ids
        ):
            raise ValidationError("inspection_citation", "Unapproved or wrong-asset citation")
