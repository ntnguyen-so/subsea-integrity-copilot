"""Content-addressed author-harness templates and effective execution policy.

Task phase, prompts, schemas, registry and budgets produce a reproducible harness
identity. Bound incident values are not the harness template identity; the service
separately hashes actual model input. Source-byte hashes detect implementation
changes, including comment-only edits, rather than proving semantic equivalence.
"""

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from subsea_copilot import budgets
from subsea_copilot.contracts import (
    AgentResult,
    AgentTask,
    content_hash,
)
from subsea_copilot.grounding import GroundingCheckBatch, InterpretationRevision
from subsea_copilot.llm.copilot_cli import PROMPT_INSTRUCTIONS
from subsea_copilot.prompts import PromptTemplate, prompt_manifest, prompt_manifest_sha256
from subsea_copilot.runtime.agent import WorkPlan
from subsea_copilot.runtime.context import (
    COMPACTION_STAGES,
    CONTEXT_HEADROOM_CHARS,
    CONTEXT_INSTRUCTION,
    CONTEXT_POLICY_VERSION,
)
from subsea_copilot.runtime.diagnostics import REPAIR_HINTS, REPAIR_INSTRUCTION
from subsea_copilot.runtime.registry import role_policy, tool_schemas

BOUND_ENVELOPE = "\nBOUND_CONTEXT\n"
RUNTIME_ENVELOPE = "RUNTIME_REPLY_CONSTRAINTS\n"
_PACKAGE = Path(__file__).resolve().parents[1]
_IMPLEMENTATION = {
    "\\".join(parts): hashlib.sha256(_PACKAGE.joinpath(*parts).read_bytes()).hexdigest()
    for parts in (
        ("runtime", "agent.py"), ("runtime", "context.py"),
        ("runtime", "diagnostics.py"), ("runtime", "gateway.py"),
        ("runtime", "workflow.py"), ("runtime", "provenance.py"),
        ("llm", "copilot_cli.py"), ("validation.py",),
        ("grounding.py",), ("redaction.py",), ("history.py",), ("interpretation.py",),
        ("agent_evidence.py",), ("runtime", "registry.py"),
        ("prompts", "__init__.py"),
    )
}


def harness_provenance(
    task: AgentTask, phase: str, prompt: str, context: dict[str, Any], *, prompt_limit: int,
    prompt_asset: PromptTemplate | None = None,
) -> dict[str, Any]:
    """Fingerprint phase instructions and effective authority for checkpoint compatibility."""
    phase_kind = (
        "critic"
        if phase.startswith("critic-")
        else "reflection"
        if phase.startswith("reflection")
        else phase
    )
    schema = (
        WorkPlan
        if phase_kind == "plan"
        else GroundingCheckBatch
        if phase_kind == "critic"
        else InterpretationRevision
        if phase_kind == "reflection"
        else AgentResult
    )
    templates: dict[str, str] = {
        "system": prompt,
        "bound_envelope": BOUND_ENVELOPE,
        "runtime_envelope": RUNTIME_ENVELOPE,
        "transport": PROMPT_INSTRUCTIONS,
        "schema_repair": REPAIR_INSTRUCTION,
        "context_view": CONTEXT_INSTRUCTION,
    }
    for key in ("reflection_instruction", "batch_instruction", "pressure_summary_contract"):
        if isinstance(context.get(key), str):
            templates[key] = context[key]
    fingerprints = {
        key: hashlib.sha256(text.encode("utf-8")).hexdigest() for key, text in templates.items()
    }
    fingerprints["result_schema"] = content_hash(schema.model_json_schema())
    fingerprints["repair_hints"] = content_hash({**REPAIR_HINTS})
    policy: dict[str, Any] = {
        "role": task.role,
        "role_policy": {
            key: sorted(value) if isinstance(value, frozenset) else value
            for key, value in asdict(role_policy(task.role, task.decision_policy)).items()
        },
        "tools": tool_schemas(task.role, task.decision_policy),
        "decision_policy": task.decision_policy,
        "execution_bounds": {
            key: value
            for key, value in vars(budgets).items()
            if key.isupper() and isinstance(value, int)
        },
        "prompt_limit": prompt_limit,
        "context_policy": CONTEXT_POLICY_VERSION,
        "context_headroom": CONTEXT_HEADROOM_CHARS,
        "context_stages": list(COMPACTION_STAGES),
    }
    policy_hash = content_hash(policy)
    # Reuse/resume must identify the harness, not merely the requested model or prompt name.
    identity: dict[str, Any] = {
        "role": task.role,
        "phase_kind": phase_kind,
        "templates": fingerprints,
        "policy_sha256": policy_hash,
        "implementation": _IMPLEMENTATION,
        "prompt_asset": prompt_asset.provenance() if prompt_asset is not None else None,
        "prompt_catalog_sha256": prompt_manifest_sha256(),
    }
    return {
        "version": "author-harness-v1",
        "harness_id": "harness-" + content_hash(identity),
        **identity,
        "policy": policy,
        "prompt_catalog": prompt_manifest(),
        "investigation_catalog_known": task.prompt_catalog_sha256 is not None,
        "bound_schema_sha256": content_hash(context["result_schema"]),
    }
