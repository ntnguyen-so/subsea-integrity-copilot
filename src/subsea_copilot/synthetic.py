"""Original synthetic source; configuration is not diagnostic evidence."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from .contracts import PipelineSegment, Point, RawRecord, Sensor, SitePack

SOURCE_VERSION: Literal["pressure-v3"] = "pressure-v3"
EXTENDED_PACK_VERSION = "pressure-pack-v4-extended"
CUSTOMER_QUESTIONS = [
    "Leak or faulty sensors?",
    "Where should we inspect, and why?",
    "What evidence supports this, and what remains unknown?",
]

SCENARIOS = {
    "S1": "Localized pressure drop with concurrent sensor faults",
    "S2": "Scattered sensor defects",
    "S3": "Full-source telemetry outage",
    "S4": "Broad operating pressure change; cause requires investigation",
    "S5": "Physical signal with insufficient observers",
    "S6": "Verified-normal variability",
    "S7": "Extended network: localized drop among mixed sensor, gateway and operating disturbances",
}


@dataclass(frozen=True)
class ReplayDataset:
    pack: SitePack
    baseline: list[RawRecord]
    records: list[RawRecord]
    epoch: datetime


def generate_pack(site_id: str = "northsea", *, version: str | None = None) -> SitePack:
    """The brief's Y or a versioned extension; paired taps share a gateway."""
    lines = [
        ("P1", "Trunk", (0.0, -800.0), (0.0, 0.0)),
        ("P2", "Branch A", (0.0, 0.0), (-640.0, 480.0)),
        ("P3", "Branch B", (0.0, 0.0), (640.0, 480.0)),
    ]
    extended = version == EXTENDED_PACK_VERSION
    if version not in {None, "pressure-pack-v3", EXTENDED_PACK_VERSION}:
        raise ValueError(f"Unknown synthetic geometry version: {version}")
    if extended:
        lines = [
            ("P1", "Trunk", (0.0, -1600.0), (0.0, 0.0)),
            ("P2", "West trunk", (0.0, 0.0), (-1280.0, 960.0)),
            ("P3", "East trunk", (0.0, 0.0), (1280.0, 960.0)),
            ("P4", "West outer", (-1280.0, 960.0), (-2560.0, 1920.0)),
            ("P5", "West inner", (-1280.0, 960.0), (-320.0, 2240.0)),
            ("P6", "East inner", (1280.0, 960.0), (320.0, 2240.0)),
            ("P7", "East outer", (1280.0, 960.0), (2560.0, 1920.0)),
        ]
    segments = []
    sensors = []
    for segment_id, name, start, end in lines:
        segment = PipelineSegment(
            id=segment_id,
            name=name,
            points=[Point(x=start[0], y=start[1]), Point(x=end[0], y=end[1])],
            length_m=1600 if extended else 800,
        )
        segments.append(segment)
        dx = (end[0] - start[0]) / segment.length_m
        dy = (end[1] - start[1]) / segment.length_m
        for station in range(8 if extended else 4):
            chainage = 100.0 + 200 * station
            station_id = f"{segment_id}-ST{station + 1}"
            for side in (-1, 1):
                sensors.append(
                    Sensor(
                        id=f"{station_id}-{'A' if side < 0 else 'B'}",
                        station_id=station_id,
                        segment_id=segment_id,
                        chainage_m=chainage,
                        position=Point(
                            x=start[0] + dx * chainage - side * dy * segment.diameter_m / 2,
                            y=start[1] + dy * chainage + side * dx * segment.diameter_m / 2,
                        ),
                        failure_domain_id=f"gateway-{segment_id}-{station % 2}",
                    )
                )
    return SitePack(
        id=site_id,
        name="NorthSea Extended Pressure Network"
        if extended
        else "NorthSea Pressure Monitoring Network",
        version=EXTENDED_PACK_VERSION if extended else "pressure-pack-v3",
        sensors=sensors,
        segments=segments,
    )


def _timestamp(instant: datetime, local: bool) -> str:
    if local:
        # The adapter explicitly declares Europe/Oslo, including its DST rules.
        from zoneinfo import ZoneInfo

        return (
            instant.astimezone(ZoneInfo("Europe/Oslo")).strftime("%Y-%m-%d %H:%M:%S")
            + " Europe/Oslo"
        )
    return instant.isoformat()


