"""Pure replay clock and event-time scheduling; no storage or monitoring worker."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .contracts import RawRecord, SitePack
from .ingest import parse_timestamp
from .synthetic import ReplayDataset


def completed_endpoints(
    clock_seconds: float,
    pack: SitePack,
    last_endpoint: int = 0,
) -> list[int]:
    watermark = clock_seconds - pack.lateness_seconds
    first = (last_endpoint // pack.hop_seconds + 1) * pack.hop_seconds
    return list(
        range(
            first, math.floor(watermark / pack.hop_seconds) * pack.hop_seconds + 1, pack.hop_seconds
        )
    )


def affected_endpoints(
    observed_seconds: float,
    clock_seconds: float,
    pack: SitePack,
) -> list[int]:
    watermark = clock_seconds - pack.lateness_seconds
    return [
        endpoint
        for endpoint in completed_endpoints(clock_seconds, pack)
        if endpoint - pack.window_seconds <= observed_seconds < endpoint
        and endpoint >= watermark - pack.revision_seconds
    ]


def arrived_records(dataset: ReplayDataset, clock_seconds: float) -> list[RawRecord]:
    return [
        record
        for record in dataset.records
        if (parse_timestamp(record.received_at) - dataset.epoch).total_seconds() <= clock_seconds
    ]


@dataclass
class ReplayClock:
    duration_seconds: float = 360
    clock_seconds: float = 0
    speed: int = 1
    playing: bool = False

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0 or not 0 <= self.clock_seconds <= self.duration_seconds:
            raise ValueError("Invalid replay duration/clock")
        self.set_speed(self.speed)

    def advance(self, wall_seconds: float) -> float:
        if not math.isfinite(wall_seconds) or wall_seconds < 0:
            raise ValueError("Elapsed wall time must be finite and nonnegative")
        if self.playing:
            self.clock_seconds = min(
                self.duration_seconds, self.clock_seconds + wall_seconds * self.speed
            )
            if self.clock_seconds == self.duration_seconds:
                self.playing = False
        return self.clock_seconds

    def play(self) -> None:
        self.playing = self.clock_seconds < self.duration_seconds

    def pause(self) -> None:
        self.playing = False

    def step(self, hop_seconds: int = 5) -> float:
        if self.playing:
            raise ValueError("Step is only available while paused")
        if hop_seconds <= 0:
            raise ValueError("Hop must be positive")
        self.clock_seconds = min(self.duration_seconds, self.clock_seconds + hop_seconds)
        return self.clock_seconds

    def set_speed(self, speed: int) -> None:
        if speed not in {1, 2, 5, 10, 20, 30}:
            raise ValueError("Supported replay speeds: 1, 2, 5, 10, 20, 30")
        self.speed = speed
