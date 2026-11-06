"""Pressure alerts and cross-sensor investigation; no scenario labels or LLM arithmetic."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from .anomaly import MedianMADDetector
from .contracts import (
    CanonicalObservation,
    Claim,
    EventAssessment,
    EvidenceItem,
    QualityFinding,
    QualityReport,
    SitePack,
    WindowSnapshot,
    content_hash,
)
from .localization import locate, pipeline_distances


def _longest_run(times: Sequence[float], sample_seconds: int) -> tuple[float, float] | None:
    longest: tuple[float, float] | None = None
    previous = -math.inf
    run_start = 0.0
    for second in sorted(set(times)):
        if second - previous > sample_seconds * 1.01:
            run_start = second
        if longest is None or second - run_start + sample_seconds > longest[1] - longest[0]:
            longest = (run_start, second + sample_seconds)
        previous = second
    return longest


def _duration(times: Sequence[float], sample_seconds: int) -> float:
    longest = _longest_run(times, sample_seconds)
    return longest[1] - longest[0] if longest else 0.0


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
    if any(sensor.channels != ["pressure"] for sensor in pack.sensors):
        raise ValueError(
            "Pressure investigation requires pressure instruments; create a new replay"
        )
    start = epoch + timedelta(seconds=end_seconds - pack.window_seconds)
    end = epoch + timedelta(seconds=end_seconds)
    clock = epoch + timedelta(seconds=clock_seconds)
    selected = sorted(
        {
            row.id: row
            for row in observations
            if start <= row.observed_at < end
            and row.received_at <= clock
            and row.observed_at <= clock
        }.values(),
        key=lambda row: row.id,
    )
    normal = [
        row
        for row in baseline
        if row.observed_at < epoch
        and row.received_at <= epoch
        and row.validity == "usable"
        and row.value is not None
        and row.channel == "pressure"
    ]
    groups: dict[str, list[CanonicalObservation]] = defaultdict(list)
    baselines: dict[str, list[float]] = defaultdict(list)
    for row in selected:
        if row.channel == "pressure":
            groups[row.sensor_id].append(row)
    for row in normal:
        if row.value is not None:
            baselines[row.sensor_id].append(row.value)
    expected_each = math.ceil(pack.window_seconds / pack.sample_seconds)
    findings: list[QualityFinding] = []
    stats: dict[str, dict[str, Any]] = {}
    evidence: dict[str, EvidenceItem] = {}
    claims: dict[str, Claim] = {}

    def ledger(
        kind: str,
        value: dict[str, Any],
        claim_kind: str | None = None,
        sensor_id: str | None = None,
    ) -> str:
        identifier = f"ev-{len(evidence):03d}"
        evidence[identifier] = EvidenceItem(
            id=identifier,
            kind=kind,
            value=value,
            sensor_id=sensor_id,
            channel="pressure" if sensor_id else None,
        )
        if claim_kind:
            claim_id = f"claim-{len(claims):03d}"
            claims[claim_id] = Claim(
                id=claim_id,
                kind=claim_kind,
                value=value,
                evidence_ids=[identifier],
            )
        return identifier

    ledger(
        "sensor_metadata",
        {
            "pack_id": pack.id,
            "pack_version": pack.version,
            "sensors": [sensor.model_dump(mode="json") for sensor in pack.sensors],
        },
    )
    missing_baseline = False
    for sensor in pack.sensors:
        rows = groups[sensor.id]
        usable = [row for row in rows if row.validity == "usable" and row.value is not None]
        values = baselines[sensor.id]
        model = None
        if len(values) >= pack.persistence_seconds:
            model = MedianMADDetector.fit(
                values,
                pack.minimum_scales["pressure"],
                pack.anomaly_threshold,
            )
        else:
            missing_baseline = True
        scores = [
            (row, model.score(row.value))
            for row in usable
            if row.value is not None and model is not None
        ]
        drops = [
            (row.observed_at - epoch).total_seconds()
            for row, score in scores
            if score <= -pack.anomaly_threshold
        ]
        excursions = {
            (row.observed_at - epoch).total_seconds()
            for row, score in scores
            if abs(score) >= pack.anomaly_threshold
        }
        times = [(row.observed_at - epoch).total_seconds() for row, _ in scores]
        readings = [row.value for row, _ in scores if row.value is not None]
        trend = False
        if model and len(times) >= pack.persistence_seconds and len(set(times)) > 1:
            ordered = sorted(zip(times, readings, strict=True))
            first = [value for _, value in ordered[: len(ordered) // 3]]
            last = [value for _, value in ordered[-len(ordered) // 3 :]]
            span = float(np.median(np.asarray(last))) - float(np.median(np.asarray(first)))
            if abs(span) >= pack.anomaly_threshold * model.scale:
                correlation = float(np.corrcoef(np.asarray(times), np.asarray(readings))[0, 1])
                trend = abs(correlation) >= 0.85
        finding = QualityFinding(
            sensor_id=sensor.id,
            channel="pressure",
            expected=expected_each,
            received=len({row.observed_at for row in rows}),
            usable=len({row.observed_at for row in usable}),
            missing=max(0, expected_each - len({row.observed_at for row in usable})),
            hard_excluded=sum(row.validity not in {"usable", "missing"} for row in rows),
            spike_count=sum(
                second - pack.sample_seconds not in excursions
                and second + pack.sample_seconds not in excursions
                for second in excursions
            ),
            anomaly_count=len(excursions),
            max_score=max((abs(score) for _, score in scores), default=0),
            persistence_seconds=_duration(sorted(excursions), pack.sample_seconds),
        )
        findings.append(finding)
        stats[sensor.id] = {
            "median": model.center if model else None,
            "scale": model.scale if model else pack.minimum_scales["pressure"],
            "drops": set(drops),
            "excursions": excursions,
            "rises": {
                (row.observed_at - epoch).total_seconds()
                for row, score in scores
                if score >= pack.anomaly_threshold
            },
            "duration": _duration(drops, pack.sample_seconds),
            "usable": finding.usable,
            "trend": trend,
            "deficit": model.center
            - float(
                np.median(
                    [row.value for row, score in scores if score <= -pack.anomaly_threshold]
                    if _duration(drops, pack.sample_seconds) >= pack.persistence_seconds
                    else [row.value for row in usable]
                )
            )
            if model and usable
            else None,
        }
    distances = pipeline_distances(pack)
    for sensor, finding in zip(pack.sensors, findings, strict=True):
        peer = [
            other
            for other in pack.sensors
            if other.station_id == sensor.station_id and other.id != sensor.id
        ]
        finding.peer_disagreement = finding.persistence_seconds >= pack.persistence_seconds and any(
            stats[other.id]["usable"] >= expected_each * pack.min_coverage
            and _duration(
                sorted(
                    (stats[sensor.id]["drops"] & stats[other.id]["drops"])
                    | (stats[sensor.id]["rises"] & stats[other.id]["rises"])
                ),
                pack.sample_seconds,
            )
            < pack.persistence_seconds
            for other in peer
        )
        finding.drift_suspected = finding.peer_disagreement and stats[sensor.id]["trend"]
    expected = expected_each * len(pack.sensors)
    usable_count = sum(finding.usable for finding in findings)
    coverage = min(1.0, usable_count / expected) if expected else 0
    domains = {
        sensor.failure_domain_id
        for sensor in pack.sensors
        if stats[sensor.id]["usable"] >= expected_each * pack.min_coverage
    }
    warmup = (
        end_seconds < pack.window_seconds
        or clock_seconds < end_seconds + pack.lateness_seconds
        or missing_baseline
    )
    pressure = [
        sensor
        for sensor, finding in zip(pack.sensors, findings, strict=True)
        if stats[sensor.id]["duration"] >= pack.persistence_seconds
        and stats[sensor.id]["usable"] >= expected_each * pack.min_coverage
        and not finding.peer_disagreement
    ]
    clusters = []
    for anchor in pressure:
        group = [anchor]
        joint = stats[anchor.id]["drops"].copy()
        for sensor in pressure:
            if sensor.id == anchor.id or distances[anchor.id, sensor.id] > pack.neighborhood_m:
                continue
            overlap = joint & stats[sensor.id]["drops"]
            if _duration(sorted(overlap), pack.sample_seconds) >= pack.persistence_seconds:
                group.append(sensor)
                joint = overlap
        if (
            len(group) >= pack.min_observers
            and len({sensor.station_id for sensor in group}) >= pack.min_stations
            and len({sensor.failure_domain_id for sensor in group}) >= pack.min_failure_domains
        ):
            clusters.append(group)
    support = max(clusters, key=len, default=[])
    limitations = [
        "SYNTHETIC_UNCALIBRATED",
        "PRESSURE_PATTERNS_NOT_PROOF",
        "OPERATING_CONTEXT_REQUIRED",
    ]
    sustained_changes = [
        finding
        for finding in findings
        if finding.persistence_seconds >= pack.persistence_seconds
        and finding.usable >= expected_each * pack.min_coverage
        and not finding.peer_disagreement
    ]
    broad = len(sustained_changes) >= max(pack.min_observers, len(pack.sensors) // 2)
    multiple_regions = support and any(
        not {sensor.id for sensor in group} & {sensor.id for sensor in support}
        for group in clusters
    )
    transient = False
    for anchor in pack.sensors:
        for timestamp in stats[anchor.id]["excursions"]:
            group = [
                sensor
                for sensor in pack.sensors
                if distances[anchor.id, sensor.id] <= pack.neighborhood_m
                and timestamp in stats[sensor.id]["excursions"]
            ]
            if (
                len(group) >= pack.min_observers
                and len({sensor.station_id for sensor in group}) >= pack.min_stations
                and len({sensor.failure_domain_id for sensor in group}) >= pack.min_failure_domains
            ):
                transient = True
                break
        if transient:
            break
    if warmup:
        hypothesis = "insufficient_evidence"
        limitations.append("WARMING_UP")
    elif coverage < pack.min_coverage or len(domains) < pack.min_failure_domains:
        hypothesis = "insufficient_evidence"
        limitations.append("COVERAGE_LOST")
    elif broad:
        hypothesis = "insufficient_evidence"
        limitations.append("COMMON_MODE_PRESSURE_CHANGE")
    elif multiple_regions:
        hypothesis = "insufficient_evidence"
        limitations.append("MULTIPLE_PRESSURE_REGIONS")
    elif support:
        hypothesis = "suspected_leak"
        limitations.append("VERIFY_OPERATING_CHANGES_AND_SHARED_FAILURES")
    elif pressure:
        hypothesis = "insufficient_evidence"
        limitations.append("INSUFFICIENT_INDEPENDENT_OBSERVERS")
    elif sustained_changes:
        hypothesis = "insufficient_evidence"
        limitations.append("UNEXPLAINED_PRESSURE_CHANGE")
    elif transient:
        hypothesis = "insufficient_evidence"
        limitations.append("CORRELATED_PRESSURE_TRANSIENT")
    elif any(
        finding.spike_count
        or finding.hard_excluded
        or finding.peer_disagreement
        or finding.missing > expected_each * 0.1
        for finding in findings
    ):
        hypothesis = "sensor_or_telemetry_issue"
    else:
        hypothesis = "no_event"
        limitations.append("NO_EVENT_NOT_SAFETY")

    for finding in findings:
        value = finding.model_dump(mode="json", exclude={"evidence_ids"})
        finding.evidence_ids = [
            ledger("sensor_health", value, "sensor_health", finding.sensor_id),
        ]
        periods: dict[str, Any] = {}
        if len(pack.sensors) > 32:
            recent = [
                row.value
                for row in groups[finding.sensor_id]
                if row.validity == "usable"
                and row.value is not None
                and end - timedelta(seconds=20) <= row.observed_at < end
            ]
            reference = stats[finding.sensor_id]["median"]
            periods.update(
                recent_pressure_drop_bar=reference - float(np.median(recent))
                if reference is not None and recent
                else None,
                recent_usable_samples=len(recent),
                recent_period_seconds=[end_seconds - 20, end_seconds],
            )
            for direction, key in (("drop", "drops"), ("rise", "rises")):
                run = _longest_run(stats[finding.sensor_id][key], pack.sample_seconds)
                periods[f"pressure_{direction}_period_seconds"] = (
                    list(run) if run and run[1] - run[0] >= pack.persistence_seconds else None
                )
        ledger(
            "channel_summary",
            {
                "detector": "pressure-median-mad-v2",
                "unit": "bar",
                "baseline_median": stats[finding.sensor_id]["median"],
                "baseline_scale": stats[finding.sensor_id]["scale"],
                "anomaly_threshold": pack.anomaly_threshold,
                "median_pressure_drop_bar": stats[finding.sensor_id]["deficit"],
                "anomaly_count": finding.anomaly_count,
                "max_score": finding.max_score,
                "pressure_drop_persistence_seconds": stats[finding.sensor_id]["duration"],
                **periods,
            },
            sensor_id=finding.sensor_id,
        )
    degraded = any(
        finding.hard_excluded
        or finding.spike_count
        or finding.peer_disagreement
        or finding.missing > expected_each * 0.1
        for finding in findings
    )
    quality = QualityReport(
        status="WARMING_UP"
        if warmup
        else (
            "COVERAGE_LOST"
            if coverage < pack.min_coverage or len(domains) < pack.min_failure_domains
            else ("DEGRADED" if degraded else "NORMAL")
        ),
        expected_samples=expected,
        received_samples=sum(f.received for f in findings),
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
        support = pressure
    support_ids = sorted(sensor.id for sensor in support)
    segment_ids = sorted({sensor.segment_id for sensor in support})
    failure_domain_count = len({sensor.failure_domain_id for sensor in support})
    joint = (
        set.intersection(*(stats[sensor.id]["drops"] for sensor in support)) if support else set()
    )
    persistence = _duration(sorted(joint), pack.sample_seconds)
    event_id = ledger(
        "event_criteria",
        {
            "hypothesis": hypothesis,
            "supporting_sensor_ids": support_ids,
            "failure_domain_count": failure_domain_count,
            "station_count": len({sensor.station_id for sensor in support}),
            "persistence_seconds": persistence,
            "detector": "pressure-median-mad-v2",
            "criteria": "pressure-investigation-v2",
            "operating_context": (
                "No valve/compressor records supplied; operator verification required"
            ),
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
        healthy = {
            sensor.id: stats[sensor.id]
            for sensor, finding in zip(pack.sensors, findings, strict=True)
            if stats[sensor.id]["usable"] >= expected_each * pack.min_coverage
            and not finding.peer_disagreement
            and stats[sensor.id]["deficit"] is not None
            and (
                stats[sensor.id]["duration"] >= pack.persistence_seconds
                or finding.persistence_seconds < pack.persistence_seconds
            )
        }
        location = locate(
            pack,
            {key: value["deficit"] for key, value in healthy.items()},
            {key: value["scale"] for key, value in healthy.items()},
            segment_ids,
            {key: value["usable"] / expected_each for key, value in healthy.items()},
        )
        ledger(
            "location_fit",
            {
                "status": location.status,
                "best": location.best.model_dump(mode="json") if location.best else None,
                "compatible": [item.model_dump(mode="json") for item in location.compatible],
                "inspection_start_m": location.inspection_start_m,
                "inspection_end_m": location.inspection_end_m,
                "station_bracket_m": location.station_bracket_m,
                "unit": "m",
                "method": location.method,
            },
            "location",
        )
        limitations.extend(["INSPECTION_INTERVAL_NOT_LEAK_POINT", "COMPATIBLE_NOT_CONFIDENCE"])
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
            "parameters": "pressure-window-v2",
            "baseline": "pressure-median-mad-v2",
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
