"""Author and verify four frozen pressure examples before running any agents.

The versioned recipe supplies source truth and expected outcomes on the 24-tap Y
network. Seeded Gaussian spatial deficits, isolated spikes, gaps and invalid values
produce ordinary RawRecords; only ReplayDataset crosses the runtime boundary.
The manifest keeps recipe/source labels, content hashes, measured diagnostic outputs
and explicit checks separate. These are illustrative synthetic patterns, not observed
field leaks or a calibrated transient hydraulic model.
"""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import RawRecord, Sensor, content_hash
from .diagnostics import analyze_window
from .ingest import normalize_records
from .localization import pipeline_distances, point_at_chainage
from .replay_sources import source_payload
from .synthetic import ReplayDataset, generate_pack

CASES_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "golden" / "cases-v1.json"
VERSION = "golden-pressure-v1"


def load_cases() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if value["version"] != VERSION or len(value["cases"]) != 4:
        raise ValueError("Unrecognized golden recipe version")
    return value


def generate_golden(
    case: dict[str, Any], seed: int = 20261107, duration_seconds: int = 120,
    site_id: str = "northsea",
) -> ReplayDataset:
    """Generate a 60-second normal preroll plus a seeded post-start recording.

    The source is active at t=0, making the first complete window mature. Network
    distance controls the Gaussian deficit; gap/invalid/spike schedules are authored.
    No truth fields, case IDs or scenario names are emitted in measurement records.
    """
    if duration_seconds < 60:
        raise ValueError("Golden datasets require a complete 60-second window")
    pack = generate_pack(site_id)
    rng = random.Random(seed)
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    baseline: list[RawRecord] = []
    records: list[RawRecord] = []
    source = case["source"]
    distances: dict[str, float] = {}
    if source:
        segment = next(s for s in pack.segments if s.id == source["segment_id"])
        probe = Sensor(
            id="source-only", station_id="source-only", segment_id=segment.id,
            chainage_m=source["chainage_m"],
            position=point_at_chainage(segment, source["chainage_m"]),
            failure_domain_id="source-only",
        )
        routes = pipeline_distances(pack.model_copy(update={"sensors": [*pack.sensors, probe]}))
        distances = {s.id: routes[probe.id, s.id] for s in pack.sensors}
    spikes = {item["sensor_id"]: item["phase_seconds"] for item in case["spikes"]}
    for second in range(-60, duration_seconds):
        for sensor in pack.sensors:
            center = 80 - sensor.chainage_m * 0.001 - (0.8 if sensor.segment_id != "P1" else 0)
            numeric_value = center + rng.uniform(-0.025, 0.025)
            if second >= 0:
                if case["outage"] or (
                    sensor.id in case["gap_sensor_ids"] and second % 3 == 0
                ):
                    continue
                if source:
                    numeric_value -= source["strength_bar"] * math.exp(
                        -0.5 * (distances[sensor.id] / source["spread_m"]) ** 2
                    )
                if sensor.id in spikes and (second - spikes[sensor.id]) % 17 == 0:
                    numeric_value += 2.5
            value: float | str = numeric_value
            if second >= 0 and sensor.id in case["invalid_sensor_ids"] and second % 4 == 0:
                value = "not-a-pressure"
            observed = epoch + timedelta(seconds=second)
            row = RawRecord(
                sensor_id=sensor.id, channel="pressure",
                observed_at=observed.isoformat(), received_at=observed.isoformat(),
                value=value, unit="bar", source_id="synthetic-gateway",
                source_record_id=f"measurement:{second}:{sensor.id}",
            )
            (baseline if second < 0 else records).append(row)
    return ReplayDataset(pack=pack, baseline=baseline, records=records, epoch=epoch)


def dataset_hash(dataset: ReplayDataset) -> str:
    """Identify exact runtime inputs, not merely the seed or human-readable case label."""
    return content_hash(source_payload(dataset))


