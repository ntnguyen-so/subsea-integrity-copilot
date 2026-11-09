"""Topology-aware pressure inspection brackets, not hydraulic leak coordinates."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import median

from .contracts import LocationCandidate, LocationFit, PipelineSegment, Point, Sensor, SitePack


def point_at_chainage(segment: PipelineSegment, chainage_m: float) -> Point:
    """Project engineering chainage onto drawing geometry, scaled to declared length."""
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


def pipeline_distances(pack: SitePack) -> dict[tuple[str, str], float]:
    """Only shared endpoints connect pipes; geometric crossings do not."""
    endpoints = {
        segment.id: (
            (segment.points[0].x, segment.points[0].y),
            (segment.points[-1].x, segment.points[-1].y),
        )
        for segment in pack.segments
    }
    vertices = {point for pair in endpoints.values() for point in pair}
    routes = {(a, b): 0.0 if a == b else math.inf for a in vertices for b in vertices}
    for segment in pack.segments:
        a, b = endpoints[segment.id]
        routes[a, b] = routes[b, a] = min(routes[a, b], segment.length_m)
    # Floyd-Warshall on segment endpoints gives shortest connected-pipe paths;
    # Euclidean proximity across disconnected branches is deliberately ignored.
    for via in vertices:
        for a in vertices:
            for b in vertices:
                routes[a, b] = min(routes[a, b], routes[a, via] + routes[via, b])
    lengths = {segment.id: segment.length_m for segment in pack.segments}
    result = {}
    for first in pack.sensors:
        for second in pack.sensors:
            direct = (
                abs(first.chainage_m - second.chainage_m)
                if first.segment_id == second.segment_id
                else math.inf
            )
            a_ends = zip(
                endpoints[first.segment_id],
                (first.chainage_m, lengths[first.segment_id] - first.chainage_m),
                strict=True,
            )
            indirect = []
            for endpoint_a, offset_a in a_ends:
                for endpoint_b, offset_b in zip(
                    endpoints[second.segment_id],
                    (second.chainage_m, lengths[second.segment_id] - second.chainage_m),
                    strict=True,
                ):
                    indirect.append(offset_a + routes[endpoint_a, endpoint_b] + offset_b)
            result[first.id, second.id] = min(direct, *indirect)
    return result


def locate(
    pack: SitePack,
    deficits: Mapping[str, float],
    scales: Mapping[str, float],
    segment_ids: Sequence[str],
    weights: Mapping[str, float] | None = None,
    *,
    focus_deficits: Mapping[str, float] | None = None,
) -> LocationFit:
    """Bracket sustained affected stations using usable neighbors on the same pipe.

    This deterministic legacy helper proposes an inspection interval, never a
    probability distribution or an inferred hydraulic leak coordinate.
    """
    stations: dict[tuple[str, float], list[bool]] = defaultdict(list)
    observers = []
    for sensor in pack.sensors:
        if sensor.id not in deficits or sensor.id not in scales or scales[sensor.id] <= 0:
            continue
        if weights is not None and weights.get(sensor.id, 0) < pack.min_coverage:
            continue
        dropped = deficits[sensor.id] >= pack.anomaly_threshold * scales[sensor.id]
        stations[sensor.segment_id, sensor.chainage_m].append(dropped)
        if dropped and sensor.segment_id in segment_ids:
            observers.append(sensor)
    if (
        len(observers) < pack.min_observers
        or len({sensor.station_id for sensor in observers}) < pack.min_stations
        or len({sensor.failure_domain_id for sensor in observers}) < pack.min_failure_domains
    ):
        return LocationFit(status="withheld", reason="Insufficient independent pressure observers")
    affected = {sensor.segment_id for sensor in observers}
    if len(affected) != 1:
        return LocationFit(
            status="ambiguous", reason="Pressure evidence spans multiple pipe segments"
        )
    segment_id = next(iter(affected))
    positions = sorted({sensor.chainage_m for sensor in observers})
    healthy = [
        chainage
        for (segment, chainage), flags in stations.items()
        if segment == segment_id and not any(flags)
    ]
    before = [chainage for chainage in healthy if chainage < positions[0]]
    after = [chainage for chainage in healthy if chainage > positions[-1]]
    if any(positions[0] < chainage < positions[-1] for chainage in healthy):
        return LocationFit(status="ambiguous", reason="Disconnected pressure-drop regions")
    if not before or not after:
        if focus_deficits is not None:
            return _pressure_peak_focus(pack, segment_id, focus_deficits, scales, weights)
        return LocationFit(
            status="withheld", reason="No usable unaffected pressure stations on both sides"
        )
    # Midpoints reflect station spacing, not a fitted pressure decay model.
    # Missing flanks or a bracket wider than policy allows withhold the result.
    lower = (max(before) + positions[0]) / 2
    upper = (positions[-1] + min(after)) / 2
    if upper - lower > pack.max_location_width_m:
        if focus_deficits is not None:
            return _pressure_peak_focus(pack, segment_id, focus_deficits, scales, weights)
        return LocationFit(status="withheld", reason="Inspection bracket exceeds qualified width")
    segment = next(segment for segment in pack.segments if segment.id == segment_id)

    def candidate(chainage: float) -> LocationCandidate:
        return LocationCandidate(
            segment_id=segment_id,
            chainage_m=chainage,
            position=point_at_chainage(segment, chainage),
        )

    return LocationFit(
        status="located",
        best=candidate(median([lower, upper])),
        compatible=[candidate(lower), candidate(upper)],
        inspection_start_m=lower,
        inspection_end_m=upper,
        station_bracket_m=[max(before), positions[0], positions[-1], min(after)],
        reason="Priority inspection interval between station midpoints; not an exact leak location "
        "or a confidence interval",
    )


def _pressure_peak_focus(
    pack: SitePack,
    segment_id: str,
    deficits: Mapping[str, float],
    scales: Mapping[str, float],
    weights: Mapping[str, float] | None,
) -> LocationFit:
    """Bound a prominent pressure focus, not the full above-threshold footprint."""
    grouped: dict[float, list[Sensor]] = defaultdict(list)
    for sensor in pack.sensors:
        if sensor.segment_id == segment_id:
            grouped[sensor.chainage_m].append(sensor)
    positions = sorted(grouped)
    measured: dict[float, float] = {}
    bands: dict[float, float] = {}
    for position, sensors in grouped.items():
        if len(sensors) < 2 or any(
            sensor.id not in deficits or sensor.id not in scales or scales[sensor.id] <= 0
            or (weights is not None and weights.get(sensor.id, 0) < pack.min_coverage)
            for sensor in sensors
        ):
            continue
        values = [deficits[sensor.id] for sensor in sensors]
        band = pack.anomaly_threshold * max(scales[sensor.id] for sensor in sensors)
        if max(values) - min(values) <= band:
            measured[position] = median(values)
            bands[position] = band
    if not measured:
        return LocationFit(status="withheld", reason="No usable paired pressure-peak observations")
    # Extended networks may have a wide above-threshold footprint. A unique
    # paired peak may narrow inspection only if adjacent contrasts exceed noise.
    peak = max(measured.values())
    band = max(bands.values())
    core = sorted(position for position, value in measured.items() if peak - value <= band)
    first, last = positions.index(core[0]), positions.index(core[-1])
    if peak <= band or first == 0 or last == len(positions) - 1:
        return LocationFit(status="withheld", reason="Pressure peak has no bounding station pair")
    if positions[first:last + 1] != core:
        return LocationFit(
            status="ambiguous", reason="Multiple or incompletely observed pressure peaks",
        )
    before, after = positions[first - 1], positions[last + 1]
    if before not in measured or after not in measured:
        return LocationFit(
            status="withheld", reason="Pressure-peak comparison station is unavailable",
        )
    if min(measured[position] for position in core) - max(measured[before], measured[after]) < band:
        return LocationFit(
            status="withheld",
            reason="Neighboring pressure contrast is below baseline noise allowance",
        )
    witnesses = [sensor for position in [before, *core, after] for sensor in grouped[position]]
    if (
        len(witnesses) < pack.min_observers
        or len({sensor.station_id for sensor in witnesses}) < pack.min_stations
        or len({sensor.failure_domain_id for sensor in witnesses}) < pack.min_failure_domains
    ):
        return LocationFit(
            status="withheld", reason="Pressure-peak comparisons lack independent observers",
        )
    lower, upper = (before + core[0]) / 2, (core[-1] + after) / 2
    if upper - lower > pack.max_location_width_m:
        return LocationFit(status="withheld", reason="Pressure-peak focus exceeds qualified width")
    segment = next(segment for segment in pack.segments if segment.id == segment_id)
    candidates = [
        LocationCandidate(
            segment_id=segment_id, chainage_m=value, position=point_at_chainage(segment, value),
        )
        for value in [median([lower, upper]), lower, upper]
    ]
    return LocationFit(
        status="located", best=candidates[0], compatible=candidates[1:],
        inspection_start_m=lower, inspection_end_m=upper,
        station_bracket_m=[before, core[0], core[-1], after],
        method="pressure-peak-focus-v1",
        reason="Priority inspection focus around a unique measured pressure-deficit peak, "
        "bounded by weaker neighboring stations. These stations need not be unaffected. "
        "This is a spatial pressure-focus heuristic, not hydraulic leak coordinates "
        "or a confidence interval.",
    )
