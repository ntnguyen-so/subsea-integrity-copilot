"""Inspectable acoustic excess fit, not a calibrated confidence estimator."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .contracts import LocationCandidate, LocationFit, PipelineSegment, Point, SitePack


def point_at_chainage(segment: PipelineSegment, chainage_m: float) -> Point:
    lengths = [
        math.hypot(b.x - a.x, b.y - a.y)
        for a, b in zip(segment.points[:-1], segment.points[1:], strict=True)
    ]
    total = sum(lengths)
    if total <= 0 or segment.length_m <= 0:
        raise ValueError("Pipeline geometry must have positive length")
    remaining = chainage_m / segment.length_m * total
    for a, b, length in zip(segment.points[:-1], segment.points[1:], lengths, strict=True):
        if remaining <= length and length > 0:
            fraction = remaining / length
            return Point(x=a.x + fraction * (b.x - a.x), y=a.y + fraction * (b.y - a.y))
        remaining -= length
    return segment.points[-1]


def locate(
    pack: SitePack,
    excess: Mapping[str, float],
    scales: Mapping[str, float],
    segment_ids: Sequence[str],
    weights: Mapping[str, float] | None = None,
) -> LocationFit:
    sensors = [
        sensor
        for sensor in pack.sensors
        if sensor.id in excess and sensor.id in scales and scales[sensor.id] > 0
    ]
    if len(sensors) < pack.min_observers:
        return LocationFit(status="withheld", reason="Insufficient usable acoustic observers")
    candidates = []
    for segment in pack.segments:
        if segment.id not in segment_ids:
            continue
        grid = [
            index * pack.location_grid_m
            for index in range(int(segment.length_m // pack.location_grid_m) + 1)
        ]
        if grid[-1] != segment.length_m:
            grid.append(segment.length_m)
        for chainage in grid:
            point = point_at_chainage(segment, chainage)
            kernels = []
            observed = []
            precision = []
            for sensor in sensors:
                distance2 = (sensor.position.x - point.x) ** 2 + (sensor.position.y - point.y) ** 2
                kernels.append(1 / (distance2 + pack.location_r0_m**2))
                observed.append(excess[sensor.id])
                precision.append((weights or {}).get(sensor.id, 1) / scales[sensor.id] ** 2)
            denominator = sum(w * k * k for w, k in zip(precision, kernels, strict=True))
            if denominator <= 0:
                continue
            strength = max(
                0.0,
                sum(w * k * y for w, k, y in zip(precision, kernels, observed, strict=True))
                / denominator,
            )
            residual = math.sqrt(
                sum(
                    w * (y - strength * k) ** 2
                    for w, k, y in zip(precision, kernels, observed, strict=True)
                )
                / len(sensors)
            )
            candidates.append(
                LocationCandidate(
                    segment_id=segment.id,
                    chainage_m=chainage,
                    position=point,
                    residual=residual,
                    strength=strength,
                )
            )
    if not candidates:
        return LocationFit(status="withheld", reason="No relevant pipeline candidates")
    candidates.sort(
        key=lambda candidate: (candidate.residual, candidate.segment_id, candidate.chainage_m)
    )
    best = candidates[0]
    if best.residual > 4:
        return LocationFit(
            status="withheld", best=best, reason="Poor fit to idealized acoustic propagation model"
        )
    compatible = [
        candidate
        for candidate in candidates
        if candidate.residual <= best.residual + pack.compatible_residual_tolerance
    ]
    segments = {candidate.segment_id for candidate in compatible}
    width = max(candidate.chainage_m for candidate in compatible) - min(
        candidate.chainage_m for candidate in compatible
    )
    if len(segments) > 1:
        status, reason = "ambiguous", "Multiple physically compatible pipeline segments"
    elif width > pack.max_location_width_m:
        status, reason = "withheld", "Compatible candidate set exceeds qualified width"
    else:
        status, reason = "located", "Compatible grid candidates, not a confidence interval"
    return LocationFit(
        status=status, best=best, compatible=compatible, reason=reason, grid_m=pack.location_grid_m
    )
