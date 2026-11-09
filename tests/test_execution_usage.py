from datetime import timedelta

import pytest

from subsea_copilot.contracts import AgentTask, utc_now
from subsea_copilot.execution_usage import summarize_usage


def task(calls=1):
    return AgentTask(
        id="root", root_id="root", site_id="northsea", generation_id="generation",
        snapshot_id="snapshot", role="operator_response", purpose="answer_question",
        question="Review the pressure incident", mode="live", model_calls=calls,
        deadline=utc_now() + timedelta(seconds=900),
    )


def receipt(input_tokens=1000, output_tokens=100, read=0, write=0, model="gpt-6.1-sol"):
    return {
        "observed_model": model,
        "usage": {
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cache_read_tokens": read, "cache_write_tokens": write,
            "reasoning_tokens": 50,
        },
    }


def test_input_subsets_and_reasoning_are_not_double_counted():
    metrics = summarize_usage([task()], [receipt(read=200, write=300)])
    assert metrics["total_tokens"] == 1100
    assert metrics["cache_read_tokens"] == 200
    assert metrics["cache_write_tokens"] == 300
    assert metrics["cost_usd"] == pytest.approx(0.003)
    assert metrics["cost_min_usd"] == pytest.approx(0.003)
    assert metrics["cost_max_usd"] == pytest.approx(0.003)
    assert metrics["priced_calls"] == 1


@pytest.mark.parametrize("input_tokens,cost", [(272000, 0.545), (272001, 1.089504)])
def test_context_tier_applies_per_model_call(input_tokens, cost):
    metrics = summarize_usage([task()], [receipt(input_tokens=input_tokens)])
    assert metrics["cost_min_usd"] == pytest.approx(cost)
    assert metrics["cost_max_usd"] == pytest.approx(cost)


@pytest.mark.parametrize("call", [
    {"usage": None},
    receipt(output_tokens=None),
    receipt(input_tokens=-1),
])
def test_missing_or_invalid_counts_are_not_presented_as_zero_cost(call):
    metrics = summarize_usage([task()], [call])
    assert metrics["reported_calls"] == 0
    assert metrics["cost_usd"] is None
    assert metrics["cost_min_usd"] is None


@pytest.mark.parametrize("call", [
    receipt(model="unpublished-model"),
])
def test_unpriced_calls_retain_known_tokens_and_explicit_cost_coverage(call):
    metrics = summarize_usage([task()], [call])
    assert metrics["reported_calls"] == 1
    assert metrics["total_tokens"] == 1100
    assert metrics["priced_calls"] == 0
    assert metrics["cost_min_usd"] is None


@pytest.mark.parametrize("read,write", [(None, None), (800, 800), (200, 300), (0, 0)])
def test_standard_estimate_does_not_depend_on_cache_counters(read, write):
    metrics = summarize_usage([task()], [receipt(read=read, write=write)])
    assert metrics["cost_usd"] == pytest.approx(0.003)
    assert metrics["cost_min_usd"] == pytest.approx(0.003)
    assert metrics["cost_max_usd"] == pytest.approx(0.003)
    assert metrics["priced_calls"] == 1


def test_completed_usage_is_partial_until_all_reserved_calls_report():
    metrics = summarize_usage([task(3), task(2)], [receipt(), receipt()])
    assert metrics["reserved_calls"] == 5
    assert metrics["completed_calls"] == metrics["reported_calls"] == 2
    assert metrics["total_tokens"] == 2200
