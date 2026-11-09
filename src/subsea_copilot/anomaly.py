"""Small fitted one-class model; no LLM or heavyweight ML dependency."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MedianMADDetector:
    """Frozen per-instrument normal reference; scores are residuals, not probabilities."""

    center: float
    scale: float
    threshold: float

    @classmethod
    def fit(
        cls, verified_normal: Sequence[float], minimum_scale: float, threshold: float
    ) -> MedianMADDetector:
        """Fit median and robust noise scale from explicitly verified-normal values."""
        values = np.asarray(verified_normal, dtype=float)
        if not len(values) or not np.isfinite(values).all():
            raise ValueError("Detector training requires finite verified-normal readings")
        if minimum_scale <= 0 or threshold <= 0:
            raise ValueError("Detector scale and threshold must be positive")
        center = float(np.median(values))
        # 1.4826 makes MAD comparable to sigma for Gaussian data. The declared
        # floor avoids near-zero scales; neither it nor the threshold is learned.
        scale = max(float(np.median(np.abs(values - center))) * 1.4826, minimum_scale)
        return cls(center, scale, threshold)

    def score(self, value: float) -> float:
        return (value - self.center) / self.scale
