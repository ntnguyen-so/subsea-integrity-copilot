"""Index and reopen original detection reports without regrading or inference.

Approved archive roots are runtime, eval and docs; only known report versions with a
run ID are indexed. Tokens bind relative path, mtime and size, not a model score.
Loading rechecks identity and file stability, then removes agent-process audit fields.
The public index hides filesystem paths; missing/corrupt archives remain explicit
warnings or errors rather than silently substituting the latest evaluation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .contracts import utc_now

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "runtime" / "evaluation-history.json"
VERSIONS = {"reference-evaluation-v1", "spatial-evaluation-v1"}
ARCHIVE_ROOTS = ("runtime", "eval", "docs")


def header(path: Path) -> dict[str, Any]:
    """Read only ordered top-level metadata, not multi-megabyte frame arrays."""
    decoder = json.JSONDecoder()
    metadata: dict[str, Any] = {}
    with path.open(encoding="utf-8") as source:
        prefix = source.read(65536)
    cursor = prefix.index("{") + 1
    while cursor < len(prefix):
        while cursor < len(prefix) and prefix[cursor] in " \r\n\t,":
            cursor += 1
        if prefix[cursor : cursor + 1] == "}":
            break
        key, cursor = decoder.raw_decode(prefix, cursor)
        while cursor < len(prefix) and prefix[cursor] in " \r\n\t:":
            cursor += 1
        if key in {"cases", "networks", "metrics", "previous_runs"}:
            break
        value, cursor = decoder.raw_decode(prefix, cursor)
        metadata[key] = value
    return metadata


def rebuild_history(root: Path = ROOT, index: Path = INDEX) -> dict[str, Any]:
    """Persist metadata-only discovery, retaining separate suites and report revisions."""
    from .reference_evaluation import write_report

    paths: set[Path] = set()
    for folder in (root / "runtime", root / "eval", root / "docs" / "evidence"):
        if folder.exists():
            paths.update(folder.rglob("report.json"))
            paths.update(folder.rglob("evaluation-report.json"))
    paths.update((root / "runtime").glob("evaluation-before*.json"))
    paths.discard(root / "runtime" / "evaluation-report.json")
    entries = []
    warnings = []
    for path in sorted(paths):
        try:
            relative = path.resolve().relative_to(root.resolve())
            if relative.parts[0] not in ARCHIVE_ROOTS:
                raise ValueError("Archive is outside the approved output folders")
            info = header(path)
            if info.get("version") not in VERSIONS or not info.get("run_id"):
                continue
            stat = path.stat()
            identity = f"{relative}|{stat.st_mtime_ns}|{stat.st_size}"
            entries.append(
                {
                    "archive_id": hashlib.sha256(identity.encode()).hexdigest(),
                    "run_id": info["run_id"],
                    "suite": info.get("suite", "current"),
                    "version": info["version"],
                    "created_at": info.get("created_at"),
                    "status": info.get("status", "not_recorded"),
                    "split": info.get("split"),
                    "agent_model": info.get("agent_model"),
                    "label": path.stem if path.parent == root / "runtime" else path.parent.name,
                    "relative_path": str(relative),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "available": True,
                }
            )
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "Archived evaluation %s cannot be indexed: %s", path.name, type(exc).__name__
            )
            warnings.append(f"{path.parent.name}: {type(exc).__name__}")
    entries.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    result = {
        "version": "evaluation-history-v1",
        "created_at": utc_now().isoformat(),
        "entries": entries,
        "warnings": warnings,
    }
    write_report(index, result)
    return result


def public_history(index: Path = INDEX) -> dict[str, Any]:
    """Project archive tokens and labels without exposing local filesystem metadata."""
    if not index.exists():
        return {"entries": [], "warnings": []}
    result = json.loads(index.read_text(encoding="utf-8"))
    if result.get("version") != "evaluation-history-v1":
        raise ValueError("Unrecognized evaluation history index")
    return {
        "entries": [
            {
                key: value
                for key, value in row.items()
                if key not in {"relative_path", "size", "mtime_ns"}
            }
            for row in result["entries"]
        ],
        "warnings": result["warnings"],
    }


def load_archive(archive_id: str, *, root: Path = ROOT, index: Path = INDEX) -> dict[str, Any]:
    """Return original recorded scores only if indexed path, revision and scope match."""
    from .temporal_evaluation import without_agent_audit_results

    catalog = json.loads(index.read_text(encoding="utf-8"))
    entry = next((row for row in catalog["entries"] if row["archive_id"] == archive_id), None)
    if entry is None:
        raise LookupError("Unknown archived evaluation")
    path = (root / entry["relative_path"]).resolve()
    relative = path.relative_to(root.resolve())
    if not relative.parts or relative.parts[0] not in ARCHIVE_ROOTS:
        raise ValueError("Archive is outside approved output folders")
    stat = path.stat()
    if stat.st_size != entry["size"] or stat.st_mtime_ns != entry["mtime_ns"]:
        raise ValueError("Archive changed since indexing; refresh the history catalog")
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    after = path.stat()
    if after.st_size != stat.st_size or after.st_mtime_ns != stat.st_mtime_ns:
        raise ValueError("Archive changed while loading; refresh the history catalog")
    if report.get("version") not in VERSIONS or report.get("run_id") != entry["run_id"]:
        raise ValueError("Archive identity does not match the history catalog")
    if report.get("suite", "current") != entry["suite"]:
        raise ValueError("Archive suite does not match the history catalog")
    report = without_agent_audit_results(report)
    report.pop("agent_reference_evaluation", None)
    report["historical_archive_id"] = archive_id
    report["historical_archive_label"] = entry["label"]
    return report
