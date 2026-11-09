"""Shared redaction for opt-in trace content and durable public diagnostics.

JSON-aware filtering removes sensitive keys/private reasoning and recursively
cleans string values; plain text uses credential-pattern replacement. This is
defense in depth, not permission to capture arbitrary data: telemetry still
requires explicit synthetic-only content opt-in and bounds output separately.
"""

import json
import re
from typing import Any

SENSITIVE_KEYS = re.compile(
    r"secret|password|authorization|credential|api[_-]?key|token(?!s$)", re.I
)


def redact_content(value: str) -> str:
    """Preserve unchanged JSON bytes when safe; redact nested content without breaking JSON."""
    def redact_text(text: str) -> str:
        text = re.sub(
            r"(?i)(?:bearer\s+\S+|(?:password|secret|token|api[_-]?key)\s*[:=]\s*\S+)",
            "[REDACTED]",
            text,
        )
        return re.sub(r"(?:gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)", "[REDACTED]", text)

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            if item.get("type") in {"thinking", "reasoning", "redacted_thinking"}:
                return {"type": "private_reasoning_removed"}
            return {
                key: "[REDACTED]"
                if SENSITIVE_KEYS.search(key) or "reasoning" in key.lower()
                else clean(child)
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, str):
            return redact_content(item)
        return item

    if value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
            cleaned = clean(parsed)
            # Preserve safe original serialization so evidence quotes/fingerprints do not drift.
            return json.dumps(cleaned, ensure_ascii=True) if cleaned != parsed else value
        except json.JSONDecodeError:
            pass
    return redact_text(value)
