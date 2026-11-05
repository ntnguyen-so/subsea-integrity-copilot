"""Canonical conversion, with explicit hard-invalidity and retained provenance."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import CanonicalObservation, RawRecord, Sensor, SitePack, content_hash

UNITS = {"pressure": "bar", "acoustic": "a.u.", "methane": "umol/L", "temperature": "degC"}
SENTINELS = {"", "null", "none", "na", "n/a", "-9999"}


def parse_timestamp(text: str) -> datetime:
    """Require an explicit ISO offset or a named IANA timezone."""
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        try:
            stamp, zone = text.rsplit(" ", 1)
            parsed = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
            tz = ZoneInfo(zone)
            candidate = parsed.replace(tzinfo=tz)
            # Reject ambiguous/nonexistent local times instead of guessing DST.
            if candidate.utcoffset() != parsed.replace(tzinfo=tz, fold=1).utcoffset():
                raise ValueError("Ambiguous or nonexistent local time")
            parsed = candidate
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(f"Unknown or malformed zoned timestamp: {text}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must explicitly declare a timezone")
    return parsed.astimezone(UTC)


def normalize_records(
    records: Sequence[RawRecord],
    pack: SitePack,
) -> list[CanonicalObservation]:
    buffer = CanonicalBuffer(pack)
    buffer.ingest(records)
    return buffer.observations()


def _normalize_record(
    record: RawRecord,
    digest: str,
    sensor_map: dict[str, Sensor],
    conflicted: bool,
) -> CanonicalObservation:
    identity = f"{record.source_id}:{record.source_record_id}"
    transformations = []
    validity = "usable"
    # Invalid timestamps have no truthful event time. Retain the record with
    # an explicit malformed flag and deterministic sentinel time, never usable.
    try:
        observed_at = parse_timestamp(record.observed_at)
    except ValueError:
        observed_at = datetime(1970, 1, 1, tzinfo=UTC)
        validity = "malformed"
        transformations.append("invalid observed timestamp; sentinel event time")
    try:
        received_at = parse_timestamp(record.received_at)
    except ValueError:
        received_at = datetime(1970, 1, 1, tzinfo=UTC)
        validity = "malformed"
        transformations.append("invalid received timestamp; sentinel arrival time")
    transformations.append("explicit timestamp converted to UTC")
    arrival_delay = (received_at - observed_at).total_seconds()
    if validity == "usable" and arrival_delay < 0:
        validity = "malformed"
        transformations.append("arrival precedes event time")
    elif validity == "usable" and arrival_delay > 0:
        transformations.append(f"arrival_delay_seconds:{arrival_delay:g}")
    value = None
    raw_value = record.value
    if (
        raw_value is None
        or raw_value == -9999
        or (isinstance(raw_value, str) and raw_value.strip().lower() in SENTINELS)
    ):
        if validity == "usable":
            validity = "missing"
        transformations.append("documented null/sentinel retained as missing")
    else:
        try:
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError("Nonfinite value")
        except (TypeError, ValueError, OverflowError):
            value = None
            validity = "malformed"
            transformations.append("malformed/nonfinite numeric payload")
    canonical_unit = UNITS[record.channel]
    if record.channel == "pressure" and record.unit in {"kPa", "MPa", "Pa"}:
        factor = {"kPa": 0.01, "MPa": 10.0, "Pa": 0.00001}[record.unit]
        if value is not None:
            value *= factor
        transformations.append(f"{record.unit} multiplied by {factor:g} to bar")
    elif record.channel == "methane" and record.unit == "nmol/L":
        if value is not None:
            value /= 1000
        transformations.append("nmol/L divided by 1000 to umol/L")
    elif record.unit != canonical_unit:
        validity = "malformed"
        transformations.append(f"unknown or incompatible unit: {record.unit}")
    sensor = sensor_map.get(record.sensor_id)
    if sensor is None or record.channel not in sensor.channels:
        validity = "malformed"
        transformations.append("unknown sensor/channel capability")
    if value is not None and (
        (record.channel in {"acoustic", "methane"} and value < 0)
        or (record.channel == "pressure" and not 0 <= value <= 250)
        or (record.channel == "temperature" and not -5 <= value <= 60)
    ):
        validity = "impossible"
        transformations.append("outside declared physical domain")
    if conflicted:
        validity = "conflicted"
        transformations.append("identity conflict; all payloads quarantined")
    return CanonicalObservation(
        id=f"obs-{digest}",
        identity=identity,
        sensor_id=record.sensor_id,
        channel=record.channel,
        observed_at=observed_at,
        received_at=received_at,
        value=value,
        unit=canonical_unit,
        validity=validity,
        source_id=record.source_id,
        source_record_id=record.source_record_id,
        original=record,
        transformations=transformations,
    )


def _observation_order(observation: CanonicalObservation) -> tuple[datetime, datetime, str]:
    return observation.observed_at, observation.received_at, observation.id


class CanonicalBuffer:
    """Incrementally canonicalize released batches in one site/replay scope.

    Ingestion hashes only the supplied batch. The first identity conflict emits
    replacement masks for previous payloads as well as the new payload. Previously
    returned observations remain unchanged; their replacements must be persisted
    by the caller without mutating any pinned diagnostic snapshot.
    """

    def __init__(self, pack: SitePack) -> None:
        self._sensor_map = {sensor.id: sensor.model_copy(deep=True) for sensor in pack.sensors}
        self._by_digest: dict[str, CanonicalObservation] = {}
        self._identities: dict[str, set[str]] = defaultdict(set)
        self._ordered: list[CanonicalObservation] | None = None

    def ingest(self, records: Sequence[RawRecord]) -> list[CanonicalObservation]:
        changed: dict[str, CanonicalObservation] = {}
        for record in records:
            digest = content_hash(record.model_dump(mode="json"))
            if digest in self._by_digest:
                continue
            identity = f"{record.source_id}:{record.source_record_id}"
            previous = self._identities[identity]
            if len(previous) == 1:
                old_digest = next(iter(previous))
                old = self._by_digest[old_digest]
                masked = old.model_copy(
                    update={
                        "validity": "conflicted",
                        "transformations": [
                            *old.transformations,
                            "identity conflict; all payloads quarantined",
                        ],
                    }
                )
                self._by_digest[old_digest] = masked
                changed[old_digest] = masked
            previous.add(digest)
            observation = _normalize_record(
                record.model_copy(deep=True),
                digest,
                self._sensor_map,
                len(previous) > 1,
            )
            self._by_digest[digest] = observation
            changed[digest] = observation
        if changed:
            self._ordered = None
        return sorted(changed.values(), key=_observation_order)

    def observations(self) -> list[CanonicalObservation]:
        """Event-time ordered current view; copying its list does not rehash rows."""
        if self._ordered is None:
            self._ordered = sorted(self._by_digest.values(), key=_observation_order)
        return self._ordered.copy()
