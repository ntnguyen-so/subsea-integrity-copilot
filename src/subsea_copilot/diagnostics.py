"""Label-free, event-time numerical summaries and bounded claim ledger."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from .contracts import (
    CanonicalObservation,
    Claim,
    EventAssessment,
    EvidenceItem,
    QualityFinding,
    QualityReport,
    Sensor,
    SitePack,
    WindowSnapshot,
    content_hash,
)
from .localization import locate, point_at_chainage


def _duration(times: Sequence[float], sample_seconds: int) -> float:
    longest = run = 0.0
    previous = -math.inf
    run_start = 0.0
    for second in sorted(set(times)):
        if second - previous > sample_seconds * 1.01:
            run_start = second
        run = second - run_start + sample_seconds
        longest = max(longest, run)
        previous = second
    return longest


def analyze_window(
    pack: SitePack,
    baseline: Sequence[CanonicalObservation],
    observations: Sequence[CanonicalObservation],
    generation_id: str,
    end_seconds: int,
    clock_seconds: float,
    epoch: datetime,
    tenant_id: str = "demo",
    revision: int = 1,
    predecessor_id: str | None = None,
) -> WindowSnapshot:
    if epoch.tzinfo is None or epoch.utcoffset() is None:
        raise ValueError("epoch must be timezone aware")
    if not math.isfinite(clock_seconds) or end_seconds <= 0 or revision < 1:
        raise ValueError("Invalid window clock, endpoint or revision")
    start = epoch + timedelta(seconds=end_seconds - pack.window_seconds)
    end = epoch + timedelta(seconds=end_seconds)
    clock = epoch + timedelta(seconds=clock_seconds)
    selected = sorted(
        {
            observation.id: observation
            for observation in observations
            if start <= observation.observed_at < end
            and observation.received_at <= clock
            and observation.observed_at <= clock
        }.values(),
        key=lambda observation: observation.id,
    )
    # Pre-roll is explicit and verified externally; no unreleased/future normal sample
    # is accepted as a baseline simply because a caller supplied it.
    normal = [
        observation
        for observation in baseline
        if observation.observed_at < epoch
        and observation.received_at <= epoch
        and observation.validity == "usable"
        and observation.value is not None
    ]
    groups: dict[tuple[str, str], list[CanonicalObservation]] = defaultdict(list)
    baselines: dict[tuple[str, str], list[float]] = defaultdict(list)
    for observation in selected:
        groups[(observation.sensor_id, observation.channel)].append(observation)
    for observation in normal:
        if observation.value is not None:
            baselines[(observation.sensor_id, observation.channel)].append(observation.value)
    expected_each = math.ceil(pack.window_seconds / pack.sample_seconds)
    findings = []
    stats: dict[tuple[str, str], dict[str, Any]] = {}
    evidence: dict[str, EvidenceItem] = {}
    claims: dict[str, Claim] = {}

    def ledger(
        kind: str,
        value: dict[str, Any],
        claim_kind: str | None = None,
        sensor_id: str | None = None,
        channel: str | None = None,
    ) -> str:
        evidence_id = f"ev-{len(evidence):03d}"
        evidence[evidence_id] = EvidenceItem(
            id=evidence_id,
            kind=kind,
            value=value,
            sensor_id=sensor_id,
            channel=channel,
        )
        if claim_kind:
            claim_id = f"claim-{len(claims):03d}"
            claims[claim_id] = Claim(
                id=claim_id, kind=claim_kind, value=value, evidence_ids=[evidence_id]
            )
        return evidence_id

    missing_baseline = False
    ledger(
        "sensor_metadata",
        {
            "pack_id": pack.id,
            "pack_version": pack.version,
            "sensors": [sensor.model_dump(mode="json") for sensor in pack.sensors],
        },
    )
    for sensor in pack.sensors:
        for channel in sensor.channels:
            key = (sensor.id, channel)
            channel_rows = groups[key]
            usable = [
                row for row in channel_rows if row.validity == "usable" and row.value is not None
            ]
            values = baselines[key]
            if len(values) >= pack.persistence_seconds:
                median = float(np.median(values))
                scale = max(
                    float(np.median(np.abs(np.asarray(values) - median))) * 1.4826,
                    pack.minimum_scales[channel],
                )
            else:
                median, scale = 0.0, pack.minimum_scales[channel]
                missing_baseline = True
            scores = (
                [(row, (row.value - median) / scale) for row in usable if row.value is not None]
                if values
                else []
            )
            positive = [
                (row.observed_at - epoch).total_seconds()
                for row, score in scores
                if score >= pack.anomaly_threshold
            ]
            excursions = [
                (row.observed_at - epoch).total_seconds()
                for row, score in scores
                if abs(score) >= pack.anomaly_threshold
            ]
            persistence = _duration(positive, pack.sample_seconds)
            positive_set = set(excursions)
            spikes = sum(
                second - pack.sample_seconds not in positive_set
                and second + pack.sample_seconds not in positive_set
                for second in positive_set
            )
            received_times = {row.observed_at for row in channel_rows}
            usable_times = {row.observed_at for row in usable}
            finding = QualityFinding(
                sensor_id=sensor.id,
                channel=channel,
                expected=expected_each,
                received=len(received_times),
                usable=len(usable_times),
                missing=max(0, expected_each - len(usable_times)),
                hard_excluded=sum(
                    row.validity not in {"usable", "missing"} for row in channel_rows
                ),
                spike_count=spikes,
                max_score=max((abs(score) for _, score in scores), default=0),
                persistence_seconds=_duration(excursions, pack.sample_seconds),
            )
            stats[key] = {
                "median": median,
                "scale": scale,
                "positive": positive,
                "duration": persistence,
                "health_duration": _duration(excursions, pack.sample_seconds),
                "usable": len(usable_times),
                "excess": float(np.median([row.value for row in usable])) - median
                if usable
                else None,
            }
            findings.append(finding)
    expected = expected_each * sum(len(sensor.channels) for sensor in pack.sensors)
    usable_count = sum(finding.usable for finding in findings)
    coverage = min(1.0, usable_count / expected) if expected else 0
    domains = {
        sensor.failure_domain_id
        for sensor in pack.sensors
        if any(
            stats[(sensor.id, channel)]["usable"] >= expected_each * pack.min_coverage
            for channel in sensor.channels
        )
    }
    warmup = (
        end_seconds < pack.window_seconds
        or clock_seconds < (end_seconds + pack.lateness_seconds)
        or missing_baseline
    )
    acoustic = [
        sensor
        for sensor in pack.sensors
        if stats[(sensor.id, "acoustic")]["duration"] >= pack.persistence_seconds
        and stats[(sensor.id, "acoustic")]["usable"] >= expected_each * pack.min_coverage
    ]
    methane = [
        sensor
        for sensor in pack.sensors
        if stats[(sensor.id, "methane")]["duration"] >= pack.persistence_seconds
        and stats[(sensor.id, "methane")]["usable"] >= expected_each * pack.min_coverage
    ]

    def distance(a: Sensor, b: Sensor) -> float:
        return math.hypot(a.position.x - b.position.x, a.position.y - b.position.y)

    # Require overlapping raw-time excursions across independent nearby observers.
    clusters = []
    for anchor in acoustic:
        neighborhood = [
            sensor for sensor in acoustic if distance(sensor, anchor) <= pack.neighborhood_m
        ]
        joint_times = set(stats[(anchor.id, "acoustic")]["positive"])
        qualified = []
        for sensor in neighborhood:
            overlap = joint_times.intersection(stats[(sensor.id, "acoustic")]["positive"])
            if _duration(sorted(overlap), pack.sample_seconds) >= pack.persistence_seconds:
                qualified.append(sensor)
        corroborators = []
        for sensor in methane:
            nearby = [
                other for other in qualified if distance(sensor, other) <= pack.neighborhood_m
            ]
            if not nearby:
                continue
            methane_times = stats[(sensor.id, "methane")]["positive"]
            matches = [
                second
                for second in methane_times
                if any(
                    0 <= second - acoustic_time <= pack.methane_lag_seconds
                    for acoustic_time in joint_times
                )
            ]
            if _duration(matches, pack.sample_seconds) >= pack.persistence_seconds:
                corroborators.append(sensor)
        independent = {sensor.failure_domain_id for sensor in qualified}
        if len(qualified) >= pack.min_observers and len(independent) >= pack.min_failure_domains:
            clusters.append((qualified, corroborators))
    supported = [(group, corroborators) for group, corroborators in clusters if corroborators]
    support = max(supported, key=lambda item: len(item[0]), default=([], []))[0]
    for finding in findings:
        if finding.persistence_seconds < pack.persistence_seconds:
            continue
        sensor = next(sensor for sensor in pack.sensors if sensor.id == finding.sensor_id)
        neighboring_excursions = [
            other
            for other in pack.sensors
            if other.id != sensor.id
            and distance(sensor, other) <= pack.neighborhood_m
            and stats[(other.id, finding.channel)]["health_duration"] >= pack.persistence_seconds
        ]
        finding.drift_suspected = not neighboring_excursions
    limitations = ["SYNTHETIC_UNCALIBRATED"]
    if warmup:
        hypothesis = "insufficient_evidence"
        limitations.append("WARMING_UP")
    elif coverage < pack.min_coverage or len(domains) < pack.min_failure_domains:
        hypothesis = "insufficient_evidence"
        limitations.append("COVERAGE_LOST")
    elif support:
        hypothesis = "suspected_leak"
    elif len(acoustic) >= max(pack.min_observers, len(pack.sensors) // 2) and not methane:
        hypothesis = "environmental_disturbance"
        limitations.append("NO_METHANE_CORROBORATION")
    elif acoustic and methane:
        hypothesis = "insufficient_evidence"
        limitations.append("INSUFFICIENT_INDEPENDENT_OBSERVERS")
    elif methane:
        hypothesis = "insufficient_evidence"
        limitations.append("NO_ACOUSTIC_CORROBORATION")
    elif acoustic or any(
        (finding.spike_count >= 2 or (finding.spike_count and finding.max_score >= 10))
        or finding.hard_excluded
        or finding.drift_suspected
        or finding.missing > expected_each * 0.1
        for finding in findings
    ):
        hypothesis = "sensor_or_telemetry_issue"
        if acoustic:
            limitations.append("NO_METHANE_CORROBORATION")
    else:
        hypothesis = "no_event"
        limitations.append("NO_EVENT_NOT_SAFETY")
    # Drift is a soft, isolated-channel pattern; high corroborated leak readings
    # remain usable and are not labeled faulty merely because they are high.
    for finding in findings:
        value = {
            "sensor_id": finding.sensor_id,
            "channel": finding.channel,
            "expected": finding.expected,
            "received": finding.received,
            "usable": finding.usable,
            "missing": finding.missing,
            "hard_excluded": finding.hard_excluded,
            "spike_count": finding.spike_count,
            "drift_suspected": finding.drift_suspected,
        }
        finding.evidence_ids = [
            ledger("sensor_health", value, "sensor_health", finding.sensor_id, finding.channel)
        ]
        # Baseline/noise and raw magnitude are summary evidence, not probabilities.
        ledger(
            "channel_summary",
            {
                "expected": finding.expected,
                "received": finding.received,
                "usable": finding.usable,
                "missing": finding.missing,
                "baseline_median": stats[(finding.sensor_id, finding.channel)]["median"],
                "baseline_scale": stats[(finding.sensor_id, finding.channel)]["scale"],
                "median_excess": stats[(finding.sensor_id, finding.channel)]["excess"],
                "max_score": finding.max_score,
                "persistence_seconds": finding.persistence_seconds,
            },
            sensor_id=finding.sensor_id,
            channel=finding.channel,
        )
    degraded = any(
        finding.hard_excluded
        or finding.spike_count
        or finding.drift_suspected
        or finding.missing > expected_each * 0.1
        for finding in findings
    )
    status = (
        "WARMING_UP"
        if warmup
        else (
            "COVERAGE_LOST"
            if coverage < pack.min_coverage
            else ("DEGRADED" if degraded else "NORMAL")
        )
    )
    quality = QualityReport(
        status=status,
        expected_samples=expected,
        received_samples=sum(finding.received for finding in findings),
        usable_samples=usable_count,
        coverage=coverage,
        failure_domains_available=len(domains),
        findings=findings,
        conflicts=sorted({row.identity for row in selected if row.validity == "conflicted"}),
        issues=limitations[1:],
    )
    ledger(
        "coverage",
        {
            "coverage": coverage,
            "usable_samples": usable_count,
            "received_samples": quality.received_samples,
            "expected_samples": expected,
            "failure_domains_available": len(domains),
            "unit": "fraction",
        },
        "coverage",
    )
    if hypothesis != "suspected_leak":
        support = acoustic
    support_ids = sorted(sensor.id for sensor in support)
    segment_ids = sorted({sensor.segment_id for sensor in support})
    failure_domain_count = len({sensor.failure_domain_id for sensor in support})
    persistence = min((stats[(sensor.id, "acoustic")]["duration"] for sensor in support), default=0)
    event_id = ledger(
        "event_criteria",
        {
            "hypothesis": hypothesis,
            "supporting_sensor_ids": support_ids,
            "failure_domain_count": failure_domain_count,
            "persistence_seconds": persistence,
        },
        "hypothesis",
    )
    event = EventAssessment(
        hypothesis=hypothesis,
        eligible_hypotheses=[hypothesis, "insufficient_evidence"]
        if hypothesis != "insufficient_evidence"
        else [hypothesis],
        supporting_sensor_ids=support_ids,
        failure_domain_count=failure_domain_count,
        persistence_seconds=persistence,
        segment_ids=segment_ids,
        evidence_ids=[event_id],
        counterevidence=limitations[1:],
        eligible_location=hypothesis == "suspected_leak",
    )
    location = None
    if event.eligible_location:
        limitations.extend(
            [
                "LOCATION_MODEL_SIMPLIFIED",
                "GRID_NOT_ACCURACY",
                "COMPATIBLE_NOT_CONFIDENCE",
            ]
        )
        acoustic_stats = {
            sensor.id: stats[(sensor.id, "acoustic")]
            for sensor in pack.sensors
            if stats[(sensor.id, "acoustic")]["usable"] >= expected_each * pack.min_coverage
        }
        # A nearby crossing pipe remains a candidate even if the observing nodes
        # are administratively associated with only one of its two branches.
        relevant_segments = set(segment_ids)
        for segment in pack.segments:
            for index in range(int(segment.length_m // pack.location_grid_m) + 1):
                candidate = point_at_chainage(segment, index * pack.location_grid_m)
                if any(
                    math.hypot(sensor.position.x - candidate.x, sensor.position.y - candidate.y)
                    <= pack.neighborhood_m
                    for sensor in support
                ):
                    relevant_segments.add(segment.id)
                    break
        location = locate(
            pack,
            {key: value["excess"] for key, value in acoustic_stats.items()},
            {key: value["scale"] for key, value in acoustic_stats.items()},
            sorted(relevant_segments),
            {key: value["usable"] / expected_each for key, value in acoustic_stats.items()},
        )
        ledger(
            "location_fit",
            {
                "status": location.status,
                "best": location.best.model_dump(mode="json") if location.best else None,
                "compatible": [item.model_dump(mode="json") for item in location.compatible],
                "unit": "m",
                "method": location.method,
            },
            "location",
        )
        if location.status != "located":
            limitations.append(
                "LOCATION_AMBIGUOUS" if location.status == "ambiguous" else "LOCATION_WITHHELD"
            )
    for code in dict.fromkeys(limitations):
        ledger("limitation", {"code": code}, "limitation")
    input_hash = content_hash(
        {
            "observations": [row.model_dump(mode="json") for row in selected],
            "baseline": [
                row.model_dump(mode="json") for row in sorted(normal, key=lambda row: row.id)
            ],
            "pack": pack.model_dump(mode="json"),
        }
    )
    identity = content_hash(
        {
            "tenant": tenant_id,
            "site": pack.id,
            "generation": generation_id,
            "end": end_seconds,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "warming_up": warmup,
            "input": input_hash,
            "revision": revision,
            "predecessor": predecessor_id,
            "parameters": "window-v1",
            "baseline": "baseline-v1",
        }
    )
    return WindowSnapshot(
        id=f"window-{identity}",
        tenant_id=tenant_id,
        site_id=pack.id,
        generation_id=generation_id,
        window_start=start,
        window_end=end,
        end_seconds=end_seconds,
        revision=revision,
        predecessor_id=predecessor_id,
        input_hash=input_hash,
        pack_version=pack.version,
        clock_seconds=clock_seconds,
        watermark_seconds=clock_seconds - pack.lateness_seconds,
        canonical_count=len(selected),
        quality=quality,
        event=event,
        location=location,
        evidence=evidence,
        claims=claims,
    )
