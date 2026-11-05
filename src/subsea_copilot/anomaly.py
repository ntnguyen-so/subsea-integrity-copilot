"""Small fitted one-class model; no LLM or heavyweight ML dependency."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MedianMADDetector:
    center: float
    scale: float
    threshold: float

    @classmethod
    def fit(
        cls, verified_normal: Sequence[float], minimum_scale: float, threshold: float
    ) -> MedianMADDetector:
        values = np.asarray(verified_normal, dtype=float)
        if not len(values) or not np.isfinite(values).all():
            raise ValueError("Detector training requires finite verified-normal readings")
        if minimum_scale <= 0 or threshold <= 0:
            raise ValueError("Detector scale and threshold must be positive")
        center = float(np.median(values))
        scale = max(float(np.median(np.abs(values - center))) * 1.4826, minimum_scale)
        return cls(center, scale, threshold)

    def score(self, value: float) -> float:
        return (value - self.center) / self.scale
