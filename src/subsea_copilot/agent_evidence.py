"""Measurement-only agent views; archived numerical decisions are not agent evidence."""

from .contracts import EventAssessment, WindowSnapshot

_HEALTH_DECISIONS = {"drift_suspected", "peer_disagreement"}
_DATA_LIMITATIONS = {
    "WARMING_UP", "COVERAGE_LOST", "SYNTHETIC_UNCALIBRATED",
    "synthetic_data", "read_only", "missing_data", "warming_up",
    "coverage_lost", "degraded_coverage", "metadata_unavailable",
}
_MEASUREMENTS = {
    "sensor_metadata", "sensor_health", "channel_summary", "coverage",
    "limitation", "topology", "ontology",
}


def measurement_snapshot(snapshot: WindowSnapshot) -> WindowSnapshot:
    evidence = {}
    for identifier, item in snapshot.evidence.items():
        if item.kind not in _MEASUREMENTS:
            continue
        value = item.value
        if item.kind == "limitation" and (
            not isinstance(value, dict) or value.get("code") not in _DATA_LIMITATIONS
        ):
            continue
        if item.kind == "sensor_health" and isinstance(value, dict):
            value = {key: number for key, number in value.items() if key not in _HEALTH_DECISIONS}
            item = item.model_copy(update={"value": value})
        evidence[identifier] = item
    claims = {
        identifier: claim.model_copy(update={
            "value": {
                key: value for key, value in claim.value.items()
                if key not in _HEALTH_DECISIONS
            } if isinstance(claim.value, dict) else claim.value,
        })
        for identifier, claim in snapshot.claims.items()
        if claim.kind in {"coverage", "sensor_health", "limitation"}
        and len(claim.evidence_ids) == 1 and claim.evidence_ids[0] in evidence
    }
    quality = snapshot.quality.model_copy(update={
        "findings": [
            finding.model_copy(update={"drift_suspected": False, "peer_disagreement": False})
            for finding in snapshot.quality.findings
        ],
        "issues": [
            code for code in snapshot.quality.issues if code in _DATA_LIMITATIONS
        ],
    })
    return snapshot.model_copy(update={
        "quality": quality,
        "event": EventAssessment(
            hypothesis="insufficient_evidence",
            eligible_hypotheses=[],
            criteria_id="measurement-only-no-domain-decision",
        ),
        "location": None,
        "evidence": evidence,
        "claims": claims,
    })
