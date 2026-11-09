"""Versioned site and method knowledge; no synthetic scenario truth."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import SitePack
from .synthetic import generate_pack

METHODS = {
    "pressure-median-mad-v2": {
        "kind": "method",
        "description": "Per-instrument median/MAD model fitted on verified-normal pressure. "
        "Two-sided alerts at five robust scales; no live retraining on suspected events.",
        "limitations": ["Anomaly residuals are not event probabilities"],
    },
    "pressure-investigation-v2": {
        "kind": "rule",
        "description": "Persistent overlapping pressure drops at nearby connected-pipe stations "
        "in independent failure domains; assess sensor faults and broad operating changes.",
        "limitations": [
            "Patterns support suspicion, not proof",
            "Valve/compressor context is not connected; operator verification required",
        ],
    },
    "pressure-alert-bracket-v2": {
        "kind": "method",
        "description": "Bracket affected stations using midpoints to unaffected stations "
        "on either side; recommend an inspection interval, not a hydraulic source coordinate",
        "limitations": [
            "Inspection intervals are not confidence intervals",
            "Station spacing limits the recommended inspection interval",
        ],
    },
    "read-only-v1": {
        "kind": "policy",
        "description": "Suspected event evidence only; verify with a qualified operator",
        "limitations": [
            "No confirmed leak or safe-production determination",
            "No autonomous control",
        ],
    },
}


def load_pack(site_id: str = "northsea", path: Path | None = None) -> SitePack:
    if path is not None:
        pack = SitePack.model_validate_json(path.read_text(encoding="utf-8"))
        if pack.id != site_id:
            raise ValueError("Requested site does not match pack identity")
        return pack
    return generate_pack(site_id)


def knowledge_items(pack: SitePack) -> list[dict[str, Any]]:
    """Expose versioned assets and declared method caveats, never scenario injection labels."""
    return [
        {"id": pack.id, "kind": "site", "name": pack.name, "version": pack.version},
        *[
            {"id": sensor.id, "kind": "sensor", **sensor.model_dump(mode="json")}
            for sensor in pack.sensors
        ],
        *[
            {"id": segment.id, "kind": "pipeline", **segment.model_dump(mode="json")}
            for segment in pack.segments
        ],
        *[{"id": identifier, **method} for identifier, method in METHODS.items()],
    ]
