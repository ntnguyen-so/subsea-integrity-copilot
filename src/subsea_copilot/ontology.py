"""Versioned site and method knowledge; no synthetic scenario truth."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import SitePack
from .synthetic import generate_pack

METHODS = {
    "baseline-v1": {
        "kind": "method",
        "description": "Verified-normal median/MAD with channel-specific minimum noise scale",
        "limitations": ["Anomaly residuals are not event probabilities"],
    },
    "event-rules-v1": {
        "kind": "rule",
        "description": "Persistent local acoustic observers in independent failure domains "
        "with overlapping or delayed methane corroboration",
        "limitations": ["Independence and propagation are synthetic fixture assumptions"],
    },
    "acoustic-excess-distance-decay-v1": {
        "kind": "method",
        "description": "Nonnegative strength fit to A/(distance squared + r0 squared)",
        "limitations": [
            "Compatible grid candidates are not confidence intervals",
            "Grid spacing is not localization accuracy",
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
