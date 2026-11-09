"""Root-scoped provider usage and explicitly hypothetical OpenAI API pricing."""

from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import JsonValue

from .contracts import AgentTask

PRICING_URL = "https://developers.openai.com/api/docs/pricing"
PRICING_DATE = "2026-11-08"
# USD per million tokens: standard input and output.
STANDARD_RATES = {
    "gpt-6.1-sol": (
        (Decimal("2"), Decimal("10")),
        (Decimal("4"), Decimal("15")),
    ),
}


def _count(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def summarize_usage(
    tasks: Sequence[AgentTask], calls: Sequence[Mapping[str, JsonValue]],
) -> dict[str, object]:
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
              "cache_write_tokens": 0}
    reported = priced = cached_reported = 0
    cost = Decimal(0)
    models: set[str] = set()
    for call in calls:
        usage = call.get("usage")
        if not isinstance(usage, dict):
            continue
        input_tokens = _count(usage.get("input_tokens"))
        output_tokens = _count(usage.get("output_tokens"))
        if input_tokens is None or output_tokens is None:
            continue
        reported += 1
        totals["input_tokens"] += input_tokens
        totals["output_tokens"] += output_tokens
        read = _count(usage.get("cache_read_tokens"))
        write = _count(usage.get("cache_write_tokens"))
        if read is not None:
            totals["cache_read_tokens"] += read
        if write is not None:
            totals["cache_write_tokens"] += write
        model = call.get("observed_model")
        if isinstance(model, str):
            models.add(model)
        if read is not None and write is not None and read + write <= input_tokens:
            cached_reported += 1
        if not isinstance(model, str) or model not in STANDARD_RATES:
            continue
        rates = STANDARD_RATES[model][int(input_tokens > 272_000)]
        cost += (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
        priced += 1
    expected = sum(task.model_calls for task in tasks)
    return {
        **totals, "total_tokens": totals["input_tokens"] + totals["output_tokens"],
        "reserved_calls": expected, "completed_calls": len(calls),
        "reported_calls": reported, "cache_reported_calls": cached_reported,
        "priced_calls": priced, "models": sorted(models),
        "cost_usd": float(cost) if priced else None,
        "cost_min_usd": float(cost) if priced else None,
        "cost_max_usd": float(cost) if priced else None,
        "pricing_url": PRICING_URL, "pricing_date": PRICING_DATE,
        "pricing_basis": "OpenAI Standard API equivalent; not a Copilot charge",
        "pricing_assumptions": (
            "All input tokens use standard input rates, with no cache adjustments. "
            "Reasoning is included in output. "
            "Per-call input above 272K uses long-context rates. "
            "Excludes regional/FedRAMP uplifts, tools, infrastructure and taxes. "
            "Missing usage or unpublished model rates are not estimated."
        ),
        "rates_per_million": {
            model: {
                "short": [float(rate) for rate in STANDARD_RATES[model][0]],
                "long": [float(rate) for rate in STANDARD_RATES[model][1]],
            }
            for model in sorted(models) if model in STANDARD_RATES
        },
    }
