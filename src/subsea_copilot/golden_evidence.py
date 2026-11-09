"""Verify persisted synthetic telemetry rather than trusting exporter enqueue success.

Local Langfuse observations supply stored generation/tool inputs, outputs and public
model metadata. Runtime/extractor inputs are scanned for hidden-truth keys; external
judge/extractor evidence must match submitted input and accepted-output hashes.
Bounded capture and credential filtering keep receipts public. Presence/hash checks
support provenance, not completeness of runtime reasoning or semantic correctness.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from .contracts import content_hash


def normalized_content(value: Any) -> Any:
    """Decode up to two JSON string layers used by stored observation encodings."""
    for _ in range(2):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            break
    return value


def _contains_hidden_truth(value: Any) -> bool:
    parsed = normalized_content(value)
    if isinstance(parsed, dict):
        return bool({
            "source_truth", "hidden_expected_outcomes", "golden_case_id", "source_probe",
            "leak_source", "source_sensor_issue_labels", "truth",
        } & parsed.keys()) or any(_contains_hidden_truth(item) for item in parsed.values())
    if isinstance(parsed, list):
        return any(_contains_hidden_truth(item) for item in parsed)
    return False


def public_observation_metadata(value: Any) -> dict[str, Any]:
    """Allowlist public model/error attributes without exporting auth/configuration fields."""
    metadata = normalized_content(value)
    if not isinstance(metadata, dict):
        return {}
    attributes = metadata.get("attributes")
    if isinstance(attributes, dict):
        metadata = {**metadata, **attributes}
    metadata = {key.removeprefix("attributes."): item for key, item in metadata.items()}
    return {
        key: item for key, item in metadata.items()
        if (key in {"error.code", "error.type", "judge.outcome"} or key.rsplit(".", 1)[-1] in {
            "role", "phase", "requested_model", "observed_model",
            "model_identity_source", "call_id", "task_id", "mode",
        }) and isinstance(item, (str, int, float, bool))
        and not re.search(r"secret|password|authorization|credential", key, re.I)
    }


def content_evidence(
    observations: list[dict[str, Any]], kind: str,
    *, expected_input_hash: str | None = None, expected_output_hash: str | None = None,
) -> dict[str, Any]:
    """Require stored generation IO and, for runtime traces, tool IO as well.

    Judge/mapping checks require one generation whose complete input and output hashes
    both match. Runtime truth-key scanning is a structural safeguard, not proof that
    arbitrary prose cannot leak a label or that every model interaction was captured.
    """
    required = (
        {"generation"} if kind in {"external_judge", "output_mapping"}
        else {"generation", "tool"}
    )
    checked = []
    for observation in observations:
        observation_type = str(observation.get("type", "")).lower()
        if observation_type not in required:
            continue
        actual_input = normalized_content(observation.get("input"))
        actual_output = normalized_content(observation.get("output"))
        has_content = actual_input not in (None, "", {}, []) and (
            actual_output not in (None, "", {}, [])
        )
        entry = {
            "observation_id": observation.get("id"), "name": observation.get("name"),
            "type": observation_type, "stored_input_present": has_content,
            "input_sha256": content_hash(actual_input) if actual_input is not None else None,
            "output_sha256": content_hash(actual_output) if actual_output is not None else None,
            "input_chars": len(json.dumps(actual_input)),
            "output_chars": len(json.dumps(actual_output)),
            "observed_model": observation.get("model"),
            "usage_details": observation.get("usageDetails"),
            "public_model_metadata": observation.get("public_model_metadata", {}),
        }
        if kind in {"runtime_agent", "output_mapping"}:
            entry["hidden_truth_absent_from_stored_input"] = not _contains_hidden_truth(
                actual_input,
            )
        if kind in {"external_judge", "output_mapping"}:
            entry["input_matches_submitted_judge_packet"] = (
                expected_input_hash is not None and entry["input_sha256"] == expected_input_hash
            )
            entry["output_matches_recorded_verdict"] = (
                expected_output_hash is not None and entry["output_sha256"] == expected_output_hash
            )
        checked.append(entry)
    observed_types = {entry["type"] for entry in checked}
    passed = (
        required <= observed_types and all(entry["stored_input_present"] for entry in checked)
        and all(
            entry.get("hidden_truth_absent_from_stored_input", True) for entry in checked
        )
        and (kind not in {"external_judge", "output_mapping"} or any(
            entry["input_matches_submitted_judge_packet"]
            and entry["output_matches_recorded_verdict"] for entry in checked
        ))
    )
    return {
        "passed": passed, "required_content_types": sorted(required),
        "observations": checked,
        "scope": (
            "Reads stored io fields. External judge input/verdict must match complete hashes. "
            "Runtime content is verified present, not independently certified complete."
        ),
    }


def fetch_stored_observations(trace_id: str) -> list[dict[str, Any]]:
    """Same loopback/auth source as Telemetry.verify_trace; no redirects or secret output."""
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id):
        raise ValueError("Invalid trace identifier")
    endpoint = os.environ.get(
        "SUBSEA_LANGFUSE_OTLP_ENDPOINT", "http://127.0.0.1:3001/api/public/otel/v1/traces",
    )
    parts = urlsplit(endpoint)
    if (
        parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parts.username or parts.password or parts.query or parts.fragment
    ):
        raise ValueError("Only the configured local Langfuse can be queried")
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not public or not secret:
        raise ValueError("Langfuse verification is not configured")
    authorization = base64.b64encode(f"{public}:{secret}".encode()).decode()
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    all_observations = []
    cursor = None
    captured_bytes = 0
    for _ in range(50):
        query = {
            "traceId": trace_id, "fields": "core,basic,io,model,usage,metadata", "limit": "5",
        }
        if cursor:
            query["cursor"] = cursor
        url = f"{parts.scheme}://{parts.netloc}/api/public/v2/observations?{urlencode(query)}"
        request = urllib.request.Request(url, headers={"Authorization": f"Basic {authorization}"})
        with opener.open(request, timeout=5) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Stored observation response exceeds bounded capture")
        captured_bytes += len(raw)
        if captured_bytes > 10_000_000:
            raise ValueError("Stored trace responses exceed bounded aggregate capture")
        value = json.loads(raw)
        observations = value.get("data") if isinstance(value, dict) else None
        if not isinstance(observations, list) or len(observations) > 5 or any(
            not isinstance(item, dict) or item.get("traceId") != trace_id for item in observations
        ):
            raise ValueError("Stored trace observations are absent or incorrectly scoped")
        all_observations.extend(observations)
        cursor = (value.get("meta") or {}).get("cursor")
        if not cursor:
            break
        if not isinstance(cursor, str):
            raise ValueError("Invalid observation page cursor")
    else:
        raise ValueError("Stored trace pagination exceeded its bound")
    if not all_observations:
        raise ValueError("No stored trace observations")
    # Select only synthetic public IO/model fields, never returned configuration/headers.
    selected = []
    for item in all_observations:
        row = {key: item.get(key) for key in (
            "id", "traceId", "name", "type", "parentObservationId", "sessionId",
            "input", "output", "model", "usageDetails", "level", "statusMessage",
        )}
        row["public_model_metadata"] = public_observation_metadata(item.get("metadata"))
        selected.append(row)
    return selected


def verify_stored_content(
    trace_id: str, kind: str, output: Path, *,
    expected_input_hash: str | None = None, expected_output_hash: str | None = None,
) -> dict[str, Any]:
    """Save selected stored observations; unavailable/invalid capture is a failed receipt."""
    try:
        observations = fetch_stored_observations(trace_id)
        evidence = content_evidence(
            observations, kind, expected_input_hash=expected_input_hash,
            expected_output_hash=expected_output_hash,
        )
        destination = output / "stored-observations"
        destination.mkdir(parents=True, exist_ok=True)
        artifact = destination / f"{trace_id}.json"
        artifact.write_text(
            json.dumps(observations, indent=2, allow_nan=False), encoding="utf-8",
        )
        evidence["artifact"] = str(artifact)
        return evidence
    except (OSError, ValueError, urllib.error.URLError):
        return {"passed": False, "error_code": "stored_content_unavailable"}
