"""Original synthetic source; configuration is not diagnostic evidence."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .contracts import PipelineSegment, Point, RawRecord, Sensor, SitePack

SCENARIOS = {
    "S1": "Localized acoustic and delayed methane signal",
    "S2": "Scattered sensor defects",
    "S3": "Shared gateway outage",
    "S4": "Broad environmental disturbance",
    "S5": "Physical signal with insufficient observers",
    "S6": "Verified-normal variability",
}


@dataclass(frozen=True)
class ReplayDataset:
    pack: SitePack
    baseline: list[RawRecord]
    records: list[RawRecord]
    epoch: datetime


def generate_pack(site_id: str = "northsea") -> SitePack:
    """Three connected 800 m straight polylines, four paired stations each."""
    lines = [
        ("P1", (0.0, 0.0), (800.0, 0.0)),
        ("P2", (800.0, 0.0), (1440.0, 480.0)),
        ("P3", (800.0, 0.0), (1440.0, -480.0)),
    ]
    segments = []
    sensors = []
    for segment_id, start, end in lines:
        segments.append(
            PipelineSegment(
                id=segment_id,
                points=[Point(x=start[0], y=start[1]), Point(x=end[0], y=end[1])],
                length_m=800,
            )
        )
        dx, dy = (end[0] - start[0]) / 800, (end[1] - start[1]) / 800
        for station in range(4):
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
                            x=start[0] + dx * chainage - side * dy * 8,
                            y=start[1] + dy * chainage + side * dx * 8,
                        ),
                        failure_domain_id=f"gateway-{segment_id}-{station % 2}",
                    )
                )
    return SitePack(id=site_id, sensors=sensors, segments=segments)


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
    pack = generate_pack(site_id)
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    baseline: list[RawRecord] = []
    records: list[RawRecord] = []
    # Run-level changes exercise noise, signal strength, response lag and missingness.
    noise_multiplier = rng.uniform(0.8, 1.25)
    strength = rng.uniform(11000, 15000)
    lag = rng.randint(18, 25)
    leak_x = rng.choice([375.0, 400.0, 425.0])
    for second in range(-60, duration_seconds):
        normal = second < 0
        target = baseline if normal else records
        for index, sensor in enumerate(pack.sensors):
            distance = math.hypot(sensor.position.x - leak_x, sensor.position.y)
            active = second >= 90 and scenario in {"S1", "S5"}
            # S3 includes a full-source loss; the trusted source clock still advances.
            if not normal and scenario == "S3" and second >= 90:
                continue
            if not normal and scenario == "S5" and second >= 90 and index not in {2, 3}:
                continue
            for channel in sensor.channels:
                unit = {"acoustic": "a.u.", "methane": "umol/L", "temperature": "degC"}[channel]
                center, noise = {
                    "acoustic": (1.0, 0.03),
                    "methane": (0.2, 0.015),
                    "temperature": (4.0, 0.03),
                }[channel]
                numeric_value = center + rng.gauss(0, noise * noise_multiplier)
                if active and channel == "acoustic":
                    numeric_value += strength / (distance * distance + pack.location_r0_m**2)
                if active and second >= 90 + lag and channel == "methane":
                    numeric_value += 2200 / (distance * distance + 80**2)
                if not normal and scenario == "S4" and second >= 90:
                    if channel == "acoustic":
                        numeric_value += 0.65
                    if channel == "temperature":
                        numeric_value += 0.3
                if not normal and scenario == "S2":
                    if index == 18 and channel == "acoustic" and second >= 90:
                        numeric_value += (second - 90) * 0.012
                    if index in {0, 10, 22} and second % 31 == 0:
                        numeric_value += 4 if channel == "acoustic" else 0.5
                    if index in {6, 14, 20} and second % 3 == 0:
                        continue
                value: float | str | None = numeric_value
                if not normal and rng.random() < 0.004:
                    value = None
                if not normal and scenario == "S1" and index == 22 and second >= 90:
                    if channel == "temperature" and second % 4 == 0:
                        value = "-9999"
                if channel == "methane" and index % 5 == 0 and value is not None:
                    value = float(value) * 1000
                    unit = "nmol/L"
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
