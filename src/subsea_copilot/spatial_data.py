"""Source-labelled, time-varying 112-instrument evaluation networks."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .contracts import RawRecord, Sensor
from .localization import pipeline_distances, point_at_chainage
from .synthetic import EXTENDED_PACK_VERSION, ReplayDataset, generate_pack

DURATION_SECONDS = 360
CHECKPOINTS = (150, 360)


def temporal_cases(suite: str) -> list[dict[str, Any]]:
    def leak(segment: str, chainage: int, start: int, end: int | None) -> dict[str, Any]:
        return {
            "segment_id": segment, "chainage_m": chainage, "start_seconds": start,
            "end_seconds": end, "strength_bar": 1.8, "spread_m": 140,
        }

    def case(identifier: str, name: str, **events: Any) -> dict[str, Any]:
        return {
            "id": identifier, "name": name, "source": None, "issues": [],
            "gateway_offset": None, "operating_change": None, **events,
        }

    if suite == "recovery":
        return [
            case("R1", "Leak stops and pressure recovers",
                 source=leak("P5", 800, 90, 180)),
            case("R2", "Leak clears, then a second leak starts on another branch",
                 sources=[leak("P5", 800, 90, 150), leak("P6", 1000, 240, None)]),
        ]
    if suite == "non_leak":
        return [
            case("C1", "Paired operating shift without leakage", operating_change={
                "segment_id": "P2", "start_seconds": 90, "end_seconds": 145, "rise_bar": 0.4,
            }),
            case("C2", "Shared gateway offset and restoration without leakage", gateway_offset={
                "failure_domain_id": "gateway-P7-0", "start_seconds": 90,
                "end_seconds": 210, "drop_bar": 0.75,
            }),
            case("C3", "Invalid values and telemetry gaps recover without leakage", issues=[
                {"sensor_id": "P4-ST8-A", "kind": "invalid",
                 "start_seconds": 90, "end_seconds": 210},
                {"sensor_id": "P1-ST7-B", "kind": "missing",
                 "start_seconds": 90, "end_seconds": 210},
            ]),
        ]
    raise ValueError(f"Unknown temporal evaluation suite: {suite}")


def leak_episodes(case: dict[str, Any]) -> list[dict[str, Any]]:
    return case["sources"] if "sources" in case else [case["source"]] if case["source"] else []


def active_event(event: dict[str, Any], second: int) -> bool:
    return second >= event["start_seconds"] and (
        event.get("end_seconds") is None or second < event["end_seconds"]
    )


def spatial_cases() -> list[dict[str, Any]]:
    issues = [
        {"sensor_id": "P1-ST6-A", "kind": "drift", "start_seconds": 180},
        {"sensor_id": "P3-ST7-A", "kind": "drift", "start_seconds": 180},
        {"sensor_id": "P4-ST7-B", "kind": "spike", "start_seconds": 180},
        {"sensor_id": "P6-ST3-A", "kind": "spike", "start_seconds": 180},
        {"sensor_id": "P1-ST7-B", "kind": "missing", "start_seconds": 180},
        {"sensor_id": "P3-ST5-B", "kind": "missing", "start_seconds": 180},
        {"sensor_id": "P4-ST8-A", "kind": "invalid", "start_seconds": 180},
        {"sensor_id": "P6-ST8-B", "kind": "flatline", "start_seconds": 180},
    ]
    return [
        {
            "id": "N1",
            "name": "Broad leak footprint with shared-connection and scattered issues",
            "source": {
                "segment_id": "P5",
                "chainage_m": 800,
                "start_seconds": 90,
                "strength_bar": 1.8,
                "spread_m": 350,
            },
            "issues": issues,
            "gateway_offset": {
                "failure_domain_id": "gateway-P7-0",
                "start_seconds": 90,
                "drop_bar": 0.75,
            },
            "operating_change": {
                "segment_id": "P2",
                "start_seconds": 90,
                "end_seconds": 145,
                "rise_bar": 0.4,
            },
        },
        {
            "id": "N2",
            "name": "Localized east-inner leak with independent west-side faults",
            "source": {
                "segment_id": "P6",
                "chainage_m": 1000,
                "start_seconds": 90,
                "strength_bar": 1.8,
                "spread_m": 140,
            },
            "issues": [
                {**item, "sensor_id": replacement}
                for item, replacement in zip(
                    issues,
                    (
                        "P1-ST6-A",
                        "P3-ST7-A",
                        "P4-ST7-B",
                        "P2-ST3-A",
                        "P1-ST7-B",
                        "P3-ST5-B",
                        "P4-ST8-A",
                        "P5-ST8-B",
                    ),
                    strict=True,
                )
            ],
            "gateway_offset": {
                "failure_domain_id": "gateway-P7-0",
                "start_seconds": 90,
                "drop_bar": 0.75,
            },
            "operating_change": {
                "segment_id": "P2",
                "start_seconds": 90,
                "end_seconds": 145,
                "rise_bar": 0.4,
            },
        },
        {
            "id": "N3",
            "name": "Leak look-alike: shared connection, operating shift and sensor faults",
            "source": None,
            "issues": [{**item, "start_seconds": 90} for item in issues],
            "gateway_offset": {
                "failure_domain_id": "gateway-P7-0",
                "start_seconds": 90,
                "drop_bar": 0.75,
            },
            "operating_change": {
                "segment_id": "P2",
                "start_seconds": 90,
                "end_seconds": 145,
                "rise_bar": 0.4,
            },
        },
    ]


def spatial_dataset(case: dict[str, Any], seed: int, site_id: str) -> ReplayDataset:
    pack = generate_pack(site_id, version=EXTENDED_PACK_VERSION)
    rng = random.Random(seed)
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    sources = leak_episodes(case)
    distances: list[dict[str, float]] = []
    for source in sources:
        segment = next(segment for segment in pack.segments if segment.id == source["segment_id"])
        probe = Sensor(
            id="source-only",
            station_id="source-only",
            segment_id=segment.id,
            chainage_m=source["chainage_m"],
            position=point_at_chainage(segment, source["chainage_m"]),
            failure_domain_id="source-only",
        )
        routes = pipeline_distances(pack.model_copy(update={"sensors": [*pack.sensors, probe]}))
        distances.append({sensor.id: routes[probe.id, sensor.id] for sensor in pack.sensors})
    issues = {item["sensor_id"]: item for item in case["issues"]}
    baseline: list[RawRecord] = []
    records: list[RawRecord] = []
    stuck: dict[str, float] = {}
    for second in range(-60, DURATION_SECONDS):
        for index, sensor in enumerate(pack.sensors):
            center = 80 - sensor.chainage_m * 0.001 - (0.8 if sensor.segment_id != "P1" else 0)
            value = center + rng.gauss(0, 0.04)
            value += 0.02 * math.sin(second / 18)
            for source, distance_map in zip(sources, distances, strict=True):
                if not active_event(source, second):
                    continue
                age = second - source["start_seconds"]
                distance = distance_map[sensor.id]
                footprint = 0.8 * math.exp(-0.5 * (distance / source["spread_m"]) ** 2)
                footprint += 0.2 * math.exp(-distance / 1000)
                value -= source["strength_bar"] * footprint * (1 - math.exp(-age / 6))
            offset = case["gateway_offset"]
            if (
                offset and active_event(offset, second)
                and sensor.failure_domain_id == offset["failure_domain_id"]
            ):
                value -= offset["drop_bar"]
            operating = case["operating_change"]
            if (
                operating and sensor.segment_id == operating["segment_id"]
                and operating["start_seconds"] <= second < operating["end_seconds"]
            ):
                value += operating["rise_bar"]
            issue = issues.get(sensor.id)
            issue_active = bool(issue and active_event(issue, second))
            if issue and issue_active:
                age = second - issue["start_seconds"]
                if issue["kind"] == "missing" and second % 3 == 0:
                    continue
                if issue["kind"] == "drift":
                    value += (-1 if sensor.id.startswith("P3") else 1) * age * 0.014
                elif issue["kind"] == "spike" and (age - index % 17) % 29 == 0:
                    value += 2.5
                elif issue["kind"] == "flatline":
                    value = stuck.setdefault(sensor.id, value)
            unit = "bar"
            if isinstance(value, float):
                if index % 5 == 0:
                    value *= 100
                    unit = "kPa"
                elif index % 7 == 0:
                    value /= 10
                    unit = "MPa"
            instant = epoch + timedelta(seconds=second)
            record_value: float | str = (
                "not-a-pressure"
                if issue
                and issue["kind"] == "invalid"
                and issue_active
                and second % 4 == 0
                else value
            )
            observed = instant.isoformat()
            if index % 7 == 0:
                from zoneinfo import ZoneInfo

                observed = (
                    instant.astimezone(ZoneInfo("Europe/Oslo")).strftime("%Y-%m-%d %H:%M:%S")
                    + " Europe/Oslo"
                )
            row = RawRecord(
                sensor_id=sensor.id,
                channel="pressure",
                observed_at=observed,
                received_at=instant.isoformat(),
                value=record_value,
                unit=unit,
                source_id="synthetic-gateway",
                source_record_id=f"measurement:{second}:{sensor.id}",
            )
            (baseline if second < 0 else records).append(row)
    return ReplayDataset(pack=pack, baseline=baseline, records=records, epoch=epoch)


def spatial_truth(case: dict[str, Any], dataset: ReplayDataset, end_seconds: int) -> dict[str, Any]:
    start = max(0, end_seconds - dataset.pack.window_seconds)
    # Snapshots end exclusively: their latest possible observation is end - 1.
    active_source = next(
        (source for source in leak_episodes(case) if active_event(source, end_seconds - 1)), None,
    )
    issues = [
        {"sensor_id": item["sensor_id"], "kind": item["kind"]}
        for item in case["issues"]
        if active_event(item, end_seconds - 1)
    ]
    offset = case["gateway_offset"]
    if offset and active_event(offset, end_seconds - 1):
        issues += [
            {"sensor_id": sensor.id, "kind": "offset"}
            for sensor in dataset.pack.sensors
            if sensor.failure_domain_id == offset["failure_domain_id"]
        ]
    operating = case["operating_change"]
    return {
        "leak_source": active_source,
        "sensor_issues": issues,
        "instrumentation_concern": any(item["kind"] != "missing" for item in issues),
        "pressure_trigger": bool(
            active_source
            or any(item["kind"] not in {"missing", "invalid", "flatline"} for item in issues)
        ),
        "review_required": bool(active_source or issues),
        "pressure_anomaly_sensors": [],
        "missing_value_sensors": [
            item["sensor_id"] for item in issues if item["kind"] in {"missing", "invalid"}
        ],
        "expected_inspection": None,
        "operating_change": operating
        if operating and start < operating["end_seconds"]
        and end_seconds > operating["start_seconds"]
        else None,
    }
