"""Seeded measurement source for repeatable demos, not a calibrated hydraulic model.

``generate_pack`` supplies topology and instruments; ``generate_scenario`` emits
60 seconds of verified-normal training data followed by an arrival-ordered replay.
Scenario IDs and injection parameters are source/test knowledge, not evidence to
give the investigating model. Runtime tools must expose measurements instead.

Generation order:
1. Build the small Y network, or the larger S7 network, and seed a private RNG.
2. Draw one set of signal parameters, then generate each second/sensor/channel.
3. Start with nominal pressure, random measurement noise and slow variability.
4. Add the selected physical-like signal, instrument faults and telemetry gaps.
5. Encode raw payloads with mixed units/times, nulls, sentinels, delays and retries.

This module creates raw input, not anomaly scores or agent diagnoses. ``ingest.py``
later normalizes these records; downstream diagnostics compare replay measurements
against the separate normal baseline. Constants below are authored demo assumptions,
not parameters fitted to offshore measurements.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from .contracts import PipelineSegment, Point, RawRecord, Sensor, SitePack

# Source recipe and geometry have separate identities for replay provenance.
SOURCE_VERSION: Literal["pressure-v3"] = "pressure-v3"
EXTENDED_PACK_VERSION = "pressure-pack-v4-extended"
CUSTOMER_QUESTIONS = [
    "Leak or faulty sensors?",
    "Where should we inspect, and why?",
    "What evidence supports this, and what remains unknown?",
]

# These labels describe the authored injections, not guaranteed detector outcomes.
# S6 has no intentional physical/instrument event, but still exercises raw-data
# imperfections common to all replay scenarios.
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
    """Return geometry, separate normal/replay records and their shared time origin.

    ``baseline`` spans [-60, 0) seconds; ``records`` spans [0, duration_seconds).
    Records can be absent, invalid or duplicated, so list length is not coverage.
    """

    pack: SitePack
    baseline: list[RawRecord]
    records: list[RawRecord]
    epoch: datetime


def generate_pack(site_id: str = "northsea", *, version: str | None = None) -> SitePack:
    """Build deterministic geometry and pressure instruments, without observations.

    The default has three 800m segments, four stations per segment and 24 taps.
    The extension has seven 1600m segments, eight stations per segment and 112 taps.
    SitePack supplies the remaining monitoring-policy defaults.
    """
    # Coordinates are local illustrative metres, not latitude/longitude. Each
    # station has two taps, but sharing a gateway limits their independence.
    lines = [
        ("P1", "Trunk", (0.0, -800.0), (0.0, 0.0)),
        ("P2", "Branch A", (0.0, 0.0), (-640.0, 480.0)),
        ("P3", "Branch B", (0.0, 0.0), (640.0, 480.0)),
    ]
    extended = version == EXTENDED_PACK_VERSION
    if version not in {None, "pressure-pack-v3", EXTENDED_PACK_VERSION}:
        raise ValueError(f"Unknown synthetic geometry version: {version}")
    if extended:
        # Identical endpoints define connectivity: P1 branches into P2/P3, then
        # P2 into P4/P5 and P3 into P6/P7. Segment length matches endpoint distance.
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
        # Unit direction along the segment converts chainage (metres from start)
        # into x/y coordinates; (-dy, dx) is its perpendicular wall-offset vector.
        dx = (end[0] - start[0]) / segment.length_m
        dy = (end[1] - start[1]) / segment.length_m
        for station in range(8 if extended else 4):
            # Stations are at 100, 300, ... metres; A/B taps lie on opposite
            # walls of the same cross-section, half a pipe diameter from center.
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
                        # Two alternating gateways serve each segment. Both taps
                        # and multiple stations therefore share failure domains.
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
    """Encode the same instant as offset-aware ISO or explicitly named local time."""
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
    """Inject authored disturbances into noisy pressure records at one-second cadence.

    The seed controls noise and footprint variability, not measured field physics.
    Event time starts at a fixed UTC epoch; receive time independently models delay.
    A run generates data in memory only: no files, database writes or model calls.
    The seed, scenario, duration and source implementation determine its raw output.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown synthetic scenario: {scenario}")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    # A private RNG avoids changing global random state. Draw order matters:
    # changing loop order or skipping a draw changes later noise/null samples.
    rng = random.Random(seed)
    pack = generate_pack(site_id, version=EXTENDED_PACK_VERSION if scenario == "S7" else None)
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    baseline: list[RawRecord] = []
    records: list[RawRecord] = []
    # Remember the first post-onset value of S7's stuck instrument.
    flatline_values: dict[str, float] = {}
    # Distinct phases stagger these S7 spikes instead of making them simultaneous.
    impulse_phases = {"P2-ST2-A": 0, "P4-ST7-B": 9, "P6-ST3-A": 17}
    # Draw once per dataset: noise scale, maximum drop in bar, Gaussian width in
    # metres, and source chainage on P1. These are not redrawn for each reading.
    noise_multiplier = rng.uniform(0.8, 1.25)
    strength = rng.uniform(1.3, 1.8)
    spread = rng.uniform(100, 130)
    leak_x = rng.choice([375.0, 400.0, 425.0])
    extended_distances: dict[str, float] = {}
    if scenario == "S7":
        from .localization import pipeline_distances, point_at_chainage

        # Move the source to P5 at 775/800/825m. A temporary probe obtains shortest
        # connected-pipe distances to real taps; it is never added to returned
        # geometry or emitted as a measurement. Euclidean shortcuts are not used.
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
    # Negative seconds belong only to the baseline. Sustained disturbances start
    # at +90s; sporadic gaps/spikes may occur earlier. Timings are demo assumptions.
    for second in range(-60, duration_seconds):
        normal = second < 0
        target = baseline if normal else records
        for index, sensor in enumerate(pack.sensors):
            # For the small Y, distance is along P1 or via its junction to P2/P3.
            # S7 instead uses the precomputed routes across all seven segments.
            distance = (
                abs(sensor.chainage_m - leak_x)
                if sensor.segment_id == "P1"
                else 800 - leak_x + sensor.chainage_m
            )
            if scenario == "S7":
                distance = extended_distances[sensor.id]
            active = second >= 90 and scenario in {"S1", "S5", "S7"}
            # No record is different from a record containing a null/sentinel.
            # S3 drops every source after +90s; its trusted clock still advances.
            if not normal and scenario == "S3" and second >= 90:
                continue
            # S5 retains only P1-ST2-A/B: a physical-like drop with just one
            # paired station/shared gateway, deliberately insufficient observers.
            if not normal and scenario == "S5" and second >= 90 and index not in {2, 3}:
                continue
            for channel in sensor.channels:
                # Generated packs currently declare pressure only. Compute in bar:
                # 80bar nominal minus 0.001bar/metre chainage and a 0.8bar branch
                # offset, plus Gaussian noise (~0.032-0.05bar standard deviation)
                # and a common 0.02bar sinusoid (period 36*pi seconds).
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
                        # Six-second rise and thirty-second settling scale the
                        # signal toward its full magnitude. Distance attenuates
                        # it through a 350m Gaussian core and 1000m exponential tail.
                        ramp = (1 - math.exp(-age / 6)) * (0.8 + 0.2 * (1 - math.exp(-age / 30)))
                        footprint = 0.8 * math.exp(-0.5 * (distance / 350) ** 2)
                        footprint += 0.2 * math.exp(-distance / 1000)
                    else:
                        # S1/S5 reach full amplitude over five seconds. The
                        # Gaussian footprint is strongest at the authored source
                        # and decays with connected-pipe distance, not time delay.
                        ramp = min(1.0, (second - 90) / 5)
                        footprint = math.exp(-0.5 * (distance / spread) ** 2)
                    numeric_value -= strength * footprint * ramp
                if not normal and scenario == "S4" and second >= 90:
                    # A simultaneous network-wide 0.75bar step is an operating-
                    # change example; pressure alone does not establish its cause.
                    numeric_value -= 0.75
                if not normal and scenario == "S2":
                    # P1-ST2-A drifts upward by 0.012bar/s after onset. Three
                    # separated taps spike +2.5bar every 31s (even before onset);
                    # three others omit every third reading throughout replay.
                    if index == 2 and second >= 90:
                        numeric_value += (second - 90) * 0.012
                    if index in {0, 10, 22} and second % 31 == 0:
                        numeric_value += 2.5
                    if index in {6, 14, 20} and second % 3 == 0:
                        continue
                if not normal and scenario == "S7" and second >= 90:
                    # Independent-looking instrument defects coexist with the
                    # connected P5 pressure footprint: two upward drifts, one
                    # downward drift, phased 29s spikes and periodic missing rows.
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
                        # Cache the first post-onset pressure and repeat it exactly;
                        # this flatline precedes the later random-null encoding.
                        numeric_value = flatline_values.setdefault(sensor.id, numeric_value)
                    if sensor.id == "P3-ST2-A" and (second - 90) % 18 < 6:
                        # Repeated six-second, -0.9bar pulses, not a sustained drop.
                        numeric_value -= 0.9
                    if sensor.failure_domain_id == "gateway-P7-0":
                        # A shared -0.75bar bias plus three missing seconds per
                        # 37s cycle affects all eight taps on this one gateway.
                        numeric_value -= 0.75
                        if (second - 90) % 37 in {19, 20, 21}:
                            continue
                    if sensor.segment_id == "P2" and second < 145:
                        # A temporary +0.4bar branch-wide operating disturbance
                        # ends at +145s; it is separate from individual tap defects.
                        numeric_value += 0.4
                # Exercise ingestion with absent values, sentinels, mixed units,
                # delayed arrivals and exact duplicate payloads; do not clean here.
                value: float | str | None = numeric_value
                if not normal and rng.random() < 0.004:
                    # About 0.4% of otherwise emitted replay samples are explicit
                    # null payloads, including S6; baseline samples stay present.
                    value = None
                if not normal and scenario == "S1" and index == 22 and second >= 90:
                    if second % 4 == 0:
                        # P3-ST4-A sends a documented missing-value sentinel every
                        # fourth second. "-9999" is a string, NOT negative pressure:
                        # ingest.py retains the raw payload and marks it missing.
                        value = "-9999"
                if (
                    not normal
                    and scenario == "S7"
                    and sensor.id == "P4-ST8-A"
                    and second >= 90
                    and second % 4 == 0
                ):
                    # The same legacy-device sentinel pattern on S7's P4-ST8-A.
                    value = "-9999"
                if value is not None and value != "-9999":
                    # Encode equivalent pressures, not different physical values:
                    # 1bar=100kPa=0.1MPa. Multiples of five take precedence over
                    # multiples of seven. Null/sentinel payloads remain unscaled.
                    if index % 5 == 0:
                        value = float(value) * 100
                        unit = "kPa"
                    elif index % 7 == 0:
                        value = float(value) / 10
                        unit = "MPa"
                observed = epoch + timedelta(seconds=second)
                # Only the first instrument arrives eight seconds late every
                # 71s during replay, exercising the normal five-second allowance
                # and late-evidence path. Baseline arrivals are immediate.
                delay = 0 if normal else (8 if second % 71 == 0 and index == 0 else 0)
                record = RawRecord(
                    sensor_id=sensor.id,
                    channel=channel,
                    # Every seventh instrument uses named Oslo event time; receive
                    # time always stays offset-aware ISO. Both refer to UTC instants.
                    observed_at=_timestamp(observed, index % 7 == 0),
                    received_at=(observed + timedelta(seconds=delay)).isoformat(),
                    value=value,
                    unit=unit,
                    # Identity is independent of encoded value, unit and arrival:
                    # ingestion can distinguish exact retries from conflicts.
                    source_record_id=f"{site_id}:{second}:{sensor.id}:{channel}",
                )
                target.append(record)
                if not normal and second % 97 == 0 and index == 11:
                    # Copy the entire payload and identity: this is an exact
                    # transport retry to deduplicate, not an extra observation.
                    target.append(record.model_copy())
    # Emit arrival order, not event-time order: delayed records may appear after
    # newer measurements. All receive times use the same UTC ISO representation;
    # identity is the deterministic tie-breaker, including equal retry copies.
    records.sort(key=lambda record: (record.received_at, record.source_record_id))
    return ReplayDataset(pack=pack, baseline=baseline, records=records, epoch=epoch)