def measured_manifest(case: dict[str, Any], dataset: ReplayDataset) -> dict[str, Any]:
    """Compare authored expectations with production diagnostics at endpoint 60/clock 65.

    Fifteen invalid values and twenty omitted samples follow the every-fourth/every-
    third schedules in that 60-second window. Source containment is checked separately
    from the inferred station-midpoint interval, never used to generate that interval.
    """
    snapshot = analyze_window(
        dataset.pack, normalize_records(dataset.baseline, dataset.pack),
        normalize_records(dataset.records, dataset.pack), "manifest-input",
        60, 65, dataset.epoch,
    )
    summaries = {
        item.sensor_id: item.value for item in snapshot.evidence.values()
        if item.kind == "channel_summary"
    }
    inspection = (
        {
            "segment_id": snapshot.location.best.segment_id,
            "start_m": snapshot.location.inspection_start_m,
            "end_m": snapshot.location.inspection_end_m,
        } if snapshot.location and snapshot.location.status == "located"
        and snapshot.location.best else None
    )
    expected = case["expected"]
    observed_pressure = any(f.anomaly_count for f in snapshot.quality.findings)
    affected = sorted(snapshot.event.supporting_sensor_ids)
    checks = {
        "pressure_trigger": observed_pressure == expected["pressure_trigger"],
        "class": snapshot.event.hypothesis == expected["hypothesis"],
        "inspection": inspection == expected["inspection"],
        "affected_taps": affected == expected["affected_sensor_ids"],
        "quality_pattern": bool(
            any(f.missing or f.hard_excluded for f in snapshot.quality.findings)
        ) == expected["missing_or_invalid"],
    }
    findings = {f.sensor_id: f for f in snapshot.quality.findings}
    checks["explicit_fault_and_gap_patterns"] = (
        all(findings[identifier].hard_excluded == 15 for identifier in case["invalid_sensor_ids"])
        and all(findings[identifier].missing == 20 for identifier in case["gap_sensor_ids"])
        and all(findings[item["sensor_id"]].spike_count >= 3 for item in case["spikes"])
    )
    source_truth = None
    if case["source"]:
        source = case["source"]
        segment = next(s for s in dataset.pack.segments if s.id == source["segment_id"])
        source_truth = {
            **source, "position": point_at_chainage(segment, source["chainage_m"]).model_dump(),
        }
        checks["source_inside_interval"] = bool(
            inspection and inspection["segment_id"] == source["segment_id"]
            and inspection["start_m"] <= source["chainage_m"] <= inspection["end_m"]
        )
    return {
        "case_id": case["id"], "name": case["name"], "recipe": case,
        "source_truth": source_truth, "dataset_sha256": dataset_hash(dataset),
        "pack_version": dataset.pack.version,
        "sensor_positions": [sensor.model_dump(mode="json") for sensor in dataset.pack.sensors],
        "raw_baseline_count": len(dataset.baseline), "raw_record_count": len(dataset.records),
        "first_complete_window": {
            "end_seconds": 60, "clock_seconds": 65,
            "hypothesis": snapshot.event.hypothesis, "inspection": inspection,
            "supporting_sensor_ids": affected, "coverage": snapshot.quality.coverage,
            "quality_findings": [f.model_dump(mode="json") for f in snapshot.quality.findings],
            "pressure_summaries": summaries,
        },
        "deterministic_fixture_checks": checks,
        "fixture_verified": all(checks.values()),
    }


def write_manifest(
    output: Path, *, write_inputs: bool = True, site_id: str = "northsea",
) -> dict[str, Any]:
    """Persist evaluation truth/verification and optional label-free runtime JSONL inputs."""
    corpus = load_cases()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in corpus["cases"]:
        dataset = generate_golden(case, corpus["seed"], corpus["duration_seconds"], site_id)
        row = measured_manifest(case, dataset)
        rows.append(row)
        if write_inputs:
            destination = output / "runtime-inputs" / case["id"]
            destination.mkdir(parents=True, exist_ok=True)
            for name, records in (("baseline", dataset.baseline), ("arrivals", dataset.records)):
                (destination / f"{name}.jsonl").write_text(
                    "".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8",
                )
            (destination / "pack.json").write_text(dataset.pack.model_dump_json(indent=2))
    manifest = {
        "version": VERSION, "recipe_sha256": content_hash(corpus), "scope": corpus["scope"],
        "seed": corpus["seed"], "duration_seconds": corpus["duration_seconds"],
        "truth_isolation": (
            "Manifest/recipes/source probe are evaluation-only. Runtime gets only pack, "
            "baseline, arrivals and epoch. Content-addressed frozen-pressure scenarios exclude "
            "scenario-specific history. No labels in prompts, tools or knowledge."
        ),
        "passed": all(row["fixture_verified"] for row in rows), "cases": rows,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8",
    )
    return manifest