def generate_scenario(
    scenario: str,
    seed: int = 2026,
    duration_seconds: int = 360,
    site_id: str = "northsea",
) -> ReplayDataset:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown synthetic scenario: {scenario}")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    rng = random.Random(seed)
    pack = generate_pack(site_id, version=EXTENDED_PACK_VERSION if scenario == "S7" else None)
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    baseline: list[RawRecord] = []
    records: list[RawRecord] = []
    flatline_values: dict[str, float] = {}
    impulse_phases = {"P2-ST2-A": 0, "P4-ST7-B": 9, "P6-ST3-A": 17}
    # Illustrative pressure footprints, not a transient hydraulic simulator.
    noise_multiplier = rng.uniform(0.8, 1.25)
    strength = rng.uniform(1.3, 1.8)
    spread = rng.uniform(100, 130)
    leak_x = rng.choice([375.0, 400.0, 425.0])
    extended_distances: dict[str, float] = {}
    if scenario == "S7":
        from .localization import pipeline_distances, point_at_chainage

        leak_x += 400
        segment = next(segment for segment in pack.segments if segment.id == "P5")
        probe = Sensor(
            id="synthetic-source-probe",
            station_id="synthetic-source-probe",
            segment_id="P5",
            chainage_m=leak_x,
            position=point_at_chainage(segment, leak_x),
            failure_domain_id="synthetic-source-only",
        )
        routes = pipeline_distances(pack.model_copy(update={"sensors": [*pack.sensors, probe]}))
        extended_distances = {sensor.id: routes[probe.id, sensor.id] for sensor in pack.sensors}
    for second in range(-60, duration_seconds):
        normal = second < 0
        target = baseline if normal else records
        for index, sensor in enumerate(pack.sensors):
            distance = (
                abs(sensor.chainage_m - leak_x)
                if sensor.segment_id == "P1"
                else 800 - leak_x + sensor.chainage_m
            )
            if scenario == "S7":
                distance = extended_distances[sensor.id]
            active = second >= 90 and scenario in {"S1", "S5", "S7"}
            # S3 includes a full-source loss; the trusted source clock still advances.
            if not normal and scenario == "S3" and second >= 90:
                continue
            if not normal and scenario == "S5" and second >= 90 and index not in {2, 3}:
                continue
            for channel in sensor.channels:
                unit = "bar"
                center = 80 - sensor.chainage_m * 0.001
                if sensor.segment_id != "P1":
                    center -= 0.8
                numeric_value = center + rng.gauss(0, 0.04 * noise_multiplier)
                numeric_value += 0.02 * math.sin(second / 18)
                if active:
                    if scenario == "S7":
                        # Synthetic engineering assumptions, not calibrated gas hydraulics:
                        # a broad local core plus a weak connected-network tail, with a
                        # common settling envelope (no modeled propagation/arrival times).
                        age = second - 90
                        ramp = (1 - math.exp(-age / 6)) * (0.8 + 0.2 * (1 - math.exp(-age / 30)))
                        footprint = 0.8 * math.exp(-0.5 * (distance / 350) ** 2)
                        footprint += 0.2 * math.exp(-distance / 1000)
                    else:
                        ramp = min(1.0, (second - 90) / 5)
                        footprint = math.exp(-0.5 * (distance / spread) ** 2)
                    numeric_value -= strength * footprint * ramp
                if not normal and scenario == "S4" and second >= 90:
                    numeric_value -= 0.75
                if not normal and scenario == "S2":
                    if index == 2 and second >= 90:
                        numeric_value += (second - 90) * 0.012
                    if index in {0, 10, 22} and second % 31 == 0:
                        numeric_value += 2.5
                    if index in {6, 14, 20} and second % 3 == 0:
                        continue
                if not normal and scenario == "S7" and second >= 90:
                    if sensor.id in {"P1-ST6-A", "P4-ST3-B"}:
                        numeric_value += (second - 90) * 0.014
                    if sensor.id == "P3-ST7-A":
                        numeric_value -= (second - 90) * 0.012
                    impulse_phase = impulse_phases.get(sensor.id)
                    if impulse_phase is not None and (second - 90 - impulse_phase) % 29 == 0:
                        numeric_value += 2.5
                    if sensor.id in {"P1-ST7-B", "P3-ST5-B", "P6-ST6-A"} and second % 3 == 0:
                        continue
                    if sensor.id == "P6-ST8-B":
                        # Stuck sample retains a plausible pressure, unlike missing telemetry.
                        numeric_value = flatline_values.setdefault(sensor.id, numeric_value)
                    if sensor.id == "P3-ST2-A" and (second - 90) % 18 < 6:
                        numeric_value -= 0.9
                    if sensor.failure_domain_id == "gateway-P7-0":
                        numeric_value -= 0.75
                        if (second - 90) % 37 in {19, 20, 21}:
                            continue
                    if sensor.segment_id == "P2" and second < 145:
                        numeric_value += 0.4
                value: float | str | None = numeric_value
                if not normal and rng.random() < 0.004:
                    value = None
                if not normal and scenario == "S1" and index == 22 and second >= 90:
                    if second % 4 == 0:
                        value = "-9999"
                if (
                    not normal
                    and scenario == "S7"
                    and sensor.id == "P4-ST8-A"
                    and second >= 90
                    and second % 4 == 0
                ):
                    value = "-9999"
                if value is not None and value != "-9999":
                    if index % 5 == 0:
                        value = float(value) * 100
                        unit = "kPa"
                    elif index % 7 == 0:
                        value = float(value) / 10
                        unit = "MPa"
                observed = epoch + timedelta(seconds=second)
                delay = 0 if normal else (8 if second % 71 == 0 and index == 0 else 0)
                record = RawRecord(
                    sensor_id=sensor.id,
                    channel=channel,
                    observed_at=_timestamp(observed, index % 7 == 0),
                    received_at=(observed + timedelta(seconds=delay)).isoformat(),
                    value=value,
                    unit=unit,
                    source_record_id=f"{site_id}:{second}:{sensor.id}:{channel}",
                )
                target.append(record)
                if not normal and second % 97 == 0 and index == 11:
                    target.append(record.model_copy())
    records.sort(key=lambda record: (record.received_at, record.source_record_id))
    return ReplayDataset(pack=pack, baseline=baseline, records=records, epoch=epoch)
